"""R2 v1 完整快照：去重、原子提交、容量与跨环境恢复。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from core.config import Config
from core.domain.models import SourceDocument, SyncTargetKind
from core.managers.r2_backup_manager import (
    R2BackupManager,
    apply_pending_restore,
    commit_applied_restore,
    rollback_applied_restore,
)
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.sync_targets.memory import InMemorySyncTarget


def _db(path: Path, marker: str = "original") -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, file_path TEXT NOT NULL)")
        db.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        db.execute("INSERT INTO marker VALUES (?)", (marker,))
        db.commit()


async def _manager(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "knowledge_repository.db"
    _db(db_path)
    bundle = data_dir / "library" / "d1"
    bundle.mkdir(parents=True)
    (bundle / "original.pdf").write_bytes(b"same-content")
    (bundle / "clean.md").write_bytes(b"same-content")
    (bundle / "pages.json").write_text("[]", encoding="utf-8")
    (bundle / "meta.json").write_text("{}", encoding="utf-8")
    (data_dir / "vector_store.db").write_bytes(b"milvus-state")
    (data_dir / "embedding_cache.db").write_bytes(b"cache-state")
    (data_dir / "index_compatibility.json").write_text("{}", encoding="utf-8")
    lightrag = data_dir / "lightrag_workspaces" / "papers"
    lightrag.mkdir(parents=True)
    (lightrag / "graph.json").write_text('{"ok":true}', encoding="utf-8")

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument(
            doc_id="d1",
            title="D1",
            file_path=str(bundle / "original.pdf"),
            content_type="application/pdf",
            size_bytes=12,
            content_hash="hash",
            collection="papers",
        )
    )
    config = Config(
        {
            "r2_sync": {
                "enabled": True,
                "account_id": "account",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "bucket": "bucket",
            },
            "vector_db": {"backend": "milvus", "db_filename": "vector_store.db"},
            "graph": {"working_dir": "lightrag_workspaces"},
        }
    )
    target = InMemorySyncTarget(SyncTargetKind.R2, limit_bytes=10 * 1024**3)
    manager = R2BackupManager(
        target=target,
        source_store=store,
        config=config,
        r2_config=config.get_r2_sync_config(),
        data_dir=data_dir,
        db_path=db_path,
    )
    return manager, target, config, data_dir


def _replace_manifest(target: InMemorySyncTarget, manifest: dict) -> None:
    latest_key = "knowledge-arch/v1/latest.json"
    latest = json.loads(target._objects[latest_key])
    manifest["file_count"] = len(manifest["files"])
    manifest["logical_bytes"] = sum(int(entry["size"]) for entry in manifest["files"])
    payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    target._objects[latest["manifest_key"]] = payload
    latest["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    target._objects[latest_key] = json.dumps(
        latest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


async def test_backup_deduplicates_and_keeps_only_latest(tmp_path: Path) -> None:
    manager, target, _, _ = await _manager(tmp_path)
    first = await manager.backup()
    assert first["status"] == "success"
    latest = json.loads(target._objects["knowledge-arch/v1/latest.json"])
    manifest = json.loads(target._objects[latest["manifest_key"]])
    assert manifest["file_count"] >= 8
    # original.pdf 与 clean.md 内容相同，只存一个 blob。
    blob_keys = [key for key in target._objects if "/blobs/" in key]
    assert len(blob_keys) < manifest["file_count"]
    runtime_entry = next(
        entry for entry in manifest["files"] if entry["path"] == "config/runtime_config.json"
    )
    sanitized_runtime = target._objects[
        f"knowledge-arch/v1/blobs/{runtime_entry['sha256']}"
    ].decode("utf-8")
    assert '"secret"' not in sanitized_runtime
    assert "secret_access_key" not in sanitized_runtime
    assert "r2_sync" not in sanitized_runtime

    second = await manager.backup()
    assert second["uploaded_bytes"] == 0
    manifests = [key for key in target._objects if "/snapshots/" in key]
    assert manifests == [
        f"knowledge-arch/v1/snapshots/{second['snapshot_id']}/manifest.json"
    ]

    forced = await manager.backup(force=True)
    assert forced["uploaded_bytes"] > 0
    status = await manager.storage_status()
    assert status["bucket_used_bytes"] == status["plugin_used_bytes"]
    assert status["snapshot"]["snapshot_id"] == forced["snapshot_id"]


async def test_restore_stages_validates_and_replaces_all_components(tmp_path: Path) -> None:
    manager, _, config, data_dir = await _manager(tmp_path)
    backup = await manager.backup()
    assert backup["status"] == "success"

    (data_dir / "library" / "d1" / "original.pdf").write_bytes(b"corrupted-local")
    (data_dir / "vector_store.db").write_bytes(b"changed")
    with closing(sqlite3.connect(data_dir / "knowledge_repository.db")) as db:
        db.execute("UPDATE marker SET value = 'changed'")
        db.commit()

    prepared = await manager.prepare_restore(auto_restart=False)
    assert prepared["restart_required"] is True
    assert apply_pending_restore(data_dir, config) is True
    assert (data_dir / "library" / "d1" / "original.pdf").read_bytes() == b"same-content"
    assert (data_dir / "vector_store.db").read_bytes() == b"milvus-state"
    with closing(sqlite3.connect(data_dir / "knowledge_repository.db")) as db:
        assert db.execute("SELECT value FROM marker").fetchone() == ("original",)
    commit_applied_restore(data_dir)


async def test_failed_latest_commit_preserves_previous_snapshot(tmp_path: Path) -> None:
    manager, target, _, data_dir = await _manager(tmp_path)
    first = await manager.backup()
    previous = target._objects["knowledge-arch/v1/latest.json"]
    (data_dir / "library" / "d1" / "clean.md").write_text("changed", encoding="utf-8")

    original_push = target.push_backup

    async def fail_latest(key: str, payload: bytes, content_type: str) -> str:
        if key == "knowledge-arch/v1/latest.json":
            raise RuntimeError("commit failed")
        return await original_push(key, payload, content_type)

    target.push_backup = fail_latest  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="commit failed"):
        await manager.backup()
    assert target._objects["knowledge-arch/v1/latest.json"] == previous
    assert first["snapshot_id"] in previous.decode("utf-8")


async def test_restore_rejects_corrupted_blob_and_records_error(tmp_path: Path) -> None:
    manager, target, _, _ = await _manager(tmp_path)
    await manager.backup()
    latest = json.loads(target._objects["knowledge-arch/v1/latest.json"])
    manifest = json.loads(target._objects[latest["manifest_key"]])
    entry = manifest["files"][0]
    target._objects[f"knowledge-arch/v1/blobs/{entry['sha256']}"] = b"corrupted"

    with pytest.raises(ValueError, match="校验失败"):
        await manager.prepare_restore()
    assert manager.active_job is not None
    assert manager.active_job["status"] == "error"


async def test_restore_rejects_tampered_manifest_and_path_traversal(tmp_path: Path) -> None:
    manager, target, _, _ = await _manager(tmp_path)
    await manager.backup()
    latest_key = "knowledge-arch/v1/latest.json"
    latest = json.loads(target._objects[latest_key])
    manifest_key = latest["manifest_key"]
    target._objects[manifest_key] += b" "
    with pytest.raises(ValueError, match="manifest 哈希"):
        await manager.prepare_restore()

    manifest = json.loads(target._objects[manifest_key])
    manifest["files"][0]["path"] = "../escape.db"
    _replace_manifest(target, manifest)
    with pytest.raises(ValueError, match="非法备份路径"):
        await manager.prepare_restore()
    assert not (tmp_path / "escape.db").exists()


async def test_restore_rejects_invalid_sqlite_after_hash_verification(tmp_path: Path) -> None:
    manager, target, _, _ = await _manager(tmp_path)
    await manager.backup()
    latest = json.loads(target._objects["knowledge-arch/v1/latest.json"])
    manifest = json.loads(target._objects[latest["manifest_key"]])
    database = next(
        entry
        for entry in manifest["files"]
        if entry["path"] == "database/knowledge_repository.db"
    )
    invalid = b"not-a-sqlite-database"
    digest = hashlib.sha256(invalid).hexdigest()
    database["sha256"] = digest
    database["size"] = len(invalid)
    target._objects[f"knowledge-arch/v1/blobs/{digest}"] = invalid
    _replace_manifest(target, manifest)

    with pytest.raises(sqlite3.DatabaseError):
        await manager.prepare_restore()


async def test_restore_blocks_when_local_disk_is_insufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _, _, _ = await _manager(tmp_path)
    await manager.backup()

    class Usage:
        free = 0

    monkeypatch.setattr("core.managers.r2_backup_manager.shutil.disk_usage", lambda _: Usage())
    with pytest.raises(RuntimeError, match="本地空间不足"):
        await manager.prepare_restore()


async def test_applied_restore_can_roll_back_to_previous_environment(tmp_path: Path) -> None:
    manager, _, config, data_dir = await _manager(tmp_path)
    await manager.backup()
    local_file = data_dir / "library" / "d1" / "original.pdf"
    local_file.write_bytes(b"new-local-state")
    await manager.prepare_restore()
    assert apply_pending_restore(data_dir, config) is True
    assert local_file.read_bytes() == b"same-content"

    assert rollback_applied_restore(data_dir) is True
    assert local_file.read_bytes() == b"new-local-state"
