"""Read-only Zotero Web API v3 client and personal-library snapshot reader."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.adapters.zotero.sqlite_reader import ZoteroSnapshot
from core.domain.models import (
    DocumentOrigin,
    ZoteroAttachment,
    ZoteroCollection,
    ZoteroItem,
    ZoteroLibrary,
    ZoteroRelation,
    ZoteroTag,
)

logger = logging.getLogger("astrbot_plugin_knowledge_repository")

API_BASE_URL = "https://api.zotero.org"
API_VERSION = "3"
DEFAULT_TIMEOUT = 15.0
_NON_REGULAR_TYPES = {"attachment", "note", "annotation"}
_VENUE_FIELDS = ("publicationTitle", "proceedingsTitle", "bookTitle", "conferenceName")


class ZoteroWebApiError(RuntimeError):
    """Zotero Web API request failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ZoteroWebApiClient:
    """Minimal GET-only Zotero Web API client."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def get_current_key(self) -> dict[str, Any]:
        payload, _ = self._request_json("keys/current")
        if not isinstance(payload, dict):
            raise ZoteroWebApiError("Expected key metadata JSON")
        return payload

    def list_user_collections(self, user_id: str) -> list[dict[str, Any]]:
        return self._paginate_json(f"users/{user_id}/collections", {"format": "json"})

    def list_user_items(self, user_id: str) -> list[dict[str, Any]]:
        return self._paginate_json(
            f"users/{user_id}/items",
            {"format": "json", "include": "data", "limit": 100},
        )

    def download_user_file(self, user_id: str, item_key: str, target_path: Path) -> Path:
        raw, _ = self._request_bytes(f"users/{user_id}/items/{item_key}/file")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(raw)
        return target_path

    def _paginate_json(self, path: str, params: dict[str, str | int]) -> list[dict[str, Any]]:
        url_or_path: str = path
        current_params: dict[str, str | int] | None = params
        result: list[dict[str, Any]] = []
        while True:
            payload, headers = self._request_json(url_or_path, current_params)
            if not isinstance(payload, list):
                raise ZoteroWebApiError("Expected Zotero list JSON")
            result.extend(item for item in payload if isinstance(item, dict))
            next_url = _next_link(headers.get("Link", ""))
            if not next_url:
                return result
            url_or_path = next_url
            current_params = None

    def _request_json(
        self,
        path_or_url: str,
        params: dict[str, str | int] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        raw, headers = self._request_bytes(path_or_url, params)
        try:
            return json.loads(raw.decode("utf-8")), headers
        except json.JSONDecodeError as exc:
            raise ZoteroWebApiError(f"Invalid Zotero JSON: {exc}") from exc

    def _request_bytes(
        self,
        path_or_url: str,
        params: dict[str, str | int] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        url = self._build_url(path_or_url, params)
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "Zotero-API-Version": API_VERSION,
                "Zotero-API-Key": self.api_key,
            },
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                return resp.read(), _headers_to_dict(getattr(resp, "headers", {}))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise ZoteroWebApiError(
                detail or f"Zotero Web API HTTP {exc.code}",
                status=exc.code,
            ) from exc
        except Exception as exc:
            raise ZoteroWebApiError(str(exc)) from exc

    def _build_url(self, path_or_url: str, params: dict[str, str | int] | None = None) -> str:
        if path_or_url.startswith(("http://", "https://")):
            base = path_or_url
        else:
            base = f"{self.base_url}/{path_or_url.lstrip('/')}"
        if not params:
            return base
        return f"{base}?{urllib.parse.urlencode(params)}"


class ZoteroWebApiReader:
    """Builds a ZoteroSnapshot from one personal Zotero Web API library."""

    def __init__(
        self,
        client: ZoteroWebApiClient,
        *,
        user_id: str,
        username: str = "",
        download_dir: Path | None = None,
    ) -> None:
        self._client = client
        self._user_id = str(user_id)
        self._username = username or "Zotero Web"
        self._download_dir = download_dir

    def read_snapshot(self) -> ZoteroSnapshot:
        library = ZoteroLibrary(
            library_id=self._user_id,
            library_type="user",
            name=self._username,
        )
        snapshot = ZoteroSnapshot(library=library)
        collections_payload = self._client.list_user_collections(self._user_id)
        items_payload = self._client.list_user_items(self._user_id)

        snapshot.collections = self._collections(collections_payload)
        snapshot.items = self._items(items_payload)
        snapshot.attachments = self._attachments(items_payload)
        snapshot.collection_items = self._collection_items(items_payload)
        snapshot.item_tags = self._item_tags(items_payload)
        snapshot.relations = self._relations(items_payload)
        return snapshot

    def _collections(self, payload: list[dict[str, Any]]) -> list[ZoteroCollection]:
        result = []
        for entry in payload:
            data = _data(entry)
            key = str(data.get("key") or entry.get("key") or "")
            if not key:
                continue
            result.append(
                ZoteroCollection(
                    collection_key=key,
                    library_id=self._user_id,
                    name=str(data.get("name") or key),
                    parent_collection_key=str(data.get("parentCollection") or ""),
                    origin=DocumentOrigin.ZOTERO,
                )
            )
        return result

    def _items(self, payload: list[dict[str, Any]]) -> list[ZoteroItem]:
        result = []
        for entry in payload:
            data = _data(entry)
            if str(data.get("itemType") or "") in _NON_REGULAR_TYPES:
                continue
            key = str(data.get("key") or entry.get("key") or "")
            if not key or bool(data.get("deleted")):
                continue
            venue = next((str(data.get(k) or "") for k in _VENUE_FIELDS if data.get(k)), "")
            result.append(
                ZoteroItem(
                    item_key=key,
                    library_id=self._user_id,
                    item_type=str(data.get("itemType") or ""),
                    version=int(entry.get("version") or data.get("version") or 0),
                    deleted=False,
                    title=str(data.get("title") or ""),
                    creators=_creators(data.get("creators")),
                    year=_extract_year(str(data.get("date") or "")),
                    venue=venue,
                    doi=str(data.get("DOI") or ""),
                    url=str(data.get("url") or ""),
                    abstract=str(data.get("abstractNote") or ""),
                    origin=DocumentOrigin.ZOTERO,
                    date_added=_parse_dt(data.get("dateAdded")),
                    date_modified=_parse_dt(data.get("dateModified")),
                    raw_zotero_json=data,
                )
            )
        return result

    def _attachments(self, payload: list[dict[str, Any]]) -> list[ZoteroAttachment]:
        result = []
        for entry in payload:
            data = _data(entry)
            if str(data.get("itemType") or "") != "attachment":
                continue
            key = str(data.get("key") or entry.get("key") or "")
            if not key or bool(data.get("deleted")):
                continue
            filename = _attachment_filename(data, key)
            content_type = str(data.get("contentType") or "")
            # 不在此处下载：read_snapshot 只读元数据（快、可立即定出 docs_total），文件下载延迟
            # 到 pipeline 的 syncing_documents 阶段、只对新增/变更件触发（见 fetch_attachment_file）
            result.append(
                ZoteroAttachment(
                    attachment_key=key,
                    parent_item_key=str(data.get("parentItem") or ""),
                    library_id=self._user_id,
                    content_type=content_type,
                    filename=filename,
                    path=str(data.get("path") or ""),
                    resolved_path="",
                    link_mode=str(data.get("linkMode") or ""),
                    md5=str(data.get("md5") or ""),
                    raw_zotero_json=data,
                )
            )
        return result

    def fetch_attachment_file(self, attachment_key: str, filename: str) -> Path | None:
        """惰性下载单篇附件原件到 download_dir，返回本地路径（无 download_dir / 下载失败时 None）。

        为什么拆出来：原实现把整库 PDF 下载塞进 read_snapshot 的 reading 阶段，串行 + 每篇 15s
        超时，进度条会假死在 reading 底值（3%）直到全库下完，且每次同步都重下未变更件。改为按需
        单篇下载后，pipeline 只对新增/变更件调用本方法，进度随 docs_processed 平滑推进。"""
        if not self._download_dir:
            return None
        target = self._download_dir / attachment_key / _safe_filename(
            filename or f"{attachment_key}.pdf"
        )
        try:
            return Path(self._client.download_user_file(self._user_id, attachment_key, target))
        except ZoteroWebApiError as exc:
            logger.warning("Zotero web file download failed for %s: %s", attachment_key, exc)
            return None

    def _collection_items(self, payload: list[dict[str, Any]]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for entry in payload:
            data = _data(entry)
            if str(data.get("itemType") or "") in _NON_REGULAR_TYPES:
                continue
            item_key = str(data.get("key") or entry.get("key") or "")
            for coll_key in data.get("collections") or []:
                if item_key and coll_key:
                    pairs.append((str(coll_key), item_key))
        return pairs

    def _item_tags(self, payload: list[dict[str, Any]]) -> dict[str, list[ZoteroTag]]:
        out: dict[str, list[ZoteroTag]] = {}
        for entry in payload:
            data = _data(entry)
            if str(data.get("itemType") or "") in _NON_REGULAR_TYPES:
                continue
            item_key = str(data.get("key") or entry.get("key") or "")
            tags = data.get("tags") or []
            for raw in tags:
                if isinstance(raw, dict) and raw.get("tag"):
                    out.setdefault(item_key, []).append(
                        ZoteroTag(
                            item_key=item_key,
                            tag=str(raw.get("tag") or ""),
                            type=int(raw.get("type") or 0),
                            origin=DocumentOrigin.ZOTERO,
                        )
                    )
        return out

    def _relations(self, payload: list[dict[str, Any]]) -> list[ZoteroRelation]:
        result: list[ZoteroRelation] = []
        for entry in payload:
            data = _data(entry)
            item_key = str(data.get("key") or entry.get("key") or "")
            relations = data.get("relations") if isinstance(data.get("relations"), dict) else {}
            for relation_type, target in relations.items():
                result.append(
                    ZoteroRelation(
                        source_item_key=item_key,
                        relation_type=str(relation_type),
                        target_item_key=str(target).rstrip("/").rsplit("/", 1)[-1],
                    )
                )
        return result


def current_key_identity(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = payload.get("userID") or payload.get("userId") or payload.get("user_id")
    username = payload.get("username") or payload.get("userName") or ""
    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    user_access = access.get("user") if isinstance(access.get("user"), dict) else {}
    if not user_id:
        raise ZoteroWebApiError("Zotero API key did not return a personal userID")
    if user_access and user_access.get("library") is False:
        raise ZoteroWebApiError("Zotero API key lacks personal library read access")
    return {
        "user_id": str(user_id),
        "username": str(username or ""),
        "access": user_access if isinstance(user_access, dict) else {},
    }


def _data(entry: dict[str, Any]) -> dict[str, Any]:
    data = entry.get("data")
    return data if isinstance(data, dict) else {}


def _headers_to_dict(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        return {str(k): str(v) for k, v in headers.items()}
    return {}


def _next_link(link_header: str) -> str:
    match = re.search(r'<([^>]+)>;\s*rel="next"', link_header or "")
    return match.group(1) if match else ""


def _creators(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for creator in raw:
        if not isinstance(creator, dict):
            continue
        name = str(creator.get("name") or "").strip()
        if not name:
            first = str(creator.get("firstName") or "").strip()
            last = str(creator.get("lastName") or "").strip()
            name = last if not first else f"{last}, {first}".strip(", ")
        if name:
            out.append(name)
    return out


def _extract_year(value: str) -> str:
    match = re.search(r"\d{4}", value or "")
    return match.group(0) if match else ""


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _attachment_filename(data: dict[str, Any], key: str) -> str:
    filename = str(data.get("filename") or "")
    if filename:
        return filename
    path = str(data.get("path") or "")
    if path.startswith("storage:"):
        return path.split(":", 1)[1]
    if path:
        return Path(path).name
    title = str(data.get("title") or "")
    return title or f"{key}.pdf"


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(". ")
    return cleaned or "attachment.pdf"


def _is_pdf(content_type: str, filename: str) -> bool:
    return content_type.lower() == "application/pdf" or filename.lower().endswith(".pdf")


__all__ = [
    "API_BASE_URL",
    "API_VERSION",
    "ZoteroWebApiClient",
    "ZoteroWebApiError",
    "ZoteroWebApiReader",
    "current_key_identity",
]
