"""LightRAG Core integration helpers.

This module is intentionally small and explicit: AstrBot deployment is the first
place where real local LLM/Embedding endpoints are available, so every operation
logs readable "KR LightRAG" lines for terminal-based manual verification.
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import csv
import hashlib
import inspect
import json
import logging
import math
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from core.config import GraphConfig

if TYPE_CHECKING:
    from core.adapters.llm import LLMAdapter
    from core.repository.embedding.base import EmbeddingProvider

logger = logging.getLogger("LightRAGCore")

_QUERY_MODES = {"local", "global", "hybrid", "naive", "mix", "bypass"}
_LLM_PROGRESS_CALLBACK: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "kr_lightrag_llm_progress_callback", default=None
)


@dataclass
class BuildJob:
    job_id: str
    collection: str
    status: str = "queued"
    engine: str = "lightrag_core"
    stage: str = "queued"
    processed_docs: int = 0
    failed_docs: int = 0
    total_docs: int = 0
    processed_chunks: int = 0
    failed_chunks: int = 0
    total_chunks: int = 0
    current_doc_id: str = ""
    current_chunk_index: int = 0
    progress_basis: str = "lrag_chunks"
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    recent_error: str = ""
    paused: bool = False

    def to_dict(self) -> dict[str, Any]:
        elapsed = (self.finished_at or time.monotonic()) - self.started_at
        avg = elapsed / self.processed_chunks if self.processed_chunks > 0 else None
        remaining_chunks = max(0, self.total_chunks - self.processed_chunks)
        eta = remaining_chunks * avg if avg is not None else None
        return {
            "job_id": self.job_id,
            "type": "lightrag_build",
            "collection": self.collection,
            "engine": self.engine,
            "status": self.status,
            "stage": self.stage,
            "paused": self.paused,
            "processed_docs": self.processed_docs,
            "failed_docs": self.failed_docs,
            "total_docs": self.total_docs,
            "processed_chunks": self.processed_chunks,
            "failed_chunks": self.failed_chunks,
            "total_chunks": self.total_chunks,
            "current_doc_id": self.current_doc_id,
            "current_chunk_index": self.current_chunk_index,
            "progress_basis": self.progress_basis,
            "elapsed_seconds": round(elapsed, 2),
            "average_seconds_per_chunk": round(avg, 2) if avg is not None else None,
            "estimated_remaining_seconds": round(eta, 2) if eta is not None else None,
            "recent_error": self.recent_error,
        }


class LightRAGLLMAdapter:
    """Callable adapter matching LightRAG's llm_model_func contract."""

    def __init__(self, llm_adapter: LLMAdapter) -> None:
        self._llm_adapter = llm_adapter

    async def __call__(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        keyword_extraction: bool = False,
        **kwargs: Any,
    ) -> str:
        del kwargs
        flattened = _flatten_history(history_messages or [])
        user_prompt = f"{flattened}\n\n{prompt}" if flattened else prompt
        started = time.monotonic()
        try:
            result = await self._llm_adapter.generate(
                user_prompt, system_prompt=system_prompt or "", allow_mock=False
            )
        except Exception:
            _emit_llm_progress(
                {
                    "status": "error",
                    "elapsed_seconds": time.monotonic() - started,
                    "keyword_extraction": keyword_extraction,
                    "prompt_chars": len(user_prompt),
                }
            )
            raise
        _emit_llm_progress(
            {
                "status": "ok",
                "elapsed_seconds": time.monotonic() - started,
                "keyword_extraction": keyword_extraction,
                "prompt_chars": len(user_prompt),
            }
        )
        return result


