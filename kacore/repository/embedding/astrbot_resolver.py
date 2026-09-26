"""AstrBot Embedding provider 的解析、身份读取与脱敏错误（repository 层辅助，供 astrbot.py 使用）。

为何单独成文件：「怎么从 AstrBot Context 找到并确认一个 Embedding Provider」与「怎么用它取向量」
是两件事——前者只关心 Context/类型/ID，后者关心向量校验与身份漂移；分开后各自可独立测试。

只经 AstrBot 公开方法读信息：`context.get_provider_by_id` / `get_all_embedding_providers`，
provider 的 `meta().type/id`、`get_model()`、`get_dim()`；不读 `provider_config`（内含 API Key），
不碰 `client`。

AstrBot 行为坑（已用 4.26.7 / 4.27.4 源码核对）：
  - `EmbeddingProvider` 类只在 core 路径可导入，`astrbot.api.provider` 门面目前未导出。
  - `terminate_provider` 会关闭并替换实例，却不把旧实例移出 `embedding_provider_insts`，
    所以枚举结果里可能混着已被关闭的陈旧实例，须用 `get_provider_by_id` 做身份比对。
"""
from __future__ import annotations

import importlib
import numbers
import re
from dataclasses import dataclass
from typing import Any

# 失败阶段：出现在错误信息与 last_error 里，便于用户和日志定位。
STAGE_RESOLVE = "resolve"
STAGE_DIMENSION = "dimension"
STAGE_EMBED_QUERY = "embed_query"
STAGE_EMBED_DOCUMENTS = "embed_documents"

# EmbeddingProvider 类只在 core 路径可导入（AstrBot 自己的 kb_helper / vec_db 也这样用）；
# `astrbot.api.provider` 门面目前未导出，先试它，将来导出后自动改走公开路径。
_EMBEDDING_TYPE_MODULES = ("astrbot.api.provider", "astrbot.core.provider.provider")

_MAX_DETAIL_CHARS = 300
_SCHEME = r"(?:(?:bearer|basic|token)\s+)?"
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+"), "Bearer ***"),
    (
        re.compile(
            r"(?i)((?:api[-_ ]?key|apikey|authorization|token|secret|passw(?:or)?d)"
            r"[\"']?\s*[:=]\s*[\"']?)" + _SCHEME + r"[^\s\"',;&}]+"
        ),
        r"\1***",
    ),
    (
        re.compile(
            r"(?i)([?&](?:key|api_key|apikey|access_token|token|sig|signature)=)[^&\s\"']+"
        ),
        r"\1***",
    ),
    (re.compile(r"\bsk-[\w*.-]{4,}"), "sk-***"),
)


