"""有预算的证据阅读视图；原 chunk 文本、hash 和引用 ID 保持 canonical 身份。"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from kacore.managers.token_budget import default_tokenizer

if TYPE_CHECKING:
    from kacore.domain.models import DocumentChunk
    from kacore.repository.source_store.base import SourceDocumentStore


def evidence_text(chunk: DocumentChunk) -> str:
    """合成使用显式视图；普通模式没有视图时返回原文。"""
    return str(chunk.metadata.get("evidence_view", {}).get("text", chunk.text))


def prefix_within_budget(text: str, budget: int) -> str:
    """返回预算内前缀，不改写字符；未知 tokenizer 时仅是显式估算。"""
    counter = default_tokenizer()
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if counter.count(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _append_notes(source, root, note_ids, parts, sources, edges, token_budget, context_budget):
    """附加本地关联脚注并扣除预算，跨视图只出现一次。"""
    counter = default_tokenizer()
    for note in source.metadata.get("footnotes", []):
        key = (
            f"{root.doc_id}:{root.metadata.get('revision_id')}:"
            f"{note['page']}:{note['source_start']}"
        )
        if key in note_ids:
            continue
        addition = f"\n[PDF p.{note['page']}, 注 {note['marker']}] {note['text']}"
        cost = counter.count(addition) + 1
        if cost > min(token_budget, context_budget):
            edges.append({"source": root.chunk_id, "kind": "footnote", "status": "token_budget"})
            continue
        note_ids.add(key)
        parts.append(addition)
        sources.append({"note_id": key, "doc_id": root.doc_id, **note})
        edges.append({"source": source.chunk_id, "target": key, "kind": "footnote"})
        token_budget -= cost
        context_budget -= cost
    return token_budget, context_budget


async def build_evidence_views(
    roots: list[DocumentChunk],
    store: SourceDocumentStore,
    documents: dict[str, list[DocumentChunk]],
    edges: list[dict[str, Any]],
    *,
    token_budget: int,
    max_depth: int,
    context_budget: int = 8000,
    requested_reads: dict[str, set[str]] | None = None,
) -> list[DocumentChunk]:
    """同文档同修订续接，脚注随命中正文读取；跨视图去重且分别限制总量/扩展量。"""
    counter = default_tokenizer()
    included = {c.chunk_id for c in roots}
    note_ids: set[str] = set()
    result = []
    # 先为所有根证据预留正文，再分配扩展，避免首条扩展挤掉后续方面。
    root_cost = sum(counter.count(c.text) + 2 for c in roots)
    token_budget = min(token_budget, max(0, context_budget - root_cost))
    for root in roots:
        text = prefix_within_budget(root.text, max(0, context_budget - 2))
        if not text:
            edges.append({"source": root.chunk_id, "kind": "context", "status": "token_budget"})
            continue
        context_budget -= counter.count(text) + 2
        parts = [text]
        sources: list[dict[str, Any]] = [
            {
                "chunk_id": root.chunk_id,
                "doc_id": root.doc_id,
                "revision_id": root.metadata.get("revision_id", ""),
                "pages": root.metadata.get("pages", []),
                "start_char": root.metadata.get("start_char"),
                "end_char": root.metadata.get("end_char"),
            }
        ]
        truncated = len(text) < len(root.text)
        source = root
        requests = (requested_reads or {}).get(root.chunk_id, set())
        direction = -1 if "expand_before" in requests else 1
        for depth in range(max_depth + 1):
            if not truncated:
                token_budget, context_budget = _append_notes(
                    source,
                    root,
                    note_ids,
                    parts,
                    sources,
                    edges,
                    token_budget,
                    context_budget,
                )
            if depth == max_depth or not source.text.rstrip() or truncated:
                break
            if (
                source.text.rstrip()[-1] in ".!?。！？:;"
                and not (requests & {"expand_before", "expand_after"})
            ) or not source.metadata.get("revision_id"):
                break
            if source.doc_id not in documents:
                documents[source.doc_id] = await store.list_chunks(source.doc_id)
            neighbor = next(
                (
                    c
                    for c in documents[source.doc_id]
                    if c.ordinal == source.ordinal + direction
                    and c.metadata.get("revision_id") == source.metadata["revision_id"]
                    and c.metadata.get("chunk_kind", "body") == "body"
                ),
                None,
            )
            if neighbor is None or neighbor.chunk_id in included:
                break
            addition = prefix_within_budget(
                neighbor.text if direction > 0 else neighbor.text[::-1],
                max(0, min(token_budget, context_budget) - 1),
            )
            if not addition:
                edges.append(
                    {"source": source.chunk_id, "kind": "expand_after", "status": "token_budget"}
                )
                break
            if direction < 0:
                addition = addition[::-1]
            truncated = len(addition) < len(neighbor.text)
            cost = counter.count(addition) + 1
            token_budget -= cost
            context_budget -= cost
            if direction < 0:
                parts.insert(0, addition)
            else:
                parts.append(addition)
            included.add(neighbor.chunk_id)
            sources.append(
                {
                    "chunk_id": neighbor.chunk_id,
                    "doc_id": neighbor.doc_id,
                    "revision_id": neighbor.metadata.get("revision_id"),
                    "pages": neighbor.metadata.get("pages", []),
                    "start_char": neighbor.metadata.get("start_char", 0)
                    + (len(neighbor.text) - len(addition) if direction < 0 else 0),
                    "end_char": neighbor.metadata.get("start_char", 0)
                    + (len(neighbor.text) if direction < 0 else len(addition)),
                }
            )
            edges.append(
                {
                    "source": source.chunk_id,
                    "target": neighbor.chunk_id,
                    "kind": "adjacent_after" if direction > 0 else "adjacent_before",
                    "depth": depth + 1,
                }
            )
            source = neighbor
        view_text = "\n".join(parts)
        view = {
            "id": "view-" + hashlib.sha256(view_text.encode()).hexdigest()[:16],
            "text": view_text,
            "sources": sources,
            "truncated": truncated,
            "token_count": counter.count(view_text),
            "measurement": "estimated",
        }
        result.append(replace(root, metadata={**root.metadata, "evidence_view": view}))
    return result
