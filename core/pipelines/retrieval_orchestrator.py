"""Unified evidence retrieval for default and high-precision Ask flows."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.domain.models import DocumentChunk, DocumentLifecycle

if TYPE_CHECKING:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.lightrag_core import LightRAGCoreRegistry
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.vector_store.base import VectorStore

logger = logging.getLogger("RetrievalOrchestrator")

# 作用域类型常量（杜绝魔法字面量）。
SCOPE_COLLECTION = "collection"
SCOPE_ITEM = "item"
SCOPE_TAG = "tag"
SCOPE_LIBRARY = "library"
# 子作用域（item/tag）窄于 collection workspace，禁用 LightRAG 图谱通道以防越界泄漏。
_GRAPH_BLOCKED_SCOPES = frozenset({SCOPE_ITEM, SCOPE_TAG})


@dataclass
class RetrievalScope:
    """检索作用域（Zotero item/collection/tag/library 维度的硬过滤约束）。

    scope_type 为空表示「按 KB collection 检索」（无额外 doc 级硬过滤，沿用原行为）。
    其余类型经 zotero 镜像解析为 allowed_document_ids，在 RRF 前对所有通道强制过滤（review #3）。
    """

    scope_type: str = ""
    scope_key: str = ""
    library_id: str = ""

    @property
    def blocks_graph(self) -> bool:
        """item/tag 子作用域窄于 collection，应禁用 LightRAG 图谱通道。"""
        return self.scope_type in _GRAPH_BLOCKED_SCOPES


@dataclass
class RetrievalOutcome:
    chunks: list[DocumentChunk]
    engines: list[str] = field(default_factory=list)
    fallback_reason: str | None = None

    @property
    def actual_mode(self) -> str:
        if "astrbot" in self.engines:
            return "astrbot_fallback" if self.fallback_reason else "astrbot"
        if "milvus" in self.engines:
            return "milvus"
        if "sqlite_lexical" in self.engines:
            return "sqlite_lexical"
        return "none"


class RetrievalOrchestrator:
    """Retrieves chunk evidence and explicit LightRAG context."""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        kb_reader: KnowledgeBaseReader,
        config: Config,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        lightrag_registry: LightRAGCoreRegistry | None = None,
        index_compatibility: IndexCompatibilityStore | None = None,
        embedding_fingerprint: str | None = None,
    ) -> None:
        self._source_store = source_store
        self._kb_reader = kb_reader
        self._config = config
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._lightrag_registry = lightrag_registry
        self._index_compatibility = index_compatibility
        self._embedding_fingerprint = embedding_fingerprint

    async def retrieve(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        scope: RetrievalScope | None = None,
    ) -> list[DocumentChunk]:
        """Keep the existing chunk-only public contract."""
        return (await self.retrieve_with_outcome(collection, query, top_k, scope)).chunks

    async def resolve_scope(self, scope: RetrievalScope | None) -> set[str] | None:
        """把作用域解析为 allowed_document_ids（None 表示不施加 doc 级硬过滤）。

        item → 该 item_key 的文档；collection → 含后代集合的全部条目文档；
        tag → 带该标签的条目文档；library → 该库全部文档。均仅取 ACTIVE（排除 detached）。
        """
        if scope is None or not scope.scope_type:
            return None
        store = self._source_store
        lib = scope.library_id or "1"
        if scope.scope_type == SCOPE_LIBRARY:
            docs = await store.list_documents()
            return {
                d.doc_id
                for d in docs
                if d.library_id == lib and d.lifecycle_state == DocumentLifecycle.ACTIVE
            }
        if scope.scope_type == SCOPE_ITEM:
            item_keys: set[str] = {scope.scope_key}
        elif scope.scope_type == SCOPE_COLLECTION:
            descendants = await store.get_collection_descendants(lib, scope.scope_key)
            item_keys = set(await store.get_items_in_collections(lib, descendants))
        elif scope.scope_type == SCOPE_TAG:
            item_keys = set(await store.get_items_with_tag(lib, scope.scope_key))
        else:
            return None
        docs = await store.list_documents()
        return {
            d.doc_id
            for d in docs
            if d.library_id == lib
            and d.zotero_item_key in item_keys
            and d.lifecycle_state == DocumentLifecycle.ACTIVE
        }

    async def retrieve_with_outcome(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        scope: RetrievalScope | None = None,
    ) -> RetrievalOutcome:
        if top_k <= 0:
            return RetrievalOutcome([])

        allowed_doc_ids = await self.resolve_scope(scope)
        if allowed_doc_ids is not None and not allowed_doc_ids:
            return RetrievalOutcome([])  # 作用域内无文档，直接空。

        dense_chunks: list[DocumentChunk] = []
        engines: list[str] = []
        fallback_reason: str | None = None
        vdb = self._config.get_vector_db_config()

        milvus_compatible = bool(
            self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_milvus_compatible(self._embedding_fingerprint)
        )
        if vdb.backend == "milvus":
            if not self._vector_store or not self._embedding_provider:
                fallback_reason = "milvus_unavailable"
            elif not milvus_compatible:
                fallback_reason = "milvus_index_incompatible"
            else:
                engines.append("milvus")
                try:
                    query_vector = await self._embedding_provider.embed_query(query)
                    vec_results = await self._vector_store.search(
                        collection=collection,
                        query_vector=query_vector,
                        top_k=top_k * 2,
                    )
                    for chunk_id, _ in vec_results:
                        chunk = await self._find_local_chunk(chunk_id)
                        if chunk:
                            dense_chunks.append(chunk)
                except Exception as exc:
                    fallback_reason = f"milvus_error: {exc}"
                    logger.error("Milvus dense search failed: %s", exc)
        else:
            fallback_reason = None

        if not dense_chunks:
            if vdb.backend == "milvus" and fallback_reason is None:
                fallback_reason = "milvus_no_hits"
            engines.append("astrbot")
            try:
                dense_chunks = await self._kb_reader.search(collection, query, top_k * 2)
            except Exception as exc:
                logger.error("AstrBot native search fallback failed: %s", exc)

        anchor_chunks: list[DocumentChunk] = []
        lexical_chunks: list[DocumentChunk] = []
        try:
            anchor_chunks = await self._search_anchor_sqlite(collection, query, top_k * 2)
            if anchor_chunks:
                engines.append("sqlite_anchor")
            lexical_chunks = await self._search_lexical_sqlite(collection, query, top_k * 2)
            if lexical_chunks:
                engines.append("sqlite_lexical")
        except Exception as exc:
            logger.error("SQLite lexical search failed: %s", exc)

        # 硬过滤契约（review #3）：任何候选 chunk 必须先满足 allowed_doc_ids 才进入 RRF。
        if allowed_doc_ids is not None:
            dense_chunks = [c for c in dense_chunks if c.doc_id in allowed_doc_ids]
            anchor_chunks = [c for c in anchor_chunks if c.doc_id in allowed_doc_ids]
            lexical_chunks = [c for c in lexical_chunks if c.doc_id in allowed_doc_ids]

        rrf_scores: dict[str, tuple[DocumentChunk, float]] = {}
        rrf_k = 60

        def add_rank(chunks: list[DocumentChunk]) -> None:
            for rank, chunk in enumerate(chunks, start=1):
                score = 1.0 / (rrf_k + rank)
                existing = rrf_scores.get(chunk.chunk_id)
                rrf_scores[chunk.chunk_id] = (
                    chunk,
                    score + (existing[1] if existing else 0.0),
                )

        add_rank(dense_chunks)
        add_rank(anchor_chunks)
        add_rank(lexical_chunks)
        ordered = sorted(rrf_scores.values(), key=lambda item: item[1], reverse=True)
        return RetrievalOutcome(
            chunks=[item[0] for item in ordered[:top_k]],
            engines=list(dict.fromkeys(engines)),
            fallback_reason=fallback_reason,
        )

    async def retrieve_lightrag_context(
        self, collection: str, query: str, scope: RetrievalScope | None = None
    ) -> str:
        # item/tag 子作用域窄于 collection workspace，图谱上下文无法按 doc 硬过滤 → 拒绝以防泄漏。
        if scope is not None and scope.blocks_graph:
            raise RuntimeError("LightRAG graph context unavailable for item/tag scope")
        if self._lightrag_registry is None:
            raise RuntimeError("LightRAG Core registry is not configured")
        if not self._embedding_fingerprint or not self._index_compatibility:
            raise RuntimeError("LightRAG index compatibility state is unavailable")
        if not self._index_compatibility.is_lightrag_compatible(
            collection, self._embedding_fingerprint
        ):
            raise RuntimeError("LightRAG index is incompatible with the active embedding")
        if not self._lightrag_registry.has_workspace(collection):
            raise RuntimeError("LightRAG workspace has not been built")
        result = await self._lightrag_registry.query(
            collection,
            query,
            only_need_context=True,
        )
        context = str(result.get("context") or "").strip()
        if not context:
            raise RuntimeError("LightRAG returned empty context")
        return context

    async def _search_anchor_sqlite(
        self, collection: str, query: str, limit: int
    ) -> list[DocumentChunk]:
        anchors = self._structural_anchors(query)
        if not anchors:
            return []
        db_conn = getattr(self._source_store, "_db", None)
        if db_conn is None:
            return []

        doc_ids: list[str] = []
        async with db_conn.execute(
            "SELECT doc_id FROM documents WHERE collection = ? AND lifecycle_state = 'active'",
            (collection,),
        ) as cursor:
            async for row in cursor:
                doc_ids.append(row[0])
        if not doc_ids:
            return []

        doc_placeholders = ",".join("?" for _ in doc_ids)
        sql = (
            "SELECT chunk_id, doc_id, ordinal, text, content_hash, metadata FROM chunks "
            f"WHERE doc_id IN ({doc_placeholders}) ORDER BY ordinal ASC"
        )
        matched: list[DocumentChunk] = []
        async with db_conn.execute(sql, doc_ids) as cursor:
            async for row in cursor:
                metadata = _loads_metadata(row[5])
                if self._metadata_matches_anchor(metadata, anchors):
                    matched.append(
                        DocumentChunk(row[0], row[1], row[2], row[3], row[4], metadata)
                    )
                    if len(matched) >= limit:
                        break
        return matched

    async def _search_lexical_sqlite(
        self, collection: str, query: str, limit: int
    ) -> list[DocumentChunk]:
        terms = self._lexical_terms(query)
        if not terms:
            return []

        db_conn = getattr(self._source_store, "_db", None)
        if db_conn is None:
            return []

        doc_ids: list[str] = []
        # 排除 detached 文档（strict 脱管），避免词汇召回越过生命态。
        async with db_conn.execute(
            "SELECT doc_id FROM documents WHERE collection = ? AND lifecycle_state = 'active'",
            (collection,),
        ) as cursor:
            async for row in cursor:
                doc_ids.append(row[0])
        if not doc_ids:
            return []

        doc_placeholders = ",".join("?" for _ in doc_ids)
        like_parts = []
        params = list(doc_ids)
        for term in terms:
            if len(term) >= 2:
                like_parts.append("text LIKE ?")
                params.append(f"%{term}%")
        if not like_parts:
            return []

        sql = (
            "SELECT chunk_id, doc_id, ordinal, text, content_hash FROM chunks "
            f"WHERE doc_id IN ({doc_placeholders}) AND ({' OR '.join(like_parts)}) "
            "ORDER BY ordinal ASC"
        )
        matched: list[tuple[DocumentChunk, float]] = []
        async with db_conn.execute(sql, params) as cursor:
            async for row in cursor:
                chunk = DocumentChunk(row[0], row[1], row[2], row[3], row[4])
                matched.append((chunk, self._lexical_score(chunk.text, terms)))
        matched.sort(key=lambda item: (-item[1], item[0].ordinal))
        return [item[0] for item in matched[:limit]]

    @staticmethod
    def _lexical_terms(query: str) -> list[str]:
        terms = [term.strip().lower() for term in re.split(r"\s+", query) if term.strip()]
        # 中英混排查询（如“T55具体说了什么”）不会被空白拆开，需显式抽取 ASCII 锚点。
        terms.extend(match.group(0).lower() for match in re.finditer(r"[A-Za-z]+\d*|\d+", query))
        for cjk_run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", query):
            if len(cjk_run) > 2:
                terms.extend(cjk_run[index : index + 2] for index in range(len(cjk_run) - 1))
        return list(dict.fromkeys(term for term in terms if len(term) >= 2))[:32]

    @staticmethod
    def _lexical_score(text: str, terms: list[str]) -> float:
        lower_text = text.lower()
        score = 0.0
        for term in terms:
            count = lower_text.count(term)
            if count <= 0:
                continue
            if re.fullmatch(r"t\d{1,3}[a-z]?", term):
                heading_re = re.compile(
                    rf"(?im)^[\s#*_`>]*{re.escape(term)}[\s*_`#>]*$"
                )
                score += 100.0 if heading_re.search(text) else 10.0 * count
            elif term.isdigit() or len(term) <= 2:
                score += 0.25 * count
            else:
                score += float(count)
        return score

    @staticmethod
    def _structural_anchors(query: str) -> dict[str, set[str]]:
        anchors: dict[str, set[str]] = {
            "section_label": set(),
            "subsection_label": set(),
            "section_path": set(),
            "anchor_label": set(),
        }
        for match in re.finditer(r"(?<![A-Za-z0-9])T\d{1,3}[A-Za-z]?", query, flags=re.I):
            value = match.group(0).upper()
            anchors["section_label"].add(value)
            anchors["anchor_label"].add(value)
        for match in re.finditer(r"\b\d+(?:\.\d+){1,4}\b", query):
            anchors["section_label"].add(match.group(0))
            anchors["section_path"].add(match.group(0))
        for match in re.finditer(r"\b(?:Fig(?:ure)?|Table)\.?\s*\d+[A-Za-z]?\b", query, flags=re.I):
            anchors["anchor_label"].add(_normalize_anchor(match.group(0)))
        for match in re.finditer(
            r"\b(?:Scholium(?:\s+[a-z])?|Lemma(?:\s+[a-z])?|Speculative strategy\s+[a-z])\b",
            query,
            flags=re.I,
        ):
            anchors["subsection_label"].add(_normalize_anchor(match.group(0)))
        return {key: value for key, value in anchors.items() if value}

    @staticmethod
    def _metadata_matches_anchor(
        metadata: dict[str, object], anchors: dict[str, set[str]]
    ) -> bool:
        section_label = str(metadata.get("section_label") or "")
        section_labels = metadata.get("section_labels") or []
        subsection_label = str(metadata.get("subsection_label") or "")
        anchor_label = str(metadata.get("anchor_label") or "")
        section_path = metadata.get("section_path") or []
        section_paths = metadata.get("section_paths") or []
        if "section_label" in anchors and _normalize_anchor(section_label) in {
            _normalize_anchor(value) for value in anchors["section_label"]
        }:
            return True
        if isinstance(section_labels, list) and "section_label" in anchors:
            normalized_labels = {_normalize_anchor(str(value)) for value in section_labels}
            if normalized_labels & {
                _normalize_anchor(value) for value in anchors["section_label"]
            }:
                return True
        if "subsection_label" in anchors and _normalize_anchor(subsection_label) in {
            _normalize_anchor(value) for value in anchors["subsection_label"]
        }:
            return True
        if "anchor_label" in anchors and _normalize_anchor(anchor_label) in {
            _normalize_anchor(value) for value in anchors["anchor_label"]
        }:
            return True
        if isinstance(section_path, list) and "section_path" in anchors:
            normalized_path = {_normalize_anchor(str(value)) for value in section_path}
            if normalized_path & {
                _normalize_anchor(value) for value in anchors["section_path"]
            }:
                return True
        if isinstance(section_paths, list) and "section_path" in anchors:
            normalized_paths: set[str] = set()
            for path in section_paths:
                if isinstance(path, list):
                    normalized_paths.update(_normalize_anchor(str(value)) for value in path)
                else:
                    normalized_paths.add(_normalize_anchor(str(path)))
            if normalized_paths & {
                _normalize_anchor(value) for value in anchors["section_path"]
            }:
                return True
        return False

    async def _find_local_chunk(self, chunk_id: str) -> DocumentChunk | None:
        db_conn = getattr(self._source_store, "_db", None)
        if db_conn is None:
            return None
        try:
            async with db_conn.execute(
                "SELECT doc_id, ordinal, text, content_hash, metadata "
                "FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    metadata = _loads_metadata(row[4])
                    return DocumentChunk(chunk_id, row[0], row[1], row[2], row[3], metadata)
        except Exception as exc:
            logger.error("Failed to find local chunk %s: %s", chunk_id, exc)
        return None


def _loads_metadata(raw: object) -> dict[str, object]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(str(raw))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_anchor(value: str) -> str:
    normalized = re.sub(r"[*_`#]+", "", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.rstrip(".").upper()


__all__ = [
    "RetrievalOrchestrator",
    "RetrievalOutcome",
    "RetrievalScope",
    "SCOPE_COLLECTION",
    "SCOPE_ITEM",
    "SCOPE_TAG",
    "SCOPE_LIBRARY",
]
