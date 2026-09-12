"""结构切片的硬预算校验：软目标不拆完整段落，超限时按结构/句界拆分。

所有输出仍是 clean Markdown 的连续字符区间。拆分元数据记录原段落范围，
预算使用可注入 tokenizer；默认估算不代表未知模型的精确输入能力。
"""
from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from kacore.managers.chunk_boundaries import sentence_boundaries
from kacore.managers.chunking import ChunkSpan, parse_markdown_blocks
from kacore.managers.token_budget import TokenBudgetConfig, default_tokenizer

if TYPE_CHECKING:
    from kacore.managers.token_budget import Tokenizer


def _fitting_end(text: str, start: int, end: int, limit: int, counter: Tokenizer) -> int:
    """寻找预算内前缀；不可容纳单字符时明确失败，避免死循环或超限输出。"""
    lo, hi = start, end
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if counter.count(text[start:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    if lo == start:
        raise ValueError("chunk token budget cannot fit one character")
    return lo


def _split_end(
    text: str, start: int, end: int, limit: int, target: int,
    counter: Tokenizer, paragraph_ends: set[int],
) -> tuple[int, str]:
    """段界优先；无可用段界才按句/子句/词/字符退化，尽量均衡剩余分片。"""
    ceiling = _fitting_end(text, start, end, limit, counter)
    total = counter.count(text[start:end])
    ideal = min(target, total / math.ceil(total / limit))
    candidates = [p for p in paragraph_ends if start < p <= ceiling]
    reason = "paragraph_boundary"
    if not candidates:
        candidates = [p for p in sentence_boundaries(text, start, end) if p <= ceiling]
        reason = "sentence_boundary"
    if not candidates:
        candidates = [start + m.end() for m in re.finditer(r"[,;:，；：]\s*", text[start:ceiling])]
        reason = "clause_boundary"
    if not candidates:
        candidates = [start + m.end() for m in re.finditer(r"\s+", text[start:ceiling])]
        reason = "word_boundary"
    if not candidates:
        return ceiling, "character_fallback"
    cut = min(candidates, key=lambda p: abs(counter.count(text[start:p]) - ideal))
    return cut, reason


def limit_chunk_spans(
    text: str,
    spans: list[ChunkSpan],
    *,
    budget: TokenBudgetConfig | None = None,
    tokenizer: Tokenizer | None = None,
) -> list[ChunkSpan]:
    """只在硬上限超限时拆分；目标 token 数用于选界，不是第二道硬上限。"""
    config = budget or TokenBudgetConfig()
    counter = tokenizer or default_tokenizer()
    limit = config.embedding_input_limit - 32
    if limit < 1 or config.target_chunk_tokens < 1:
        raise ValueError("chunk token limit and target must be positive")
    blocks = parse_markdown_blocks(text)
    paragraphs = [b for b in blocks if b.kind == "paragraph"]
    paragraph_ends = {b.end for b in paragraphs}
    output: list[ChunkSpan] = []
    for span in spans:
        start = span.start
        split = counter.count(text[start:span.end]) > limit
        while start < span.end:
            end, reason = span.end, "within_hard_limit"
            if counter.count(text[start:end]) > limit:
                end, reason = _split_end(
                    text, start, end, limit, config.target_chunk_tokens,
                    counter, paragraph_ends,
                )
            actual_start = start + len(text[start:end]) - len(text[start:end].lstrip())
            actual_end = start + len(text[start:end].rstrip())
            parents = [b for b in paragraphs if b.start < end and b.end > start]
            covered = [b for b in blocks if b.start < end and b.end > start]
            metadata = {
                **span.metadata,
                "block_types": list(dict.fromkeys(b.kind for b in covered)),
                "starts_at_section": any(
                    b.kind == "section_heading" and b.start == actual_start for b in covered
                ),
                "starts_at_paragraph": any(b.start == actual_start for b in parents),
                "ends_at_paragraph": actual_end in paragraph_ends,
                "paragraph_ranges": [{"start_char": b.start, "end_char": b.end} for b in parents],
                "token_count": counter.count(text[start:end]),
                "token_measurement": counter.measurement,
                "tokenizer_id": counter.tokenizer_id,
                "budget_split": split,
                "split_reason": reason,
            }
            output.append(ChunkSpan(start, end, metadata))
            start = end
    return output


__all__ = ["limit_chunk_spans"]
