"""聊天端文本切分纯函数（utils 层，零业务依赖）。

从 main.py 抽离：分段（paragraphize）、按块/句切分、消息分页、句边界截断，
供聊天回发与 api 降级摘录共用。

v0.30.0 治本修复：旧句子正则 `[。！？!?\\.](?=\\s|$)` 要求标点后跟空白——中文句号后
无空格 → 整段判定「不可切」→ 落入 `piece[i:i+max_chars]` 字符硬切（长句被拦腰截断的
根因）。现 CJK 句读（。！？，含尾随右引号/括号）不再要求后随空白；超长句先按子句
边界（，、；：,;）切，字符硬切仅作无标点长 token 的最后兜底。
"""
from __future__ import annotations

import re

# CJK 句读直接断句（吸收尾随右引号/括号）；ASCII .!? 仍要求后随空白（防拆小数/缩写）。
_SENTENCE_RE = re.compile(r".+?(?:[。！？][”』」）)]*|[.!?](?=\s|$)|$)", re.S)
# 子句边界：超长句的次级切分点。
_CLAUSE_RE = re.compile(r".+?(?:[，、；：,;]|$)", re.S)

_SENTENCE_END_CHARS = "。！？.!?"
_CLAUSE_END_CHARS = "，、；：,;"


def _hard_cut(piece: str, max_chars: int) -> list[str]:
    return [piece[i : i + max_chars] for i in range(0, len(piece), max_chars)]


def _split_oversized_sentence(sentence: str, max_chars: int) -> list[str]:
    """超长单句：先按子句边界贪心打包，仍超长的子句才字符硬切（最后兜底）。"""
    clauses = [c for c in (m.strip() for m in _CLAUSE_RE.findall(sentence)) if c]
    if len(clauses) <= 1:
        return _hard_cut(sentence, max_chars)
    out: list[str] = []
    current = ""
    for clause in clauses:
        candidate = f"{current}{clause}" if current else clause
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            out.append(current)
        if len(clause) <= max_chars:
            current = clause
        else:
            out.extend(_hard_cut(clause, max_chars))
            current = ""
    if current:
        out.append(current)
    return out


def split_by_sentences(text: str, *, max_chars: int) -> list[str]:
    """按句子边界把文本切成 ≤max_chars 的片段（句子间贪心打包，保持原序）。"""
    sentences = [s for s in (m.strip() for m in _SENTENCE_RE.findall(text)) if s]
    if not sentences:
        sentences = [text]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}" if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(sentence) <= max_chars:
            current = sentence
        else:
            chunks.extend(_split_oversized_sentence(sentence, max_chars))
            current = ""
    if current:
        chunks.append(current)
    return chunks


def split_by_blocks(text: str, *, max_chars: int) -> list[str]:
    """按空行段落切块并贪心打包成 ≤max_chars 的片段；超长段落降级到句子切分。"""
    chunks: list[str] = []
    current = ""
    for block in [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]:
        pieces = (
            [block]
            if len(block) <= max_chars
            else split_by_sentences(block, max_chars=max_chars)
        )
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(piece) <= max_chars:
                current = piece
            else:
                chunks.extend(_split_oversized_sentence(piece, max_chars))
                current = ""
    if current:
        chunks.append(current)
    return chunks


def split_message_text(text: str, *, limit: int) -> list[str]:
    """消息分页：超过 limit 时按块切分并加 `（i/n）` 前缀（预留 24 字符前缀余量）。"""
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= limit:
        return [cleaned]
    parts = split_by_blocks(cleaned, max_chars=limit - 24)
    if len(parts) == 1:
        return parts
    total = len(parts)
    return [f"（{idx}/{total}）\n{part}" for idx, part in enumerate(parts, start=1)]


def paragraphize(text: str, *, max_chars: int) -> str:
    """把超长无换行的段落按句边界重新分段（空行分隔），已有结构的段落原样保留。"""
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    if not blocks:
        return ""
    paragraphs: list[str] = []
    for block in blocks:
        if len(block) <= max_chars or "\n" in block:
            paragraphs.append(block)
            continue
        paragraphs.extend(split_by_sentences(block, max_chars=max_chars))
    return "\n\n".join(paragraphs)


def clip_at_sentence(text: str, max_chars: int) -> str:
    """截断到 max_chars 内，优先在句读、其次子句边界收尾，加省略号。

    边界须落在窗口后 3/4 段之外（≥ max_chars//4），防止截得过短；无可用边界才
    退回窗口末尾硬截。
    """
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    window = cleaned[:max_chars]
    for boundary_chars in (_SENTENCE_END_CHARS, _CLAUSE_END_CHARS):
        idx = max(window.rfind(ch) for ch in boundary_chars)
        if idx >= max_chars // 4:
            return window[: idx + 1] + "…"
    return window + "…"


__all__ = [
    "split_by_sentences",
    "split_by_blocks",
    "split_message_text",
    "paragraphize",
    "clip_at_sentence",
]
