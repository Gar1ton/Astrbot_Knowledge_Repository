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
        embedding = config.get_embedding_config()
        provider_type = embedding.provider.lower()

        logger.info(f"Assembling EmbeddingProvider for backend type: '{provider_type}'")

        inner_provider: EmbeddingProvider
        
        if provider_type == "astr":
            # AstrBot 内置 Embedding：复用主框架已配置的 embedding 模型，
            # 目前尚未完整对接 AstrBot embedding 接口，先抛出明确错误避免静默降级。
            raise NotImplementedError(
                "embedding_provider='astr' (复用 AstrBot 内置 Embedding) 尚未实现。"
                " 请暂时改用 'local' 或 'external'。"
            )
        elif provider_type == "local":
            # 引入本地懒加载实现
            from core.repository.embedding.local import LocalEmbeddingProvider

            inner_provider = LocalEmbeddingProvider(model_name=embedding.model)
        elif provider_type == "external":
            # 云端 API 兼容接口
            from core.repository.embedding.external import ExternalEmbeddingProvider

            inner_provider = ExternalEmbeddingProvider(
                base_url=embedding.base_url,
                model_name=embedding.model,
            )
        else:
            raise ValueError(
                f"Unsupported embedding provider: {embedding.provider!r}. "
                "Choose 'local' or 'external'."
            )

        # 始终用 SQLite 缓存机制包装它以享受 0 网耗 0 算力的绝对性能
        cache_db_path = f"{db_dir}/embedding_cache.db"
        logger.info(f"Wrapping provider with cached persistence at {cache_db_path}")
        cache_namespace = f"{provider_type}:{embedding.model}:{embedding.base_url}"
        return CachedEmbeddingProvider(
            inner=inner_provider,
            db_path=cache_db_path,
            namespace=cache_namespace,
        )


__all__ = ["EmbeddingProviderFactory"]
