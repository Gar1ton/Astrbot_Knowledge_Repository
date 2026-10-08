"""装饰器风格的缓存 Embedding 计算实现。

使用 SQLite 对任何 EmbeddingProvider 进行包装，把计算出的 Vector 存进数据库，
再次遇到相同哈希的文本时 0 网耗、0 算力开销召回。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import aiosqlite

from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.validation import validate_vectors

logger = logging.getLogger("CachedEmbeddingProvider")


class CachedEmbeddingProvider(EmbeddingProvider):
    """保留历史 key/schema 的 SQLite 缓存；实测维度就绪后读取，整批校验后写入。"""

    def __init__(
        self,
        inner: EmbeddingProvider,
        db_path: str = "./data/embedding_cache.db",
        namespace: str = "default",
    ) -> None:
        self._inner = inner
        self._db_path = db_path
        self._namespace = namespace
        self._initialized = False
        self._batch_lock = asyncio.Lock()

    async def _lazy_init_db(self) -> None:
        """异步延迟初始化缓存数据库及表。"""
        if self._initialized:
            return

        # 确保数据目录存在
        db_dir = os.path.dirname(self._db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    content_hash TEXT PRIMARY KEY,
                    vector TEXT NOT NULL
                )
                """
            )
            await db.commit()

        self._initialized = True
        logger.info(f"Initialized SQLite embedding cache at {self._db_path}")

    def _current_namespace(self) -> str:
        """静态 namespace + 被包装 provider 的运行时身份（若有）。

        local/external 的 `identity` 为空，namespace 与引入该机制前逐字节一致，既有缓存继续命中。
        astr 的身份含 provider ID / adapter 类型 / 模型 / 实测维度，任一变化即换一套 key，
        不会把旧模型的向量当成新模型的命中。每次现读：实测维度在首次嵌入后才确定。
        """
        identity = getattr(self._inner, "identity", None)
        if not identity:
            return self._namespace
        canonical = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return f"{self._namespace}\0{canonical}"

    @staticmethod
    def _hash(namespace: str, text: str) -> str:
        import hashlib

        return hashlib.sha256(f"{namespace}\0{text}".encode()).hexdigest()

    def _get_hash(self, text: str) -> str:
        """Hash the provider/model namespace and text into one cache key."""
        return self._hash(self._current_namespace(), text)

    @property
    def identity(self) -> dict[str, str]:
        """透传被包装 provider 的身份：组合根拿到的是本装饰器，指纹要用里层的身份。"""
        return getattr(self._inner, "identity", None) or {}

    async def embed_query(self, text: str) -> list[float]:
        # 查询通常不缓存（因为高频提问且变动大，防止缓存无限膨胀），直接穿透
        return await self._inner.embed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # 串行化同一装饰器的初始化/批次合并，避免冷启动和身份更新交叉写入。
        async with self._batch_lock:
            await self._ensure_dimension(texts[0])
            await self._lazy_init_db()
            return await self._embed_cached(texts)

    async def _ensure_dimension(self, probe_text: str) -> None:
        """external 的映射维度未经验证；astr 未声明维度时也先走真实探针。"""
        verified = getattr(self._inner, "dimension_verified", True)
        try:
            dimension = self._inner.get_dimension()
        except RuntimeError:
            dimension = 0
        if not verified or dimension <= 0:
            vector = await self._inner.embed_query(probe_text)
            validate_vectors([vector], 1, self._inner.get_dimension())

    async def _read_cache(self, hashes: list[str], dimension: int) -> dict[str, list[float]]:
        """损坏/过期记录按 miss 处理，不让单条坏缓存阻断整批。"""
        hits: dict[str, list[float]] = {}
        async with aiosqlite.connect(self._db_path) as db:
            # 保持旧表结构；分批读取兼容 SQLite 的参数数量上限。
            for start in range(0, len(hashes), 900):
                batch = hashes[start:start + 900]
                placeholders = ",".join("?" for _ in batch)
                sql = (
                    "SELECT content_hash, vector FROM embedding_cache "
                    f"WHERE content_hash IN ({placeholders})"
                )
                async with db.execute(sql, batch) as cursor:
                    async for key, encoded in cursor:
                        try:
                            vector = json.loads(encoded)
                            hits[key] = validate_vectors([vector], 1, dimension)[0]
                        except (TypeError, ValueError):
                            continue
        return hits

    async def _embed_cached(self, texts: list[str]) -> list[list[float]]:
        namespace = self._current_namespace()
        dimension = self._inner.get_dimension()
        hashes = [self._hash(namespace, text) for text in texts]
        hits = await self._read_cache(hashes, dimension)
        missing = [index for index, key in enumerate(hashes) if key not in hits]
        if not missing:
            return [hits[key] for key in hashes]

        logger.info("Embedding cache miss: %d texts", len(missing))
        calculated = await self._inner.embed_documents([texts[index] for index in missing])
        current_dim = self._inner.get_dimension()
        calculated = validate_vectors(calculated, len(missing), current_dim)
        current_namespace = self._current_namespace()
        if current_dim != dimension or current_namespace != namespace:
            # 本地模型可能在第一次 encode 后修正估计；旧命中不能混入新身份的批次。
            if hits:
                calculated = await self._inner.embed_documents(texts)
                missing = list(range(len(texts)))
                current_dim = self._inner.get_dimension()
                calculated = validate_vectors(calculated, len(texts), current_dim)
            hashes = [self._hash(self._current_namespace(), text) for text in texts]
            hits = {}

        resolved = {hashes[index]: vector for index, vector in zip(missing, calculated)}
        # 按位置合并，重复文本也保持数量；整个批次通过后才持久化。
        fresh = dict(zip(missing, calculated))
        result = [fresh[index] if index in fresh else hits[key]
                  for index, key in enumerate(hashes)]
        validate_vectors(result, len(texts), current_dim)
        await self._write_cache(resolved)
        return result

    async def _write_cache(self, vectors: dict[str, list[float]]) -> None:
        """单事务回填，网络/校验失败时不修改任何缓存记录。"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                "INSERT OR REPLACE INTO embedding_cache (content_hash, vector) VALUES (?, ?)",
                [(key, json.dumps(vector, allow_nan=False)) for key, vector in vectors.items()],
            )
            await db.commit()

    def unload(self) -> None:
        """透传卸载给被包装的 provider。

        必须透传：组合根注入给上层的是本装饰器实例，不透传的话「卸载模型」会静默失效
        （向量缓存是磁盘 SQLite，与显存无关，这里无需清理）。
        """
        self._inner.unload()

    @property
    def runtime_status(self) -> dict:
        """透传被包装 provider 的运行态——真正持有模型的是它，不是缓存层。"""
        return self._inner.runtime_status

    def get_dimension(self) -> int:
        return self._inner.get_dimension()


__all__ = ["CachedEmbeddingProvider"]
