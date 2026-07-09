"""R2 v1 manifest 条目、内容哈希、路径安全与 SQLite 快照工具。"""

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass
class BackupEntry:
    """完整快照 manifest 中的一项逻辑文件。"""

    path: str
    component: str
    sha256: str
    size: int
    content_type: str = "application/octet-stream"


def hash_inventory(root: Path) -> list[BackupEntry]:
    entries: list[BackupEntry] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        component = rel.split("/", 1)[0]
        entries.append(
            BackupEntry(
                path=rel,
                component=component,
                sha256=sha256_file(path),
                size=path.stat().st_size,
                content_type=mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
            )
        )
    return entries


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_entries(manifest: dict[str, Any]) -> list[BackupEntry]:
    raw = manifest.get("files")
    if not isinstance(raw, list):
        raise ValueError("manifest files 字段非法")
    entries: list[BackupEntry] = []
    paths: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("manifest file entry 非对象")
        entry = BackupEntry(
            path=str(item.get("path") or ""),
            component=str(item.get("component") or ""),
            sha256=str(item.get("sha256") or ""),
            size=int(item.get("size") or 0),
            content_type=str(item.get("content_type") or "application/octet-stream"),
        )
        if (
            len(entry.sha256) != 64
            or any(char not in "0123456789abcdef" for char in entry.sha256)
            or entry.size < 0
        ):
            raise ValueError(f"manifest entry 非法：{entry.path}")
        validate_relative_path(entry.path)
        if entry.path in paths:
            raise ValueError(f"manifest path 重复：{entry.path}")
        paths.add(entry.path)
        entries.append(entry)
    return entries


def validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"非法备份路径：{value!r}")


def safe_payload_path(root: Path, value: str) -> Path:
    validate_relative_path(value)
    target = (root / Path(*PurePosixPath(value).parts)).resolve()
    target.relative_to(root.resolve())
    return target


def create_sqlite_snapshot_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    check_sqlite_integrity(target)


def check_sqlite_integrity(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("PRAGMA integrity_check").fetchone()
    if row != ("ok",):
        raise ValueError(f"invalid SQLite snapshot: {row}")


__all__ = [
    "BackupEntry",
    "check_sqlite_integrity",
    "create_sqlite_snapshot_file",
    "hash_inventory",
    "parse_entries",
    "safe_payload_path",
    "sha256_file",
]
