"""NotionSyncJob 进度模型单测：progress_percent / status / 计数 / to_dict 契约（纯内存）。"""
from __future__ import annotations

from kacore.notion_sync_job import (
    NOTION_STAGE_PREPARING,
    NOTION_STAGE_PUSHING_DOCUMENTS,
    NOTION_SYNC_PARTIAL,
    NOTION_SYNC_RUNNING,
    NOTION_SYNC_SUCCESS,
    NotionSyncJob,
)


def test_to_dict_has_type_discriminator_and_status() -> None:
    job = NotionSyncJob(force=True)
    d = job.to_dict()
    assert d["type"] == "notion_sync"
    assert d["status"] == NOTION_SYNC_RUNNING
    assert d["force"] is True
    assert d["progress_percent"] == 3  # 初始 preparing 阶段底值


def test_progress_percent_pushing_documents_tracks_docs() -> None:
    job = NotionSyncJob()
    job.set_stage(NOTION_STAGE_PUSHING_DOCUMENTS)
    job.docs_total = 4
    job.docs_processed = 1
    # base(8) + 77 * (1/4) = 8 + 19 = 27
    assert job.progress_percent() == 27
    # 封顶 99：running 态即便文档全完成也不显示 100
    job.docs_processed = 4
    assert job.progress_percent() == 85  # 8 + 77*1.0
    assert job.progress_percent() <= 99


def test_progress_percent_success_is_100() -> None:
    job = NotionSyncJob()
    job.finish(NOTION_SYNC_SUCCESS)
    assert job.progress_percent() == 100
    assert job.to_dict()["finished_at"] is not None


def test_record_document_maps_action_to_counters() -> None:
    job = NotionSyncJob()
    for action in ("created", "created", "updated", "archived", "skipped", "failed"):
        job.record_document(action)
    d = job.to_dict()
    assert d["docs_processed"] == 6
    assert d["docs_created"] == 2
    assert d["docs_updated"] == 1
    assert d["docs_archived"] == 1
    assert d["docs_skipped"] == 1
    assert d["docs_failed"] == 1


def test_note_error_sets_recent_and_list() -> None:
    job = NotionSyncJob()
    job.note_error("boom")
    assert job.recent_error == "boom"
    assert job.to_dict()["errors"] == ["boom"]


def test_set_stage_updates_label() -> None:
    job = NotionSyncJob()
    job.set_stage(NOTION_STAGE_PREPARING)
    assert job.to_dict()["stage_label"] == "Preparing"


def test_partial_status_roundtrips_through_to_dict() -> None:
    job = NotionSyncJob()
    job.record_document("created")
    job.tags_pruned = 3
    job.note_error("one doc failed to push")
    job.finish(NOTION_SYNC_PARTIAL)
    d = job.to_dict()
    assert d["status"] == NOTION_SYNC_PARTIAL
    assert d["recent_error"] == "one doc failed to push"
    assert d["tags_pruned"] == 3
