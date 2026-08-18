"""MemEchoClient 单测（分支 Experiment-with-MemEcho-API）。

用可注入的 fake transport 覆盖鉴权头、端点 URL/请求体、错误码→异常映射、SSE 解析与探针，
不打真实网络。
"""

from __future__ import annotations

import json

import pytest

from kacore.adapters.memecho.client import (
    DEFAULT_IMPORT_TIMEOUT_SECONDS,
    MemEchoAuthError,
    MemEchoClient,
    MemEchoError,
    MemEchoNotFoundError,
    MemEchoPayloadTooLargeError,
    MemEchoQuotaError,
    MemEchoTimeoutError,
    MemEchoTransportError,
    to_data_url,
)


def _transport(routes: dict, calls: list | None = None):
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        if calls is not None:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "auth": headers.get("Authorization"),
                    "json": json_body,
                    "params": params,
                }
            )
        key = (method, url.split("/api/")[-1]) if "/api/" in url else (method, url)
        return routes.get(key, routes.get("*", (200, "{}")))

    return transport


async def test_auth_header_and_base_url() -> None:
    calls: list = []
    client = MemEchoClient(
        "https://api.artific.social/",
        "as_key",
        transport=_transport(
            {("GET", "v1/memory/vaults"): (200, json.dumps([{"id": "v1"}]))}, calls
        ),
    )
    assert await client.list_vaults() == [{"id": "v1"}]
    assert calls[0]["auth"] == "Bearer as_key"
    assert calls[0]["url"] == "https://api.artific.social/api/v1/memory/vaults"


async def test_no_key_means_no_auth_header() -> None:
    calls: list = []
    client = MemEchoClient("x", "", transport=_transport({"*": (200, "[]")}, calls))
    await client.list_vaults()
    assert calls[0]["auth"] is None


async def test_callable_key_resolved_per_request() -> None:
    calls: list = []
    box = {"v": "as_1"}
    client = MemEchoClient("x", lambda: box["v"], transport=_transport({"*": (200, "[]")}, calls))
    await client.list_vaults()
    box["v"] = "as_2"
    await client.list_vaults()
    assert calls[0]["auth"] == "Bearer as_1"
    assert calls[1]["auth"] == "Bearer as_2"


async def test_query_readonly_body_and_path() -> None:
    calls: list = []
    client = MemEchoClient(
        "x",
        "k",
        transport=_transport({"*": (200, json.dumps({"results": [], "degraded": False}))}, calls),
    )
    await client.query_readonly("vault-1", "hi")
    assert calls[0]["json"] == {"library_id": "vault-1", "message": "hi"}
    assert calls[0]["url"].endswith("/api/v1/memory/query-readonly")


@pytest.mark.parametrize(
    "status,exc",
    [
        (401, MemEchoAuthError),
        (403, MemEchoAuthError),
        (402, MemEchoQuotaError),
        (404, MemEchoNotFoundError),
        (413, MemEchoPayloadTooLargeError),
        (500, MemEchoError),
    ],
)
async def test_error_code_mapping(status: int, exc: type[MemEchoError]) -> None:
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (status, json.dumps({"error": "boom"}))})
    )
    with pytest.raises(exc) as ei:
        await client.list_vaults()
    assert ei.value.status == status
    assert "boom" in str(ei.value)


async def test_import_file_parses_sse_events() -> None:
    sse = 'data: {"stage":"parse"}\n\ndata: [DONE]\n\ndata: {"stage":"done"}\n'
    calls: list = []
    client = MemEchoClient("x", "k", transport=_transport({"*": (200, sse)}, calls))
    events = await client.import_file("v", "n.md", to_data_url("# hi"))
    assert events == [{"stage": "parse"}, {"stage": "done"}]
    assert calls[0]["url"] == "x/api/v1/memory/vaults/v/import_file"
    assert calls[0]["json"]["library_id"] == "v"


async def test_probe_ok_with_usage() -> None:
    client = MemEchoClient(
        "x",
        "k",
        transport=_transport(
            {
                ("GET", "v1/memory/vaults"): (200, json.dumps([{"id": "a"}, {"id": "b"}])),
                ("GET", "v1/dashboard/services/memory/usage"): (
                    200,
                    json.dumps({"vault_count": 2}),
                ),
            }
        ),
    )
    p = await client.probe()
    assert p["ok"] is True
    assert p["vault_count"] == 2
    assert p["usage"]["vault_count"] == 2


async def test_probe_reports_failure_without_raising() -> None:
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (401, json.dumps({"error": "bad key"}))})
    )
    p = await client.probe()
    assert p["ok"] is False
    assert p["status"] == 401
    assert "bad key" in p["error"]


async def test_204_no_content_returns_empty() -> None:
    client = MemEchoClient("x", "k", transport=_transport({"*": (204, "")}))
    assert await client.get_vault("v") == {}


async def test_update_vault_sends_only_provided_fields() -> None:
    calls: list = []
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (200, json.dumps({"id": "v"}))}, calls)
    )
    await client.update_vault("v", name="new-name")
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/api/v1/memory/vaults/v")
    assert calls[0]["json"] == {"name": "new-name"}


