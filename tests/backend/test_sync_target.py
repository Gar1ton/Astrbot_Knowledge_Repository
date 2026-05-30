"""SyncTarget 契约测试（接口对换：内存目标）+ QuotaUsage 派生量。"""
from __future__ import annotations

import pytest

from core.domain.models import QuotaUsage, SourceDocument, SyncTargetKind
from core.repository.sync_targets.memory import InMemorySyncTarget


def _doc(doc_id: str, collection: str = "c") -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=doc_id,
        file_path=f"/data/{doc_id}",
        content_type="application/pdf",
        size_bytes=0,
        content_hash="h",
        collection=collection,
    )


async def test_push_returns_ref_and_is_idempotent() -> None:
    target = InMemorySyncTarget(kind=SyncTargetKind.R2)
    ref1 = await target.push(_doc("d1"), b"abc")
    ref2 = await target.push(_doc("d1"), b"abcd")  # 覆盖
    assert ref1 == ref2
    usage = await target.check_quota()
    assert usage.used_bytes == 4  # 覆盖后只剩最新字节


async def test_delete() -> None:
    target = InMemorySyncTarget()
    ref = await target.push(_doc("d1"), b"abc")
    assert await target.delete(ref) is True
    assert await target.delete(ref) is False


async def test_check_quota_accumulates_and_projects() -> None:
    target = InMemorySyncTarget(kind=SyncTargetKind.R2, limit_bytes=10)
    await target.push(_doc("d1"), b"abcd")  # 4 bytes
    usage = await target.check_quota(pending_bytes=5)
    assert usage.used_bytes == 4
    assert usage.projected_bytes == 9
    assert usage.will_exceed is False
    usage2 = await target.check_quota(pending_bytes=7)
    assert usage2.will_exceed is True  # 4 + 7 > 10


def test_quota_usage_no_limit_means_no_exceed() -> None:
    usage = QuotaUsage(
        target=SyncTargetKind.NOTION, used_bytes=10**9, limit_bytes=0, pending_bytes=10**9
    )
    assert usage.ratio == 0.0
    assert usage.will_exceed is False


def test_quota_usage_ratio() -> None:
    usage = QuotaUsage(target=SyncTargetKind.R2, used_bytes=8, limit_bytes=10)
    assert usage.ratio == pytest.approx(0.8)


async def test_kind_property() -> None:
    assert InMemorySyncTarget(kind=SyncTargetKind.NOTION).kind is SyncTargetKind.NOTION
