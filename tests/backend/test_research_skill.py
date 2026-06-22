"""单元测试：ResearchSkill 的范围解析（KeywordScopeResolver）、模式选择（ModeSelector）
与编排入口（ResearchSkill.handle）。全部用假 api，不触真实检索。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.research_skill import KeywordScopeResolver, ModeSelector, ResearchSkill


class FakeApi:
    def __init__(
        self,
        collections: list[str],
        titles: dict[str, list[str]],
        *,
        ready: bool = False,
        answer: str = "ANSWER",
    ) -> None:
        self._cols = [SimpleNamespace(name=n) for n in collections]
        self._titles = titles
        self._ready = ready
        self._answer = answer
        self.ask_calls: list[dict[str, Any]] = []

    async def list_collections(self) -> list[Any]:
        return self._cols

    async def list_titles_by_collection(self) -> dict[str, list[str]]:
        return self._titles

    async def get_lightrag_readiness(self, collection: str) -> dict[str, Any]:
        return {"ready": self._ready}

    async def ask(self, **kwargs: Any) -> dict[str, Any]:
        self.ask_calls.append(kwargs)
        return {"answer": self._answer}


async def _collect(agen: Any) -> list[str]:
    return [chunk async for chunk in agen]


# ── ScopeResolver ────────────────────────────────────────────────────


async def test_scope_explicit_name_match() -> None:
    api = FakeApi(["ML", "biology"], {"ML": ["X"], "biology": ["Y"]})
    scope = await KeywordScopeResolver(api).resolve("在 ML 里查 transformer")
    assert scope.collection == "ML"
    assert scope.confidence == "high"


async def test_scope_keyword_clear_winner() -> None:
    api = FakeApi(
        ["machine_learning", "biology"],
        {
            "machine_learning": ["Attention Is All You Need Transformer", "Residual Learning"],
            "biology": ["CRISPR Gene Editing", "Protein Folding"],
        },
    )
    scope = await KeywordScopeResolver(api).resolve("transformer attention architecture")
    assert scope.collection == "machine_learning"


async def test_scope_ambiguous_falls_to_global() -> None:
    api = FakeApi(
        ["alpha", "beta"],
        {"alpha": ["Deep Learning Networks"], "beta": ["Statistical Learning Theory"]},
    )
    scope = await KeywordScopeResolver(api).resolve("learning models")
    assert scope.collection is None
    assert scope.confidence == "medium"


async def test_scope_no_english_tokens() -> None:
    api = FakeApi(["papers"], {"papers": ["Transformer Models"]})
    scope = await KeywordScopeResolver(api).resolve("深度学习的综述")
    assert scope.collection is None


async def test_scope_uncategorized_skipped() -> None:
    # _uncategorized 含会命中的 title，但被排除竞争 → 不应误选，应回退全局。
    api = FakeApi(
        ["_uncategorized", "papers"],
        {"_uncategorized": ["Transformer Attention"], "papers": ["Biology Cells"]},
    )
    scope = await KeywordScopeResolver(api).resolve("transformer")
    assert scope.collection is None


# ── ModeSelector ─────────────────────────────────────────────────────


async def test_mode_global_forces_default() -> None:
    api = FakeApi(["ml"], {"ml": ["X"]}, ready=True)
    mode, _ = await ModeSelector(api).select("anything", "deep", None)
    assert mode == "default"


async def test_mode_deep_signal_detected() -> None:
    api = FakeApi(["ml"], {"ml": ["X"]})
    mode, _ = await ModeSelector(api).select("请综合分析这些论文", "auto", "ml")
    assert mode == "deep_thinking"


async def test_mode_lightrag_unavailable_fallback() -> None:
    api = FakeApi(["ml"], {"ml": ["X"]}, ready=False)
    mode, _ = await ModeSelector(api).select("entity relation network", "auto", "ml")
    assert mode == "default"


async def test_mode_graph_when_lightrag_ready() -> None:
    api = FakeApi(["ml"], {"ml": ["X"]}, ready=True)
    mode, _ = await ModeSelector(api).select("entity relation network", "auto", "ml")
    assert mode == "high_precision"


async def test_mode_quick_bypasses_all() -> None:
    api = FakeApi(["ml"], {"ml": ["X"]}, ready=True)
    mode, _ = await ModeSelector(api).select("综合分析关系网络", "quick", "ml")
    assert mode == "default"


# ── ResearchSkill.handle ─────────────────────────────────────────────


def _skill(api: FakeApi, flags: Any) -> ResearchSkill:
    return ResearchSkill(api, KeywordScopeResolver(api), ModeSelector(api), flags)


async def test_handle_research_disabled_short_circuits() -> None:
    api = FakeApi(["papers"], {"papers": ["Transformer"]})
    flags = SimpleNamespace(research_enabled=False, persona_enabled=False)
    chunks = await _collect(_skill(api, flags).handle(None, "transformer", "auto"))
    assert len(chunks) == 1
    assert "research 已关闭" in chunks[0]
    assert not api.ask_calls


async def test_handle_streams_steps_and_final_answer() -> None:
    api = FakeApi(["papers"], {"papers": ["Transformer"]}, answer="FINAL")
    flags = SimpleNamespace(research_enabled=True, persona_enabled=False)
    chunks = await _collect(_skill(api, flags).handle(None, "transformer", "auto"))
    assert len(chunks) == 4  # 范围 + 模式 + 三步进度其实是 3 条进度 + 1 答案
    assert chunks[-1] == "FINAL"
    assert api.ask_calls and api.ask_calls[0]["persona_enabled"] is False
    assert api.ask_calls[0]["collection"] == "papers"


async def test_handle_passes_persona_flag_when_on() -> None:
    api = FakeApi(["papers"], {"papers": ["Transformer"]})
    flags = SimpleNamespace(research_enabled=True, persona_enabled=True)
    await _collect(_skill(api, flags).handle(None, "transformer", "auto"))
    assert api.ask_calls[0]["persona_enabled"] is True
