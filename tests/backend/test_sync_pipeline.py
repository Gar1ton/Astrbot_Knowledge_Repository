"""SyncPipeline 在线同步管道单元测试。

验证批量文档上传、增量哈希判定、安全配额阻断以及云端 SQLite 快照物理归档。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config import R2SyncConfig
from core.domain.models import Collection, SyncStatus, SyncTargetKind
from core.managers.quota_manager import QuotaManager
from core.pipelines.sync_pipeline import SyncPipeline
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.sync_targets.memory import InMemorySyncTarget


@pytest.fixture
def store() -> InMemorySourceDocumentStore:
    return InMemorySourceDocumentStore()


@pytest.fixture
def temp_files(tmp_path: Path) -> tuple[Path, Path]:
    f1 = tmp_path / "f1.pdf"
    f2 = tmp_path / "f2.pdf"
    f1.write_bytes(b"content-1")
    f2.write_bytes(b"content-2")
    return f1, f2


@pytest.fixture
async def pipeline(
    store: InMemorySourceDocumentStore,
    temp_files: tuple[Path, Path],
    tmp_path: Path,
) -> SyncPipeline:
    f1, f2 = temp_files

    # 准备默认的集合与源文档
    await store.upsert_collection(Collection(name="papers"))

    from core.domain.models import SourceDocument
    await store.add_document(
        SourceDocument(
            doc_id="d1",
            title="doc-1",
            file_path=str(f1),
            content_type="application/pdf",
            size_bytes=len(b"content-1"),
            content_hash="hash-1",
            collection="papers",
        )
    )
    await store.add_document(
        SourceDocument(
            doc_id="d2",
            title="doc-2",
            file_path=str(f2),
            content_type="application/pdf",
            size_bytes=len(b"content-2"),
            content_hash="hash-2",
            collection="papers",
        )
    )

    # 初始化 R2 Target 与 QuotaManager
    r2_config = R2SyncConfig(enabled=True, bucket="test-bucket", free_tier_gb=10)
    # limit_bytes 设置为 100 字节，足够通过测试
    target = InMemorySyncTarget(kind=SyncTargetKind.R2, limit_bytes=100)
    quota_mgr = QuotaManager(sync_targets={SyncTargetKind.R2: target}, r2_config=r2_config)

    # 虚拟一个 db 文件作为备份快照
    db_file = tmp_path / "knowledge_repository.db"
    db_file.write_bytes(b"mock-sqlite-db-data")

    return SyncPipeline(
        source_store=store,
        sync_targets={SyncTargetKind.R2: target},
        quota_manager=quota_mgr,
        db_path=db_file,
    )


async def test_full_pipeline_sync_success(
    pipeline: SyncPipeline,
    store: InMemorySourceDocumentStore,
) -> None:
    # 1) 执行全量同步
    result = await pipeline.sync(SyncTargetKind.R2)

    assert result["status"] == "success"
    assert result["synced_count"] == 2
    assert result["failed_count"] == 0

    # 2) 检查记账状态是否正确置为 SYNCED
    r1 = await store.get_sync_record("d1", SyncTargetKind.R2)
    assert r1 is not None
    assert r1.status == SyncStatus.SYNCED
    assert r1.remote_ref == "papers/d1"
    assert r1.content_hash == "hash-1"

    # 3) 检查数据库快照是否成功备份到 backups/ 槽
    target = pipeline._sync_targets[SyncTargetKind.R2]
    db_bytes = target._objects.get("backups/knowledge_repository.db")
    assert db_bytes == b"mock-sqlite-db-data"


async def test_incremental_indexing_efficiency(
    pipeline: SyncPipeline,
    store: InMemorySourceDocumentStore,
) -> None:
    # 1) 首次同步，同步 2 个文档
    await pipeline.sync(SyncTargetKind.R2)

    # 2) 再次同步，没有任何文件内容改变
    res_noop = await pipeline.sync(SyncTargetKind.R2)
    # 应智能识别，不重复上传文件
    assert res_noop["synced_count"] == 0
    assert "所有文档已是最新状态" in res_noop["message"]

    # 3) 修改 d1 的哈希，只同步 d1
    d1 = await store.get_document("d1")
    assert d1 is not None
    d1.content_hash = "hash-1-modified"
    await store.update_document(d1)

    res_inc = await pipeline.sync(SyncTargetKind.R2)
    assert res_inc["synced_count"] == 1
    assert res_inc["failed_count"] == 0

    # 4) 校验 d1 哈希确实在同步记录中被更新
    r1 = await store.get_sync_record("d1", SyncTargetKind.R2)
    assert r1 is not None and r1.content_hash == "hash-1-modified"


async def test_quota_hard_block_stops_sync(
    pipeline: SyncPipeline,
    store: InMemorySourceDocumentStore,
) -> None:
    # 将 R2 存储上限直接缩水到 5 字节，由于 d1 (9B) + d2 (9B) = 18B > 5B，将强力安全拦截阻断
    target = pipeline._sync_targets[SyncTargetKind.R2]
    target._limit_bytes = 5

    result = await pipeline.sync(SyncTargetKind.R2)

    assert result["status"] == "blocked"
    assert "已被硬性安全阻断" in result["message"]
    assert result["synced_count"] == 0
    assert result["failed_count"] == 2

    # 记账状态应当仍未被记录为成功
    r1 = await store.get_sync_record("d1", SyncTargetKind.R2)
    assert r1 is None


async def test_restore_from_backup(pipeline: SyncPipeline) -> None:
    # 构造真实的 R2SyncTarget (用 mock config)
    r2_config = R2SyncConfig(
        enabled=True,
        bucket="test-bucket",
        account_id="mock-acc",
        access_key_id="x",
        secret_access_key="y",
    )
    from core.repository.sync_targets.r2 import R2SyncTarget
    real_target = R2SyncTarget(r2_config)

    # 替换 pipeline 中的 target
    pipeline._sync_targets[SyncTargetKind.R2] = real_target

    # 执行恢复
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        # Mock s3.get_object returning a body stream
        mock_body = MagicMock()
        mock_body.read.return_value = b"cloud-backup-db-content"
        mock_s3.get_object.return_value = {"Body": mock_body}

        result = await pipeline.restore(SyncTargetKind.R2)
        assert result["status"] == "success"
        assert "数据库成功恢复" in result["message"]

        # 验证本地 db 确实被改写为云端下载的内容
        assert pipeline._db_path.read_bytes() == b"cloud-backup-db-content"

