"""AstrBot 托管的 Embedding 适配器（repository 层，实现 base.py 的 EmbeddingProvider 契约）。

为何存在：AstrBot 已经管着用户配好的 Embedding 服务（API Key / Base URL / 模型 / 维度 / 代理 /
超时）。本适配器让 Knowledge Arch 只经 AstrBot 的公开抽象 `EmbeddingProvider`
（`get_embedding` / `get_embeddings` / `get_dim`）取向量：不重复保存密钥，也绝不直接碰任何服务商
API 或底层 SDK（`provider.client`、`client.embeddings.create` 一概不用，不假设底层是 OpenAI 格式）。

生命周期边界：provider 归 AstrBot 所有。本模块从不调用其 `terminate()`、不关闭其 HTTP client、
不改其配置或模型名；`unload()` 是空操作。AstrBot 热重载（terminate 旧实例 + 建新实例）后，
适配器按 ID 重新解析，因此不会继续使用已被关闭的旧 client。

AstrBot 契约里的三个坑（已用 4.26.7 / 4.27.4 源码核对，本模块据此设计）：
  1. `get_dim()` 在未配置 `embedding_dimensions` 时返回 0 → 0 = 「未声明」，不与实测比较，
     改由首个实测向量锁定维度，之后每条向量都必须与之一致。
  2. OpenAI/Gemini 源不调用 `set_model()`，公开的 `get_model()` 为空串 → 模型名只在 provider 自己
     报告时才计入 `identity`；报告为空时身份退化为 (provider ID, adapter 类型, 维度)，
     此时若用户只改了模型名而 ID/类型/维度都没变，本插件无法察觉（需手动重建索引）。
  3. 4.26.7 的 `get_embeddings_batch` 在并发下按完成顺序拼接结果 → 只用 `get_embeddings`。

批量上限、输入格式、超时全部由对应 AstrBot provider 决定；本适配器不分批、不重试，也不做
维度截断/填充/转换（维度不一致一律报错，交给用户改配置或重建索引）。
"""
from __future__ import annotations

import logging
import math
import numbers
from typing import Any

from kacore.repository.embedding.astrbot_resolver import (
    STAGE_DIMENSION,
    STAGE_EMBED_DOCUMENTS,
    STAGE_EMBED_QUERY,
    STAGE_RESOLVE,
    AstrBotEmbeddingError,
    build_error,
    exc_detail,
    load_astrbot_embedding_type,
    read_provider_info,
    resolve_astrbot_embedding_provider,
)
from kacore.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("AstrBotEmbeddingProvider")


# ── 适配器 ──────────────────────────────────────────────────────


