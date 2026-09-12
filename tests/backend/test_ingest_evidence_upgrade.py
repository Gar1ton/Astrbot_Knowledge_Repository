"""升级的生产接线回归：脚注不丢、旧引用不串文、扩展预算与用量可核实。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kacore.adapters.llm import LLMAdapter
from kacore.api import KnowledgeRepositoryApi
from kacore.config import SourceStoreConfig
from kacore.domain.footnotes import FootnoteBlock, FootnoteLinkStatus
from kacore.domain.models import DocumentChunk, SourceDocument
from kacore.managers.artifact_provenance import fulltext_with_notes, save_provenance
from kacore.managers.chunking import build_structural_chunk_spans
from kacore.managers.ingest_manager import IngestManager
from kacore.managers.markdown_extractor import MarkdownArtifact, PageSpan
from kacore.managers.token_budget import default_tokenizer
from kacore.pipelines.evidence_selection import AspectCandidates, EvidenceCandidate, select_evidence
from kacore.pipelines.evidence_session import EvidenceSession
from kacore.pipelines.evidence_views import evidence_text
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.vector_store.memory import InMemoryVectorStore
from kacore.utils.usage_ledger import current_usage, usage_request


def body(cid="a", ordinal=0, text="unfinished text"):
    return DocumentChunk(
        cid,
        "doc",
        ordinal,
        text,
        cid,
        {
            "revision_id": "r1",
            "start_char": ordinal * 20,
            "pages": [1],
        },
    )


async def test_full_pool_expands_view_without_changing_canonical_chunk():
    a, b, c = body(), body("b", 1), body("c", 2, "finished.")
    store = InMemorySourceDocumentStore()
    await store.replace_chunks("doc", [a, b, c])
    session = EvidenceSession()
    result = await session.expand([a], store, limit=1, max_depth=3)
    assert result[0].text == a.text
    assert result[0].content_hash == a.content_hash
    assert "finished." in evidence_text(result[0])
    assert "evidence_view" not in a.metadata
    repeated = await session.expand([a], store, limit=1, max_depth=3)
    assert evidence_text(repeated[0]) == evidence_text(result[0])


async def test_view_budget_and_footnote_source():
    a, b = body(text="Body1 continues"), body("b", 1, "中" * 5000)
    a.metadata["footnotes"] = [
        {
            "page": 1,
            "marker": "1",
            "text": "note explanation",
            "source_start": 40,
            "source_end": 56,
            "link_status": "linked",
        }
    ]
    store = InMemorySourceDocumentStore()
    await store.replace_chunks("doc", [a, b])
    final = await EvidenceSession().expand([a], store, limit=1, token_budget=40)
    view = final[0].metadata["evidence_view"]
    assert "note explanation" in view["text"]
    assert view["truncated"]
    assert default_tokenizer().count(view["text"]) <= 40 + default_tokenizer().count(a.text)
    assert view["sources"][1]["source_start"] == 40


async def test_unknown_revision_does_not_join_replaced_document():
    a, b = body(), body("b", 1)
    a.metadata.pop("revision_id")
    b.metadata.pop("revision_id")
    store = InMemorySourceDocumentStore()
    await store.replace_chunks("doc", [a, b])
    result = await EvidenceSession().expand([a], store, limit=2)
    assert evidence_text(result[0]) == a.text


async def test_read_actions_are_scoped_deduplicated_and_can_read_before():
    from kacore.pipelines.evidence_actions import parse_actions
    from kacore.pipelines.retrieval_orchestrator import RetrievalOutcome

    a, b = body(text="Previous sentence."), body("b", 1, "Current sentence.")
    store = InMemorySourceDocumentStore()
    await store.replace_chunks("doc", [a, b])
    session = EvidenceSession()
    session.absorb([("q", RetrievalOutcome([b]))])
    actions = parse_actions(
        [
            {"kind": "expand_before", "source_id": "foreign"},
            {"kind": "expand_before", "source_id": "b"},
            {"kind": ["arbitrary"], "source_id": "b"},
        ]
    )
    assert session.request_actions(actions)
    assert not session.request_actions(actions)
    assert "foreign" not in session.requested_reads
    result = await session.expand([b], store, limit=1)
    assert evidence_text(result[0]).startswith("Previous sentence.")


def test_shared_aspect_does_not_take_slot_from_uncovered_aspect():
    candidates = {
        cid: EvidenceCandidate(cid, "doc", "r", i, cid)
        for i, cid in enumerate(["shared", "extra", "other"])
    }
    selected = select_evidence(
        [
            AspectCandidates("a", {"shared": 1}),
            AspectCandidates("b", {"shared": 1, "extra": 0.9}),
            AspectCandidates("c", {"other": 1}),
        ],
        candidates,
        max_evidence=2,
    )
    assert selected.selected_ids == ["shared", "other"]
    assert not selected.uncovered_aspect_ids


async def test_scope_and_exclusion_are_applied_before_top_k():
    store = InMemoryVectorStore()
    for doc in ("doc", "other"):
        store.set_doc_collection_mapping(doc, "col")
    a, b = body(), body("b", 1)
    other = DocumentChunk("foreign", "other", 0, "foreign", "foreign")
    await store.upsert_chunks([other, a, b], [[1.0, 0.0]] * 3)
    result = await store.search(
        "col",
        [1.0, 0.0],
        top_k=1,
        allowed_doc_ids=frozenset({"doc"}),
        exclude_chunk_ids=frozenset({"a"}),
    )
    assert [cid for cid, _ in result] == ["b"]
    assert await store.search("col", [1.0, 0.0], top_k=1, allowed_doc_ids=frozenset()) == []


async def test_reindex_removes_old_revision_vectors_after_success():
    store = InMemorySourceDocumentStore()
    vectors = InMemoryVectorStore()
    vectors.set_doc_collection_mapping("doc", "col")
    old, new = body("old"), body("new")
    foreign = DocumentChunk("foreign", "another-doc", 0, "foreign", "h")
    await vectors.upsert_chunks([old, foreign], [[1.0, 0.0]] * 2)
    await store.replace_chunks("doc", [new])

    class Embedding:
        async def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    api = KnowledgeRepositoryApi(
        source_store=store, kb_reader=None, vector_store=vectors, embedding_provider=Embedding()
    )
    await api._index_document_chunks_with_retry("doc", "col", context="test")
    hits = await vectors.search("col", [1.0, 0.0], 10)
    assert {cid for cid, _ in hits} == {"new", "foreign"}


def test_generic_book_headings_reach_structural_chunker():
    text = "Chapter IV Mechanisms\n\nSome body.\n\n§ 2 Critique\n\nOther body."
    _, sections, _ = build_structural_chunk_spans(text, chunk_size=1000)
    assert [s.label for s in sections] == ["Chapter IV", "§2"]


async def test_rechunk_preserves_notes_and_changes_identity(tmp_path):
    store = InMemorySourceDocumentStore()
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    directory = tmp_path / "library" / "doc"
    directory.mkdir(parents=True)
    text = "A claim1."
    note = FootnoteBlock(2, "1", "Only footnotes on this page", 0, 30)
    linked = FootnoteBlock(
        1, "1", "A note", 15, 24, link_status=FootnoteLinkStatus.LINKED, body_marker_span=(7, 8)
    )
    artifact = MarkdownArtifact(
        text,
        [PageSpan(1, 0, len(text)), PageSpan(2, len(text), len(text))],
        raw_pages=["A claim1.\n\n1 A note", "1 Only footnotes on this page"],
        footnotes=[linked, note],
    )
    import json

    (directory / "pages.json").write_text(
        json.dumps(
            [
                {"page": p.page, "markdown_start_char": p.start, "markdown_end_char": p.end}
                for p in artifact.page_spans
            ]
        )
    )
    save_provenance(directory, artifact)
    (directory / "clean.md").write_text(text)
    doc = SourceDocument(
        "doc",
        "Title",
        str(directory / "original.pdf"),
        "application/pdf",
        1,
        "hash",
        "col",
        markdown_rel_path="clean.md",
    )
    await store.add_document(doc)
    first = manager._chunk_artifact(
        document_id="doc", library_id="LOCAL", item_key="", attachment_key="", artifact=artifact
    )
    await store.replace_chunks("doc", first)
    await manager.rebuild_document_chunks_from_artifact("doc")
    assert [p.page for p in await store.list_page_chunks("doc")] == [1, 2]
    assert first[0].chunk_id == (await store.list_chunks("doc"))[0].chunk_id
    assert "Only footnotes" in fulltext_with_notes(text, directory)
    assert (await store.list_chunks("doc"))[0].metadata["footnotes"][0]["text"] == "A note"
    artifact.clean_markdown = "Changed claim1."
    artifact.page_spans = [PageSpan(1, 0, len(artifact.clean_markdown))]
    changed = manager._chunk_artifact(
        document_id="doc", library_id="LOCAL", item_key="", attachment_key="", artifact=artifact
    )
    assert first[0].chunk_id != changed[0].chunk_id


async def test_usage_records_internal_fallback_and_unknown_failure():
    class Provider:
        def meta(self):
            return SimpleNamespace(id="provider")

    class Context:
        provider_manager = SimpleNamespace(curr_provider_inst=Provider())

        def __init__(self):
            self.calls = 0

        async def llm_generate(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                completion_text="" if self.calls == 1 else "answer",
                reasoning_content="reasoning" if self.calls == 1 else "",
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    @usage_request
    async def run():
        adapter = LLMAdapter(Context())
        await adapter.generate_result("question", allow_mock=False)

        async def fail(**kwargs):
            raise TimeoutError()

        with pytest.raises(TimeoutError):
            await adapter._measured_provider(fail, "q", "", "provider")
        return current_usage.get().summary()

    usage = await run()
    assert usage["call_count"] == 3
    assert usage["known_tokens"] == 30
    assert usage["unknown_calls"] == 1
    assert [c["measurement"] for c in usage["calls"]] == ["actual", "actual", "unknown"]
    assert usage["calls"][-1]["input_tokens"] is None
    assert current_usage.get() is None


async def test_maintenance_dry_run_does_not_read_or_rebuild_chunks():
    class Store(InMemorySourceDocumentStore):
        async def list_chunks(self, doc_id):
            raise AssertionError("dry run must not read chunks")

    store = Store()
    await store.add_document(
        SourceDocument("doc", "Title", "original.pdf", "application/pdf", 1, "hash", "col")
    )
    api = KnowledgeRepositoryApi(source_store=store, kb_reader=None, ingest_manager=object())
    assert await api.reprocess_documents_with_stale_cleaning(dry_run=True) == {
        "dry_run": True,
        "document_ids": ["doc"],
    }
