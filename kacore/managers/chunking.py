"""Structural clean.md chunking utilities.

The chunker works after PDF/text cleaning. It parses clean Markdown into structural
blocks, assigns section metadata, then packs chunks only on block boundaries unless a
single block is too large and must fall back to citation-aware sentence splitting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CHUNK_SCHEMA = "clean_md_structural_v3"

_SENTENCE_ENDERS = "。？！.?!"
_SECTION_LABEL_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?(T\d{1,3}[A-Za-z]?|\d+(?:\.\d+){0,4})(?:\.)?(?:\*\*)?"
)
_INLINE_ANCHOR_RE = re.compile(
    r"(?<!\S)(\*\*(?:T\d{1,3}[A-Za-z]?|Scholium(?:\s+[a-z])?\.|Lemma(?:\s+[a-z])?\.|"
    r"Speculative strategy\s+[a-z]\.)\*\*)",
    re.IGNORECASE,
)
_THESIS_RE = re.compile(r"^\*\*(T\d{1,3}[A-Za-z]?)\*\*", re.IGNORECASE)
_NUMBERED_MD_RE = re.compile(
    r"^(?P<prefix>#+\s*)?(?P<strong>\*\*)?(?P<label>\d+(?:\.\d+){0,4})(?:\.)?(?(strong)\*\*)"
    r"(?:\s+|$)(?P<title>.*)$"
)
_NUMBERED_BOLD_LINE_RE = re.compile(
    r"^\*\*(?P<label>\d+(?:\.\d+){0,4})(?:\.)?\s+(?P<title>[^*\n]+?)\*\*$"
)
_ITALIC_NUMBERED_RE = re.compile(
    r"^_(?P<label>\d+(?:\.\d+){0,4})\._\s*(?P<title>.*)$"
)
_APPENDIX_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?(?P<label>Appendix\s+[A-Z])(?:\.)?(?:\*\*)?"
    r"(?:[:.\s]+(?P<title>.*))?$",
    re.I,
)
_APPENDIX_SUBSECTION_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?(?P<label>[A-Z]\.\d+(?:\.\d+){0,3})(?:\.)?(?:\*\*)?"
    r"(?:\s+|$)(?P<title>.*)$"
)
_SUBSECTION_RE = re.compile(
    r"^\*\*(?P<label>Scholium(?:\s+[a-z])?\.|Lemma(?:\s+[a-z])?\.|"
    r"Speculative strategy\s+[a-z]\.)\*\*",
    re.IGNORECASE,
)
_FIGURE_RE = re.compile(r"^(?:\*\*)?(?P<label>Fig(?:ure)?\.?\s*\d+[A-Za-z]?\.?)", re.I)
_TABLE_RE = re.compile(r"^(?:\*\*)?(?P<label>Table\s*\d+[A-Za-z]?\.?)", re.I)
_EQUATION_LABEL_RE = re.compile(r"^(?:\*\*)?(?P<label>Eq(?:uation)?\.?\s*\d+[A-Za-z]?\.?)", re.I)
_ANCHOR_LABEL_RE = re.compile(
    r"\b(?P<label>(?:Fig(?:ure)?|Table|Eq(?:uation)?)\.?\s*\d+[A-Za-z]?\.?)",
    re.I,
)
_REFERENCES_RE = re.compile(r"^(?:#+\s*)?(?:\*\*)?references(?:\*\*)?$", re.I)
_ABBREVIATION_TAIL_RE = re.compile(
    r"(?:\bet al|fig|figure|eq|e\.g|i\.e|no|vol|pp|dr|mr|mrs|ms|prof|vs)\.$",
    re.I,
)


@dataclass(frozen=True)
class TextBlock:
    start: int
    end: int
    kind: str
    text: str
    label: str = ""
    title: str = ""
    level: int = 0


@dataclass(frozen=True)
class SectionSpan:
    label: str
    start: int
    end: int
    section_type: str
    path: tuple[str, ...] = field(default_factory=tuple)
    title: str = ""
    level: int = 0


@dataclass(frozen=True)
class SubsectionSpan:
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class ChunkSpan:
    start: int
    end: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChunkingPolicy:
    chunk_size: int = 1000

    @property
    def target_min(self) -> int:
        return max(1, int(self.chunk_size * 0.7))

    @property
    def target_max(self) -> int:
        return max(1, int(self.chunk_size * 1.6))

    @property
    def soft_max(self) -> int:
        return max(1, int(self.chunk_size * 2.2))

    @property
    def hard_limit(self) -> int:
        return max(1, int(self.chunk_size * 3.0))

    @property
    def min_chunk_chars(self) -> int:
        return max(160, int(self.chunk_size * 0.3))


def parse_markdown_blocks(md: str) -> list[TextBlock]:
    """Parse clean Markdown into exact-offset structural blocks."""
    spans = _paragraph_spans(md)
    split_spans = _split_spans_at_inline_anchors(md, spans)
    blocks: list[TextBlock] = []
    for start, end in split_spans:
        text = md[start:end]
        if not text.strip():
            continue
        blocks.append(_classify_block(start, end, text))
    return blocks


def build_structural_chunk_spans(
    md: str, *, chunk_size: int = 1000
) -> tuple[list[ChunkSpan], list[SectionSpan], list[SubsectionSpan]]:
    blocks = parse_markdown_blocks(md)
    policy = ChunkingPolicy(chunk_size=chunk_size)
    sections = build_section_spans(md, blocks)
    subsections = build_subsection_spans(md, blocks, sections)
    block_units = _expand_oversized_blocks(md, blocks, policy)
    chunks = pack_blocks_into_chunks(md, block_units, sections, subsections, policy)
    return chunks, sections, subsections


def build_section_spans(md: str, blocks: list[TextBlock]) -> list[SectionSpan]:
    headings = [block for block in blocks if block.kind == "section_heading"]
    if not headings:
        return [
            SectionSpan("front_matter", 0, len(md), "front_matter", ("front_matter",))
        ]

    sections: list[SectionSpan] = []
    first = headings[0]
    if first.start > 0:
        sections.append(
            SectionSpan(
                "front_matter",
                0,
                first.start,
                "front_matter",
                ("front_matter",),
                "front matter",
                0,
            )
        )

    stack: list[TextBlock] = []
    for idx, heading in enumerate(headings):
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        stack.append(heading)
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(md)
        path = tuple(block.label for block in stack if block.label)
        sections.append(
            SectionSpan(
                heading.label,
                heading.start,
                end,
                _section_type(heading),
                path or (heading.label,),
                heading.title,
                heading.level,
            )
        )
    return sections


def build_subsection_spans(
    md: str, blocks: list[TextBlock], sections: list[SectionSpan]
) -> list[SubsectionSpan]:
    subsection_blocks = [block for block in blocks if block.kind == "subsection_heading"]
    spans: list[SubsectionSpan] = []
    for idx, block in enumerate(subsection_blocks):
        section = section_for_position(sections, block.start)
        next_start = (
            subsection_blocks[idx + 1].start
            if idx + 1 < len(subsection_blocks)
            else (section.end if section else len(md))
        )
        if section is not None:
            next_start = min(next_start, section.end)
        spans.append(
            SubsectionSpan(_normalize_subsection_label(block.label), block.start, next_start)
        )
    return spans


def pack_blocks_into_chunks(
    md: str,
    blocks: list[TextBlock],
    sections: list[SectionSpan],
    subsections: list[SubsectionSpan],
    policy: ChunkingPolicy,
) -> list[ChunkSpan]:
    raw: list[tuple[int, int, list[TextBlock]]] = []
    cur: list[TextBlock] = []

    def flush() -> None:
        nonlocal cur
        if cur:
            raw.append((cur[0].start, cur[-1].end, cur))
            cur = []

    for block in blocks:
        if block.kind == "section_heading" and cur:
            flush()
        if not cur:
            cur = [block]
            continue
        candidate_len = block.end - cur[0].start
        cur_len = cur[-1].end - cur[0].start
        same_section = _same_section(sections, cur[0].start, block.start)
        if (
            not same_section
            or (candidate_len > policy.target_max and cur_len >= policy.target_min)
            or candidate_len > policy.soft_max
        ):
            flush()
            cur = [block]
        else:
            cur.append(block)
    flush()

    merged = _merge_short_chunks(raw, sections, policy)
    return [
        ChunkSpan(start, end, _chunk_metadata(md, start, end, chunk_blocks, sections, subsections))
        for start, end, chunk_blocks in merged
    ]


def section_for_position(sections: list[SectionSpan], pos: int) -> SectionSpan | None:
    for section in sections:
        if section.start <= pos < section.end:
            return section
    return sections[-1] if sections else None


def _paragraph_spans(md: str) -> list[tuple[int, int]]:
    if not md.strip():
        return []
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in re.finditer(r"\n[ \t]*\n[ \t\n]*", md):
        if match.start() > pos:
            spans.append((pos, match.start()))
        pos = match.end()
    if pos < len(md):
        spans.append((pos, len(md)))
    if len(spans) <= 1 and "\n" in md:
        spans = []
        pos = 0
        for match in re.finditer(r"\n+", md):
            if match.start() > pos:
                spans.append((pos, match.start()))
            pos = match.end()
        if pos < len(md):
            spans.append((pos, len(md)))
    return spans


def _split_spans_at_inline_anchors(
    md: str, spans: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    split: list[tuple[int, int]] = []
    for start, end in spans:
        cuts = [
            start + match.start()
            for match in _INLINE_ANCHOR_RE.finditer(md[start:end])
            if start + match.start() > start
        ]
        pos = start
        for cut in cuts:
            if cut > pos:
                split.append((pos, cut))
            pos = cut
        if pos < end:
            split.append((pos, end))
    return split


def _classify_block(start: int, end: int, text: str) -> TextBlock:
    stripped = text.strip()
    label = ""
    title = ""
    level = 0

    if _REFERENCES_RE.match(stripped):
        return TextBlock(start, end, "section_heading", text, "References", "References", 1)

    thesis = _THESIS_RE.match(stripped)
    if thesis:
        label = thesis.group(1).upper()
        title = _strip_markup(stripped[thesis.end() :]).strip()
        return TextBlock(start, end, "section_heading", text, label, title, 1)

    appendix = _appendix_heading(stripped)
    if appendix is not None:
        label, title, level = appendix
        return TextBlock(start, end, "section_heading", text, label, title, level)

    numbered = _numbered_heading(stripped)
    if numbered is not None:
        label, title = numbered
        level = label.count(".") + 1
        return TextBlock(start, end, "section_heading", text, label, title, level)

    subsection = _SUBSECTION_RE.match(stripped)
    if subsection:
        return TextBlock(
            start,
            end,
            "subsection_heading",
            text,
            _normalize_subsection_label(subsection.group("label")),
            "",
            0,
        )

    fig = _FIGURE_RE.match(stripped)
    if fig:
        return TextBlock(start, end, "figure_caption", text, fig.group("label"), "", 0)

    table = _TABLE_RE.match(stripped)
    if table:
        return TextBlock(start, end, "table_caption", text, table.group("label"), "", 0)

    equation_label = _EQUATION_LABEL_RE.match(stripped)
    if equation_label:
        return TextBlock(start, end, "equation", text, equation_label.group("label"), "", 0)

    if _looks_like_list_item(stripped):
        return TextBlock(start, end, "list_item", text)
    if _looks_like_equation(stripped):
        return TextBlock(start, end, "equation", text)
    return TextBlock(start, end, "paragraph", text)


def _appendix_heading(stripped: str) -> tuple[str, str, int] | None:
    appendix = _APPENDIX_RE.match(stripped)
    if appendix:
        label = _strip_markup(appendix.group("label")).title()
        title = _strip_markup(appendix.group("title") or "").strip()
        return label, title, 1
    subsection = _APPENDIX_SUBSECTION_RE.match(stripped)
    if not subsection:
        return None
    label = subsection.group("label")
    title = _strip_markup(subsection.group("title")).strip()
    if not _looks_like_heading_title(title):
        return None
    return label, title, label.count(".") + 1


def _numbered_heading(stripped: str) -> tuple[str, str] | None:
    bold_line = _NUMBERED_BOLD_LINE_RE.match(stripped)
    if bold_line:
        label = bold_line.group("label")
        title = _strip_markup(bold_line.group("title")).strip()
        if _valid_numeric_section_label(label) and _looks_like_heading_title(title):
            return label, title
        return None

    italic = _ITALIC_NUMBERED_RE.match(stripped)
    if italic:
        label = italic.group("label")
        title = _strip_markup(italic.group("title")).strip()
        if _valid_numeric_section_label(label) and _looks_like_heading_title(title):
            return label, title
        return None
    match = _NUMBERED_MD_RE.match(stripped)
    if not match:
        return None
    label = match.group("label")
    title = _strip_markup(match.group("title")).strip()
    if _valid_numeric_section_label(label) and _looks_like_heading_title(title):
        return label, title
    return None


def _valid_numeric_section_label(label: str) -> bool:
    parts = label.split(".")
    if not parts or len(parts) > 5:
        return False
    for idx, part in enumerate(parts):
        if not part.isdigit():
            return False
        if part.startswith("0") or int(part) <= 0:
            return False
        if idx == 0 and int(part) > 30:
            return False
        if idx > 0 and int(part) > 99:
            return False
    return True


def _looks_like_heading_title(title: str) -> bool:
    title = _strip_markup(title)
    if len(title) < 2 or len(title) > 180:
        return False
    if _looks_like_equation(title):
        return False
    word_count = len(re.findall(r"[A-Za-z][A-Za-z0-9-]*|[\u3400-\u4dbf\u4e00-\u9fff]", title))
    if word_count > 14:
        return False
    if re.search(r"[.!?]\s+\S", title) or title.rstrip().endswith((".", "!", "?")):
        return False
    if title.count(",") > 1 or title.count(";") > 0:
        return False
    alpha_count = sum(1 for char in title if char.isalpha())
    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", title))
    digit_count = sum(1 for char in title if char.isdigit())
    if alpha_count + cjk_count < 2:
        return False
    if digit_count > alpha_count + cjk_count and digit_count > 2:
        return False
    if re.fullmatch(r"[\d\s.,;:()\\/\-+*=<>%]+", title):
        return False
    return True


def _section_type(block: TextBlock) -> str:
    if block.label.upper().startswith("T"):
        return "thesis"
    if block.label.lower() == "references":
        return "references"
    if block.label == "front_matter":
        return "front_matter"
    if block.label.lower().startswith("appendix"):
        return "appendix"
    return "numbered_section"


def _expand_oversized_blocks(
    md: str, blocks: list[TextBlock], policy: ChunkingPolicy
) -> list[TextBlock]:
    expanded: list[TextBlock] = []
    for block in blocks:
        if (block.end - block.start) <= policy.hard_limit:
            expanded.append(block)
            continue
        for idx, (start, end) in enumerate(
            _citation_aware_sentence_spans(md, block.start, block.end, policy)
        ):
            expanded.append(
                TextBlock(
                    start,
                    end,
                    block.kind if idx == 0 else "paragraph",
                    md[start:end],
                    block.label if idx == 0 else "",
                    block.title if idx == 0 else "",
                    block.level,
                )
            )
    return expanded


def _citation_aware_sentence_spans(
    md: str, start: int, end: int, policy: ChunkingPolicy
) -> list[tuple[int, int]]:
    boundaries = _sentence_boundaries(md, start, end)
    if not boundaries or boundaries[-1] != end:
        boundaries.append(end)
    units: list[tuple[int, int]] = []
    cursor = start
    for boundary in boundaries:
        if boundary > cursor:
            units.append((cursor, boundary))
            cursor = boundary

    spans: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end: int | None = None
    for unit_start, unit_end in units:
        if (unit_end - unit_start) > policy.hard_limit:
            if cur_start is not None and cur_end is not None:
                spans.append((cur_start, cur_end))
                cur_start = cur_end = None
            spans.extend(_word_spans(md, unit_start, unit_end, policy.target_max))
            continue
        if cur_start is None:
            cur_start, cur_end = unit_start, unit_end
        elif (
            (unit_end - cur_start) > policy.target_max
            and (cur_end - cur_start) >= policy.target_min  # type: ignore[operator]
        ):
            spans.append((cur_start, cur_end))  # type: ignore[arg-type]
            cur_start, cur_end = unit_start, unit_end
        elif (unit_end - cur_start) > policy.hard_limit:
            spans.append((cur_start, cur_end))  # type: ignore[arg-type]
            cur_start, cur_end = unit_start, unit_end
        else:
            cur_end = unit_end
    if cur_start is not None and cur_end is not None:
        spans.append((cur_start, cur_end))
    return spans


def _sentence_boundaries(md: str, start: int, end: int) -> list[int]:
    boundaries: list[int] = []
    depth = 0
    for idx in range(start, end):
        char = md[idx]
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char not in _SENTENCE_ENDERS:
            continue
        if char == "." and _should_skip_period(md, start, end, idx, depth):
            continue
        boundaries.append(idx + 1)
    return boundaries


def _should_skip_period(md: str, start: int, end: int, idx: int, depth: int) -> bool:
    prev_char = md[idx - 1] if idx > start else ""
    next_char = md[idx + 1] if idx + 1 < end else ""
    if prev_char.isdigit() and next_char.isdigit():
        return True
    lookbehind = md[max(start, idx - 24) : idx + 1].lower()
    if _ABBREVIATION_TAIL_RE.search(lookbehind):
        return True
    next_nonspace = _next_nonspace(md, idx + 1, end)
    if next_nonspace in {",", ";", ":"}:
        return True
    if depth > 0 and next_nonspace not in {")", "]", "}"}:
        return True
    return False


def _word_spans(md: str, start: int, end: int, target_max: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    while (end - cursor) > target_max:
        window_end = min(end, cursor + target_max)
        cut = max(
            (match.end() for match in re.finditer(r"\s+", md[cursor:window_end])),
            default=0,
        )
        cut_pos = window_end if cut <= 0 else cursor + cut
        spans.append((cursor, cut_pos))
        cursor = cut_pos
    if cursor < end:
        spans.append((cursor, end))
    return spans


def _merge_short_chunks(
    chunks: list[tuple[int, int, list[TextBlock]]],
    sections: list[SectionSpan],
    policy: ChunkingPolicy,
) -> list[tuple[int, int, list[TextBlock]]]:
    merged: list[tuple[int, int, list[TextBlock]]] = []
    idx = 0
    while idx < len(chunks):
        start, end, blocks = chunks[idx]
        while idx + 1 < len(chunks) and (end - start) < policy.min_chunk_chars:
            next_chunk = chunks[idx + 1]
            if not _can_merge_forward(sections, start, end, blocks, next_chunk):
                break
            if (next_chunk[1] - start) > policy.hard_limit:
                break
            end = next_chunk[1]
            blocks = blocks + next_chunk[2]
            idx += 1
        if (
            merged
            and (end - start) < policy.min_chunk_chars
            and _same_section(sections, merged[-1][0], start)
            and (end - merged[-1][0]) <= policy.soft_max
        ):
            prev_start, _, prev_blocks = merged[-1]
            merged[-1] = (prev_start, end, prev_blocks + blocks)
        else:
            merged.append((start, end, blocks))
        idx += 1
    return merged


def _can_merge_forward(
    sections: list[SectionSpan],
    start: int,
    end: int,
    blocks: list[TextBlock],
    next_chunk: tuple[int, int, list[TextBlock]],
) -> bool:
    if _same_section(sections, start, next_chunk[0]):
        return True
    if blocks and _same_section(sections, blocks[-1].start, next_chunk[0]):
        return True
    if not _is_standalone_section_heading(blocks, start, end):
        return False
    current = section_for_position(sections, start)
    next_section = section_for_position(sections, next_chunk[0])
    if current is None or next_section is None:
        return False
    return _is_descendant_section(current, next_section)


def _is_standalone_section_heading(
    blocks: list[TextBlock], start: int, end: int
) -> bool:
    return (
        len(blocks) == 1
        and blocks[0].kind == "section_heading"
        and blocks[0].start == start
        and blocks[0].end == end
    )


def _chunk_metadata(
    md: str,
    start: int,
    end: int,
    blocks: list[TextBlock],
    sections: list[SectionSpan],
    subsections: list[SubsectionSpan],
) -> dict[str, Any]:
    covered_sections = _sections_for_span(sections, start, end)
    section = _section_for_span(covered_sections, start, end) or section_for_position(
        sections, start
    )
    subsection = _subsection_for_span(subsections, start, end)
    block_types = list(dict.fromkeys(block.kind for block in blocks))
    metadata: dict[str, Any] = {
        "chunk_schema": CHUNK_SCHEMA,
        "block_types": block_types,
        "starts_at_section": bool(blocks and blocks[0].kind == "section_heading"),
        "ends_at_paragraph": bool(blocks and blocks[-1].kind == "paragraph"),
    }
    if section is not None:
        metadata.update(
            {
                "section_type": section.section_type,
                "section_label": section.label,
                "section_path": list(section.path),
                "section_title": section.title,
                "section_level": section.level,
                "section_start_char": section.start,
                "section_end_char": section.end,
            }
        )
    if covered_sections:
        metadata["section_labels"] = list(
            dict.fromkeys(section.label for section in covered_sections)
        )
        metadata["section_paths"] = [
            list(section.path) for section in covered_sections if section.path
        ]
    if subsection is not None:
        metadata["subsection_label"] = subsection.label
        metadata["subsection_start_char"] = subsection.start
        metadata["subsection_end_char"] = subsection.end
    anchor = _chunk_anchor(md[start:end])
    if anchor:
        metadata["anchor_label"] = anchor
    anchor_labels = _chunk_anchor_labels(md[start:end], blocks)
    if anchor_labels:
        metadata["anchor_labels"] = anchor_labels
    return metadata


def _sections_for_span(
    sections: list[SectionSpan], start: int, end: int
) -> list[SectionSpan]:
    return [
        section
        for section in sections
        if section.start < end and section.end > start
    ]


def _section_for_span(
    sections: list[SectionSpan], start: int, end: int
) -> SectionSpan | None:
    best: SectionSpan | None = None
    best_overlap = 0
    best_depth = -1
    for section in sections:
        overlap = max(0, min(end, section.end) - max(start, section.start))
        depth = len(section.path)
        if overlap > best_overlap or (overlap == best_overlap and depth > best_depth):
            best = section
            best_overlap = overlap
            best_depth = depth
    return best


def _subsection_for_span(
    subsections: list[SubsectionSpan], start: int, end: int
) -> SubsectionSpan | None:
    best: SubsectionSpan | None = None
    best_overlap = 0
    for subsection in subsections:
        overlap = max(0, min(end, subsection.end) - max(start, subsection.start))
        if overlap > best_overlap:
            best = subsection
            best_overlap = overlap
    return best


def _same_section(sections: list[SectionSpan], left_pos: int, right_pos: int) -> bool:
    left = section_for_position(sections, left_pos)
    right = section_for_position(sections, right_pos)
    if left is None or right is None:
        return left is right
    return left.label == right.label and left.start == right.start


def _is_descendant_section(parent: SectionSpan, child: SectionSpan) -> bool:
    return (
        bool(parent.path)
        and len(child.path) > len(parent.path)
        and child.path[: len(parent.path)] == parent.path
    )


def _chunk_anchor(text: str) -> str:
    stripped = text.lstrip()
    for regex in (_THESIS_RE, _FIGURE_RE, _TABLE_RE, _EQUATION_LABEL_RE):
        match = regex.match(stripped)
        if match:
            return _normalize_anchor_label(match.group(1))
    subsection = _SUBSECTION_RE.match(stripped)
    if subsection:
        return _normalize_subsection_label(subsection.group("label"))
    return ""


def _chunk_anchor_labels(text: str, blocks: list[TextBlock]) -> list[str]:
    labels: list[str] = []
    for block in blocks:
        if block.kind in {"figure_caption", "table_caption", "equation"} and block.label:
            labels.append(_normalize_anchor_label(block.label))
    labels.extend(
        _normalize_anchor_label(match.group("label"))
        for match in _ANCHOR_LABEL_RE.finditer(text)
    )
    return list(dict.fromkeys(label for label in labels if label))


def _normalize_anchor_label(label: str) -> str:
    label = _strip_markup(label)
    label = re.sub(r"\s+", " ", label).strip().rstrip(".")
    match = re.match(
        r"^(Fig(?:ure)?|Table|Eq(?:uation)?)\.?\s*(\d+[A-Za-z]?)$",
        label,
        flags=re.I,
    )
    if not match:
        return label.upper()
    kind = match.group(1).lower().rstrip(".")
    number = match.group(2).upper()
    if kind.startswith("fig"):
        return f"FIGURE {number}"
    if kind.startswith("tab"):
        return f"TABLE {number}"
    return f"EQUATION {number}"


def _normalize_subsection_label(label: str) -> str:
    label = _strip_markup(label).strip()
    label = re.sub(r"\s+", " ", label)
    return label.rstrip(".")


def _strip_markup(text: str) -> str:
    text = text.replace("*", "").replace("_", "").replace("`", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_list_item(stripped: str) -> bool:
    return bool(re.match(r"^(?:[-*+]|\d+[.)])\s+", stripped))


def _looks_like_equation(stripped: str) -> bool:
    if len(stripped) > 120:
        return False
    return bool(re.search(r"[=∑Σ√≤≥±×÷]", stripped))


def _next_nonspace(md: str, start: int, end: int) -> str:
    cursor = start
    while cursor < end and md[cursor].isspace():
        cursor += 1
    return md[cursor] if cursor < end else ""


__all__ = [
    "CHUNK_SCHEMA",
    "ChunkSpan",
    "ChunkingPolicy",
    "SectionSpan",
    "SubsectionSpan",
    "TextBlock",
    "build_section_spans",
    "build_structural_chunk_spans",
    "build_subsection_spans",
    "pack_blocks_into_chunks",
    "parse_markdown_blocks",
    "section_for_position",
]
