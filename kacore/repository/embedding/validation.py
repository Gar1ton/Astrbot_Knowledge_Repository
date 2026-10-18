"""Embedding 返回值校验；网络响应与磁盘缓存共用有限数值和批次契约。"""
from __future__ import annotations

import math
import numbers
from typing import Any


class EmbeddingValidationError(ValueError):
    """向量违反契约；错误只含结构信息，不包含输入、向量或响应正文。"""


def validate_vectors(
    raw: Any, expected_count: int, dimension: int | None = None,
) -> list[list[float]]:
    """校验整个批次再返回；拒绝空向量、布尔值、非有限数值和不一致的维度。"""
    if not isinstance(raw, list) or len(raw) != expected_count:
        raise EmbeddingValidationError(f"Embedding 批量结果数量应为 {expected_count}")
    for index, vector in enumerate(raw):
        if not isinstance(vector, list) or not vector:
            raise EmbeddingValidationError(f"第 {index} 条 embedding 应为非空数值列表")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise EmbeddingValidationError(
                f"Embedding 维度不一致：应为 {dimension}，实际为 {len(vector)}"
            )
        for value in vector:
            try:
                finite = (
                    not isinstance(value, bool)
                    and isinstance(value, numbers.Real)
                    and math.isfinite(value)
                )
            except (OverflowError, TypeError, ValueError):
                finite = False
            if not finite:
                raise EmbeddingValidationError(f"第 {index} 条 embedding 含无效数值")
    return raw


def parse_openai_vectors(raw: Any, expected_count: int) -> list[list[float]]:
    """按唯一且完整的 index 恢复输入顺序，不接受缺项、重复项或隐式 index。"""
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list) or len(data) != expected_count:
        raise EmbeddingValidationError(f"Embedding 响应 data 数量应为 {expected_count}")
    ordered: list[Any] = [None] * expected_count
    seen: set[int] = set()
    for item in data:
        index = item.get("index") if isinstance(item, dict) else None
        if (
            isinstance(index, bool) or not isinstance(index, int)
            or not 0 <= index < expected_count or index in seen
        ):
            raise EmbeddingValidationError("Embedding 响应 index 必须唯一且完整覆盖输入")
        seen.add(index)
        ordered[index] = item.get("embedding")
    return validate_vectors(ordered, expected_count)


__all__ = ["EmbeddingValidationError", "parse_openai_vectors", "validate_vectors"]
