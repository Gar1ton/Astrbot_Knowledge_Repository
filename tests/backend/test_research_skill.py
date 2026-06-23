"""单元测试：ResearchService 的 probe（范围探查）与 execute（召回+引用）。全部用假 api。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.research_skill import ResearchService, _build_citations


class FakeApi:
    def __init__(
        self,
        collections: list[tuple[str, str]],
        titles: dict[str, list[str]],
        *,
        docs: list[Any] | None = None,
        ready: dict[str, bool] | None = None,
        reranker_active: bool = False,
        zmeta: dict[tuple[str, str], dict[str, Any]] | None = None,
        ask_result: dict[str, Any] | None = None,
        ask_exception: Exception | None = None,
    ) -> None:
        self._cols = [SimpleNamespace(name=n, description=d) for n, d in collections]
        self._titles = titles
        self._docs = docs or []
        self._ready = ready or {}
        self._reranker_active = reranker_active
        self._zmeta = zmeta or {}
        self._ask_result = ask_result or {"answer": "A", "sources": []}
        self._ask_exception = ask_exception
        self.ask_calls: list[dict[str, Any]] = []

    async def list_collections(self) -> list[Any]:
        return self._cols

    async def list_titles_by_collection(self) -> dict[str, list[str]]:
        return self._titles

    async def list_documents(self) -> list[Any]:
        return self._docs

    async def get_lightrag_readiness(self, collection: str) -> dict[str, Any]:
        return {"ready": self._ready.get(collection, False)}

    async def get_zotero_item_meta(self, library_id: str, item_key: str) -> dict[str, Any] | None:
        return self._zmeta.get((library_id, item_key))

    def is_reranker_active(self) -> bool:
        return self._reranker_active

    async def ask(self, **kwargs: Any) -> dict[str, Any]:
        self.ask_calls.append(kwargs)
        if self._ask_exception is not None:
            raise self._ask_exception
        return self._ask_result


def _doc(title: str, collection: str, *, tags: list[str] | None = None,
         item_key: str = "", library_id: str = "") -> Any:
    return SimpleNamespace(
        title=title, collection=collection, tags=tags or [],
        zotero_item_key=item_key, library_id=library_id,
    )


def _svc(api: FakeApi, *, research_enabled: bool = True, persona: bool = False) -> ResearchService:
    flags = SimpleNamespace(research_enabled=research_enabled, persona_enabled=persona)
    return ResearchService(api, flags)


# ── probe ────────────────────────────────────────────────────────────


async def test_probe_clear_winner_low_ambiguity() -> None:
    api = FakeApi(
        [("machine_learning", "ML papers"), ("biology", "bio")],
        {
            "machine_learning": ["Attention Transformer", "Residual Learning"],
            "biology": ["CRISPR Gene Editing"],
        },
    )
    res = await _svc(api).probe("transformer attention architecture")
    assert res["ambiguity"] == "low"
    assert res["collections"][0]["name"] == "machine_learning"
    assert res["available_modes"] == ["default", "deep_thinking"]


async def test_probe_competing_collections_high_ambiguity() -> None:
    api = FakeApi(
        [("alpha", "x"), ("beta", "y")],
        {"alpha": ["Deep Learning Networks"], "beta": ["Statistical Learning Theory"]},
    )
    res = await _svc(api).probe("learning models")
    assert res["ambiguity"] == "high"


async def test_probe_weak_signal_medium_ambiguity() -> None:
    api = FakeApi([("papers", "p")], {"papers": ["Transformer Models"]})
    res = await _svc(api).probe("深度学习综述")  # 无英文 token 命中
    assert res["ambiguity"] == "medium"


async def test_probe_enriches_papers_with_author_year() -> None:
    api = FakeApi(
        [("ml", "")],
        {"ml": ["Attention Transformer"]},
        docs=[_doc("Attention Transformer", "ml", item_key="K1", library_id="L")],
        zmeta={("L", "K1"): {"creators": ["Vaswani, Ashish"], "year": "2017"}},
    )
    res = await _svc(api).probe("transformer")
    assert res["papers"]
    p = res["papers"][0]
    assert p["author"] == "Vaswani"
    assert p["year"] == "2017"
    assert p["title"] == "Attention Transformer"


async def test_probe_high_precision_only_when_lightrag_ready() -> None:
    api = FakeApi([("ml", "")], {"ml": ["Graph Networks"]}, ready={"ml": True})
    res = await _svc(api).probe("transformer")
    assert "high_precision" in res["available_modes"]


async def test_probe_suggests_deep_thinking_on_signal() -> None:
    api = FakeApi([("ml", "")], {"ml": ["X"]})
    res = await _svc(api).probe("请综合分析这些论文")
    assert res["suggested_mode"] == "deep_thinking"


async def test_probe_matches_chinese_collection_name() -> None:
    # 中文 query 命中中文集合名（probe 分词支持 CJK bigram），双语 research 的范围探查可用。
    api = FakeApi([("机器学习", "深度学习论文"), ("biology", "")], {"机器学习": [], "biology": []})
    res = await _svc(api).probe("机器学习相关研究")
    assert res["collections"][0]["name"] == "机器学习"
    assert res["ambiguity"] == "low"


async def test_probe_uncategorized_excluded() -> None:
    api = FakeApi(
        [("_uncategorized", ""), ("papers", "")],
        {"_uncategorized": ["Transformer Attention"], "papers": ["Biology"]},
    )
    res = await _svc(api).probe("transformer")
    assert all(c["name"] != "_uncategorized" for c in res["collections"])


# ── execute ──────────────────────────────────────────────────────────


async def test_execute_wires_english_retrieval_and_persona_default() -> None:
    api = FakeApi([("ml", "")], {"ml": ["X"]}, ask_result={"answer": "ANS", "sources": []})
    await _svc(api, persona=True).execute("q", "ml", mode="default")
    call = api.ask_calls[0]
    assert call["use_english_retrieval"] is True
    assert call["answer_language"] == "auto"
    assert call["persona_enabled"] is True
    assert call["collection"] == "ml"


async def test_execute_wide_widens_candidate_pool_only_with_reranker() -> None:
    api_on = FakeApi([("ml", "")], {"ml": ["X"]}, reranker_active=True)
    await _svc(api_on).execute("q", "ml", breadth="wide")
    assert api_on.ask_calls[0]["use_reranker"] is True
    assert api_on.ask_calls[0]["candidate_k"] == 5 * 8

    api_off = FakeApi([("ml", "")], {"ml": ["X"]}, reranker_active=False)
    await _svc(api_off).execute("q", "ml", breadth="wide")
    assert api_off.ask_calls[0]["use_reranker"] is False
    assert api_off.ask_calls[0]["candidate_k"] is None


async def test_execute_rejects_strict_mode_without_collection() -> None:
    api = FakeApi([("ml", "")], {"ml": ["X"]})
    res = await _svc(api).execute("q", None, mode="high_precision")
    assert api.ask_calls == []
    assert res["status"] == "needs_scope"
    assert res["mode"] == "high_precision"
    assert "default" in res["answer"]


async def test_execute_preserves_requested_mode_on_backend_error() -> None:
    api = FakeApi(
        [("ml", "")],
        {"ml": ["X"]},
        ask_exception=RuntimeError("LightRAG not ready"),
    )
    res = await _svc(api).execute("q", "ml", mode="high_precision")
    assert api.ask_calls[0]["retrieval_mode"] == "high_precision"
    assert res["status"] == "error"
    assert res["mode"] == "high_precision"
    assert "LightRAG not ready" in res["error"]


async def test_execute_builds_citations_author_year_title() -> None:
    sources = [
        {"doc_id": "d1", "author": "Vaswani", "year": "2017", "title": "Attention Transformer"},
        {"doc_id": "d1", "author": "Vaswani", "year": "2017", "title": "Attention Transformer"},
        {"doc_id": "d2", "title": "Local Note Only"},
    ]
    api = FakeApi([("ml", "")], {"ml": ["X"]}, ask_result={"answer": "ANS", "sources": sources})
    res = await _svc(api).execute("q", "ml")
    assert res["citations"] == ["Vaswani - 2017 - Attention Transformer", "Local Note Only"]
    assert res["answer"] == "ANS"


def test_build_citations_dedup_and_fallback() -> None:
    out = _build_citations(
        [
            {"doc_id": "d1", "author": "A", "year": "2020", "title": "T1"},
            {"doc_id": "d1", "author": "A", "year": "2020", "title": "T1"},
            {"document_id": "d2", "title": "T2"},
        ]
    )
    assert out == ["A - 2020 - T1", "T2"]
