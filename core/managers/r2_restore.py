"""应用或回滚已经完整校验的 R2 restore staging。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config

_PENDING_RESTORE = ".r2_pending_restore.json"
_APPLIED_RESTORE = ".r2_applied_restore.json"
_ROLLBACK_DIR = ".r2_restore_rollback"


def apply_pending_restore(data_dir: Path, config: Config) -> bool:
    """在数据库和索引连接建立前应用已验证 staging。"""
    marker_path = data_dir / _PENDING_RESTORE
    if not marker_path.exists():
        return False
    marker = _read_json(marker_path)
    snapshot_id = str(marker.get("snapshot_id") or "")
    stage_root = Path(str(marker.get("stage_root") or ""))
    payload = stage_root / "payload"
    if not snapshot_id or not payload.is_dir():
        raise RuntimeError("R2 pending restore marker is invalid")

    portable_path = payload / "config" / "portable_config.json"
    current_runtime = _read_json(data_dir / "runtime_config.json")
    portable = _read_json(portable_path)
    staged_runtime = payload / "config" / "runtime_config.json"
    _write_json_atomic(staged_runtime, _merge_portable_config(current_runtime, portable))

    source_cfg = config.get_source_store_config()
    vector_cfg = config.get_vector_db_config()
    graph_root = Path(config.get_graph_config().working_dir)
    if not graph_root.is_absolute():
        graph_root = data_dir / graph_root
    mappings = [
        (payload / "database" / "knowledge_repository.db", data_dir / source_cfg.db_filename),
        (payload / "library", data_dir / "library"),
        (payload / "indexes" / "vector_store.db", data_dir / vector_cfg.db_filename),
        (payload / "indexes" / "embedding_cache.db", data_dir / "embedding_cache.db"),
        (
            payload / "indexes" / "index_compatibility.json",
            data_dir / "index_compatibility.json",
        ),
        (payload / "lightrag", graph_root),
        (staged_runtime, data_dir / "runtime_config.json"),
    ]
    rollback = data_dir / _ROLLBACK_DIR / snapshot_id
    if rollback.exists():
        shutil.rmtree(rollback)
    rollback.mkdir(parents=True, exist_ok=True)
    applied: list[dict[str, str]] = []
    try:
        for idx, (source, target) in enumerate(mappings):
            if not source.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            old = rollback / f"{idx:02d}-{target.name}"
            if target.exists():
                shutil.move(str(target), str(old))
            shutil.move(str(source), str(target))
            applied.append({"target": str(target), "old": str(old)})
        _rewrite_restored_document_paths(data_dir / source_cfg.db_filename, data_dir)
    except Exception:
        for row in reversed(applied):
            target = Path(row["target"])
            old = Path(row["old"])
            if target.exists():
                _remove_path(target)
            if old.exists():
                shutil.move(str(old), str(target))
        raise

    _write_json_atomic(
        data_dir / _APPLIED_RESTORE,
        {"snapshot_id": snapshot_id, "rollback": str(rollback), "applied": applied},
    )
    marker_path.unlink(missing_ok=True)
    shutil.rmtree(stage_root, ignore_errors=True)
    return True


def commit_applied_restore(data_dir: Path) -> None:
    marker = data_dir / _APPLIED_RESTORE
    if not marker.exists():
        return
    payload = _read_json(marker)
    rollback = Path(str(payload.get("rollback") or ""))
    if rollback.exists():
        shutil.rmtree(rollback, ignore_errors=True)
    marker.unlink(missing_ok=True)


def rollback_applied_restore(data_dir: Path) -> bool:
    marker = data_dir / _APPLIED_RESTORE
    if not marker.exists():
        return False
    payload = _read_json(marker)
    for row in reversed(payload.get("applied") or []):
        target = Path(str(row.get("target") or ""))
        old = Path(str(row.get("old") or ""))
        if target.exists():
            _remove_path(target)
        if old.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(target))
    rollback = Path(str(payload.get("rollback") or ""))
    shutil.rmtree(rollback, ignore_errors=True)
    marker.unlink(missing_ok=True)
    return True


def _merge_portable_config(current: dict[str, Any], portable: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for section, values in portable.items():
        if not isinstance(values, dict):
            continue
        existing = merged.get(section)
        target = dict(existing) if isinstance(existing, dict) else {}
        target.update(values)
        merged[section] = target
    return merged


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _rewrite_restored_document_paths(db_path: Path, data_dir: Path) -> None:
    if not db_path.exists():
        return
    with closing(sqlite3.connect(db_path)) as db:
        rows = db.execute("SELECT doc_id FROM documents").fetchall()
        for (doc_id,) in rows:
            original = data_dir / "library" / str(doc_id) / "original.pdf"
            if original.exists():
                db.execute(
                    "UPDATE documents SET file_path = ? WHERE doc_id = ?",
                    (str(original), str(doc_id)),
                )
        db.commit()


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


__all__ = [
    "apply_pending_restore",
    "commit_applied_restore",
    "rollback_applied_restore",
]
