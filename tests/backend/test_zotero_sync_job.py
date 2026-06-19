"""ZoteroSyncJob 进度模型单测：progress_percent / status / to_dict 契约（纯内存，无 I/O）。"""
from __future__ import annotations

from core.zotero_sync_job import (
    ZOTERO_STAGE_READING,
    ZOTERO_STAGE_SYNCING_DOCS,
    ZOTERO_SYNC_PARTIAL,
    ZOTERO_SYNC_RUNNING,
    ZOTERO_SYNC_SUCCESS,
    ZoteroSyncJob,
)


def test_to_dict_has_type_discriminator_and_status() -> None:
    job = ZoteroSyncJob(incremental=True)
    d = job.to_dict()
    assert d["type"] == "zotero_sync"
    assert d["status"] == ZOTERO_SYNC_RUNNING
    assert d["progress_percent"] == 3  # 初始 reading 阶段底值


def test_progress_percent_syncing_documents_tracks_docs() -> None:
    job = ZoteroSyncJob()
    job.set_stage(ZOTERO_STAGE_SYNCING_DOCS)
    job.docs_total = 4
    job.docs_processed = 2
    # base(10) + 80 * (2/4) = 50
    assert job.progress_percent() == 50
    # 封顶 99：即便文档全完成，running 态也不显示 100
    job.docs_processed = 4
    assert job.progress_percent() == 90  # 10 + 80*1.0
    assert job.progress_percent() <= 99


def test_progress_percent_success_is_100() -> None:
    job = ZoteroSyncJob()
    job.finish(ZOTERO_SYNC_SUCCESS)
    assert job.progress_percent() == 100
    assert job.to_dict()["finished_at"] is not None


def test_note_error_sets_recent_and_list() -> None:
    job = ZoteroSyncJob()
    job.note_error("boom")
    assert job.recent_error == "boom"
    assert job.to_dict()["errors"] == ["boom"]


def test_set_stage_updates_label() -> None:
    job = ZoteroSyncJob()
    job.set_stage(ZOTERO_STAGE_READING)
    assert job.to_dict()["stage_label"] == "Reading Zotero library"


def test_partial_status_roundtrips_through_to_dict() -> None:
    job = ZoteroSyncJob()
    job.docs_processed = 3
    job.note_error("one doc failed to index")
    job.finish(ZOTERO_SYNC_PARTIAL)
    d = job.to_dict()
    assert d["status"] == ZOTERO_SYNC_PARTIAL
    assert d["recent_error"] == "one doc failed to index"
