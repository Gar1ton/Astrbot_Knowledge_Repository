"""SyncTarget 的内存实现（无网络，供接口对换测试）。

模拟一个有存储上限的对象存储：按 remote_ref 存字节、统计用量、支持配置上限以触发配额逻辑。
base_used_bytes 用于模拟「已有用量」而不真分配字节（如演示配额仪表盘接近上限的场景）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.domain.models import QuotaUsage, SyncTargetKind
from core.repository.sync_targets.base import SyncTarget

if TYPE_CHECKING:
    from core.domain.models import SourceDocument


class InMemorySyncTarget(SyncTarget):
    """纯内存同步目标。limit_bytes<=0 表示无存储上限（模拟 Notion 这类不以字节计的目标）。"""

    def __init__(
        self,
        kind: SyncTargetKind = SyncTargetKind.R2,
        limit_bytes: int = 0,
        base_used_bytes: int = 0,
    ) -> None:
        self._kind = kind
        self._limit_bytes = limit_bytes
        self._base_used_bytes = base_used_bytes
        self._objects: dict[str, bytes] = {}
        self._metadata: dict[str, dict[str, str]] = {}

    @property
    def kind(self) -> SyncTargetKind:
        return self._kind

    async def push(self, document: SourceDocument, payload: bytes) -> str:
        ref = f"{document.collection}/{document.doc_id}"
        self._objects[ref] = payload   # 覆盖即幂等
        return ref

    async def delete(self, remote_ref: str) -> bool:
        return self._objects.pop(remote_ref, None) is not None

    async def push_backup(self, key: str, payload: bytes, content_type: str) -> str:
        self._objects[key] = payload
        return key

    async def pull_backup(self, key: str) -> bytes:
        return self._objects[key]

    async def upload_backup_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str = "application/octet-stream",
        sha256: str = "",
    ) -> str:
        self._objects[key] = path.read_bytes()
        self._metadata[key] = {"sha256": sha256} if sha256 else {}
        return key

    async def download_backup_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._objects[key])

    async def list_backup_objects(self, prefix: str = "") -> list[dict[str, object]]:
        return [
            {"key": key, "size": len(value), "last_modified": ""}
            for key, value in sorted(self._objects.items())
            if key.startswith(prefix)
        ]

    async def stat_backup_object(self, key: str) -> dict[str, object] | None:
        value = self._objects.get(key)
        if value is None:
            return None
        return {
            "key": key,
            "size": len(value),
            "metadata": dict(self._metadata.get(key, {})),
        }

    async def delete_backup_objects(self, keys: list[str]) -> None:
        for key in keys:
            self._objects.pop(key, None)
            self._metadata.pop(key, None)

    async def check_quota(self, pending_bytes: int = 0) -> QuotaUsage:
        used = self._base_used_bytes + sum(len(b) for b in self._objects.values())
        return QuotaUsage(
            target=self._kind,
            used_bytes=used,
            limit_bytes=self._limit_bytes,
            pending_bytes=pending_bytes,
        )


__all__ = ["InMemorySyncTarget"]
