"""派生制品的原始页与脚注旁车；保留全文阅读和重切所需的信息，不改 PDF。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from kacore.domain.footnotes import FootnoteBlock

if TYPE_CHECKING:
    from kacore.managers.markdown_extractor import MarkdownArtifact

PROVENANCE_FILE = "provenance.json"
PROCESSING_VERSION = "cleaning-v2"


def save_provenance(directory: Path, artifact: MarkdownArtifact) -> None:
    """用临时文件替换旁车；原始页偏移只针对 raw_pages，正文偏移仍针对 clean.md。"""
    payload = {
        "processing_version": PROCESSING_VERSION,
        "raw_pages": artifact.raw_pages,
        "footnotes": [{**asdict(note), "doc_id": directory.name} for note in artifact.footnotes],
    }
    path = directory / PROVENANCE_FILE
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_provenance(directory: Path) -> tuple[list[str], list[FootnoteBlock]]:
    """旧制品无旁车时返回空；损坏的旁车报错，避免重建时静默丢脚注。"""
    path = directory / PROVENANCE_FILE
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["raw_pages"], [FootnoteBlock(**note) for note in data["footnotes"]]


def fulltext_with_notes(text: str, directory: Path) -> str:
    """全文读取补上逐页脚注；canonical clean.md 不变，旧字符定位继续有效。"""
    _, notes = load_provenance(directory)
    if not notes:
        return text
    return (
        text
        + "\n\n## 脚注\n\n"
        + "\n\n".join(f"[PDF p.{note.page}, 注 {note.marker}] {note.text}" for note in notes)
    )
