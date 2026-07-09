"""EventHandler.on_ka_notion 契约测试：push 启动语义、force 二次确认、status 汇总。"""
from __future__ import annotations

from typing import Any

import pytest

from knowledge_arch.event_handler import EventHandler


class _FakeApi:
    def __init__(self, status: dict[str, Any]) -> None:
        self._status = status

    async def get_notion_push_status(self) -> dict[str, Any]:
        return self._status


class _FakeInitializer:
    def __init__(self, api: Any) -> None:
        self.api = api


def _handler(status: dict[str, Any] | None = None) -> EventHandler:
    api = _FakeApi(status or {"status": "ok", "enabled": True})
    return EventHandler(_FakeInitializer(api))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_push_returns_started_marker() -> None:
    msg = await _handler().on_ka_notion("push")
    assert "任务已启动" in msg
    assert "全量" not in msg  # 增量推送不带全量标记


@pytest.mark.asyncio
async def test_force_push_requires_confirmation() -> None:
    handler = _handler()
    first = await handler.on_ka_notion("force push")
    assert "任务已启动" not in first
    assert "再次发送" in first
    # 60s 内重发确认 → 启动，且文案带「全量」供 main 推导 force
    second = await handler.on_ka_notion("force push")
    assert "任务已启动" in second
    assert "全量" in second


@pytest.mark.asyncio
async def test_invalid_action_usage_hint() -> None:
    msg = await _handler().on_ka_notion("pull")
    assert "用法" in msg


@pytest.mark.asyncio
async def test_status_summarizes_ledger() -> None:
    handler = _handler(
        {
            "status": "ok",
            "enabled": True,
            "database_id": "db-a",
            "qa_database_id": "db-q",
            "auto_sync_interval_sec": 3600,
            "documents": {"synced": 5, "degraded": 1, "failed": 0},
            "outbox_pending": 2,
            "outbox_failed": 0,
        }
    )
    msg = await handler.on_ka_notion("status")
    assert "已建库" in msg
    assert "synced=5" in msg
    assert "每 3600s" in msg


@pytest.mark.asyncio
async def test_status_disabled_hint() -> None:
    handler = _handler({"status": "ok", "enabled": False})
    msg = await handler.on_ka_notion("status")
    assert "未启用" in msg
