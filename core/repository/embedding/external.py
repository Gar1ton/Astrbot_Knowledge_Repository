"""基于云端 API 的 Embedding 计算实现。

使用 pure aiohttp 异步网络请求实现对 OpenAI 兼容接口的调用，
零外部 SDK (如 openai-python) 依赖，保持系统绝对轻量。
"""
from __future__ import annotations

import logging
import os

import aiohttp

from core.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("ExternalEmbeddingProvider")

# 优先级：环境变量优先，配置回退
ENV_EMBEDDING_API_KEY = "KR_EMBEDDING_API_KEY"
ENV_EMBEDDING_BASE_URL = "KR_EMBEDDING_BASE_URL"


class ExternalEmbeddingProvider(EmbeddingProvider):
    """基于云端大模型 API（如 OpenAI, 阿里 DashScope）的 Embedding 适配器。"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "text-embedding-3-large",
    ) -> None:
        # 环境变量注入
        self._api_key = os.environ.get(ENV_EMBEDDING_API_KEY) or api_key
        self._base_url = os.environ.get(ENV_EMBEDDING_BASE_URL) or base_url
        self._model_name = model_name

        # 剥离可能多余的 /embeddings 或 /v1 路径
        self._base_url = self._base_url.rstrip("/")
        
        # 维度识别
        self._dimension_mapping = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        self._dimension = self._dimension_mapping.get(self._model_name, 1536)

    async def embed_query(self, text: str) -> list[float]:
        res = await self.embed_documents([text])
        return res[0] if res else []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": texts,
            "model": self._model_name,
        }

        # 阿里 DashScope 或其他兼容接口的特殊微调支持可以在此注入
        # 针对 text-embedding-3 系列，OpenAI 支持维度压缩
        if "text-embedding-3" in self._model_name:
            payload["dimensions"] = self._dimension

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"Embedding API failed with status {resp.status}: {err_text}")
                        msg = f"Embedding API 响应异常，HTTP {resp.status}: {err_text}"
                        raise RuntimeError(msg)
                    
                    data = await resp.json()
                    
                    # 按照 standard OpenAI 契约解析
                    embeddings_data = data.get("data", [])
                    # 确保按 input 数组顺序排列 (使用 index 属性)
                    embeddings_data.sort(key=lambda x: x.get("index", 0))
                    
                    result = [item.get("embedding") for item in embeddings_data]
                    if not result:
                        raise RuntimeError(f"Embedding API 未能返回有效向量：{data}")
                    
                    # 动态覆写真实维度
                    if result and result[0]:
                        self._dimension = len(result[0])
                        
                    return result
        except Exception as e:
            logger.error(f"Network error in ExternalEmbedding: {e}")
            raise RuntimeError(f"Embedding 接口通信错误: {e}") from e

    def get_dimension(self) -> int:
        return self._dimension


__all__ = ["ExternalEmbeddingProvider"]
