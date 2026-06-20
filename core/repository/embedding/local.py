"""基于 sentence-transformers 的本地 Embedding 计算实现。

贯彻按需懒加载原则：如果不显式启用本地 Embedding 模式，完全不加载 sentence-transformers 库。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from core.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("LocalEmbeddingProvider")


class LocalEmbeddingProvider(EmbeddingProvider):
    """基于本地加载 HuggingFace 模型的 Embedding 计算适配器。"""

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        idle_timeout: int = 420,
    ) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int = 0
        # idle_timeout=0 表示永不自动卸载
        self._idle_timeout = idle_timeout
        self._lock = threading.Lock()
        self._idle_timer: threading.Timer | None = None

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
            f"Loading local embedding model: '{self._model_name}' "
            f"(it may download weights if not cached)..."
        )
        try:
            # 如果本地无缓存，此处将自动触发 HuggingFace 下载
            self._model = SentenceTransformer(self._model_name)
            # 加载完成后动态获取真实的维度以防字典未命中
            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = self._model.get_embedding_dimension()
            elif hasattr(self._model, "get_sentence_embedding_dimension"):
                self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                f"Local model '{self._model_name}' loaded successfully. "
                f"Dimension: {self._dimension}"
            )
        except Exception as e:
            logger.error(f"Failed to load local model {self._model_name}: {e}")
            raise RuntimeError(f"加载本地向量模型 {self._model_name} 失败: {e}") from e

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
        return await asyncio.to_thread(self._embed_query_sync, text)

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
        return await asyncio.to_thread(self._embed_documents_sync, texts)

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
