"""检索候选的自适应截断（utils，纯函数零依赖）。

为何存在：固定 top_k 截断对简单/复杂查询都不友好——窄查询被塞噪声、宽查询被饿死。
本模块按已排序候选的相邻分数落差（score-gap / 拐点）动态决定保留多少，让窄查询
少而精、宽查询多而全。纯函数，无 I/O 与外部依赖，便于单测。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.repository.reranker.base import ScoredChunk


def adaptive_cutoff(
    scored: list[ScoredChunk], *, keep_max: int, min_keep: int = 3
) -> list[ScoredChunk]:
    """对按 score 降序的候选做拐点截断，返回前缀子集。

    契约：
        - 入参 scored 必须已按 score 降序；本函数不重排、不修改入参。
        - 至多保留 keep_max 个；至少保留 min_keep 个（候选更少时取其长度）。
        - 在 [min_keep, keep_max) 窗口内寻找最大相邻分数落差，于落差处切断，
          以「相关→不相关」的拐点作为自适应边界；窗口内无候选时退回 keep_max。
        - 空入参返回空列表。
    """
    if not scored:
        return []
    upper = min(keep_max, len(scored))
    floor = min(min_keep, len(scored))
    if upper <= floor:
        return list(scored[:upper])
    best_cut = upper  # 无显著落差时保留到 upper。
    best_gap = -1.0
    for i in range(floor, upper):
        gap = scored[i - 1].score - scored[i].score
        if gap > best_gap:
            best_gap = gap
            best_cut = i
    return list(scored[:best_cut])


__all__ = ["adaptive_cutoff"]
