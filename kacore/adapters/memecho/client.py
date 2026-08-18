"""MemoryEcho REST 客户端（adapters 层，分支 Experiment-with-MemEcho-API 新增）。

把 Artific 托管记忆服务 MemoryEcho 的 REST 端点翻译为项目内部可消费的 dict/结构，
隔离 HTTP（aiohttp）、Bearer 鉴权、超时与降级/错误解析。纯翻译层，不夹带召回/写回决策。

设计要点：
- 可注入 ``transport``（默认 aiohttp）→ 单测无需真实网络。transport 契约：
  ``async (method, url, *, headers, json_body, params, timeout_seconds) -> (status, text)``。
- ``api_key`` 允许是字符串或 ``Callable[[], str]``，后者供延迟从 secret_store/env 取值。
- **本客户端对上层只抛 ``MemEchoError``**：超时/连接失败等传输层异常在 ``_call_transport()``
  统一翻译，不让 ``asyncio.TimeoutError`` / ``aiohttp.ClientError`` 逃逸——否则调用方按
  ``MemEchoError`` 写的单篇容错（``import_documents``）会被整批打断。
- 超时分两档：普通 REST 用 ``timeout_seconds``；SSE 长任务 ``import_file`` 用
  ``import_timeout_seconds``（服务端要读文件+切片+入库，秒级超时不够）。
"""
from __future__ import annotations

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("MemEchoClient")

DEFAULT_BASE_URL = "https://api.artific.social"
# 文件导入（SSE）的默认超时：服务端逐块解析+向量化，远慢于普通 REST，故与 timeout_seconds 分档。
DEFAULT_IMPORT_TIMEOUT_SECONDS = 300
_API_PREFIX = "/api/v1/memory"
_USAGE_PATH = "/api/v1/dashboard/services/memory/usage"

# transport 契约：返回 (http_status, response_text)。
Transport = Callable[..., Awaitable[tuple[int, str]]]


# ── 异常层级 ──────────────────────────────────────────────────────


