"""LightRAG Core integration helpers.

This module is intentionally small and explicit: AstrBot deployment is the first
place where real local LLM/Embedding endpoints are available, so every operation
logs readable "KR LightRAG" lines for terminal-based manual verification.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import logging
import re
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
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    recent_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        elapsed = (self.finished_at or time.time()) - self.started_at
        return {
            "job_id": self.job_id,
            "collection": self.collection,
            "engine": self.engine,
            "status": self.status,
            "stage": self.stage,
            "processed_docs": self.processed_docs,
            "failed_docs": self.failed_docs,
            "total_docs": self.total_docs,
            "elapsed_seconds": round(elapsed, 2),
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
        del keyword_extraction, kwargs
        flattened = _flatten_history(history_messages or [])
        user_prompt = f"{flattened}\n\n{prompt}" if flattened else prompt
        return await self._llm_adapter.generate(
            user_prompt, system_prompt=system_prompt or "", allow_mock=False
        )


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
    ) -> None:
        self._config = config
        self._data_dir = data_dir
        self._llm_adapter = llm_adapter
        self._embedding_provider = embedding_provider
        self._instances: dict[str, Any] = {}
        self._workspace_map: dict[str, str] = {}
        self._root = self._resolve_root(config.working_dir)
        self._map_path = self._root / "workspace_map.json"
        self._load_workspace_map()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

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

    async def insert_document(self, collection: str, doc_id: str, text: str) -> None:
        rag = await self.get(collection)
        _terminal(f"ainsert collection={collection!r} doc_id={doc_id!r} chars={len(text)}")
        await rag.ainsert(text, ids=[doc_id])

    async def query(self, collection: str, query: str) -> dict[str, Any]:
        from lightrag import QueryParam

        rag = await self.get(collection)
        mode = self._config.query_mode if self._config.query_mode in _QUERY_MODES else "mix"
        _terminal(f"aquery collection={collection!r} mode={mode!r} query={query!r}")
        answer = await rag.aquery(query, param=QueryParam(mode=mode))
        return {
            "answer": str(answer),
            "context": "",
            "collection": collection,
            "engine": "lightrag_core",
            "debug": {"query_mode": mode},
        }

    async def export_graph(self, collection: str) -> dict[str, Any]:
        rag = await self.get(collection)
        with tempfile.TemporaryDirectory(prefix="kr_lightrag_export_") as tmp:
            output = Path(tmp) / "graph.csv"
            _terminal(f"export_data collection={collection!r} output={output}")
            await rag.aexport_data(str(output), file_format="csv", include_vector_data=False)
            if not output.exists():
                raise RuntimeError("LightRAG export_data did not create an output file")
            return parse_lightrag_csv(output, collection)

    async def delete_doc(self, collection: str, doc_id: str) -> dict[str, Any]:
        rag = await self.get(collection)
        _terminal(f"adelete_by_doc_id collection={collection!r} doc_id={doc_id!r}")
        result = await rag.adelete_by_doc_id(doc_id)
        return {
            "engine": "lightrag_core",
            "collection": collection,
            "doc_id": doc_id,
            "result": str(result),
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
            embedding_dim=self._config.embedding_dim,
            max_token_size=self._config.max_token_size,
        )
        return LightRAG(
            working_dir=str(workspace_dir),
            workspace=self._workspace_map[collection],
            embedding_func=EmbeddingFunc(
                embedding_dim=self._config.embedding_dim,
                func=embedding,
                max_token_size=self._config.max_token_size,
                model_name=embedding.model_name,
            ),
            llm_model_func=LightRAGLLMAdapter(self._llm_adapter),
            llm_model_max_async=self._config.llm_max_async,
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
    docs: list[Any], chunks_by_doc: dict[str, list[Any]]
) -> dict[str, int | str]:
    docs_count = len(docs)
    chunks_count = sum(len(chunks_by_doc.get(doc.doc_id, [])) for doc in docs)
    chars_count = sum(
        len("\n\n".join(chunk.text for chunk in chunks_by_doc.get(doc.doc_id, []))) for doc in docs
    )
    estimated_llm_min = docs_count
    estimated_llm_max = max(docs_count, docs_count * 4 + max(0, chars_count // 6000))
    estimated_embedding_batches = max(1 if docs_count else 0, (chunks_count + 9) // 10)
    return {
        "docs_count": docs_count,
        "chunks_count": chunks_count,
        "chars_count": chars_count,
        "estimated_llm_calls_min": estimated_llm_min,
        "estimated_llm_calls_max": estimated_llm_max,
        "estimated_embedding_batches": estimated_embedding_batches,
        "estimated_duration_seconds_min": docs_count * 5,
        "estimated_duration_seconds_max": max(docs_count * 20, estimated_llm_max * 15),
        "estimate_notice": "这是估算，不是承诺；实际 LLM 调用次数和耗时可能更高。",
    }


def parse_lightrag_csv(path: Path, collection: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    sections = _split_export_sections(text)
    if "ENTITIES" not in sections and "RELATIONS" not in sections:
        raise RuntimeError(
            "LightRAG export_data output did not contain ENTITIES or RELATIONS sections"
        )

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
