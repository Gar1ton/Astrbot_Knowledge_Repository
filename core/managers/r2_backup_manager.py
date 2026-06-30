"""R2 完整备份管理器：内容寻址快照、容量审计与跨设备恢复。

该管理器把插件持久化状态视为一个整体 inventory。blob 先上传，manifest 次之，
latest 指针最后提交；任何前置失败都不会破坏上一份可恢复快照。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from core.config import runtime_persistable_keys
from core.managers.r2_backup_manifest import (
    BackupEntry,
    check_sqlite_integrity,
    create_sqlite_snapshot_file,
    hash_inventory,
    parse_entries,
    safe_payload_path,
    sha256_file,
)
from core.managers.r2_restore import (
    apply_pending_restore,
    commit_applied_restore,
    rollback_applied_restore,
)

if TYPE_CHECKING:
    from core.config import Config, R2SyncConfig
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.sync_targets.base import SyncTarget

_PREFIX = "knowledge-arch/v1"
_LATEST_KEY = f"{_PREFIX}/latest.json"
_PENDING_RESTORE = ".r2_pending_restore.json"
_STAGING_DIR = ".r2_restore_staging"
_SCHEMA_VERSION = 1


@dataclass
class R2BackupJob:
    """供 WebUI 与聊天命令共用的运行态任务快照。"""

    job_id: str
    action: str
    status: str = "running"
    stage: str = "inventory"
    progress: int = 0
    detail: str = ""
    files_total: int = 0
    files_done: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    snapshot_id: str = ""
    error: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str = ""

    def finish(self, status: str, *, error: str = "") -> None:
        self.status = status
        self.error = error
        self.progress = 100 if status == "success" else self.progress
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class R2BackupManager:
    """以最新完整快照为单位管理 R2 备份。"""

    def __init__(
        self,
        *,
        target: SyncTarget,
        source_store: SourceDocumentStore,
        config: Config,
        r2_config: R2SyncConfig,
        data_dir: Path,
        db_path: Path,
        quiesce_indexes: Callable[[], Awaitable[None]] | None = None,
        reload_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._target = target
        self._source_store = source_store
        self._config = config
        self._r2_config = r2_config
        self._data_dir = data_dir
        self._db_path = db_path
        self._quiesce_indexes = quiesce_indexes
        self._reload_callback = reload_callback
        self._lock = asyncio.Lock()
        self._job: R2BackupJob | None = None
        self._task: asyncio.Task[dict[str, Any]] | None = None

    @property
    def active_job(self) -> dict[str, Any] | None:
        return self._job.to_dict() if self._job else None

    def start_backup(self, *, force: bool = False) -> dict[str, Any]:
        return self._start("force_push" if force else "push", self.backup(force=force))

    def start_restore(self, *, auto_restart: bool = False) -> dict[str, Any]:
        action = "force_pull" if auto_restart else "pull"
        return self._start(action, self.prepare_restore(auto_restart=auto_restart))

    def _start(self, action: str, coro: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[attr-defined]
            return {
                "status": "busy",
                "message": "已有 R2 备份/恢复任务正在运行",
                "job": self.active_job,
            }
        self._job = R2BackupJob(job_id=uuid.uuid4().hex, action=action)
        self._task = asyncio.create_task(self._run_job(coro))
        return {"status": "started", "job": self.active_job}

    async def _run_job(self, coro: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        assert self._job is not None
        try:
            result = await coro
            if result.get("status") == "success":
                self._job.finish("success")
                if self._job.action == "force_pull" and self._reload_callback is not None:
                    asyncio.create_task(self._delayed_reload())
            else:
                self._job.finish("error", error=str(result.get("message") or "R2 task failed"))
            return result
        except asyncio.CancelledError:
            self._job.finish("cancelled", error="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - 后台任务需落可观测终态
            self._job.finish("error", error=str(exc))
            return {"status": "error", "message": str(exc), "job": self.active_job}

    async def _delayed_reload(self) -> None:
        await asyncio.sleep(0.25)
        if self._reload_callback is not None:
            await self._reload_callback()

    async def wait_current(self) -> dict[str, Any] | None:
        if self._task is None:
            return None
        return await self._task

    async def backup(self, *, force: bool = False) -> dict[str, Any]:
        """创建并原子提交最新完整快照。"""
        async with self._lock:
            self._require_enabled()
            job = self._ensure_job("force_push" if force else "push")
            snapshot_id = _snapshot_id()
            job.snapshot_id = snapshot_id
            work = Path(tempfile.mkdtemp(prefix="r2-backup-", dir=self._data_dir))
            try:
                job.stage, job.progress = "inventory", 3
                if self._quiesce_indexes is not None:
                    await self._quiesce_indexes()
                inventory_root = work / "inventory"
                await self._build_inventory(inventory_root)
                entries = await asyncio.to_thread(hash_inventory, inventory_root)
                unique_entries = {entry.sha256: entry for entry in entries}
                job.files_total = len(unique_entries)
                job.bytes_total = sum(item.size for item in entries)
                missing_bytes = 0
                existing: set[str] = set()
                job.stage, job.progress = "quota", 8
                bucket_objects = await self._target.list_backup_objects("")
                bucket_used = sum(int(item.get("size") or 0) for item in bucket_objects)
                plugin_objects = {
                    str(item.get("key") or ""): int(item.get("size") or 0)
                    for item in bucket_objects
                    if str(item.get("key") or "").startswith(f"{_PREFIX}/")
                }
                for digest, entry in unique_entries.items():
                    key = _blob_key(digest)
                    if key in plugin_objects:
                        existing.add(digest)
                    else:
                        missing_bytes += entry.size
                if bucket_used + missing_bytes > self._r2_config.free_tier_bytes:
                    raise RuntimeError(
                        "R2 备份将超出配置的 10 GiB 安全上限："
                        f"当前 {bucket_used} B，净新增 {missing_bytes} B"
                    )

                job.stage, job.progress = "upload", 10
                for digest, entry in unique_entries.items():
                    if not force and digest in existing:
                        job.files_done += 1
                        job.bytes_done += entry.size
                        continue
                    await self._target.upload_backup_file(
                        _blob_key(digest),
                        inventory_root / Path(entry.path),
                        content_type=entry.content_type,
                        sha256=digest,
                    )
                    job.files_done += 1
                    job.bytes_done += entry.size
                    if job.files_total:
                        job.progress = 10 + int(70 * job.files_done / job.files_total)

                manifest = {
                    "schema_version": _SCHEMA_VERSION,
                    "snapshot_id": snapshot_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "app_version": "v0.29.0",
                    "logical_bytes": job.bytes_total,
                    "file_count": len(entries),
                    "files": [asdict(item) for item in entries],
                }
                manifest_key = f"{_PREFIX}/snapshots/{snapshot_id}/manifest.json"
                manifest_bytes = _json_bytes(manifest)
                job.stage, job.progress = "commit", 84
                await self._target.push_backup(
                    manifest_key, manifest_bytes, "application/json"
                )
                latest = {
                    "schema_version": _SCHEMA_VERSION,
                    "snapshot_id": snapshot_id,
                    "manifest_key": manifest_key,
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "updated_at": manifest["created_at"],
                }
                await self._target.push_backup(
                    _LATEST_KEY, _json_bytes(latest), "application/json"
                )

                job.stage, job.progress = "cleanup", 92
                await self._garbage_collect(manifest_key, set(unique_entries))
                job.stage, job.progress = "done", 100
                result = {
                    "status": "success",
                    "snapshot_id": snapshot_id,
                    "file_count": len(entries),
                    "logical_bytes": job.bytes_total,
                    "uploaded_bytes": sum(
                        entry.size
                        for digest, entry in unique_entries.items()
                        if force or digest not in existing
                    ),
                }
                job.finish("success")
                return result
            except Exception as exc:
                job.finish("error", error=str(exc))
                raise
            finally:
                shutil.rmtree(work, ignore_errors=True)

    async def prepare_restore(self, *, auto_restart: bool = False) -> dict[str, Any]:
        """下载、验证 latest 快照并登记待应用恢复。"""
        async with self._lock:
            self._require_enabled()
            job = self._ensure_job("force_pull" if auto_restart else "pull")
            try:
                latest, manifest = await self._load_latest_manifest()
            except Exception as exc:
                job.finish("error", error=str(exc))
                raise
            snapshot_id = str(latest["snapshot_id"])
            job.snapshot_id = snapshot_id
            try:
                files = parse_entries(manifest)
            except Exception as exc:
                job.finish("error", error=str(exc))
                raise
            job.files_total = len(files)
            job.bytes_total = sum(item.size for item in files)
            free = shutil.disk_usage(self._data_dir).free
            if free < job.bytes_total:
                exc = RuntimeError(
                    f"本地空间不足：需要至少 {job.bytes_total} B，可用 {free} B"
                )
                job.finish("error", error=str(exc))
                raise exc

            stage_root = self._data_dir / _STAGING_DIR / snapshot_id
            if stage_root.exists():
                shutil.rmtree(stage_root)
            payload_root = stage_root / "payload"
            payload_root.mkdir(parents=True, exist_ok=True)
            job.stage, job.progress = "download", 5
            try:
                for entry in files:
                    target_path = safe_payload_path(payload_root, entry.path)
                    await self._target.download_backup_file(
                        _blob_key(entry.sha256), target_path
                    )
                    actual = await asyncio.to_thread(sha256_file, target_path)
                    if actual != entry.sha256 or target_path.stat().st_size != entry.size:
                        raise ValueError(f"备份对象校验失败：{entry.path}")
                    job.files_done += 1
                    job.bytes_done += entry.size
                    job.progress = 5 + int(80 * job.files_done / max(job.files_total, 1))

                job.stage, job.progress = "verify", 88
                db_path = payload_root / "database" / "knowledge_repository.db"
                if not db_path.exists():
                    raise ValueError("备份缺少 knowledge_repository.db")
                await asyncio.to_thread(check_sqlite_integrity, db_path)
                marker = {
                    "snapshot_id": snapshot_id,
                    "stage_root": str(stage_root),
                    "auto_restart": auto_restart,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                _write_json_atomic(self._data_dir / _PENDING_RESTORE, marker)
                job.stage, job.progress = "restart", 95
                result = {
                    "status": "success",
                    "snapshot_id": snapshot_id,
                    "restart_required": True,
                    "auto_restart": auto_restart,
                    "message": "完整快照已下载并验证，等待重启应用。",
                }
                job.finish("success")
                return result
            except Exception as exc:
                shutil.rmtree(stage_root, ignore_errors=True)
                job.finish("error", error=str(exc))
                raise

    async def storage_status(self) -> dict[str, Any]:
        """返回 Bucket 总量、插件物理量与当前快照逻辑量。"""
        self._require_enabled()
        objects = await self._target.list_backup_objects("")
        bucket_used = sum(int(item.get("size") or 0) for item in objects)
        plugin = [
            item
            for item in objects
            if str(item.get("key") or "").startswith(f"{_PREFIX}/")
        ]
        plugin_used = sum(int(item.get("size") or 0) for item in plugin)
        snapshot: dict[str, Any] | None = None
        latest_present = any(
            str(item.get("key") or "") == _LATEST_KEY for item in plugin
        )
        if latest_present:
            latest, manifest = await self._load_latest_manifest()
            logical = int(manifest.get("logical_bytes") or 0)
            referenced = {entry.sha256 for entry in parse_entries(manifest)}
            referenced_keys = {_blob_key(digest) for digest in referenced}
            blob_physical = sum(
                int(item.get("size") or 0)
                for item in plugin
                if str(item.get("key") or "") in referenced_keys
            )
            snapshot = {
                "snapshot_id": latest.get("snapshot_id"),
                "updated_at": latest.get("updated_at"),
                "logical_bytes": logical,
                "file_count": int(manifest.get("file_count") or 0),
                "deduplicated_bytes": max(logical - blob_physical, 0),
            }
        return {
            "status": "ok",
            "bucket_used_bytes": bucket_used,
            "plugin_used_bytes": plugin_used,
            "bucket_limit_bytes": self._r2_config.free_tier_bytes,
            "plugin_object_count": len(plugin),
            "snapshot": snapshot,
            "job": self.active_job,
        }

    async def _build_inventory(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            create_sqlite_snapshot_file,
            self._db_path,
            root / "database" / "knowledge_repository.db",
        )

        library_target = root / "library"
        library_source = self._data_dir / "library"
        if library_source.exists():
            await asyncio.to_thread(shutil.copytree, library_source, library_target)
        else:
            library_target.mkdir(parents=True, exist_ok=True)
        for doc in await self._source_store.list_documents():
            original = Path(doc.file_path)
            portable = library_target / doc.doc_id / "original.pdf"
            if not portable.exists() and original.is_file():
                portable.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copy2, original, portable)

        vector_cfg = self._config.get_vector_db_config()
        await asyncio.to_thread(
            _copy_optional,
            self._data_dir / vector_cfg.db_filename,
            root / "indexes" / "vector_store.db",
        )
        await asyncio.to_thread(
            _copy_optional,
            self._data_dir / "embedding_cache.db",
            root / "indexes" / "embedding_cache.db",
        )
        await asyncio.to_thread(
            _copy_optional,
            self._data_dir / "index_compatibility.json",
            root / "indexes" / "index_compatibility.json",
        )

        graph_root = Path(self._config.get_graph_config().working_dir)
        if not graph_root.is_absolute():
            graph_root = self._data_dir / graph_root
        if graph_root.exists():
            await asyncio.to_thread(shutil.copytree, graph_root, root / "lightrag")

        portable = _portable_config(self._config)
        (root / "config").mkdir(parents=True, exist_ok=True)
        # 不原样复制 runtime_config.json：旧版或手工文件可能含白名单外字段；两份配置均净化。
        _write_json_atomic(root / "config" / "runtime_config.json", portable)
        _write_json_atomic(root / "config" / "portable_config.json", portable)

    async def _load_latest_manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            latest_bytes = await self._target.pull_backup(_LATEST_KEY)
        except Exception as exc:
            raise FileNotFoundError("R2 中没有可恢复的 v1 快照") from exc
        latest = json.loads(latest_bytes.decode("utf-8"))
        if not isinstance(latest, dict):
            raise ValueError("latest.json 内容非法")
        manifest_key = str(latest.get("manifest_key") or "")
        if not manifest_key.startswith(f"{_PREFIX}/snapshots/"):
            raise ValueError("latest.json manifest_key 非法")
        manifest_bytes = await self._target.pull_backup(manifest_key)
        expected = str(latest.get("manifest_sha256") or "")
        if hashlib.sha256(manifest_bytes).hexdigest() != expected:
            raise ValueError("manifest 哈希校验失败")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest 内容非法")
        if int(manifest.get("schema_version") or 0) != _SCHEMA_VERSION:
            raise ValueError("不支持的 R2 manifest schema")
        if str(manifest.get("snapshot_id") or "") != str(latest.get("snapshot_id") or ""):
            raise ValueError("latest 与 manifest snapshot_id 不一致")
        entries = parse_entries(manifest)
        if int(manifest.get("file_count") or 0) != len(entries):
            raise ValueError("manifest file_count 不一致")
        if int(manifest.get("logical_bytes") or 0) != sum(entry.size for entry in entries):
            raise ValueError("manifest logical_bytes 不一致")
        return latest, manifest

    async def _garbage_collect(self, manifest_key: str, digests: set[str]) -> None:
        objects = await self._target.list_backup_objects(f"{_PREFIX}/")
        keep = {_LATEST_KEY, manifest_key, *(_blob_key(item) for item in digests)}
        stale = [
            str(item.get("key") or "")
            for item in objects
            if str(item.get("key") or "") not in keep
        ]
        await self._target.delete_backup_objects(stale)

    def _require_enabled(self) -> None:
        if not self._r2_config.enabled:
            raise RuntimeError("R2 sync is disabled in configuration")

    def _ensure_job(self, action: str) -> R2BackupJob:
        if self._job is None or self._job.status != "running":
            self._job = R2BackupJob(job_id=uuid.uuid4().hex, action=action)
        return self._job


def _portable_config(config: Config) -> dict[str, Any]:
    public = config.to_public_dict()
    allowed = runtime_persistable_keys()
    result: dict[str, Any] = {}
    excluded = {
        ("zotero_sync", "zotero_data_dir"),
        ("zotero_sync", "api_port"),
        ("zotero_sync", "linked_root"),
    }
    for section, keys in allowed.items():
        values = public.get(section)
        if not isinstance(values, dict):
            continue
        selected = {
            key: values[key]
            for key in keys
            if key in values
            and (section, key) not in excluded
            and section != "r2_sync"
        }
        if selected:
            result[section] = selected
    return result


def _snapshot_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _blob_key(digest: str) -> str:
    return f"{_PREFIX}/blobs/{digest}"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_json_bytes(value))
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _copy_optional(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


__all__ = [
    "R2BackupJob",
    "R2BackupManager",
    "apply_pending_restore",
    "commit_applied_restore",
    "rollback_applied_restore",
]
