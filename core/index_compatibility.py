"""Embedding-backed index compatibility state.

Milvus and LightRAG are rebuildable projections of the SQLite source store.
This small JSON state prevents an index built with one embedding model from
silently participating after the runtime embedding fingerprint changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from core.config import EmbeddingConfig

logger = logging.getLogger("IndexCompatibilityStore")


def embedding_fingerprint(config: EmbeddingConfig, dimension: int) -> str:
    payload = {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "dimension": dimension,
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IndexCompatibilityStore:
    """Persists the embedding fingerprint used by each rebuildable index."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._state = self._load()

    def is_milvus_compatible(self, fingerprint: str) -> bool:
        return self._state.get("milvus", {}).get("fingerprint") == fingerprint

    def mark_milvus_compatible(self, fingerprint: str) -> None:
        self._state["milvus"] = {"fingerprint": fingerprint, "reason": ""}
        self._save()

    def mark_milvus_incompatible(self, reason: str) -> None:
        self._state["milvus"] = {"fingerprint": "", "reason": reason}
        self._save()

    def is_lightrag_compatible(self, collection: str, fingerprint: str) -> bool:
        collections = self._state.get("lightrag", {}).get("collections", {})
        return collections.get(collection) == fingerprint

    def mark_lightrag_compatible(self, collection: str, fingerprint: str) -> None:
        lightrag = self._state.setdefault("lightrag", {})
        collections = lightrag.setdefault("collections", {})
        collections[collection] = fingerprint
        lightrag["reason"] = ""
        self._save()

    def remove_lightrag_collection(self, collection: str) -> None:
        collections = self._state.get("lightrag", {}).get("collections", {})
        if collections.pop(collection, None) is not None:
            self._save()

    def mark_all_incompatible(self, reason: str) -> None:
        self._state["milvus"] = {"fingerprint": "", "reason": reason}
        self._state["lightrag"] = {"collections": {}, "reason": reason}
        self._save()

    def reason(self, index: str) -> str:
        value = self._state.get(index, {})
        return str(value.get("reason") or "")

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read index compatibility state: %s", exc)
            return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to persist index compatibility state: %s", exc)
            raise


__all__ = ["IndexCompatibilityStore", "embedding_fingerprint"]
