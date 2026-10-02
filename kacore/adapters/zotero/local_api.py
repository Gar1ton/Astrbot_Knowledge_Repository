"""Zotero 本地 API 的只读访问适配器。

本项目的 Zotero 批量镜像仍以只读 `zotero.sqlite` 为主路径；本模块只使用
`http://localhost:23119/api/` 暴露的 Web API v3 兼容 GET 端点，补足 PDF reader
需要的 annotation / file view URL 等实时能力。这里不实现任何写请求。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DEFAULT_PORT = 23119
DEFAULT_USER_ID = "0"
API_VERSION = "3"


class ZoteroLocalApiError(RuntimeError):
    """Local API 不可用或返回非预期响应。

    status 为 HTTP 状态码；连接失败、超时、JSON 解析失败等本地错误使用 None。
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def probe_connection(port: int = DEFAULT_PORT, timeout: float = 1.0) -> dict[str, object]:
    """探测本地 Zotero HTTP 服务是否可达。返回 `{connected, port, detail}`。

    连接失败/超时视为未连接；403 也代表 Zotero 已运行但 Local API 未启用。
    """
    url = f"http://localhost:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return {"connected": True, "port": port, "detail": f"HTTP {resp.status}"}
    except urllib.error.HTTPError as exc:
        # 有响应即说明 Zotero 本地服务正在监听。
        return {"connected": True, "port": port, "detail": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"connected": False, "port": port, "detail": str(exc)}


class ZoteroLocalApiClient:
    """只读 Zotero Local API client。

    约束：所有方法只发 GET；调用方负责决定是否缓存结果。Local API 未启用时会抛
    ZoteroLocalApiError(status=403)，上层 UI 通常应降级为空状态而不是报错。
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        *,
        user_id: str = DEFAULT_USER_ID,
        timeout: float = 3.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.port = port
        self.user_id = user_id
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def get_status_schema(self) -> dict[str, Any]:
        """读取 schema 探针端点，返回 API/schema 版本和 item type 数量。"""
        payload, headers, status = self._request_json("itemTypes")
        return {
            "connected": True,
            "status": status,
            "api_version": headers.get("Zotero-API-Version", ""),
            "schema_version": headers.get("Zotero-Schema-Version", ""),
            "item_types": len(payload) if isinstance(payload, list) else 0,
        }

    def list_items(
        self,
        *,
        item_type: str | None = None,
        include: str = "data",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """列出本地用户库条目；item_type 透传 Zotero `itemType` 查询参数。"""
        params: dict[str, str | int] = {"format": "json", "include": include}
        if item_type:
            params["itemType"] = item_type
        if limit is not None:
            params["limit"] = limit
        payload, _, _ = self._request_json(f"users/{self.user_id}/items", params)
        if not isinstance(payload, list):
            raise ZoteroLocalApiError("Expected Zotero item list JSON")
        return [item for item in payload if isinstance(item, dict)]

    def get_item(self, item_key: str, *, include: str = "data") -> dict[str, Any] | None:
        """读取单个 Zotero item；404 返回 None。"""
        path = f"users/{self.user_id}/items/{urllib.parse.quote(item_key)}"
        try:
            payload, _, _ = self._request_json(path, {"format": "json", "include": include})
        except ZoteroLocalApiError as exc:
            if exc.status == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def get_file_view_url(self, item_key: str) -> str | None:
        """返回 attachment 的本地 file URL 文本；不可用时返回 None。"""
        path = f"users/{self.user_id}/items/{urllib.parse.quote(item_key)}/file/view/url"
        try:
            text, _, _ = self._request_text(path)
        except ZoteroLocalApiError as exc:
            if exc.status == 404:
                return None
            raise
        text = text.strip()
        return text or None

    def _request_json(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> tuple[Any, dict[str, str], int]:
        text, headers, status = self._request_text(path, params)
        try:
            return json.loads(text), headers, status
        except json.JSONDecodeError as exc:
            raise ZoteroLocalApiError(f"Invalid Zotero JSON: {exc}") from exc

    def _request_text(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> tuple[str, dict[str, str], int]:
        url = self._build_url(path, params)
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={"Zotero-API-Version": API_VERSION},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                raw = resp.read()
                headers = _headers_to_dict(getattr(resp, "headers", {}))
                return raw.decode("utf-8"), headers, int(getattr(resp, "status", 200))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise ZoteroLocalApiError(
                detail or f"Zotero Local API HTTP {exc.code}", status=exc.code
            ) from exc
        except Exception as exc:
            raise ZoteroLocalApiError(str(exc)) from exc

    def _build_url(self, path: str, params: dict[str, str | int] | None = None) -> str:
        base = f"http://127.0.0.1:{self.port}/api/{path.lstrip('/')}"
        if not params:
            return base
        return f"{base}?{urllib.parse.urlencode(params)}"


def normalize_zotero_annotation(doc_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """把 Zotero annotation item JSON 归一化为前端稳定 shape。"""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    key = str(data.get("key") or item.get("key") or "")
    position = _parse_annotation_position(data.get("annotationPosition"))
    page_label = str(data.get("annotationPageLabel") or "")
    page = _annotation_page(page_label, position)
    out: dict[str, Any] = {
        "id": key,
        "doc_id": doc_id,
        "text": str(data.get("annotationText") or ""),
        "type": str(data.get("annotationType") or ""),
    }
    optional = {
        "comment": data.get("annotationComment"),
        "color": data.get("annotationColor"),
        "page": page,
        "page_label": page_label,
        "position": position,
        "created_at": data.get("dateAdded"),
        "updated_at": data.get("dateModified"),
    }
    for key_name, value in optional.items():
        if value not in (None, ""):
            out[key_name] = value
    return out


def _parse_annotation_position(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _annotation_page(page_label: str, position: dict[str, Any] | None) -> int | None:
    try:
        return int(page_label)
    except (TypeError, ValueError):
        pass
    if position is None:
        return None
    page_index = position.get("pageIndex")
    if isinstance(page_index, int):
        return page_index + 1
    return None


def _headers_to_dict(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        return {str(k): str(v) for k, v in headers.items()}
    return {}


__all__ = [
    "API_VERSION",
    "DEFAULT_PORT",
    "DEFAULT_USER_ID",
    "ZoteroLocalApiClient",
    "ZoteroLocalApiError",
    "normalize_zotero_annotation",
    "probe_connection",
]
