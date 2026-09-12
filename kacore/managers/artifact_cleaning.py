"""逐页清洗的保守升级规则：页边噪声、结构保护与有出处的脚注分离。

仅在标号、页面位置和正文引用/书目特征同时支持时分离脚注；疑似编号列表原样保留。
原始逐页 Markdown 另外保存，所有脚注 source 偏移始终指向该原始页面。
"""

from __future__ import annotations

import re
from dataclasses import replace

from kacore.domain.footnotes import FootnoteBlock, FootnoteLinkStatus
from kacore.managers.footnote_linking import extract_footnote_candidates, link_footnotes
from kacore.managers.structural_protection import repair_wrapped_text_preserving_blocks

_DOWNLOAD = re.compile(r"^\s*(?:This content downloaded from\b|All use subject to https?://)", re.I)
_BIBLIO = re.compile(
    r"(?:\b(?:Ibid|See|Press|University|Journal|Vol|pp)\b|\b(?:18|19|20)\d{2}\b|[“”\"])", re.I
)
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|§\s*\d|(?:Chapter|Part)\s+[\dIVXLCDM]+\b)", re.I)


def clean_page_structure(raw: str, *, page: int) -> tuple[str, list[FootnoteBlock]]:
    """分离强依据脚注并修复正文；不把普通数字章节当作注释删除。"""
    body, candidates = extract_footnote_candidates(raw, page=page)
    linked = link_footnotes(body, candidates)
    # 候选检测不能证明脚注身份；整区任一条不可信则全部留在正文，避免吞掉末尾正文。
    credible = bool(linked) and all(
        n.link_status == FootnoteLinkStatus.LINKED or _BIBLIO.search(n.text) for n in linked
    )
    if not credible or any(_HEADING.match(line) for line in raw[len(body) :].splitlines()):
        body, linked = raw, []
    lines = body.splitlines()
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    margins = set(nonempty[:4] + nonempty[-4:])
    body = "\n".join(
        line for i, line in enumerate(lines) if not (i in margins and _DOWNLOAD.match(line))
    )
    cleaned = repair_wrapped_text_preserving_blocks(body).strip("\n")
    # 修复换行会改变引用位置，只在同页清洗正文重新定位；source 范围仍指向 raw。
    notes = link_footnotes(
        cleaned,
        [
            replace(n, body_marker_span=None, link_status=FootnoteLinkStatus.UNLINKED)
            for n in linked
        ],
    )
    return cleaned, notes


__all__ = ["clean_page_structure"]
