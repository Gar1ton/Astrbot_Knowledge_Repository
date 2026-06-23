"""Research 服务：对话式知识检索的两个无状态后端能力（见 ../ARCHITECTURE.md）。

交互模型（v0.28.0 重构）：主对话 LLM 当指挥，下面挂两个工具——
  · probe(query)：模糊检索元数据（标题/集合/标签），返回候选 + ambiguity + 建议模式，
    供主 LLM 判断「回应范围 + 模式」并决定直接执行还是反问用户确认；
  · execute(...)：真正的 chunk 召回（英文召回 + 按问题语言作答 + reranker/wide）+ 确定性引用列表。

本模块只做编排与打分，不写召回算法、不碰任何同步配置（Zotero/Notion/R2 的 token/url）。
范围界定与模式选择最终交给主 LLM；这里的 ambiguity/suggested_mode 只是廉价启发式提示。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.api import KnowledgeRepositoryApi

logger = logging.getLogger("ResearchService")

# 答案默认 top_k 不变；breadth 只放大「候选池」，由 reranker 收口（无 reranker 时不放大）。
_ANSWER_TOP_K = 5
_BREADTH_MULT = {"narrow": 1, "normal": 3, "wide": 8}

# probe 结果上限，控制喂给 LLM 的 token。
_MAX_COLLECTIONS = 8
_MAX_PAPERS = 8
_MAX_TAGS = 10

# ambiguity 判定阈值（与旧 KeywordScopeResolver 对齐）。
_MIN_COVERAGE = 0.25
_DOMINANCE_RATIO = 2.0

_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with",
        "by", "from", "and", "or", "is", "are", "was", "this", "that",
        "it", "what", "how", "when", "where", "about", "using", "based",
        "can", "does", "will", "has", "have", "between", "through",
    }
)

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


def _tokenize(text: str) -> set[str]:
    """中英双语分词：英文取 3+ 字母词（去停用词），中文取 CJK 连续段的 2-gram。

    中文无空格分隔，字粒度噪声大、整段过严，故用滑窗 2-gram 折中——既能让中文集合名/
    标题在 probe 里被中文 query 命中，又不至于像单字那样过度误配。
    """
    tokens = {t for t in re.findall(r"[a-z]{3,}", text.lower()) if t not in _STOP_WORDS}
    for run in re.findall(r"[一-鿿]+", text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _coverage(query_tokens: set[str], corpus_tokens: set[str]) -> float:
    if not query_tokens or not corpus_tokens:
        return 0.0
    return len(query_tokens & corpus_tokens) / len(query_tokens)


class ResearchService:
    """probe + execute 两个无状态能力的后端实现。

    flags：暴露 .research_enabled / .persona_enabled 的对象（运行态即 PluginInitializer）。
    """

    def __init__(self, api: KnowledgeRepositoryApi, flags: Any) -> None:
        self._api = api
        self._flags = flags

    # ── 工具一：范围探查 ─────────────────────────────────────────

    async def probe(self, query: str) -> dict[str, Any]:
        """模糊检索元数据，返回候选 + ambiguity + 建议/可用模式，供主 LLM 判断回应范围。"""
        collections = await self._api.list_collections()
        active = [c for c in collections if not c.name.startswith("_")]
        titles_by_col = await self._api.list_titles_by_collection()
        q_tokens = _tokenize(query)

        # 集合打分（名 + 描述 + 标题语料的 token 覆盖率）。
        scored_cols: list[dict[str, Any]] = []
        for col in active:
            corpus = _tokenize(col.name) | _tokenize(col.description)
            for title in titles_by_col.get(col.name, []):
                corpus |= _tokenize(title)
            score = _coverage(q_tokens, corpus)
            scored_cols.append(
                {
                    "name": col.name,
                    "description": col.description,
                    "doc_count": len(titles_by_col.get(col.name, [])),
                    "match_score": round(score, 3),
                }
            )
        scored_cols.sort(key=lambda c: c["match_score"], reverse=True)

        # 命中论文（标题 token 命中）+ author/year enrich；命中标签。
        papers, tags = await self._match_papers_and_tags(q_tokens)

        # LightRAG 就绪度（决定 high_precision 是否可用）。
        lightrag_ready: dict[str, bool] = {}
        for col in active:
            try:
                readiness = await self._api.get_lightrag_readiness(col.name)
                lightrag_ready[col.name] = bool(readiness.get("ready", False))
            except Exception:
                lightrag_ready[col.name] = False

        available_modes = ["default", "deep_thinking"]
        if any(lightrag_ready.values()):
            available_modes.append("high_precision")

        return {
            "query": query,
            "collections": scored_cols[:_MAX_COLLECTIONS],
            "papers": papers[:_MAX_PAPERS],
            "tags": tags[:_MAX_TAGS],
            "ambiguity": self._assess_ambiguity(scored_cols),
            "suggested_mode": self._suggest_mode(query, lightrag_ready),
            "available_modes": available_modes,
            "lightrag_ready": lightrag_ready,
        }

    async def _match_papers_and_tags(
        self, q_tokens: set[str]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        docs = await self._api.list_documents()
        ranked: list[tuple[int, dict[str, Any]]] = []
        tag_hits: set[str] = set()
        for doc in docs:
            for tag in doc.tags:
                if _tokenize(tag) & q_tokens or tag.lower() in {t for t in q_tokens}:
                    tag_hits.add(tag)
            overlap = len(_tokenize(doc.title) & q_tokens)
            if overlap == 0:
                continue
            entry: dict[str, Any] = {
                "title": doc.title,
                "collection": doc.collection,
                "author": "",
                "year": "",
            }
            if getattr(doc, "zotero_item_key", "") and getattr(doc, "library_id", ""):
                try:
                    zmeta = await self._api.get_zotero_item_meta(
                        doc.library_id, doc.zotero_item_key
                    )
                    if zmeta:
                        creators = zmeta.get("creators") or []
                        entry["author"] = creators[0].split(",")[0] if creators else ""
                        entry["year"] = zmeta.get("year", "")
                except Exception:
                    pass
            ranked.append((overlap, entry))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in ranked], sorted(tag_hits)

    def _assess_ambiguity(self, scored_cols: list[dict[str, Any]]) -> str:
        """low=单一集合明确胜出（主 LLM 可直接执行）；high=多集合竞争（宜反问）；medium=信号弱。"""
        ranked = [c for c in scored_cols if c["match_score"] >= _MIN_COVERAGE]
        if not ranked:
            return "medium"
        top = ranked[0]["match_score"]
        second = ranked[1]["match_score"] if len(ranked) > 1 else 0.0
        if second >= _MIN_COVERAGE and top < _DOMINANCE_RATIO * second:
            return "high"
        return "low"

    def _suggest_mode(self, query: str, lightrag_ready: dict[str, bool]) -> str:
        q = query.lower()
        if any(sig in q for sig in _DEEP_SIGNALS):
            return "deep_thinking"
        if any(sig in q for sig in _GRAPH_SIGNALS) and any(lightrag_ready.values()):
            return "high_precision"
        return "default"

    # ── 工具二：执行召回 ─────────────────────────────────────────

    async def execute(
        self,
        query: str,
        collection: str | None = None,
        mode: str = "default",
        breadth: str = "normal",
        persona_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """真正召回并作答：英文召回 + 按问题语言答 + reranker/wide + 确定性引用列表。"""
        if mode not in {"default", "high_precision", "graph_only", "deep_thinking"}:
            mode = "default"
        # high_precision/deep_thinking/graph_only 需要具体集合；全局时降级 default。
        if mode != "default" and not collection:
            mode = "default"

        use_reranker = self._api.is_reranker_active()
        mult = _BREADTH_MULT.get(breadth, _BREADTH_MULT["normal"])
        candidate_k = _ANSWER_TOP_K * mult if (use_reranker and mult > 1) else None

        if persona_enabled is None:
            persona_enabled = bool(getattr(self._flags, "persona_enabled", False))

        try:
            result = await self._api.ask(
                question=query,
                collection=collection,
                top_k=_ANSWER_TOP_K,
                retrieval_mode=mode,
                use_english_retrieval=True,
                answer_language="auto",
                persona_enabled=persona_enabled,
                candidate_k=candidate_k,
                use_reranker=use_reranker,
            )
        except Exception as exc:  # noqa: BLE001 - 工具入口需兜底，不向框架抛出
            logger.error("ResearchService.execute api.ask failed: %s", exc)
            return {
                "answer": "检索时发生错误，请稍后再试。",
                "citations": [],
                "scope": collection or "全局",
                "mode": mode,
                "sources": [],
            }

        sources = result.get("sources") or []
        return {
            "answer": result.get("answer") or "未找到相关内容。",
            "citations": _build_citations(sources),
            "scope": collection or "全局",
            "mode": result.get("actual_retrieval_mode") or mode,
            "sources": sources,
        }


def _build_citations(sources: list[dict[str, Any]]) -> list[str]:
    """从 sources 确定性拼装 `Author - Year - Title`（按文档去重，缺字段则退化）。"""
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        doc_id = str(src.get("doc_id") or src.get("document_id") or "")
        if doc_id and doc_id in seen:
            continue
        if doc_id:
            seen.add(doc_id)
        parts = [
            str(src.get("author") or "").strip(),
            str(src.get("year") or "").strip(),
            str(src.get("title") or "").strip(),
        ]
        line = " - ".join(p for p in parts if p)
        if line:
            out.append(line)
    return out


__all__ = ["ResearchService"]
