"""召回模式公共常量与兼容规范化（core 横切支撑）。

后端 API、Research 服务与 AstrBot 薄壳共同消费这些值，避免公开模式名在多入口漂移。
v0.30.1 将 ``high_precision`` 更名为语义准确的 ``graph_mixed``；旧输入仅兼容一版，
所有内部控制流与响应统一使用新值。
"""
from __future__ import annotations

MODE_DEFAULT = "default"
MODE_ENHANCED = "enhanced"
MODE_GRAPH_MIXED = "graph_mixed"
MODE_GRAPH_ONLY = "graph_only"
MODE_DEEP_THINKING = "deep_thinking"

LEGACY_MODE_HIGH_PRECISION = "high_precision"

VALID_RETRIEVAL_MODES = frozenset(
    {
        MODE_DEFAULT,
        MODE_ENHANCED,
        MODE_GRAPH_MIXED,
        MODE_GRAPH_ONLY,
        MODE_DEEP_THINKING,
    }
)
STRICT_COLLECTION_MODES = frozenset(
    {MODE_GRAPH_MIXED, MODE_GRAPH_ONLY, MODE_DEEP_THINKING}
)


def normalize_retrieval_mode(value: str) -> tuple[str, bool]:
    """返回 ``(规范模式, 是否命中旧别名)``；不识别的值原样返回供调用方校验。"""
    mode = str(value or MODE_DEFAULT).strip() or MODE_DEFAULT
    if mode == LEGACY_MODE_HIGH_PRECISION:
        return MODE_GRAPH_MIXED, True
    return mode, False


__all__ = [
    "LEGACY_MODE_HIGH_PRECISION",
    "MODE_DEEP_THINKING",
    "MODE_DEFAULT",
    "MODE_ENHANCED",
    "MODE_GRAPH_MIXED",
    "MODE_GRAPH_ONLY",
    "STRICT_COLLECTION_MODES",
    "VALID_RETRIEVAL_MODES",
    "normalize_retrieval_mode",
]
