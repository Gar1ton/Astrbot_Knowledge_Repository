"""Research Skill：由 AstrBot LLM 经自然语言调用的只读知识检索工具。

职责边界（见 ../ARCHITECTURE.md）：本模块只做「意图 → 范围 → 模式 → api.ask」的编排，
不写召回业务、不碰任何同步配置（Zotero/Notion/R2 的 token/url）。范围解析与模式选择各为
独立可替换模块（接口先行），ResearchSkill 仅薄壳编排并以生成器逐步产出进度与最终答案。
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.api import KnowledgeRepositoryApi

logger = logging.getLogger("ResearchSkill")


# ── 模块一：范围解析接口（ScopeResolution + ScopeResolver ABC）─────────


@dataclass
class ScopeResolution:
    collection: str | None  # None = 全局检索
    scope_type: str = ""  # "" = collection 级；"item" = 单篇（v2）
    scope_key: str = ""  # scope_type="item" 时的 doc_id（v2 填充）
    confidence: str = "low"  # "high" | "medium" | "low"
    reason: str = ""  # 进度消息文案
    top_candidates: list[str] = field(default_factory=list)  # 供调试/展示


class ScopeResolver(ABC):
    """召回范围解析接口。

    当前实现：KeywordScopeResolver（纯字符串，零延迟）。
    未来可替换：LLMScopeResolver（mini LLM call，精度更高），上层零修改。
    """

    @abstractmethod
    async def resolve(self, query: str) -> ScopeResolution: ...


# ── 模块二：KeywordScopeResolver（纯字符串覆盖率评分）──────────────────

_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with",
        "by", "from", "and", "or", "is", "are", "was", "this", "that",
        "it", "what", "how", "when", "where", "about", "using", "based",
        "can", "does", "will", "has", "have", "between", "through",
    }
)


class KeywordScopeResolver(ScopeResolver):
    # ── 调参区（修改这两个常量即可调整策略）─────────────────────────
    MIN_COVERAGE = 0.25  # query 词元中至少此比例出现在集合 title 里才计分
    DOMINANCE_RATIO = 2.0  # top-1 分数须达 top-2 的此倍数才算「明确胜出」
    # ────────────────────────────────────────────────────────────────

    def __init__(self, api: KnowledgeRepositoryApi) -> None:
        self._api = api

    def _tokenize(self, text: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {t for t in tokens if t not in _STOP_WORDS}

    def _score(self, query_tokens: set[str], titles: list[str]) -> float:
        if not query_tokens or not titles:
            return 0.0
        col_tokens = {tok for t in titles for tok in self._tokenize(t)}
        hits = query_tokens & col_tokens
        return len(hits) / len(query_tokens)

    async def resolve(self, query: str) -> ScopeResolution:
        collections = await self._api.list_collections()
        active = [c for c in collections if not c.name.startswith("_")]
        if not active:
            return ScopeResolution(None, reason="无可用集合，全局检索")

        # Phase 1：显式集合名命中
        q_lower = query.lower()
        for col in active:
            if col.name.lower() in q_lower:
                return ScopeResolution(
                    col.name,
                    confidence="high",
                    reason=f"查询明确提及「{col.name}」",
                )

        # Phase 2：title corpus 覆盖率评分
        title_index = await self._api.list_titles_by_collection()
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return ScopeResolution(
                None, confidence="low", reason="未提取到英文关键词，全局检索"
            )

        scores = {
            col.name: self._score(query_tokens, title_index.get(col.name, []))
            for col in active
        }
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_candidates = [n for n, s in ranked[:3] if s >= self.MIN_COVERAGE]

        if not ranked or ranked[0][1] < self.MIN_COVERAGE:
            return ScopeResolution(
                None,
                confidence="low",
                reason="无明显集合匹配，全局检索",
                top_candidates=top_candidates,
            )

        top_name, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0

        if second_score >= self.MIN_COVERAGE and top_score < self.DOMINANCE_RATIO * second_score:
            # 多集合竞争，降全局
            names = [n for n, _ in ranked[:2]]
            return ScopeResolution(
                None,
                confidence="medium",
                reason=f"多集合相关（{'、'.join(names)}），全局检索",
                top_candidates=top_candidates,
            )

        return ScopeResolution(
            top_name,
            confidence="medium",
            reason=f"关键词命中「{top_name}」({top_score:.0%} 覆盖)",
            top_candidates=top_candidates,
        )


# ── 模块三：ModeSelector（retrieval_mode 决策，与 scope 正交）──────────

_DEEP_SIGNALS = frozenset(
    {
        "分析", "综合", "系统", "全面", "对比", "比较", "梳理",
        "综述", "review", "compare", "comprehensive", "systematic",
        "relationship", "overview", "summary",
    }
)

_GRAPH_SIGNALS = frozenset(
    {
        "关系", "关联", "网络", "图谱", "连接",
        "network", "relation", "graph", "link", "between",
    }
)


class ModeSelector:
    """根据用户意图 + LightRAG 可用性选择 retrieval_mode。

    depth 由 LLM 从对话推断，"auto" 时由本类从 query 关键词推断。
    LightRAG 未就绪时自动降级，不报错（图谱召回当前仅支持在 WebUI 中构建）。
    """

    def __init__(self, api: KnowledgeRepositoryApi) -> None:
        self._api = api

    async def select(
        self,
        query: str,
        depth: str,  # "quick" | "deep" | "auto"
        collection: str | None,
    ) -> tuple[str, str]:  # (retrieval_mode, reason)
        # 全局检索只支持 default
        if collection is None:
            return "default", "全局检索模式，使用标准向量召回"

        # depth=quick：快速答案，不管 LightRAG
        if depth == "quick":
            return "default", "快速模式：标准向量召回"

        # depth=deep 或 auto 推断为深度：优先 deep_thinking（不依赖 LightRAG）
        effective_deep = (depth == "deep") or self._infer_deep(query)
        if effective_deep:
            return "deep_thinking", "深度分析模式：FAIR-RAG 迭代召回"

        # auto + 图谱信号 + LightRAG 可用 → high_precision
        if self._infer_graph(query):
            readiness = await self._api.get_lightrag_readiness(collection)
            if readiness.get("ready", False):
                return "high_precision", "图谱模式：LightRAG 知识图谱召回"

        return "default", "标准模式：向量召回"

    def _infer_deep(self, query: str) -> bool:
        q = query.lower()
        return any(sig in q for sig in _DEEP_SIGNALS)

    def _infer_graph(self, query: str) -> bool:
        q = query.lower()
        return any(sig in q for sig in _GRAPH_SIGNALS)


# ── 模块四：ResearchSkill（薄壳编排）──────────────────────────────────


class ResearchSkill:
    """编排 scope 解析 → mode 选择 → api.ask，以生成器逐步产出进度与答案。

    自身不写召回业务，也绝不调用任何 config/secret/sync 写接口。
    """

    def __init__(
        self,
        api: KnowledgeRepositoryApi,
        scope_resolver: ScopeResolver,
        mode_selector: ModeSelector,
        flags: Any,
    ) -> None:
        # flags：暴露 .research_enabled / .persona_enabled 的对象（运行态即 PluginInitializer）。
        self._api = api
        self._scope_resolver = scope_resolver
        self._mode_selector = mode_selector
        self._flags = flags

    async def handle(self, event: Any, query: str, depth: str = "auto") -> AsyncIterator[str]:
        """LLM 调用工具时的入口：四步进度 + 最终答案，逐条 yield。

        event 仅为运行态签名占位（main.py 真壳把每条 yield 包成 plain_result 回发）。
        """
        if not getattr(self._flags, "research_enabled", False):
            yield "🔬 research 已关闭，请先发送 /ka research on 开启。"
            return

        yield "🔍 正在分析召回范围…"

        scope = await self._scope_resolver.resolve(query)
        scope_label = scope.collection or "全局"
        yield f"📚 召回范围：{scope_label}（{scope.reason}）"

        mode, mode_reason = await self._mode_selector.select(query, depth, scope.collection)
        yield f"⚙️ 召回模式：{mode_reason}"

        try:
            result = await self._api.ask(
                question=query,
                collection=scope.collection,
                retrieval_mode=mode,
                scope_type=scope.scope_type,
                scope_key=scope.scope_key,
                persona_enabled=bool(getattr(self._flags, "persona_enabled", False)),
                top_k=5,
            )
            answer = result.get("answer") or "未找到相关内容。"
        except Exception as exc:  # noqa: BLE001 - 工具入口需兜底，不向框架抛出
            logger.error("ResearchSkill api.ask failed: %s", exc)
            answer = "检索时发生错误，请稍后再试。"

        yield answer


__all__ = [
    "ScopeResolution",
    "ScopeResolver",
    "KeywordScopeResolver",
    "ModeSelector",
    "ResearchSkill",
]
