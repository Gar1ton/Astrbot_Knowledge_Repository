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

# API Key 仅由环境变量注入；Base URL 与模型来自顶层 embedding 配置。
ENV_EMBEDDING_API_KEY = "KR_EMBEDDING_API_KEY"


class ExternalEmbeddingProvider(EmbeddingProvider):
    """基于云端大模型 API（如 OpenAI, 阿里 DashScope）的 Embedding 适配器。"""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "text-embedding-3-large",
    ) -> None:
        self._api_key = os.environ.get(ENV_EMBEDDING_API_KEY) or ""
        self._base_url = base_url
        self._model_name = model_name

        # 剥离可能多余的 /embeddings 或 /v1 路径
        self._base_url = self._base_url.rstrip("/")
        
        # 维度识别（动态更新覆盖）
        self._dimension_mapping = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
            "BAAI/bge-m3": 1024,
            "BAAI/bge-large-en-v1.5": 1024,
            "BAAI/bge-base-en-v1.5": 768,
            "BAAI/bge-small-en-v1.5": 384,
            "BAAI/bge-large-zh-v1.5": 1024,
            "BAAI/bge-base-zh-v1.5": 768,
            "BAAI/bge-small-zh-v1.5": 512,
            "intfloat/multilingual-e5-small": 384,
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
                        logger.error(f"Embedding API failed with status {resp.status}")
                        msg = f"Embedding API 响应异常，HTTP {resp.status}"
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
            logger.error("External embedding request failed: %s", type(e).__name__)
            raise RuntimeError(f"Embedding 接口通信错误: {e}") from e

    def get_dimension(self) -> int:
        return self._dimension


__all__ = ["ExternalEmbeddingProvider"]
