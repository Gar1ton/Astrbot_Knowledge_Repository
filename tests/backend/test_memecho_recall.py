"""MemEchoRecall 编排单测（分支 Experiment-with-MemEcho-API）。

覆盖召回结果 shaping、只读/留痕切换、降级兜底、写回容错与文件导入汇总。
"""

from __future__ import annotations

import json

import pytest

from kacore.adapters.memecho.client import MemEchoClient
from kacore.pipelines.memecho_recall import MemEchoRecall, MemEchoRecallResult


def _client(routes: dict, calls: list | None = None) -> MemEchoClient:
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        if calls is not None:
            calls.append(url)
        key = (method, url.split("/api/")[-1])
        return routes.get(key, routes.get("*", (200, "{}")))

    return MemEchoClient("x", "k", transport=transport)


async def test_recall_shapes_sources_and_context() -> None:
    client = _client(
        {
            ("POST", "v1/memory/query-readonly"): (
                200,
                json.dumps(
                    {
                        "results": [
                            {"id": "m1", "role": "user", "content": "喜欢深色模式", "score": 0.9},
                            {"content": "讨厌弹窗"},
                        ],
                        "degraded": False,
                    }
                ),
            )
        }
    )
    res = await MemEchoRecall(client).recall("偏好？", "v1")
    assert isinstance(res, MemEchoRecallResult)
    assert res.degraded is False
    assert len(res.sources) == 2
    assert res.sources[0]["origin"] == "memecho"
    assert res.sources[0]["text"] == "喜欢深色模式"
    assert res.sources[0]["score"] == 0.9
    assert "[1] 喜欢深色模式" in res.context
    assert "[2] 讨厌弹窗" in res.context


async def test_recall_requires_vault() -> None:
    with pytest.raises(ValueError):
        await MemEchoRecall(_client({})).recall("q", "")


async def test_recall_degraded_falls_back_to_messages() -> None:
    client = _client(
        {
            "*": (
                200,
                json.dumps(
                    {
                        "results": [],
                        "degraded": True,
                        "messages": [{"role": "user", "content": "最近消息"}],
                    }
                ),
            )
        }
    )
    res = await MemEchoRecall(client).recall("q", "v1")
    assert res.degraded is True
    assert res.sources[0]["text"] == "最近消息"


async def test_recall_uses_query_when_not_readonly() -> None:
    calls: list = []
    client = _client({"*": (200, json.dumps({"results": [], "degraded": False}))}, calls)
    await MemEchoRecall(client).recall("q", "v1", readonly=False)
    assert calls[0].endswith("/api/v1/memory/query")


async def test_write_back_success_and_error_are_non_fatal() -> None:
    ok_client = _client({"*": (200, json.dumps({"status": "ok"}))})
    assert await MemEchoRecall(ok_client).write_back("v1", "q", "a") is True
    bad_client = _client({"*": (500, json.dumps({"error": "down"}))})
    assert await MemEchoRecall(bad_client).write_back("v1", "q", "a") is False


async def test_import_documents_summary_and_progress() -> None:
    client = _client({"*": (200, 'data: {"pct":100}\n')})
    events: list = []
    summary = await MemEchoRecall(client).import_documents(
        "v1",
        [{"doc_id": "d1", "title": "A", "content": "aaa"}, {"doc_id": "d2", "content": "bbb"}],
        progress_cb=events.append,
    )
    assert summary == {"imported": 2, "failed": [], "total": 2}
    assert len(events) == 2
    assert events[0]["status"] == "ok"


async def test_import_documents_records_failures() -> None:
    client = _client({"*": (413, json.dumps({"error": "too big"}))})
    summary = await MemEchoRecall(client).import_documents("v1", [{"doc_id": "d1", "content": "x"}])
    assert summary["imported"] == 0
    assert summary["total"] == 1
    assert len(summary["failed"]) == 1
    assert summary["failed"][0]["status"] == 413


async def test_import_documents_survives_timeout_on_one_doc() -> None:
    """首篇超时不得打断整批——真机 30s 超时正是在这里冒成 HTTP 500 的。"""
    seen: list = []

    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        seen.append(json_body.get("file_name") if json_body else None)
        if len(seen) == 1:
            raise TimeoutError()
        return 200, 'data: {"pct":100}\n'

    client = MemEchoClient("x", "k", transport=transport)
    events: list = []
    summary = await MemEchoRecall(client).import_documents(
        "v1",
        [{"doc_id": "d1", "content": "aaa"}, {"doc_id": "d2", "content": "bbb"}],
        progress_cb=events.append,
    )
    assert summary["imported"] == 1
    assert summary["total"] == 2
    assert len(summary["failed"]) == 1
    assert summary["failed"][0]["doc_id"] == "d1"
    assert summary["failed"][0]["status"] is None
    assert summary["failed"][0]["error"]  # 超时文案不得为空串
    assert [e["status"] for e in events] == ["error", "ok"]


async def test_import_documents_survives_unexpected_exception() -> None:
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        raise RuntimeError("unexpected")

    client = MemEchoClient("x", "k", transport=transport)
    summary = await MemEchoRecall(client).import_documents(
        "v1", [{"doc_id": "d1", "content": "x"}, {"doc_id": "d2", "content": "y"}]
    )
    assert summary["imported"] == 0
    assert summary["total"] == 2
    assert len(summary["failed"]) == 2