class MemEchoError(Exception):
    """MemEcho 调用失败基类。携带 HTTP 状态码与服务端 error 文案。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MemEchoAuthError(MemEchoError):
    """401/403：API Key 无效/撤销/过期，或 scope 不足。"""


class MemEchoQuotaError(MemEchoError):
    """402：套餐配额用尽且按量计费不可用。"""


class MemEchoNotFoundError(MemEchoError):
    """404：vault 或资源不存在（含已删除）。"""


class MemEchoPayloadTooLargeError(MemEchoError):
    """413：请求体超限（文件导入上限 16 MiB）。"""


class MemEchoTimeoutError(MemEchoError):
    """请求超时：无 HTTP 状态码，``status`` 恒为 None。"""


class MemEchoTransportError(MemEchoError):
    """传输层失败（DNS/连接/TLS/注入 transport 自身抛错）：无 HTTP 状态码。"""


# ── 客户端 ────────────────────────────────────────────────────────


class MemEchoClient:
    """MemoryEcho REST 客户端。所有方法返回已解析的 JSON（dict/list）或抛 MemEchoError。"""

    def __init__(
        self,
        base_url: str,
        api_key: str | Callable[[], str],
        *,
        timeout_seconds: int = 30,
        import_timeout_seconds: int | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = max(1, int(timeout_seconds))
        # 未显式配置时取「普通超时」与默认导入超时的较大者：调大 timeout_seconds 的人
        # 显然是想让慢网络也能过，不该被导入档反过来卡回去。
        self._import_timeout_seconds = (
            max(1, int(import_timeout_seconds))
            if import_timeout_seconds
            else max(self._timeout_seconds, DEFAULT_IMPORT_TIMEOUT_SECONDS)
        )
        self._transport: Transport = transport or _aiohttp_transport

    def _resolve_key(self) -> str:
        key = self._api_key() if callable(self._api_key) else self._api_key
        return str(key or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._resolve_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _call_transport(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> tuple[int, str]:
        """调用 transport，并把一切非 HTTP 失败翻译成 MemEchoError。唯一的出网口。

        超时/连接失败原本会以 ``asyncio.TimeoutError`` / ``aiohttp.ClientError`` 原样抛出，
        逃过调用方的 ``except MemEchoError``——真机上一次 30s 导入超时就是这样打断整批并冒成
        HTTP 500（且 ``str(TimeoutError())`` 为空串，前端只剩 "Internal Server Error"）。
        """
        effective_timeout = timeout_seconds or self._timeout_seconds
        try:
            return await self._transport(
                method,
                url,
                headers=self._headers(),
                json_body=json_body,
                params=params,
                timeout_seconds=effective_timeout,
            )
        except MemEchoError:
            raise
        except TimeoutError as exc:
            # Python 3.11 起 asyncio.TimeoutError 即内置 TimeoutError；aiohttp 亦抛此类。
            raise MemEchoTimeoutError(
                f"请求超时（{effective_timeout}s）：{method} {url}"
            ) from exc
        except Exception as exc:
            raise MemEchoTransportError(
                f"请求失败（{type(exc).__name__}）：{exc or f'{method} {url}'}"
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        status, text = await self._call_transport(
            method, url, json_body=json_body, params=params
        )
        if status == 204:
            return None
        data = _loads_json(text)
        if status >= 400:
            raise _error_for(status, data, text)
        return data

    # ── 记忆库 Vaults ─────────────────────────────────────────────
    async def list_vaults(self) -> list[dict[str, Any]]:
        data = await self._request("GET", f"{_API_PREFIX}/vaults")
        return data if isinstance(data, list) else []

    async def get_vault(self, vault_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{_API_PREFIX}/vaults/{vault_id}") or {}

    async def create_vault(
        self, name: str, description: str = "", vault_type: str = "normal"
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if description:
            body["description"] = description
        if vault_type:
            body["vault_type"] = vault_type
        return await self._request("POST", f"{_API_PREFIX}/vaults", json_body=body) or {}

    async def update_vault(
        self, vault_id: str, name: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        """更新记忆库名称/描述；两字段均可选，只更新提供的字段。"""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        return await self._request(
            "PATCH", f"{_API_PREFIX}/vaults/{vault_id}", json_body=body
        ) or {}

    async def delete_vault(self, vault_id: str) -> None:
        """软删除记忆库（移入回收站）；成功返回 204。"""
        await self._request("DELETE", f"{_API_PREFIX}/vaults/{vault_id}")

    async def list_vault_trash(self) -> list[dict[str, Any]]:
        """列出回收站中的记忆库（按删除时间倒序）。"""
        data = await self._request("GET", f"{_API_PREFIX}/vaults/trash")
        return data if isinstance(data, list) else []

    async def restore_vault(self, trash_id: str) -> dict[str, Any]:
        """从回收站恢复记忆库；``trash_id`` 为回收站条目 ID（非原记忆库 ID）。"""
        return await self._request(
            "POST", f"{_API_PREFIX}/vaults/trash/{trash_id}/restore"
        ) or {}

    async def purge_vault(self, trash_id: str) -> None:
        """彻底删除回收站中的记忆库（不可恢复）；成功返回 204。"""
        await self._request("DELETE", f"{_API_PREFIX}/vaults/trash/{trash_id}")

    async def get_usage(self) -> dict[str, Any]:
        return await self._request("GET", _USAGE_PATH) or {}

    # ── 记忆消息 ──────────────────────────────────────────────────
    async def list_messages(
        self, vault_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"{_API_PREFIX}/vaults/{vault_id}/messages",
            params={"limit": limit, "offset": offset},
        )
        return data if isinstance(data, list) else []

    # ── 召回 ──────────────────────────────────────────────────────
    async def query_readonly(self, vault_id: str, message: str) -> dict[str, Any]:
        body = {"library_id": vault_id, "message": message}
        return await self._request(
            "POST", f"{_API_PREFIX}/query-readonly", json_body=body
        ) or {}

    async def query(self, vault_id: str, message: str) -> dict[str, Any]:
        body = {"library_id": vault_id, "message": message}
        return await self._request("POST", f"{_API_PREFIX}/query", json_body=body) or {}

    # ── 写回 ──────────────────────────────────────────────────────
    async def append_user_message(self, vault_id: str, message: str) -> dict[str, Any]:
        body = {"library_id": vault_id, "message": message}
        return await self._request(
            "POST", f"{_API_PREFIX}/append-user-message", json_body=body
        ) or {}

    async def append_assistant_message(
        self, vault_id: str, message: str
    ) -> dict[str, Any]:
        body = {"library_id": vault_id, "message": message}
        return await self._request(
            "POST", f"{_API_PREFIX}/append-assistant-message", json_body=body
        ) or {}

    # ── 文件导入（SSE）────────────────────────────────────────────
    async def import_file(
        self, vault_id: str, file_name: str, data_url: str, *, preset: str = "default"
    ) -> list[dict[str, Any]]:
        """导入单个文件；返回解析出的 SSE 进度事件列表（transport 收全文后解析）。"""
        body = {
            "library_id": vault_id,
            "file_name": file_name,
            "data_url": data_url,
            "preset": preset,
        }
        url = f"{self._base_url}{_API_PREFIX}/vaults/{vault_id}/import_file"
        status, text = await self._call_transport(
            "POST", url, json_body=body, timeout_seconds=self._import_timeout_seconds
        )
        if status >= 400:
            raise _error_for(status, _loads_json(text), text)
        return _parse_sse_events(text)

    async def list_files(self, vault_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"{_API_PREFIX}/files", params={"library_id": vault_id}
        )
        return data if isinstance(data, list) else []

    async def get_file_content(self, vault_id: str, attachment_id: str) -> str:
        """获取已导入文件的原始内容。Content-Type 与原文件一致，故按文本原样返回。"""
        url = f"{self._base_url}{_API_PREFIX}/files/content"
        status, text = await self._call_transport(
            "GET", url, params={"library_id": vault_id, "attachment_id": attachment_id}
        )
        if status >= 400:
            raise _error_for(status, _loads_json(text), text)
        return text

    # ── 连通探针 ──────────────────────────────────────────────────
    async def probe(self) -> dict[str, Any]:
        """轻量连通性探针：返回 {ok, vault_count, usage?, error?, status?}。不抛异常。"""
        try:
            vaults = await self.list_vaults()
        except MemEchoError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status}
        out: dict[str, Any] = {"ok": True, "vault_count": len(vaults)}
        try:
            out["usage"] = await self.get_usage()
        except MemEchoError as exc:  # usage 失败不影响连通判定
            logger.debug("memecho usage probe failed: %s", exc)
        return out


# ── 模块级 helper ─────────────────────────────────────────────────


async def _aiohttp_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    params: dict[str, Any] | None,
    timeout_seconds: int,
) -> tuple[int, str]:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as resp:
            return resp.status, await resp.text()


def _loads_json(text: str) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"error": text}


def _error_for(status: int, data: Any, text: str = "") -> MemEchoError:
    msg = ""
    if isinstance(data, dict):
        msg = str(data.get("error") or data.get("message") or "")
    msg = msg or text or f"HTTP {status}"
    if status in (401, 403):
        return MemEchoAuthError(msg, status=status)
    if status == 402:
        return MemEchoQuotaError(msg, status=status)
    if status == 404:
        return MemEchoNotFoundError(msg, status=status)
    if status == 413:
        return MemEchoPayloadTooLargeError(msg, status=status)
    return MemEchoError(msg, status=status)


def _parse_sse_events(text: str) -> list[dict[str, Any]]:
    """解析 text/event-stream：抽取每条 ``data:`` 负载并按 JSON 解析（忽略心跳/[DONE]）。"""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        payload = stripped[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        parsed = _loads_json(payload)
        events.append(parsed if isinstance(parsed, dict) else {"data": parsed})
    return events


def to_data_url(content: str | bytes, mime: str = "text/markdown") -> str:
    """把文本/字节内容编码为 base64 data URL（供 import_file 内联上传）。"""
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"
