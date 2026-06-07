"""Unified evidence retrieval for default and high-precision Ask flows."""
from __future__ import annotations

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

        lexical_chunks: list[DocumentChunk] = []
        try:
            lexical_chunks = await self._search_lexical_sqlite(collection, query, top_k * 2)
            if lexical_chunks:
                engines.append("sqlite_lexical")
        except Exception as exc:
            logger.error("SQLite lexical search failed: %s", exc)

        # 硬过滤契约（review #3）：任何候选 chunk 必须先满足 allowed_doc_ids 才进入 RRF。
        if allowed_doc_ids is not None:
            dense_chunks = [c for c in dense_chunks if c.doc_id in allowed_doc_ids]
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
            f"LIMIT {limit * 2}"
        )
        matched: list[tuple[DocumentChunk, int]] = []
        async with db_conn.execute(sql, params) as cursor:
            async for row in cursor:
                chunk = DocumentChunk(row[0], row[1], row[2], row[3], row[4])
                lower_text = chunk.text.lower()
                matched.append((chunk, sum(lower_text.count(term) for term in terms)))
        matched.sort(key=lambda item: item[1], reverse=True)
        return [item[0] for item in matched[:limit]]

    @staticmethod
    def _lexical_terms(query: str) -> list[str]:
        terms = [term.strip().lower() for term in re.split(r"\s+", query) if term.strip()]
        for cjk_run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", query):
            if len(cjk_run) > 2:
                terms.extend(cjk_run[index : index + 2] for index in range(len(cjk_run) - 1))
        return list(dict.fromkeys(term for term in terms if len(term) >= 2))[:32]

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
                    import json

                    metadata = json.loads(row[4]) if row[4] else {}
                    return DocumentChunk(chunk_id, row[0], row[1], row[2], row[3], metadata)
        except Exception as exc:
            logger.error("Failed to find local chunk %s: %s", chunk_id, exc)
        return None


__all__ = [
    "RetrievalOrchestrator",
    "RetrievalOutcome",
    "RetrievalScope",
    "SCOPE_COLLECTION",
    "SCOPE_ITEM",
    "SCOPE_TAG",
    "SCOPE_LIBRARY",
]
