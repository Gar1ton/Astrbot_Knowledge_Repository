"""跨文档知识串线修复的回归测试（v0.25.10）。

锁住「每条证据标注来源文档」契约：当证据集混入多篇论文的 chunk 时，SEA / VERIFY /
合成三处 prompt 都必须给每条证据带上其来源标签，模型才能区分多篇拼接的证据池，
避免把 B 论文的发现张冠李戴成 A 论文的局限（如 LeanMarathon 的 goal drift 被缝进
Lean4Agent 的局限性）。同时验证 [n] 编号契约不回退、source_labels=None 向后兼容。
"""
from __future__ import annotations

import pytest

from core.config import Config
from core.domain.deep_thinking import Checklist, ChecklistItem, EvidenceItem
from core.domain.models import DocumentChunk, SourceDocument
from core.pipelines.answer_synthesis import source_tag, synthesize_answer
from core.pipelines.deep_thinking_prompts import build_sea_prompt, build_verify_prompt
from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
from core.repository.kb_reader.base import KnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore

# 两篇相似论文的证据，doc_id 即来源标签的解析键。
_CHUNK_A = DocumentChunk("a_c0", "Lean4Agent", 0, "LLMExec 局部正确性假设", "ha")
_CHUNK_B = DocumentChunk("b_c0", "LeanMarathon", 0, "goal drift 与 lost-in-the-middle", "hb")
_LABELS = {"Lean4Agent": "Lean4Agent", "LeanMarathon": "LeanMarathon"}


class _EmptyKB(KnowledgeBaseReader):
    async def list_collections(self) -> list[str]:
        return []

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        return []

    async def search(self, collection: str, query: str, top_k: int) -> list[DocumentChunk]:
        return []


class _CaptureLLM:
    """记录最后一次 generate 的 user prompt，返回固定答案（不依赖真实模型输出）。"""

    def __init__(self) -> None:
        self.last_user = ""

    async def generate(
        self, prompt: str, *, system_prompt: str = "", allow_mock: bool = True
    ) -> str:
        self.last_user = prompt
        return "answer [1] [2]"


def _evidence() -> list[EvidenceItem]:
    return [EvidenceItem(_CHUNK_A, "rerank_score"), EvidenceItem(_CHUNK_B, "rerank_score")]


# ── 证据行来源标注 ──────────────────────────────────────────
def test_sea_prompt_labels_each_evidence_with_source() -> None:
    prompt = build_sea_prompt(
        "Lean4Agent 的局限性",
        Checklist(items=[ChecklistItem(id="c1", text="局限性")]),
        _evidence(),
        source_labels=_LABELS,
    )
    assert "[a_c0]（来源：Lean4Agent）" in prompt
    assert "[b_c0]（来源：LeanMarathon）" in prompt


def test_verify_prompt_labels_each_evidence_with_source() -> None:
    prompt = build_verify_prompt(
        "Lean4Agent 的局限性",
        "答案",
        [_CHUNK_A, _CHUNK_B],
        source_labels=_LABELS,
    )
    # VERIFY 按序号编号，来源标签紧跟编号。
    assert "[1]（来源：Lean4Agent）" in prompt
    assert "[2]（来源：LeanMarathon）" in prompt


@pytest.mark.asyncio
async def test_synthesize_answer_labels_evidence_and_preserves_numbering() -> None:
    llm = _CaptureLLM()
    await synthesize_answer(
        llm,  # type: ignore[arg-type]
        "Lean4Agent 的局限性",
        [_CHUNK_A, _CHUNK_B],
        style="deep",
        source_labels=_LABELS,
    )
    user = llm.last_user
    # 每条证据带正确来源标签。
    assert "[1]（来源：Lean4Agent）" in user
    assert "[2]（来源：LeanMarathon）" in user
    # [n] 与 evidence 顺序一一对齐（契约不回退）：A 在 [1]、B 在 [2]。
    assert user.index("[1]（来源：Lean4Agent）") < user.index("[2]（来源：LeanMarathon）")


# ── doc_id → label 映射 ─────────────────────────────────────
def _doc(doc_id: str, title: str) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=title,
        file_path=f"/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="kb",
    )


@pytest.mark.asyncio
async def test_document_labels_resolves_titles_and_falls_back() -> None:
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("Lean4Agent", "Lean4Agent: 论文标题"))
    await store.add_document(_doc("BlankTitle", ""))
    orch = RetrievalOrchestrator(
        source_store=store, kb_reader=_EmptyKB(), config=Config({"vector_db": {"backend": "astr"}})
    )
    labels = await orch.document_labels(["Lean4Agent", "BlankTitle", "Missing"])
    assert labels["Lean4Agent"] == "Lean4Agent: 论文标题"
    assert labels["BlankTitle"] == "BlankTitle"  # title 空回退 doc_id
    assert labels["Missing"] == "Missing"  # 文档不存在回退 doc_id


# ── 向后兼容 ────────────────────────────────────────────────
def test_source_tag_empty_without_labels() -> None:
    assert source_tag("Lean4Agent", None) == ""
    assert source_tag("Lean4Agent", {}) == ""
    assert source_tag("Unknown", _LABELS) == ""  # 无映射条目不标注


def test_prompts_backward_compatible_without_labels() -> None:
    sea = build_sea_prompt(
        "q", Checklist(items=[ChecklistItem(id="c1", text="x")]), _evidence()
    )
    verify = build_verify_prompt("q", "a", [_CHUNK_A, _CHUNK_B])
    assert "（来源：" not in sea
    assert "（来源：" not in verify
    # 旧的纯 chunk_id / 序号前缀仍在。
    assert "[a_c0] " in sea
    assert "[1] " in verify
