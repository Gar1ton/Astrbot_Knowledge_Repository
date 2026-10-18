"""结构块保护后的行修复（managers 层，纯函数，无 I/O）。

先识别列表/表格/代码块/公式块等结构范围并保持其内部换行不变，再对范围之外的正文执行
断词/单换行修复——修正现状「先把空行间的全部单换行合并，chunking 才拿到已被合并的文本」
的顺序缺陷：结构信息在合并阶段已经丢失，chunking 只能在残局上用正则猜测。

当前由生产抽取或结构切片路径调用；无需新增解析器。

"""
from __future__ import annotations

import re

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_BLOCK_MATH_DELIM_RE = re.compile(r"^\s*\$\$\s*$")

_BLANK_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")
_FALSE_PARAGRAPH_BREAK_RE = re.compile(
    r"(?P<left>[^\s。？！.!?:;])\n\n(?P<right>(?:[\"'“‘(\[])?[a-z])"
)
_DANGLING_BREAK_RE = re.compile(
    r"(?P<left>\b(?:the|a|an|of|to|in|by|with|and|or|between|from))"
    r"\n\n(?P<right>[A-Z0-9])"
)


def _line_is_self_protected(line: str) -> bool:
    """不需要跨行状态即可判断的保护行：列表项、表格行。"""
    return bool(
        _LIST_ITEM_RE.match(line) or _TABLE_ROW_RE.match(line)
        or re.match(r"^\s*(?:#{1,6}\s|§\s*\d|(?:Chapter|Part)\s+[\dIVXLCDM]+\b)", line, re.I)
    )


def protected_line_mask(text: str) -> list[bool]:
    """逐行标记是否属于受保护结构范围（列表/表格/代码块/公式块）。

    代码块（```）与公式块（$$）用开合配对识别，两条定界行之间的全部行（含定界行本身）
    都受保护；列表项与表格行逐行自判定，不要求成块出现也不需要跨行状态。
    """
    lines = text.split("\n")
    mask = [False] * len(lines)
    in_fence = False
    in_math = False
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            mask[idx] = True
            in_fence = not in_fence
            continue
        if in_fence:
            mask[idx] = True
            continue
        if _BLOCK_MATH_DELIM_RE.match(line):
            mask[idx] = True
            in_math = not in_math
            continue
        if in_math:
            mask[idx] = True
            continue
        mask[idx] = _line_is_self_protected(line)
    return mask


def _repair_prose_segment(text: str) -> str:
    """对未受保护的正文片段执行断词修复与单换行合并（镜像 markdown_extractor 的同名算法）。"""
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"(?<=\w)-­\n(?=\w)", "-", text)
    text = re.sub(r"(?<=\w)­\n(?=\w)", "", text)
    paragraphs = re.split(r"(\n[ \t]*\n+)", text)
    repaired: list[str] = []
    for part in paragraphs:
        if not part:
            continue
        if _BLANK_PARAGRAPH_RE.fullmatch(part):
            repaired.append("\n\n")
            continue
        lines = [line.strip() for line in part.split("\n")]
        joined = " ".join(line for line in lines if line)
        joined = re.sub(r"[ \t]+", " ", joined).strip()
        if joined:
            repaired.append(joined)
    result = "".join(repaired)
    result = _DANGLING_BREAK_RE.sub(r"\g<left> \g<right>", result)
    previous = None
    while previous != result:
        previous = result
        result = _FALSE_PARAGRAPH_BREAK_RE.sub(r"\g<left> \g<right>", result)
    return result


def repair_wrapped_text_preserving_blocks(text: str) -> str:
    """结构块保护版的断词/换行修复：保护范围内原样保留，范围外按段落合并单换行。

    契约：受保护范围（列表项/表格行/代码块/公式块）逐行原样输出，内部换行绝不合并；
    范围之外的连续行组整体喂给内部段落修复，行为与
    `markdown_extractor._repair_wrapped_text` 对纯正文段落的处理一致。
    相邻两个不同保护状态的行组之间用单个换行符重新拼接，与原文中二者的行边界一致。
    """
    lines = text.split("\n")
    mask = protected_line_mask(text)

    segments: list[tuple[bool, list[str]]] = []
    for line, protected in zip(lines, mask):
        if segments and segments[-1][0] == protected:
            segments[-1][1].append(line)
        else:
            segments.append((protected, [line]))

    output_parts: list[str] = []
    for protected, seg_lines in segments:
        if protected:
            output_parts.append("\n".join(seg_lines))
        else:
            output_parts.append(_repair_prose_segment("\n".join(seg_lines)))
    return "\n".join(output_parts)


__all__ = [
    "protected_line_mask",
    "repair_wrapped_text_preserving_blocks",
]