class AstrBotEmbeddingError(RuntimeError):
    """AstrBot Embedding provider 解析 / 调用 / 校验失败。

    `str(exc)` 已含 provider ID、类型、模型（provider 自己报告时）、失败阶段与修复建议，
    可直接展示给用户；不含任何凭据。`stage` 取 STAGE_* 常量。
    """

    def __init__(self, message: str, *, stage: str, provider_id: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.provider_id = provider_id


@dataclass(frozen=True)
class ProviderInfo:
    """经公开接口读到的 provider 身份快照（全部非机密）。"""

    provider_id: str
    adapter_type: str  # meta().type（如 openai_embedding）；取不到时退化为 Python 类名
    model: str  # get_model()；provider 不报告时为空串
    declared_dim: int  # get_dim()；<= 0 表示未声明


def _redact(text: str) -> str:
    """抹掉常见凭据形态后再截断（先脱敏后截断，避免把凭据切成半截漏出去）。"""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text if len(text) <= _MAX_DETAIL_CHARS else text[:_MAX_DETAIL_CHARS] + "…"


def exc_detail(exc: Exception) -> str:
    return f"{type(exc).__name__}: {_redact(str(exc))}"


def build_error(
    stage: str,
    problem: str,
    hint: str,
    *,
    provider_id: str = "",
    adapter_type: str = "",
    model: str = "",
) -> AstrBotEmbeddingError:
    parts = [f"provider_id={provider_id!r}" if provider_id else "provider_id=<未指定>"]
    if adapter_type:
        parts.append(f"type={adapter_type}")
    if model:
        parts.append(f"model={model}")
    message = f"AstrBot Embedding 失败 [阶段 {stage}] {' '.join(parts)}：{problem}。建议：{hint}"
    return AstrBotEmbeddingError(message, stage=stage, provider_id=provider_id)


# ── Provider 解析 ───────────────────────────────────────────────


def load_astrbot_embedding_type() -> type:
    """取 AstrBot 的 EmbeddingProvider 类（用于 isinstance 判型）；取不到则 fail-closed。"""
    for module_name in _EMBEDDING_TYPE_MODULES:
        try:
            cls = getattr(importlib.import_module(module_name), "EmbeddingProvider", None)
        except Exception:  # noqa: BLE001 - 导入 AstrBot 内部模块可能抛任何错，统一按「取不到」处理
            continue
        if isinstance(cls, type):
            return cls
    raise build_error(
        STAGE_RESOLVE,
        "无法从 AstrBot 导入 EmbeddingProvider 类型，无法确认目标是 Embedding Provider",
        "确认插件运行在提供 Embedding Provider 的 AstrBot 版本内（本插件要求 >=4.5.7），"
        "必要时升级 AstrBot",
    )


def _provider_id_of(provider: Any) -> str:
    try:
        value = provider.meta().id
    except Exception:  # noqa: BLE001 - meta() 在 adapter 未注册时会抛，此时无从得知 ID
        return ""
    return value.strip() if isinstance(value, str) else ""


def _live_embedding_providers(context: Any, embedding_type: type) -> dict[str, Any]:
    """AstrBot 里当前**存活**的 Embedding Provider：{id: 实例}。

    `get_all_embedding_providers()` 只含已启用且加载成功的实例，但 AstrBot 的 terminate_provider
    不会把旧实例从该列表移除，热重载后同一 ID 可能出现「已关闭的旧实例 + 新实例」两条。
    故用 `get_provider_by_id`（读 inst_map）做身份比对，剔除陈旧实例。
    """
    lister = getattr(context, "get_all_embedding_providers", None)
    if not callable(lister):
        return {}
    getter = getattr(context, "get_provider_by_id", None)
    live: dict[str, Any] = {}
    for inst in lister() or []:
        if not isinstance(inst, embedding_type):
            continue
        provider_id = _provider_id_of(inst)
        if not provider_id:
            continue
        if callable(getter) and getter(provider_id) is not inst:
            continue
        live[provider_id] = inst
    return live


def _available_hint(context: Any, embedding_type: type) -> str:
    try:
        ids = sorted(_live_embedding_providers(context, embedding_type))
    except Exception:  # noqa: BLE001 - 仅用于报错提示，列不出来不能盖掉原始错误
        return ""
    return f"当前 AstrBot 中的 Embedding Provider ID：{', '.join(ids)}。" if ids else ""


def resolve_astrbot_embedding_provider(
    context: Any, provider_id: str, *, embedding_type: type | None = None
) -> tuple[Any, str]:
    """按配置从 AstrBot Context 取 Embedding Provider，返回 `(实例, 实际使用的 ID)`。

    规则：
      - 给了 ID：`context.get_provider_by_id(id)`，必须是 AstrBot EmbeddingProvider 的实例，
        聊天 / 重排 / 语音等其他类型一律拒绝。
      - 没给 ID：仅当存活的 Embedding Provider 恰好一个时自动选用；0 个报「没有可用」，
        多个报「须显式指定」——绝不静默取列表第一个。
    失败一律抛 AstrBotEmbeddingError(stage=resolve)，消息含可执行的修复建议。
    """
    if context is None:
        raise build_error(
            STAGE_RESOLVE,
            "没有 AstrBot Context",
            "embedding.provider=astr 只能在 AstrBot 内运行；独立运行请改用 local 或 external",
        )
    embedding_type = embedding_type or load_astrbot_embedding_type()
    provider_id = (provider_id or "").strip()
    if provider_id:
        return _resolve_by_id(context, provider_id, embedding_type), provider_id
    return _resolve_single(context, embedding_type)


def _resolve_by_id(context: Any, provider_id: str, embedding_type: type) -> Any:
    getter = getattr(context, "get_provider_by_id", None)
    if not callable(getter):
        raise build_error(
            STAGE_RESOLVE,
            "AstrBot Context 没有 get_provider_by_id 接口",
            "升级 AstrBot 到提供该接口的版本",
            provider_id=provider_id,
        )
    try:
        provider = getter(provider_id)
    except Exception as exc:  # noqa: BLE001
        raise build_error(
            STAGE_RESOLVE,
            f"get_provider_by_id 调用失败：{exc_detail(exc)}",
            "检查 AstrBot 是否正常运行",
            provider_id=provider_id,
        ) from None
    available = _available_hint(context, embedding_type)
    if provider is None:
        raise build_error(
            STAGE_RESOLVE,
            "AstrBot 中不存在该 ID 的 provider（未创建、未启用或加载失败）",
            f"在 AstrBot「模型提供商」里确认 ID 拼写并启用它。{available}",
            provider_id=provider_id,
        )
    if not isinstance(provider, embedding_type):
        raise build_error(
            STAGE_RESOLVE,
            f"该 provider 不是 Embedding Provider（实际是 {_describe_kind(provider)}）；"
            "不会把聊天 / 重排 / 语音等 provider 当作 embedding 使用",
            f"把 embedding.astrbot_provider_id 改成一个 Embedding Provider 的 ID。{available}",
            provider_id=provider_id,
        )
    return provider


def _resolve_single(context: Any, embedding_type: type) -> tuple[Any, str]:
    if not callable(getattr(context, "get_all_embedding_providers", None)):
        raise build_error(
            STAGE_RESOLVE,
            "AstrBot Context 没有 get_all_embedding_providers 接口，无法自动选择",
            "升级 AstrBot，或显式填写 embedding.astrbot_provider_id",
        )
    try:
        live = _live_embedding_providers(context, embedding_type)
    except Exception as exc:  # noqa: BLE001
        raise build_error(
            STAGE_RESOLVE,
            f"枚举 Embedding Provider 失败：{exc_detail(exc)}",
            "检查 AstrBot 是否正常运行，或显式填写 embedding.astrbot_provider_id",
        ) from None
    if not live:
        raise build_error(
            STAGE_RESOLVE,
            "AstrBot 中没有已启用的 Embedding Provider",
            "先在 AstrBot「模型提供商」中添加并启用一个 Embedding Provider，"
            "再把它的 ID 填入 embedding.astrbot_provider_id",
        )
    if len(live) > 1:
        raise build_error(
            STAGE_RESOLVE,
            f"AstrBot 中有 {len(live)} 个已启用的 Embedding Provider（{', '.join(sorted(live))}），"
            "无法判断该用哪个；不会静默选第一个",
            "在 embedding.astrbot_provider_id 显式填写其中一个 ID",
        )
    provider_id, provider = next(iter(live.items()))
    return provider, provider_id


def _describe_kind(provider: Any) -> str:
    kind = type(provider).__name__
    try:
        adapter = provider.meta().type
    except Exception:  # noqa: BLE001
        return kind
    return f"{kind}/{adapter}" if isinstance(adapter, str) and adapter else kind


def read_provider_info(provider: Any, provider_id: str) -> ProviderInfo:
    """只经公开方法读 provider 身份：`meta().type` / `get_model()` / `get_dim()`。"""
    adapter_type = _describe_kind(provider).split("/")[-1]
    model = ""
    try:
        raw_model = provider.get_model()
        model = raw_model.strip() if isinstance(raw_model, str) else ""
    except Exception:  # noqa: BLE001 - 模型名只用于标识，读不到按「不报告」处理
        pass
    try:
        raw_dim = provider.get_dim()
    except Exception as exc:  # noqa: BLE001
        raise build_error(
            STAGE_RESOLVE,
            f"get_dim() 调用失败：{exc_detail(exc)}",
            "检查该 provider 在 AstrBot 中的 embedding_dimensions 配置",
            provider_id=provider_id,
            adapter_type=adapter_type,
            model=model,
        ) from None
    if isinstance(raw_dim, bool) or not isinstance(raw_dim, numbers.Integral):
        raise build_error(
            STAGE_RESOLVE,
            f"get_dim() 返回了非整数（{type(raw_dim).__name__}）",
            "该 provider 未按 AstrBot 的 EmbeddingProvider 契约实现 get_dim()",
            provider_id=provider_id,
            adapter_type=adapter_type,
            model=model,
        )
    return ProviderInfo(provider_id, adapter_type, model, int(raw_dim))


__all__ = [
    "STAGE_DIMENSION",
    "STAGE_EMBED_DOCUMENTS",
    "STAGE_EMBED_QUERY",
    "STAGE_RESOLVE",
    "AstrBotEmbeddingError",
    "ProviderInfo",
    "build_error",
    "exc_detail",
    "load_astrbot_embedding_type",
    "read_provider_info",
    "resolve_astrbot_embedding_provider",
]
