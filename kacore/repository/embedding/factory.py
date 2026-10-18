"""Embedding 提供者实例化工厂。

负责解析配置，并动态决策、按需加载、缓存包装目标 Embedding 后端。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.cached import CachedEmbeddingProvider

if TYPE_CHECKING:
    from kacore.config import Config

logger = logging.getLogger("EmbeddingProviderFactory")


class EmbeddingProviderFactory:
    """动态组装与懒加载 Embedding 后端的工厂。"""

    @staticmethod
    def create_provider(
        config: Config, db_dir: str = "./data", context: Any | None = None
    ) -> EmbeddingProvider:
        """根据后端有效配置，自适应实例化对应的 Embedding 提供者。

        `context` 是 AstrBot Context，仅 provider=astr 使用（由组合根传入）；local/external
        忽略它。astr 解析失败抛 AstrBotEmbeddingError，由组合根降级处理。
        """
        embedding = config.get_embedding_config()
        provider_type = embedding.provider.lower()

        logger.info(f"Assembling EmbeddingProvider for backend type: '{provider_type}'")

        inner_provider: EmbeddingProvider
        # local/external 沿用历史 namespace（保持既有缓存命中）；astr 的 model/base_url 配置被忽略，
        # 其真实身份（provider ID / adapter / 模型 / 维度）由 Cached 从 inner.identity 现读并入。
        cache_namespace = f"{provider_type}:{embedding.model}:{embedding.base_url}"

        if provider_type == "astr":
            # 复用 AstrBot 已配置的 EmbeddingProvider：密钥/地址/模型都在 AstrBot 侧，
            # 这里只解析出 provider 并经其公开抽象取向量。
            from kacore.repository.embedding.astrbot import AstrBotEmbeddingProvider

            inner_provider = AstrBotEmbeddingProvider(context, embedding.astrbot_provider_id)
            cache_namespace = "astr"
        elif provider_type == "local":
            # 引入本地懒加载实现
            from kacore.repository.embedding.local import LocalEmbeddingProvider

            inner_provider = LocalEmbeddingProvider(
                model_name=embedding.model,
                idle_timeout=embedding.local_idle_timeout_seconds,
                load_timeout=embedding.load_timeout_seconds,
                device=embedding.device,
            )
        elif provider_type == "external":
            # 云端 API 兼容接口
            from kacore.repository.embedding.external import ExternalEmbeddingProvider

            inner_provider = ExternalEmbeddingProvider(
                base_url=embedding.base_url,
                model_name=embedding.model,
            )
        else:
            raise ValueError(
                f"Unsupported embedding provider: {embedding.provider!r}. "
                "Choose 'local', 'external' or 'astr'."
            )

        # 始终用 SQLite 缓存机制包装它以享受 0 网耗 0 算力的绝对性能
        cache_db_path = f"{db_dir}/embedding_cache.db"
        logger.info(f"Wrapping provider with cached persistence at {cache_db_path}")
        return CachedEmbeddingProvider(
            inner=inner_provider,
            db_path=cache_db_path,
            namespace=cache_namespace,
        )


__all__ = ["EmbeddingProviderFactory"]
