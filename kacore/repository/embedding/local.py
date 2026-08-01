"""基于 sentence-transformers 的本地 Embedding 计算实现。

贯彻按需懒加载原则：如果不显式启用本地 Embedding 模式，完全不加载 sentence-transformers 库。

首次加载会从 HuggingFace 下载权重（大模型可达 GB 级），是本插件唯一一处「可能挂住几分钟
甚至永不返回」的本地 I/O。故本模块承担两个稳健性职责：
    - 加载期心跳日志：长耗时不再全程静默，终端页能看到「还在下载、已等多久」。
    - 加载超时闸（load_timeout）：只在模型尚未加载时对该次调用生效；已加载后的 encode 不设
      超时，理由同 reranker（本地推理无法可靠中断，成本由 batch/候选数控制）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from kacore.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("LocalEmbeddingProvider")

# 加载期心跳间隔（秒）：下载大模型时定期报活，避免终端页看起来「什么都没发生」。
_LOAD_HEARTBEAT_SECONDS = 30.0

# HuggingFace 缓存目录的环境变量优先级（与 huggingface_hub 一致），仅用于日志提示。
_HF_CACHE_ENV_VARS = ("SENTENCE_TRANSFORMERS_HOME", "HF_HUB_CACHE", "HF_HOME")


def _hf_cache_hint() -> str:
    """返回权重缓存目录提示：便于用户确认「下载到哪」「Docker 里是否持久化」。"""
    for env_var in _HF_CACHE_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return f"{value}（{env_var}）"
    return "~/.cache/huggingface（默认）"


class LocalEmbeddingProvider(EmbeddingProvider):
    """基于本地加载 HuggingFace 模型的 Embedding 计算适配器。"""

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        idle_timeout: int = 420,
        load_timeout: float = 180.0,
        device: str = "auto",
    ) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int = 0
        # idle_timeout=0 表示永不自动卸载
        self._idle_timeout = idle_timeout
        # load_timeout<=0 表示不加闸（保留旧的无限等待行为）
        self._load_timeout = max(0.0, float(load_timeout))
        # "auto" 交给 SentenceTransformer 自行探测；显式值原样传入并在加载前校验可用性。
        self._device: str | None = None if device == "auto" else device
        self._lock = threading.Lock()
        self._idle_timer: threading.Timer | None = None
        # 有一次加载正在进行中：后续调用直接快速失败，不再往线程池里塞会卡在 _lock 上的线程
        # （超时只让 await 放弃等待，线程本身停不下来，堆多了会耗尽默认 executor）。
        self._loading = False

        # 常见模型的维度映射字典，用于避免冷启动加载前获取维度的性能开销
        self._dimension_mapping = {
            "BAAI/bge-small-zh-v1.5": 512,
            "BAAI/bge-m3": 1024,
            "BAAI/bge-large-en-v1.5": 1024,
            "BAAI/bge-large-zh-v1.5": 1024,
            "thenlper/gte-large": 1024,
            "sentence-transformers/all-MiniLM-L6-v2": 384,
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
            "intfloat/multilingual-e5-small": 384,
        }
        self._dimension = self._dimension_mapping.get(self._model_name, 384)

    def _lazy_init(self) -> None:
        """按需初始化，在此处导入大包并触发下载。调用方须持有 self._lock。"""
        if self._model is not None:
            return

        try:
            # 彻底的运行时懒加载
            from sentence_transformers import SentenceTransformer
            logger.info("Successfully imported sentence-transformers for local embedding.")
        except ImportError as e:
            error_msg = (
                f"本地向量模型需要 sentence-transformers 依赖。\n"
                f"检测到未安装，请在运行环境中执行：\n"
                f"  pip install sentence-transformers\n"
                f"原报错: {e}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        # 显式选择 cuda 但环境不支持时必须报错，不能悄悄退化到 CPU——本地 Embedding 是主
        # 向量索引路径，静默降级会让用户在不知情的情况下承受数十倍的批量编码耗时。
        self._fail_fast_if_explicit_cuda_unavailable()

        logger.info(
            "开始加载本地 Embedding 模型 '%s'（未缓存时会从 HuggingFace 下载权重，"
            "缓存目录 %s，device=%s）",
            self._model_name,
            _hf_cache_hint(),
            self._device or "auto",
        )
        started = time.monotonic()
        stop_heartbeat = self._start_load_heartbeat(started)
        self._loading = True
        try:
            # 如果本地无缓存，此处将自动触发 HuggingFace 下载
            self._model = SentenceTransformer(self._model_name, device=self._device)
            # 加载完成后动态获取真实的维度以防字典未命中
            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = self._model.get_embedding_dimension()
            elif hasattr(self._model, "get_sentence_embedding_dimension"):
                self._dimension = self._model.get_sentence_embedding_dimension()
            torch_version, cuda_available, gpu_name = self._torch_diagnostics()
            resolved_device = str(getattr(self._model, "device", self._device or "cpu"))
            logger.info(
                "本地 Embedding 模型 '%s' 加载完成，维度 %s，耗时 %.1fs，"
                "torch=%s cuda_available=%s resolved_device=%s gpu=%s",
                self._model_name,
                self._dimension,
                time.monotonic() - started,
                torch_version,
                cuda_available,
                resolved_device,
                gpu_name,
            )
        except Exception as e:
            logger.error(
                "本地 Embedding 模型 '%s' 加载失败（已等待 %.1fs）：%s",
                self._model_name,
                time.monotonic() - started,
                e,
                exc_info=True,
            )
            raise RuntimeError(f"加载本地向量模型 {self._model_name} 失败: {e}") from e
        finally:
            self._loading = False
            stop_heartbeat.set()

    def _start_load_heartbeat(self, started: float) -> threading.Event:
        """加载期每 30s 报活一次；返回的 Event 置位即停。

        为何存在：`SentenceTransformer()` 内部的下载进度条不走 logging，终端页在长下载期间
        完全没有输出，用户无法区分「在下载」与「已卡死」。
        """
        stop = threading.Event()

        def _beat() -> None:
            while not stop.wait(_LOAD_HEARTBEAT_SECONDS):
                logger.info(
                    "本地 Embedding 模型 '%s' 仍在加载/下载中，已等待 %.0fs…",
                    self._model_name,
                    time.monotonic() - started,
                )

        thread = threading.Thread(target=_beat, name="embedding-load-heartbeat", daemon=True)
        thread.start()
        return stop

    def _fail_fast_if_explicit_cuda_unavailable(self) -> None:
        """用户显式选了 cuda/cuda:N 但环境不支持时，加载前直接报错。

        与 reranker（`bge_local.py`）刻意不同：那里不可用就静默回退按序输出，因为 reranker
        退化只影响排序质量；这里是主向量索引路径，静默退化到 CPU 会让批量 encode 慢上数十倍
        且用户完全不知情，必须在加载前就明确失败。仅当用户显式选择非 auto/cpu 时才做这个检查。
        """
        if self._device is None or self._device == "cpu":
            return
        try:
            import torch
        except ImportError as e:
            raise RuntimeError(
                f"Embedding 设备被显式设为 '{self._device}'，但未安装 torch，无法使用 GPU。\n"
                "请安装支持 CUDA 的 torch，或将 embedding.device 改为 'auto'/'cpu'。"
            ) from e
        if not torch.cuda.is_available():
            raise RuntimeError(
                f"Embedding 设备被显式设为 '{self._device}'，但当前环境 CUDA 不可用"
                "（torch.cuda.is_available() 为 False）。\n"
                "请检查 GPU 驱动/CUDA 版 torch 安装，或将 embedding.device 改为 'auto'/'cpu'。"
            )

    def _torch_diagnostics(self) -> tuple[str, bool, str]:
        """返回 (torch 版本, cuda 是否可用, GPU 名称或 'none')，仅用于诊断日志，绝不抛异常。"""
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            gpu_name = torch.cuda.get_device_name(0) if cuda_available else "none"
            return str(torch.__version__), cuda_available, gpu_name
        except (ImportError, RuntimeError):
            return "unknown", False, "none"

    def _reset_idle_timer(self) -> None:
        """每次 encode 结束后重置空闲卸载计时器。"""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        if self._idle_timeout > 0:
            self._idle_timer = threading.Timer(self._idle_timeout, self._unload)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _unload(self) -> None:
        """空闲超时后卸载模型以释放内存，下次调用时自动重新加载。"""
        with self._lock:
            if self._model is not None:
                logger.info(
                    f"Local model '{self._model_name}' idle for {self._idle_timeout}s, "
                    "unloading to free memory."
                )
                self._model = None
        self._idle_timer = None

    async def embed_query(self, text: str) -> list[float]:
        # 阻塞计算投递到线程池
        return await self._run_guarded(self._embed_query_sync, text)

    def _embed_query_sync(self, text: str) -> list[float]:
        # 持锁期间完成加载+encode，防止计时器在 encode 过程中卸载模型
        with self._lock:
            self._lazy_init()
            res = self._model.encode(self._prepare_query(text), normalize_embeddings=True)
        self._reset_idle_timer()
        return [float(x) for x in res]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._run_guarded(self._embed_documents_sync, texts)

    async def _run_guarded(self, fn: Callable[[Any], Any], payload: Any) -> Any:
        """把阻塞计算投递到线程池；只在「模型尚未加载」这一段等待上加超时闸。

        契约：
        - 模型已加载（或 load_timeout<=0）→ 直接 await，encode 不设上限。
        - 模型未加载 → 只有「等到模型加载完成」这段等待受 load_timeout 约束；一旦
          `self._model` 不再是 None（加载已完成，即便是在这次调用里才刚完成），后续的
          encode 耗时不再计入超时——通过轮询 `self._model`/`call` 状态实现，不引入新的
          线程间同步原语，`fn` 内部「持锁完成加载+encode」的既有结构完全不变。
        - 超时**不会**中止后台加载线程：`asyncio.to_thread` 无法取消，权重会继续下载并写入
          HuggingFace 缓存，后续调用可能直接命中缓存而成功。
        """
        if self._model is None and self._loading and self._load_timeout > 0:
            raise RuntimeError(
                f"本地向量模型 {self._model_name} 仍在后台加载/下载中，请稍后重试。"
            )
        call = asyncio.ensure_future(asyncio.to_thread(fn, payload))
        if self._model is not None or self._load_timeout <= 0:
            return await call

        deadline = time.monotonic() + self._load_timeout
        poll_interval = 0.5
        while self._model is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    "本地 Embedding 模型 '%s' 在 %.0fs 内未完成加载，本次调用放弃等待；"
                    "下载/加载仍在后台继续，完成后可重试。",
                    self._model_name,
                    self._load_timeout,
                )
                raise RuntimeError(
                    f"本地向量模型 {self._model_name} 加载超时"
                    f"（{self._load_timeout:.0f}s）。首次使用需从 HuggingFace 下载权重，"
                    "下载仍在后台继续；请检查网络后重试，或改用 external Embedding。"
                )
            await asyncio.wait({call}, timeout=min(poll_interval, remaining))
            if call.done():
                # 加载与 encode 都已在超时窗口内跑完（或抛出异常），直接返回/重新抛出。
                return await call
        # 模型已加载完成：剩下的 encode 阶段不再设超时，让 call 跑到底。
        return await call

    def _embed_documents_sync(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self._lazy_init()
            res = self._model.encode(self._prepare_documents(texts), normalize_embeddings=True)
        self._reset_idle_timer()
        return [[float(x) for x in row] for row in res]

    def _prepare_query(self, text: str) -> str:
        if self._model_name.startswith("intfloat/") and "e5" in self._model_name.lower():
            return f"query: {text}"
        return text

    def _prepare_documents(self, texts: list[str]) -> list[str]:
        if self._model_name.startswith("intfloat/") and "e5" in self._model_name.lower():
            return [f"passage: {text}" for text in texts]
        return texts

    def get_dimension(self) -> int:
        return self._dimension


__all__ = ["LocalEmbeddingProvider"]