class LightRAGEmbeddingAdapter:
    """Callable adapter matching LightRAG's EmbeddingFunc contract."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        embedding_dim: int,
        max_token_size: int,
        model_name: str = "kr-configured-embedding",
    ) -> None:
        self._provider = provider
        self.embedding_dim = embedding_dim
        self.max_token_size = max_token_size
        self.model_name = model_name

    async def __call__(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        del kwargs
        vectors = await self._provider.embed_documents(list(texts))
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding batch mismatch: expected {len(texts)} vectors, got {len(vectors)}."
            )
        for vector in vectors:
            if len(vector) != self.embedding_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.embedding_dim}, "
                    f"got {len(vector)}."
                )
        return np.asarray(vectors, dtype=np.float32)


class LightRAGCoreRegistry:
    """Creates, caches and finalizes official LightRAG instances per collection."""

    def __init__(
        self,
        *,
        config: GraphConfig,
        data_dir: Path,
        llm_adapter: LLMAdapter,
        embedding_provider: EmbeddingProvider | None,
        embedding_dim: int,
        max_token_size: int,
        embedding_model: str,
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._llm_adapter = llm_adapter
        self._embedding_provider = embedding_provider
        self._embedding_dim = embedding_dim
        self._max_token_size = max_token_size
        self._embedding_model = embedding_model
        self._instances: dict[str, Any] = {}
        self._workspace_map: dict[str, str] = {}
        self._collection_locks: dict[str, asyncio.Lock] = {}
        self._root = self._resolve_root(config.working_dir)
        self._map_path = self._root / "workspace_map.json"
        self._load_workspace_map()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def has_workspace(self, collection: str) -> bool:
        safe = self._workspace_map.get(collection)
        return bool(safe and (self._root / safe).is_dir())

    def existing_collections(self) -> list[str]:
        return sorted(
            collection for collection in self._workspace_map if self.has_workspace(collection)
        )

    async def get(self, collection: str) -> Any:
        if not self._config.enabled:
            raise RuntimeError("LightRAG Core is disabled in graph.enabled")
        if self._embedding_provider is None:
            raise RuntimeError("LightRAG Core requires a configured EmbeddingProvider")
        if collection in self._instances:
            return self._instances[collection]

        rag = self._new_instance(collection)
        _terminal(f"initialize_storages collection={collection!r}")
        await rag.initialize_storages()
        self._instances[collection] = rag
        return rag

    async def close(self) -> None:
        for collection, rag in list(self._instances.items()):
            try:
                _terminal(f"finalize_storages collection={collection!r}")
                await rag.finalize_storages()
            except Exception as exc:
                logger.warning("LightRAG finalize failed for %s: %s", collection, exc)
        self._instances.clear()

    def _get_collection_lock(self, collection: str) -> asyncio.Lock:
        if not hasattr(self, "_collection_locks"):
            self._collection_locks = {}
        if collection not in self._collection_locks:
            self._collection_locks[collection] = asyncio.Lock()
        return self._collection_locks[collection]

    async def reset_workspace(self, collection: str) -> None:
        """Delete one derived workspace after an explicit rebuild/delete action."""
        async with self._get_collection_lock(collection):
            rag = self._instances.pop(collection, None)
            if rag is not None:
                # Clear shared in-memory data for all JsonKVStorage & JsonDocStatusStorage instances
                for attr in [
                    "text_chunks",
                    "full_docs",
                    "full_entities",
                    "full_relations",
                    "entity_chunks",
                    "relation_chunks",
                    "doc_status",
                ]:
                    storage = getattr(rag, attr, None)
                    if storage is not None and hasattr(storage, "drop"):
                        try:
                            await storage.drop()
                        except Exception as exc:
                            logger.warning(
                                "Failed to drop storage %s during workspace reset: %s", attr, exc
                            )
                _terminal(f"finalize_storages collection={collection!r} before reset")
                await rag.finalize_storages()
            safe = self._workspace_map.get(collection)
            if safe is None:
                return
            workspace = (self._root / safe).resolve()
            workspace.relative_to(self._root.resolve())
            if workspace.is_dir():
                shutil.rmtree(workspace)
            self._workspace_map.pop(collection, None)
            self._save_workspace_map()

    async def chunk_document(self, collection: str, text: str) -> tuple[list[str], str]:
        """按当前 LightRAG SDK 默认路径生成 LRAG chunk，不复用 Milvus chunk。"""
        rag = await self.get(collection)
        try:
            value = rag.chunking_func(
                rag.tokenizer,
                text,
                None,
                False,
                int(rag.chunk_overlap_token_size),
                int(rag.chunk_token_size),
            )
            rows = await value if inspect.isawaitable(value) else value
            chunks = [str(row.get("content") or "") for row in rows if row.get("content")]
            return (chunks or [text], "lrag_chunks")
        except Exception as exc:
            logger.warning("LightRAG chunk planning failed; using estimated chunks: %s", exc)
            return (_fallback_text_chunks(text), "estimated_lrag_chunks")

    async def insert_document(
        self,
        collection: str,
        doc_id: str,
        text: str,
        *,
        lrag_chunks: list[str] | None = None,
        progress_callback: Any = None,
    ) -> None:
        async with self._get_collection_lock(collection):
            rag = await self.get(collection)
            chunks = lrag_chunks or []
            token = _LLM_PROGRESS_CALLBACK.set(progress_callback)
            try:
                if chunks and hasattr(rag, "ainsert_custom_chunks"):
                    _terminal(
                        f"ainsert_custom_chunks collection={collection!r} doc_id={doc_id!r} "
                        f"chars={len(text)} chunks={len(chunks)}"
                    )
                    await rag.ainsert_custom_chunks(text, chunks, doc_id=doc_id)
                    return
                _terminal(
                    f"ainsert collection={collection!r} doc_id={doc_id!r} "
                    f"chars={len(text)} chunks={len(chunks)}"
                )
                result = await rag.ainsert(text, ids=[doc_id])
                if result is not None:
                    _terminal(f"ainsert done track_id={result!r}")
            finally:
                _LLM_PROGRESS_CALLBACK.reset(token)

    async def query(
        self, collection: str, query: str, *, only_need_context: bool = False
    ) -> dict[str, Any]:
        from lightrag import QueryParam

        if not self.has_workspace(collection):
            raise RuntimeError(f"LightRAG workspace is not built for collection '{collection}'")
        rag = await self.get(collection)
        mode = self._config.query_mode if self._config.query_mode in _QUERY_MODES else "mix"
        _terminal(
            f"aquery collection={collection!r} mode={mode!r} "
            f"only_need_context={only_need_context!r} query={query!r}"
        )
        value = await rag.aquery(
            query,
            param=QueryParam(mode=mode, only_need_context=only_need_context),
        )
        return {
            "answer": "" if only_need_context else str(value),
            "context": str(value) if only_need_context else "",
            "collection": collection,
            "engine": "lightrag_core",
            "debug": {"query_mode": mode, "only_need_context": only_need_context},
        }

    async def export_graph(self, collection: str) -> dict[str, Any]:
        if not self.has_workspace(collection):
            raise RuntimeError(f"LightRAG workspace is not built for collection '{collection}'")
        rag = await self.get(collection)
        with tempfile.TemporaryDirectory(prefix="kr_lightrag_export_") as tmp:
            output = Path(tmp) / "graph.csv"
            _terminal(f"export_data collection={collection!r} output={output}")
            await rag.aexport_data(str(output), file_format="csv", include_vector_data=False)
            if not output.exists():
                raise RuntimeError("LightRAG export_data did not create an output file")
            return parse_lightrag_csv(output, collection)

    async def delete_doc(self, collection: str, doc_id: str) -> dict[str, Any]:
        if not self.has_workspace(collection):
            return {
                "engine": "lightrag_core",
                "collection": collection,
                "doc_id": doc_id,
                "result": "skipped",
                "message": "workspace is not built",
            }
        async with self._get_collection_lock(collection):
            rag = await self.get(collection)
            _terminal(f"adelete_by_doc_id collection={collection!r} doc_id={doc_id!r}")
            result = await rag.adelete_by_doc_id(doc_id)
            status = getattr(result, "status", None) or str(result)
            message = getattr(result, "message", None) or ""
            return {
                "engine": "lightrag_core",
                "collection": collection,
                "doc_id": doc_id,
                "result": status,
                "message": message,
            }

    async def manual_probe(
        self,
        *,
        collection: str,
        text: str,
        doc_id: str,
        query: str,
    ) -> dict[str, Any]:
        """Deployment-only end-to-end probe using real configured providers."""
        steps: list[dict[str, Any]] = []

        async def run_step(name: str, fn):
            started = time.time()
            try:
                value = await fn()
                item = {
                    "step": name,
                    "status": "ok",
                    "elapsed_seconds": round(time.time() - started, 2),
                }
                if value is not None:
                    item["result"] = value
                steps.append(item)
                _terminal(f"probe {name} OK")
                return value
            except Exception as exc:
                item = {
                    "step": name,
                    "status": "error",
                    "elapsed_seconds": round(time.time() - started, 2),
                    "error": str(exc),
                }
                steps.append(item)
                _terminal(f"probe {name} ERROR {exc}")
                raise

        try:
            await run_step("initialize_storages", lambda: self.get(collection))
            await run_step("ainsert", lambda: self.insert_document(collection, doc_id, text))
            await run_step(
                "aquery_context",
                lambda: self.query(collection, query, only_need_context=True),
            )
            await run_step("aquery", lambda: self.query(collection, query))
            before = await run_step(
                "export_data_before_delete", lambda: self.export_graph(collection)
            )
            await run_step("adelete_by_doc_id", lambda: self.delete_doc(collection, doc_id))
            after = await run_step(
                "export_data_after_delete", lambda: self.export_graph(collection)
            )
            before_shape = (len(before.get("nodes", [])), len(before.get("edges", [])))
            after_shape = (len(after.get("nodes", [])), len(after.get("edges", [])))
            delete_stable = before_shape != (0, 0) and after_shape != before_shape
            return {
                "status": "success",
                "delete_strategy": "adelete_by_doc_id",
                "delete_stable": delete_stable,
                "steps": steps,
            }
        except Exception:
            return {
                "status": "error",
                "delete_strategy": "unverified",
                "delete_stable": False,
                "steps": steps,
            }

    def _new_instance(self, collection: str) -> Any:
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc

        workspace_dir = self._workspace_dir(collection)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        embedding = LightRAGEmbeddingAdapter(
            self._embedding_provider,  # type: ignore[arg-type]
            embedding_dim=self._embedding_dim,
            max_token_size=self._max_token_size,
            model_name=self._embedding_model,
        )
        return LightRAG(
            working_dir=str(workspace_dir),
            workspace=self._workspace_map[collection],
            embedding_func=EmbeddingFunc(
                embedding_dim=self._embedding_dim,
                func=embedding,
                max_token_size=self._max_token_size,
                model_name=embedding.model_name,
            ),
            llm_model_func=LightRAGLLMAdapter(self._llm_adapter),
            llm_model_max_async=self._config.llm_max_async,
            default_llm_timeout=self._config.lightrag_llm_timeout_seconds,
            embedding_func_max_async=self._config.embedding_max_async,
            auto_manage_storages_states=False,
        )

    def _workspace_dir(self, collection: str) -> Path:
        safe = self._workspace_map.get(collection)
        if safe is None:
            safe = sanitize_collection_name(collection, set(self._workspace_map.values()))
            self._workspace_map[collection] = safe
            self._save_workspace_map()
        return self._root / safe

    def _resolve_root(self, configured: str) -> Path:
        root = Path(configured)
        if not root.is_absolute():
            root = self._data_dir / root
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _load_workspace_map(self) -> None:
        if not self._map_path.exists():
            return
        try:
            data = json.loads(self._map_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._workspace_map = {str(k): str(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning("Failed to read LightRAG workspace map: %s", exc)

    def _save_workspace_map(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._map_path.write_text(
            json.dumps(self._workspace_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def sanitize_collection_name(collection: str, existing: set[str] | None = None) -> str:
    existing = existing or set()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", collection.strip()).strip("._-").lower()
    if not base:
        base = "collection"
    digest = hashlib.sha1(collection.encode("utf-8")).hexdigest()[:10]
    safe = f"{base[:48]}_{digest}"
    while safe in existing:
        digest = hashlib.sha1(f"{collection}:{len(existing)}".encode()).hexdigest()[:10]
        safe = f"{base[:48]}_{digest}"
    return safe


def estimate_lightrag_build(
    docs: list[Any],
    chunks_by_doc: dict[str, list[Any]],
    max_doc_chars: int = 0,
    *,
    is_local_lightrag_llm: bool = False,
    seconds_per_chunk_local: float = 90.0,
    seconds_per_chunk_remote: float = 20.0,
) -> dict[str, int | float | str]:
    docs_count = len(docs)

    doc_char_counts: list[int] = []
    chunks_count = 0
    raw_chars = 0
    for doc in docs:
        chunks = chunks_by_doc.get(doc.doc_id, [])
        chunks_count += len(chunks)
        doc_chars = len("\n\n".join(chunk.text for chunk in chunks))
        raw_chars += doc_chars
        doc_char_counts.append(min(doc_chars, max_doc_chars) if max_doc_chars > 0 else doc_chars)

    chars_count = sum(doc_char_counts)
    # LightRAG SDK 默认 F chunker 是 token-based；这里 dry-run 不初始化模型，按字符保守估算。
    estimated_lrag_chunks = sum(
        max(1, math.ceil(chars / 4000)) for chars in doc_char_counts if chars
    )
    estimated_llm_min = estimated_lrag_chunks
    estimated_llm_max = max(estimated_lrag_chunks, math.ceil(estimated_lrag_chunks * 1.5))
    estimated_embedding_batches = max(1 if docs_count else 0, (estimated_lrag_chunks + 9) // 10)

    per_chunk = seconds_per_chunk_local if is_local_lightrag_llm else seconds_per_chunk_remote
    duration_min = int(max(docs_count * 5, estimated_llm_min * per_chunk * 0.6))
    duration_max = int(max(duration_min, estimated_llm_max * per_chunk * 1.6))
    runtime = "local" if is_local_lightrag_llm else "remote"
    return {
        "docs_count": docs_count,
        "chunks_count": chunks_count,
        "chars_count": chars_count,
        "estimated_lrag_chunks": estimated_lrag_chunks,
        "estimated_llm_calls_min": estimated_llm_min,
        "estimated_llm_calls_max": estimated_llm_max,
        "estimated_embedding_batches": estimated_embedding_batches,
        "estimated_duration_seconds_min": duration_min,
        "estimated_duration_seconds_max": duration_max,
        "seconds_per_chunk": per_chunk,
        "runtime_profile": runtime,
        "estimate_notice": (
            "这是基于 LRAG chunk 的估算，不是倒计时；实际耗时会按运行中速度动态修正。"
        ),
    }


def parse_lightrag_csv(path: Path, collection: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    sections = _split_export_sections(text)
    if "ENTITIES" not in sections and "RELATIONS" not in sections:
        # 空图：LightRAG 提取到 0 个实体（LLM 返回为空或提取失败），不报错，返回空图
        logger.warning(
            "LightRAG export for collection %r returned no entities/relations — "
            "graph may be empty or entity extraction produced no output.",
            collection,
        )
        return {
            "status": "success",
            "collection": collection,
            "engine": "lightrag_core",
            "nodes": [],
            "edges": [],
        }

    nodes: list[dict[str, Any]] = []
    for row in _read_csv_rows(sections.get("ENTITIES", "")):
        graph_data = _literal_dict(row.get("graph_data", ""))
        name = row.get("entity_name") or graph_data.get("entity_name") or graph_data.get("name")
        if not name:
            continue
        nodes.append(
            {
                "id": str(name),
                "name": str(name),
                "type": str(graph_data.get("entity_type") or graph_data.get("type") or "Entity"),
                "description": str(graph_data.get("description") or ""),
                "source_chunk_ids": _split_source_ids(
                    row.get("source_id") or graph_data.get("source_id")
                ),
            }
        )

    node_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    for idx, row in enumerate(_read_csv_rows(sections.get("RELATIONS", ""))):
        graph_data = _literal_dict(row.get("graph_data", ""))
        src = str(row.get("src_entity") or graph_data.get("src_id") or "")
        tgt = str(row.get("tgt_entity") or graph_data.get("tgt_id") or "")
        if not src or not tgt or src not in node_ids or tgt not in node_ids:
            continue
        relation = str(graph_data.get("keywords") or graph_data.get("relation") or "related_to")
        edges.append(
            {
                "id": f"{src}->{tgt}:{idx}",
                "source": src,
                "target": tgt,
                "relation": relation,
                "description": str(graph_data.get("description") or ""),
                "weight": float(graph_data.get("weight") or 1.0),
                "source_chunk_ids": _split_source_ids(
                    row.get("source_id") or graph_data.get("source_id")
                ),
            }
        )

    return {
        "status": "success",
        "collection": collection,
        "engine": "lightrag_core",
        "nodes": nodes,
        "edges": edges,
    }


def _split_export_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("# "):
            current = line[2:].strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {
        key: "\n".join(lines).strip() for key, lines in sections.items() if "\n".join(lines).strip()
    }


def _read_csv_rows(section: str) -> list[dict[str, str]]:
    if not section:
        return []
    return list(csv.DictReader(section.splitlines()))


def _literal_dict(value: str) -> dict[str, Any]:
    try:
        parsed = ast.literal_eval(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _split_source_ids(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [part.strip() for part in re.split(r"<SEP>|[,;]", str(value)) if part.strip()]


def _flatten_history(history: list[dict[str, str]]) -> str:
    lines = []
    for item in history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _emit_llm_progress(event: dict[str, Any]) -> None:
    callback = _LLM_PROGRESS_CALLBACK.get()
    if callable(callback):
        callback(event)


def _fallback_text_chunks(
    text: str, chunk_chars: int = 4000, overlap_chars: int = 300
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    step = max(1, chunk_chars - overlap_chars)
    return [stripped[i : i + chunk_chars] for i in range(0, len(stripped), step)]


def _terminal(message: str) -> None:
    text = f"KR LightRAG {message}"
    print(text, flush=True)
    logger.info(text)


__all__ = [
    "BuildJob",
    "LightRAGCoreRegistry",
    "LightRAGEmbeddingAdapter",
    "LightRAGLLMAdapter",
    "estimate_lightrag_build",
    "parse_lightrag_csv",
    "sanitize_collection_name",
]
