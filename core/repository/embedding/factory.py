"""Embedding 提供者实例化工厂。

负责解析配置，并动态决策、按需加载、缓存包装目标 Embedding 后端。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.repository.embedding.base import EmbeddingProvider
from core.repository.embedding.cached import CachedEmbeddingProvider

if TYPE_CHECKING:
    from core.config import Config

logger = logging.getLogger("EmbeddingProviderFactory")


class EmbeddingProviderFactory:
    """动态组装与懒加载 Embedding 后端的工厂。"""

    @staticmethod
    def create_provider(config: Config, db_dir: str = "./data") -> EmbeddingProvider:
        """根据后端有效配置，自适应实例化对应的 Embedding 提供者。"""
        vdb = config.get_vector_db_config()
        provider_type = vdb.embedding_provider.lower()

        logger.info(f"Assembling EmbeddingProvider for backend type: '{provider_type}'")

        inner_provider: EmbeddingProvider
        
        if provider_type == "local":
            # 引入本地懒加载实现
            from core.repository.embedding.local import LocalEmbeddingProvider
            
            # 本地模型：从配置中提取。为了极强的自适应配置扩展，我们在 raw 字典里获取用户配置，
            # 默认为 BAAI/bge-large-en-v1.5 （英文顶尖模型）以满足学术论文检索
            vdb_raw = config.raw.get("vector_db", {})
            model_name = vdb_raw.get("embedding_model") or "BAAI/bge-large-en-v1.5"
            
            inner_provider = LocalEmbeddingProvider(model_name=model_name)
        else:
            # 引入云端 API 兼容接口
            from core.repository.embedding.external import ExternalEmbeddingProvider
            
            vdb_raw = config.raw.get("vector_db", {})
            api_key = vdb_raw.get("api_key") or ""
            base_url = vdb_raw.get("base_url") or "https://api.openai.com/v1"
            model_name = vdb_raw.get("embedding_model") or "text-embedding-3-large"
            
            inner_provider = ExternalEmbeddingProvider(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name
            )

        # 始终用 SQLite 缓存机制包装它以享受 0 网耗 0 算力的绝对性能
        cache_db_path = f"{db_dir}/embedding_cache.db"
        logger.info(f"Wrapping provider with cached persistence at {cache_db_path}")
        return CachedEmbeddingProvider(inner=inner_provider, db_path=cache_db_path)


__all__ = ["EmbeddingProviderFactory"]