class AstrBotEmbeddingProvider(EmbeddingProvider):
    """把 AstrBot 的 EmbeddingProvider 适配成 Knowledge Arch 的 EmbeddingProvider。

    契约：
      - embed_query → `get_embedding`；embed_documents → `get_embeddings`；空输入直接返回 []，
        不发任何请求。
      - 返回值必须是非空、有限数值列表；批量数量与输入一致；各向量维度一致；与 provider 声明维度
        （`get_dim()>0` 时）及此前观测维度一致——任一不满足抛 AstrBotEmbeddingError，绝不
        截断 / 填充 / 转换。
      - 每次调用都按 ID 重新解析 provider（跟随 AstrBot 热重载）；若其 adapter 类型 / 模型 /
        声明维度相对启动时变了则拒绝调用：继续写入会把不同向量空间的数据混进同一份索引。
        重启插件后新身份会进入指纹，旧索引被判不兼容并走既有重建流程。
      - 错误信息脱敏；原始异常链被切断（`from None`），避免带出含凭据片段的 SDK 报错原文。
    """

    def __init__(
        self,
        context: Any,
        provider_id: str = "",
        *,
        embedding_type: type | None = None,
    ) -> None:
        self._context = context
        self._embedding_type = embedding_type or load_astrbot_embedding_type()
        provider, resolved_id = resolve_astrbot_embedding_provider(
            context, provider_id, embedding_type=self._embedding_type
        )
        self._provider_id = resolved_id
        self._pinned = read_provider_info(provider, resolved_id)
        self._observed_dim = 0
        self._last_error: str | None = None
        logger.info(
            "AstrBot Embedding provider 已解析：id=%s type=%s model=%s declared_dim=%s",
            resolved_id,
            self._pinned.adapter_type,
            self._pinned.model or "<provider 未报告>",
            self._pinned.declared_dim or "<未声明>",
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    # ── EmbeddingProvider 契约 ──────────────────────────────────

    async def embed_query(self, text: str) -> list[float]:
        provider = self._current()
        try:
            vector = await provider.get_embedding(text)
        except Exception as exc:  # noqa: BLE001
            raise self._callbuild_error(STAGE_EMBED_QUERY, exc) from None
        return self._validate([vector], 1, STAGE_EMBED_QUERY)[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self._current()
        try:
            vectors = await provider.get_embeddings(list(texts))
        except Exception as exc:  # noqa: BLE001
            raise self._callbuild_error(STAGE_EMBED_DOCUMENTS, exc) from None
        return self._validate(vectors, len(texts), STAGE_EMBED_DOCUMENTS)

    def get_dimension(self) -> int:
        """实测维度优先，其次 provider 声明维度；两者皆无时报错而不是返回 0。"""
        dimension = self._observed_dim or self._pinned.declared_dim
        if dimension <= 0:
            raise self._fail(
                STAGE_DIMENSION,
                "provider 未声明向量维度（get_dim() 返回 0）且尚无实测向量",
                "先调用 embed_query 完成维度探针，或在 AstrBot 中为该 provider 配置 "
                "embedding_dimensions",
            )
        return dimension

    def unload(self) -> None:
        """空操作：共享 provider 归 AstrBot 管，本插件既不 terminate 也不关闭其 client。"""
        return None

    @property
    def identity(self) -> dict[str, str]:
        dimension = self._observed_dim or self._pinned.declared_dim
        return {
            "astrbot_provider_id": self._provider_id,
            "adapter_type": self._pinned.adapter_type,
            "model": self._pinned.model,
            "dimension": str(dimension) if dimension > 0 else "",
        }

    @property
    def runtime_status(self) -> dict[str, Any]:
        """由 AstrBot 托管的外部 provider：无本地模型可驻留，state 恒为 external。"""
        return {
            "provider": "astr",
            "state": "external",
            "model": self._pinned.model or None,
            "device": "",
            "last_error": self._last_error,
            "astrbot_provider_id": self._provider_id,
            "adapter_type": self._pinned.adapter_type,
        }

    # ── 内部 ────────────────────────────────────────────────────

    def _fail(self, stage: str, problem: str, hint: str) -> AstrBotEmbeddingError:
        error = build_error(
            stage,
            problem,
            hint,
            provider_id=self._provider_id,
            adapter_type=self._pinned.adapter_type,
            model=self._pinned.model,
        )
        self._last_error = str(error)
        return error

    def _callbuild_error(self, stage: str, exc: Exception) -> AstrBotEmbeddingError:
        return self._fail(
            stage,
            f"provider 调用失败：{exc_detail(exc)}",
            "检查 AstrBot「模型提供商」里该 Embedding Provider 的 API Key、Base URL、模型名与网络；"
            "批量上限与超时由该 provider 决定，必要时在 AstrBot 侧调整",
        )

    def _current(self) -> Any:
        """重新解析 provider 并核对身份未漂移。"""
        provider, _ = resolve_astrbot_embedding_provider(
            self._context, self._provider_id, embedding_type=self._embedding_type
        )
        now = read_provider_info(provider, self._provider_id)
        before = self._pinned
        if (now.adapter_type, now.model, now.declared_dim) != (
            before.adapter_type,
            before.model,
            before.declared_dim,
        ):
            raise self._fail(
                STAGE_RESOLVE,
                "provider 在插件启动后被 AstrBot 重新配置："
                f"(type, model, 声明维度) {before.adapter_type}, {before.model or '-'}, "
                f"{before.declared_dim or '-'} → {now.adapter_type}, {now.model or '-'}, "
                f"{now.declared_dim or '-'}；继续写入会把不同向量空间的数据混进同一索引",
                "重启 Knowledge Arch 插件并重建向量索引",
            )
        return provider

    def _validate(self, raw: Any, expected_count: int, stage: str) -> list[list[float]]:
        if not isinstance(raw, (list, tuple)):
            raise self._fail(
                stage,
                f"返回值类型是 {type(raw).__name__}，应为向量列表",
                "该 provider 未按 AstrBot 的 EmbeddingProvider 契约返回 list[list[float]]",
            )
        if len(raw) != expected_count:
            raise self._fail(
                stage,
                f"批量结果数量 {len(raw)} 与输入数量 {expected_count} 不一致",
                "可能触发了服务商的批量上限或静默丢弃；调小 AstrBot 侧该 provider 的批量设置，"
                "或换用支持该批量的 provider",
            )
        vectors = [self._as_vector(item, index, stage) for index, item in enumerate(raw)]
        dimension = len(vectors[0])
        for index, vector in enumerate(vectors):
            if len(vector) != dimension:
                raise self._fail(
                    stage,
                    f"第 {index} 条向量维度 {len(vector)} 与第 0 条的 {dimension} 不一致",
                    "同一批结果维度必须一致；检查该 provider 是否混用了不同模型或维度参数",
                )
        self._check_dimension(dimension, stage)
        self._observed_dim = dimension
        self._last_error = None
        return vectors

    def _check_dimension(self, dimension: int, stage: str) -> None:
        declared = self._pinned.declared_dim
        if declared > 0 and dimension != declared:
            raise self._fail(
                stage,
                f"实际向量维度 {dimension} 与 provider 声明维度 {declared}（get_dim()）不一致",
                "在 AstrBot 中把该 provider 的 embedding_dimensions 改成模型实际输出维度，"
                "或换用输出该维度的模型；本插件不会截断或填充向量",
            )
        if self._observed_dim and dimension != self._observed_dim:
            raise self._fail(
                stage,
                f"实际向量维度 {dimension} 与此前观测到的 {self._observed_dim} 不一致",
                "provider 的模型或维度在运行中被改动；重启插件并重建向量索引",
            )

    def _as_vector(self, item: Any, index: int, stage: str) -> list[float]:
        if not isinstance(item, (list, tuple)) or not item:
            size = len(item) if isinstance(item, (list, tuple)) else "-"
            raise self._fail(
                stage,
                f"第 {index} 条向量不是非空数值列表（类型 {type(item).__name__}，长度 {size}）",
                "该 provider 可能返回了空向量或未按 list[float] 契约返回；"
                "检查其模型名与服务商响应",
            )
        for position, value in enumerate(item):
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise self._fail(
                    stage,
                    f"第 {index} 条向量的第 {position} 个元素不是数值（{type(value).__name__}）",
                    "该 provider 未按 list[float] 契约返回向量",
                )
            if not math.isfinite(value):
                raise self._fail(
                    stage,
                    f"第 {index} 条向量的第 {position} 个元素是 NaN/Inf",
                    "非有限数值会污染向量索引；检查服务商响应或换用其他模型",
                )
        return [float(value) for value in item]


__all__ = [
    "STAGE_DIMENSION",
    "STAGE_EMBED_DOCUMENTS",
    "STAGE_EMBED_QUERY",
    "STAGE_RESOLVE",
    "AstrBotEmbeddingError",
    "AstrBotEmbeddingProvider",
    "load_astrbot_embedding_type",
    "resolve_astrbot_embedding_provider",
]
