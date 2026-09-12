"""页边噪声判据：重复标题与单次出版声明，限定位置且保留原文旁车。"""

from __future__ import annotations

import re


def is_publication_footer(line: str) -> bool:
    """只接受以出版标识起始的组合声明，不因正文/书目含 DOI 或版权词而删除。"""
    plain = re.sub(r"[*_`#]", "", line).strip()
    return bool(
        re.match(r"ISSN\b", plain, re.I)
        and re.search(r"\b\d{4}-[\dX]{4}\b", plain, re.I)
        and re.search(r"©|\bcopyright\b", plain, re.I)
        and re.search(r"https?://doi\.org/|\b(?:Group|Limited|Publisher)\b", plain, re.I)
    )


def is_running_heading(line: str, index: int, edge_indices: set[int]) -> bool:
    """只有首尾行的重复无编号标题可覆盖标题保护；正文中的同名标题照常保留。"""
    plain = re.sub(r"^[\s#*_]+", "", line).strip()
    return (
        index in edge_indices
        and bool(re.match(r"^\s*#{1,6}\s", line))
        and not re.match(r"(?:\d|§|Chapter\b|Part\b|Appendix\b)", plain, re.I)
    )


def publication_footer_indices(lines: list[str], margins: set[int]) -> set[int]:
    """版权声明可能折行，连同紧随其后的独立 DOI 一起清理，其他 DOI 保留。"""
    found = {i for i in margins if is_publication_footer(lines[i])}
    for i in list(found):
        for following in range(i + 1, min(len(lines), i + 5)):
            plain = lines[following].strip()
            if not plain:
                continue
            if re.fullmatch(r"(?:<u>)?https?://doi\.org/[^\s<>]+(?:</u>)?", plain):
                found.add(following)
            break
    return found


__all__ = ["is_publication_footer", "is_running_heading", "publication_footer_indices"]
