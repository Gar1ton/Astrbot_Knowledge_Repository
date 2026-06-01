"""装饰器风格的缓存 Embedding 计算实现。

使用 SQLite 对任何 EmbeddingProvider 进行包装，把计算出的 Vector 存进数据库，
再次遇到相同哈希的文本时 0 网耗、0 算力开销召回。
"""
from __future__ import annotations

import json
import logging
import os

import aiosqlite

from core.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("CachedEmbeddingProvider")


class CachedEmbeddingProvider(EmbeddingProvider):
    """具有本地 SQLite 缓存机制 of Embedding 计算装饰器。"""

    def __init__(
        self, inner: EmbeddingProvider, db_path: str = "./data/embedding_cache.db"
    ) -> None:
        self._inner = inner
        self._db_path = db_path
        self._initialized = False

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

    def _get_hash(self, text: str) -> str:
        """根据文本生成高精度 SHA-256 唯一哈希。"""
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def embed_query(self, text: str) -> list[float]:
        # 查询通常不缓存（因为高频提问且变动大，防止缓存无限膨胀），直接穿透
        return await self._inner.embed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        await self._lazy_init_db()
        
        hashes = [self._get_hash(t) for t in texts]
        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        # 1. 批量查询缓存
        async with aiosqlite.connect(self._db_path) as db:
            placeholders = ",".join("?" for _ in hashes)
            sql = (
                f"SELECT content_hash, vector FROM embedding_cache "
                f"WHERE content_hash IN ({placeholders})"
            )
            async with db.execute(sql, hashes) as cursor:
                cache_hits = {}
                async for row in cursor:
                    cache_hits[row[0]] = json.loads(row[1])

        # 2. 分拣命中与缺失
        for i, h in enumerate(hashes):
            if h in cache_hits:
                results[i] = cache_hits[h]
            else:
                missing_indices.append(i)
                missing_texts.append(texts[i])

        # 3. 对缺失片段批量调用真实底层计算，并回填入缓存
        if missing_texts:
            logger.info(f"Embedding cache miss. Calculating {len(missing_texts)} new texts...")
            calculated = await self._inner.embed_documents(missing_texts)
            
            async with aiosqlite.connect(self._db_path) as db:
                for idx, text_idx in enumerate(missing_indices):
                    vector = calculated[idx]
                    results[text_idx] = vector
                    
                    # 异步写入缓存（幂等 upsert）
                    sql_upsert = (
                        "INSERT OR REPLACE INTO embedding_cache "
                        "(content_hash, vector) VALUES (?, ?)"
                    )
                    await db.execute(
                        sql_upsert,
                        (hashes[text_idx], json.dumps(vector))
                    )
                await db.commit()

        # 4. 返回完整归并结果
        return [r for r in results if r is not None]

    def get_dimension(self) -> int:
        return self._inner.get_dimension()


__all__ = ["CachedEmbeddingProvider"]