async def test_delete_vault_returns_none_on_204() -> None:
    calls: list = []
    client = MemEchoClient("x", "k", transport=_transport({"*": (204, "")}, calls))
    assert await client.delete_vault("v") is None
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith("/api/v1/memory/vaults/v")


async def test_list_vault_trash() -> None:
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (200, json.dumps([{"id": "t1"}]))})
    )
    assert await client.list_vault_trash() == [{"id": "t1"}]


async def test_restore_vault() -> None:
    calls: list = []
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (200, json.dumps({"id": "v"}))}, calls)
    )
    await client.restore_vault("t1")
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/api/v1/memory/vaults/trash/t1/restore")


async def test_purge_vault_returns_none_on_204() -> None:
    calls: list = []
    client = MemEchoClient("x", "k", transport=_transport({"*": (204, "")}, calls))
    assert await client.purge_vault("t1") is None
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith("/api/v1/memory/vaults/trash/t1")


async def test_list_messages_passes_limit_and_offset() -> None:
    calls: list = []
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (200, json.dumps([{"id": "m1"}]))}, calls)
    )
    assert await client.list_messages("v", limit=10, offset=5) == [{"id": "m1"}]
    assert calls[0]["url"].endswith("/api/v1/memory/vaults/v/messages")
    assert calls[0]["params"] == {"limit": 10, "offset": 5}


async def test_get_file_content_returns_raw_text() -> None:
    calls: list = []
    client = MemEchoClient("x", "k", transport=_transport({"*": (200, "raw content")}, calls))
    text = await client.get_file_content("v", "a1")
    assert text == "raw content"
    assert calls[0]["url"] == "x/api/v1/memory/files/content"
    assert calls[0]["params"] == {"library_id": "v", "attachment_id": "a1"}


async def test_get_file_content_raises_on_error_status() -> None:
    client = MemEchoClient(
        "x", "k", transport=_transport({"*": (404, json.dumps({"error": "not found"}))})
    )
    with pytest.raises(MemEchoNotFoundError):
        await client.get_file_content("v", "a1")


def test_to_data_url_base64() -> None:
    url = to_data_url("# hi", "text/markdown")
    assert url.startswith("data:text/markdown;base64,")


# ── 传输层异常翻译与导入超时分档（真机 30s 导入超时逃逸后补）────────────


def _raising_transport(exc: BaseException):
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        raise exc

    return transport


def _timeout_recording_transport(seen: list, body: tuple[int, str] = (200, "[]")):
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        seen.append({"url": url, "timeout": timeout_seconds})
        return body

    return transport


async def test_request_timeout_becomes_memecho_error() -> None:
    client = MemEchoClient("x", "k", transport=_raising_transport(TimeoutError()))
    with pytest.raises(MemEchoTimeoutError) as excinfo:
        await client.list_vaults()
    assert isinstance(excinfo.value, MemEchoError)
    assert excinfo.value.status is None
    # str(TimeoutError()) 为空串；翻译后必须有可读文案，否则前端只剩 "Internal Server Error"。
    assert str(excinfo.value)


async def test_transport_failure_becomes_memecho_error() -> None:
    client = MemEchoClient("x", "k", transport=_raising_transport(ValueError("boom")))
    with pytest.raises(MemEchoTransportError) as excinfo:
        await client.list_vaults()
    assert isinstance(excinfo.value, MemEchoError)
    assert "boom" in str(excinfo.value)


async def test_memecho_error_from_transport_passes_through() -> None:
    original = MemEchoAuthError("revoked", status=401)
    client = MemEchoClient("x", "k", transport=_raising_transport(original))
    with pytest.raises(MemEchoAuthError) as excinfo:
        await client.list_vaults()
    assert excinfo.value is original


async def test_import_file_timeout_is_wrapped_too() -> None:
    client = MemEchoClient("x", "k", transport=_raising_transport(TimeoutError()))
    with pytest.raises(MemEchoTimeoutError):
        await client.import_file("v", "n.md", to_data_url("# hi"))


async def test_import_file_uses_separate_longer_timeout() -> None:
    seen: list = []
    client = MemEchoClient("x", "k", transport=_timeout_recording_transport(seen))
    await client.list_vaults()
    await client.import_file("v", "n.md", to_data_url("# hi"))
    assert seen[0]["timeout"] == 30
    assert seen[1]["timeout"] == DEFAULT_IMPORT_TIMEOUT_SECONDS


async def test_explicit_import_timeout_wins() -> None:
    seen: list = []
    client = MemEchoClient(
        "x", "k", import_timeout_seconds=45, transport=_timeout_recording_transport(seen)
    )
    await client.import_file("v", "n.md", to_data_url("# hi"))
    assert seen[0]["timeout"] == 45


async def test_import_timeout_never_below_request_timeout() -> None:
    seen: list = []
    client = MemEchoClient(
        "x", "k", timeout_seconds=600, transport=_timeout_recording_transport(seen)
    )
    await client.import_file("v", "n.md", to_data_url("# hi"))
    assert seen[0]["timeout"] == 600
