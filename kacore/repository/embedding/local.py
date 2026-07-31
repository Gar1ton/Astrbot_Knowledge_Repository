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
    ) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int = 0
        # idle_timeout=0 表示永不自动卸载
        self._idle_timeout = idle_timeout
        # load_timeout<=0 表示不加闸（保留旧的无限等待行为）
        self._load_timeout = max(0.0, float(load_timeout))
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

        logger.info(
            "开始加载本地 Embedding 模型 '%s'（未缓存时会从 HuggingFace 下载权重，"
            "缓存目录 %s）",
            self._model_name,
            _hf_cache_hint(),
        )
        started = time.monotonic()
        stop_heartbeat = self._start_load_heartbeat(started)
        self._loading = True
        try:
            # 如果本地无缓存，此处将自动触发 HuggingFace 下载
            self._model = SentenceTransformer(self._model_name)
            # 加载完成后动态获取真实的维度以防字典未命中
            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = self._model.get_embedding_dimension()
            elif hasattr(self._model, "get_sentence_embedding_dimension"):
                self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                "本地 Embedding 模型 '%s' 加载完成，维度 %s，耗时 %.1fs",
                self._model_name,
                self._dimension,
                time.monotonic() - started,
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
        """把阻塞计算投递到线程池；模型尚未加载时给这一次调用加超时闸。

        契约：
        - 模型已加载（或 load_timeout<=0）→ 直接 await，encode 不设上限。
        - 模型未加载 → 本次调用受 load_timeout 约束；超时抛 RuntimeError（中文可读），
          调用方按既有「embedding 不可用」路径降级。
        - 超时**不会**中止后台加载线程：`asyncio.to_thread` 无法取消，权重会继续下载并写入
          HuggingFace 缓存，后续调用可能直接命中缓存而成功。
        """
        if self._model is None and self._loading and self._load_timeout > 0:
            raise RuntimeError(
                f"本地向量模型 {self._model_name} 仍在后台加载/下载中，请稍后重试。"
            )
        call = asyncio.to_thread(fn, payload)
        if self._model is not None or self._load_timeout <= 0:
            return await call
        try:
            return await asyncio.wait_for(call, timeout=self._load_timeout)
        except TimeoutError as exc:
            logger.error(
                "本地 Embedding 模型 '%s' 在 %.0fs 内未就绪，本次调用放弃等待；"
                "下载仍在后台继续，完成后可重试。",
                self._model_name,
                self._load_timeout,
            )
            raise RuntimeError(
                f"本地向量模型 {self._model_name} 加载超时"
                f"（{self._load_timeout:.0f}s）。首次使用需从 HuggingFace 下载权重，"
                "下载仍在后台继续；请检查网络后重试，或改用 external Embedding。"
            ) from exc

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
