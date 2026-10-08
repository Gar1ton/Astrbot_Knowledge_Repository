"""基于云端 API 的 Embedding 计算实现。

使用 pure aiohttp 异步网络请求实现对 OpenAI 兼容接口的调用，
零外部 SDK (如 openai-python) 依赖，保持系统绝对轻量。
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.validation import (
    EmbeddingValidationError,
    parse_openai_vectors,
)

logger = logging.getLogger("ExternalEmbeddingProvider")

# API Key 仅由环境变量注入；Base URL 与模型来自顶层 embedding 配置。
ENV_EMBEDDING_API_KEY = "KR_EMBEDDING_API_KEY"

# 无超时会让一次 ask 挂满 aiohttp 默认 5 分钟；瞬断重试一次即可（对齐 adapters/llm.py）。
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10)
_MAX_RETRIES = 1
_RETRY_BACKOFF_SECONDS = 1.0


class _NonRetryableEmbeddingError(RuntimeError):
    """请求本身有问题（4xx/契约不符），重试无意义，直接失败。"""


class _RetryableEmbeddingError(RuntimeError):
    """仅承载本地构造的 HTTP 状态诊断，可在有限重试后安全展示。"""


class ExternalEmbeddingProvider(EmbeddingProvider):
    """OpenAI 文本 embedding 适配；首个有效批次锁定维度，漂移时拒绝返回向量。

    多模态模型可通过其文本入口使用；本接口不把图片编码字符串视作图片输入。
    请求端点归一化不改变配置、缓存 namespace 或索引身份。
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "text-embedding-3-large",
    ) -> None:
        self._api_key = os.environ.get(ENV_EMBEDDING_API_KEY) or ""
        self._model_name = model_name

        self._endpoint = self._embedding_endpoint(base_url)
        self._observed_dimension: int | None = None
        # 映射只供探针前展示；真实维度由首个有效批次确认。
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

    @staticmethod
    def _embedding_endpoint(base_url: str) -> str:
        """保留版本/代理前缀；完整端点不重复追加，查询参数留在路径之后。"""
        try:
            parts = urlsplit(base_url)
        except ValueError:
            raise ValueError("Embedding Base URL 无效") from None
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Embedding Base URL 必须是 HTTP(S) 地址")
        path = parts.path.rstrip("/")
        if not path.endswith("/embeddings"):
            path += "/embeddings"
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

    @property
    def dimension_verified(self) -> bool:
        """缓存读取前是否已有实测维度；模型映射只是启动前的估计。"""
        return self._observed_dimension is not None

    async def embed_query(self, text: str) -> list[float]:
        res = await self.embed_documents([text])
        return res[0] if res else []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "input": texts,
            "model": self._model_name,
            "encoding_format": "float",
        }

        # 保留既有 text-embedding-3 维度请求行为，不改变已建索引的向量空间。
        if "text-embedding-3" in self._model_name:
            payload["dimensions"] = self._dimension
        return await self._request_vectors(payload, len(texts))

    async def _request_vectors(self, payload: dict, count: int) -> list[list[float]]:
        """统一网络超时与有界重试；响应契约错误不重试。"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        attempts = _MAX_RETRIES + 1
        last_error = "请求失败"
        for attempt in range(1, attempts + 1):
            try:
                async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                    async with session.post(self._endpoint, headers=headers, json=payload) as resp:
                        if resp.status != 200:
                            logger.error(f"Embedding API failed with status {resp.status}")
                            msg = f"Embedding API 响应异常，HTTP {resp.status}"
                            # 4xx 是请求本身的问题，重试无意义；5xx/网络错误才重试。
                            if resp.status < 500:
                                raise _NonRetryableEmbeddingError(msg)
                            raise _RetryableEmbeddingError(msg)

                        try:
                            data = await resp.json()
                        except (ValueError, aiohttp.ContentTypeError):
                            raise _NonRetryableEmbeddingError(
                                "Embedding API 未返回有效 JSON"
                            ) from None
                        return self._validate_response(data, count)
            except _NonRetryableEmbeddingError as e:
                logger.error("External embedding request failed: %s", e)
                raise RuntimeError(f"Embedding 接口通信错误: {e}") from None
            except Exception as e:
                # 网络异常可能带出含凭据 URL，日志和异常均只保留错误类别。
                last_error = str(e) if isinstance(e, _RetryableEmbeddingError) else type(e).__name__
                logger.warning(
                    "External embedding attempt %d/%d failed: %s",
                    attempt,
                    attempts,
                    type(e).__name__,
                )
                if attempt < attempts:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError(f"Embedding 接口通信错误: {last_error}") from None

    def _validate_response(self, data: object, count: int) -> list[list[float]]:
        """完整批次通过后才更新维度；一次坏响应不能改变 provider 的已确认身份。"""
        try:
            result = parse_openai_vectors(data, count)
        except EmbeddingValidationError as exc:
            raise _NonRetryableEmbeddingError(str(exc)) from None
        dimension = len(result[0])
        if self._observed_dimension is not None and dimension != self._observed_dimension:
            raise _NonRetryableEmbeddingError(
                f"Embedding 维度漂移：已锁定 {self._observed_dimension}，实际为 {dimension}；"
                "检查模型配置并重启插件，沿现有索引兼容检查决定是否重建"
            )
        self._observed_dimension = self._dimension = dimension
        return result

    def get_dimension(self) -> int:
        return self._dimension

    @property
    def runtime_status(self) -> dict:
        """远端 provider 本地无模型可驻留，故无 `unload()` 可做（沿用基类空操作）。"""
        return {
            "provider": "external",
            "state": "external",
            "model": self._model_name,
            "device": "",
            "last_error": None,
        }


__all__ = ["ExternalEmbeddingProvider"]
