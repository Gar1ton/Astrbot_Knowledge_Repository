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
MODE_FULLTEXT = "fulltext"

LEGACY_MODE_HIGH_PRECISION = "high_precision"

VALID_RETRIEVAL_MODES = frozenset(
    {
        MODE_DEFAULT,
        MODE_ENHANCED,
        MODE_GRAPH_MIXED,
        MODE_GRAPH_ONLY,
        MODE_DEEP_THINKING,
        MODE_FULLTEXT,
    }
)
STRICT_COLLECTION_MODES = frozenset(
    {MODE_GRAPH_MIXED, MODE_GRAPH_ONLY, MODE_DEEP_THINKING}
)
# 与 STRICT_COLLECTION_MODES 对称：这些模式必须绑定**一篇具体文档**（doc_id），
# 光有 collection 不足以执行。没有 doc_id 概念的入口（AstrBot research 工具）见到
# 这些模式必须降级，而不是把请求透传下去撞 ValueError。
STRICT_DOCUMENT_MODES = frozenset({MODE_FULLTEXT})

# 全文检索的**确认阈值，不是上限**——超过它只要求调用方显式确认一次，确认后照常读完整篇。
# 全项目唯一真相源：HTTP 层与前端/skill 一律从响应里学这个数字，不得各自复制字面量。
FULLTEXT_CONFIRM_THRESHOLD_CHARS = 60_000


def normalize_retrieval_mode(value: str) -> tuple[str, bool]:
    """返回 ``(规范模式, 是否命中旧别名)``；不识别的值原样返回供调用方校验。"""
    mode = str(value or MODE_DEFAULT).strip() or MODE_DEFAULT
    if mode == LEGACY_MODE_HIGH_PRECISION:
        return MODE_GRAPH_MIXED, True
    return mode, False


__all__ = [
    "FULLTEXT_CONFIRM_THRESHOLD_CHARS",
    "LEGACY_MODE_HIGH_PRECISION",
    "MODE_DEEP_THINKING",
    "MODE_DEFAULT",
    "MODE_ENHANCED",
    "MODE_FULLTEXT",
    "MODE_GRAPH_MIXED",
    "MODE_GRAPH_ONLY",
    "STRICT_COLLECTION_MODES",
    "STRICT_DOCUMENT_MODES",
    "VALID_RETRIEVAL_MODES",
    "normalize_retrieval_mode",
]
