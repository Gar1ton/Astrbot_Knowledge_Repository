"""MemEchoClient 单测（分支 Experiment-with-MemEcho-API）。

用可注入的 fake transport 覆盖鉴权头、端点 URL/请求体、错误码→异常映射、SSE 解析与探针，
不打真实网络。
"""

from __future__ import annotations

import json

import pytest

from kacore.adapters.memecho.client import (
    MemEchoAuthError,
    MemEchoClient,
    MemEchoError,
    MemEchoNotFoundError,
    MemEchoPayloadTooLargeError,
    MemEchoQuotaError,
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
    client = MemEchoClient("x", "k", transport=_transport({"*": (200, sse)}))
    events = await client.import_file("v", "n.md", to_data_url("# hi"))
    assert events == [{"stage": "parse"}, {"stage": "done"}]


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


def test_to_data_url_base64() -> None:
    url = to_data_url("# hi", "text/markdown")
    assert url.startswith("data:text/markdown;base64,")
