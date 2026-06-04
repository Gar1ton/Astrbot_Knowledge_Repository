"""R2SyncTarget 单元测试。

使用 unittest.mock 模拟 boto3.client 交互细节，
验证 R2SyncTarget 文件的上传、删除、存储桶用量计算与关闭配置下的边界表现。
"""
from __future__ import annotations

import sys
from unittest.mock import ANY, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from core.config import R2SyncConfig
from core.domain.models import SourceDocument, SyncTargetKind
from core.repository.sync_targets.r2 import R2SyncTarget


def _doc(doc_id: str, collection: str = "papers") -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"title-{doc_id}",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        content_hash=f"hash-{doc_id}",
        collection=collection,
        tags=["rag"],
    )


@pytest.fixture
def r2_config() -> R2SyncConfig:
    return R2SyncConfig(
        enabled=True,
        account_id="mock-account-id",
        access_key_id="mock-access-key-id",
        secret_access_key="mock-secret-access-key",
        bucket="mock-bucket",
        free_tier_gb=10,
    )


async def test_r2_push_success(r2_config: R2SyncConfig) -> None:
    # 模拟 boto3 S3 客户端
    mock_s3 = MagicMock()
    with patch("boto3.client", return_value=mock_s3) as mock_boto:
        target = R2SyncTarget(r2_config)
        doc = _doc("d1")
        ref = await target.push(doc, b"pdf-payload")

        assert ref == "papers/d1.pdf"
        # 验证 boto3.client 构造参数
        mock_boto.assert_called_once_with(
            service_name="s3",
            endpoint_url="https://mock-account-id.r2.cloudflarestorage.com",
            aws_access_key_id="mock-access-key-id",
            aws_secret_access_key="mock-secret-access-key",
            config=ANY,  # 匹配任何 botocore Config 对象
        )
        # 验证 put_object 被调
        mock_s3.put_object.assert_called_once_with(
            Bucket="mock-bucket",
            Key="papers/d1.pdf",
            Body=b"pdf-payload",
            ContentType="application/pdf",
        )


async def test_r2_push_failure_raises(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"
    )
    with patch("boto3.client", return_value=mock_s3):
        target = R2SyncTarget(r2_config)
        with pytest.raises(RuntimeError, match="R2 upload failed"):
            await target.push(_doc("d1"), b"payload")


async def test_r2_delete_success(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    with patch("boto3.client", return_value=mock_s3):
        target = R2SyncTarget(r2_config)
        assert await target.delete("papers/d1.pdf") is True
        mock_s3.delete_object.assert_called_once_with(Bucket="mock-bucket", Key="papers/d1.pdf")


async def test_r2_backup_preserves_explicit_key(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    with patch("boto3.client", return_value=mock_s3):
        target = R2SyncTarget(r2_config)
        ref = await target.push_backup(
            "backups/knowledge_repository.db",
            b"sqlite-bytes",
            "application/x-sqlite3",
        )
        assert ref == "backups/knowledge_repository.db"
        mock_s3.put_object.assert_called_once_with(
            Bucket="mock-bucket",
            Key="backups/knowledge_repository.db",
            Body=b"sqlite-bytes",
            ContentType="application/x-sqlite3",
        )


async def test_r2_check_quota_lists_objects(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    # 模拟 S3 paginator
    mock_paginator = MagicMock()
    mock_s3.get_paginator.return_value = mock_paginator
    # 两个页面对象用量：100 字节 + 200 字节 = 300 字节
    mock_paginator.paginate.return_value = [
        {"Contents": [{"Key": "k1", "Size": 100}, {"Key": "k2", "Size": 200}]}
    ]

    with patch("boto3.client", return_value=mock_s3):
        target = R2SyncTarget(r2_config)
        usage = await target.check_quota(pending_bytes=50)

        assert usage.target == SyncTargetKind.R2
        assert usage.used_bytes == 300
        assert usage.limit_bytes == 10 * 1024 * 1024 * 1024
        assert usage.pending_bytes == 50
        assert usage.projected_bytes == 350
        assert usage.will_exceed is False


async def test_r2_disabled_boundary() -> None:
    disabled_config = R2SyncConfig(enabled=False)
    target = R2SyncTarget(disabled_config)

    # 1) 未启用时，计算配额应当返回空用量，并提示已关闭
    usage = await target.check_quota(pending_bytes=100)
    assert usage.used_bytes == 0
    assert usage.detail == "R2 同步服务已关闭"

    # 2) 未启用时执行 push 应当直接抛错
    with pytest.raises(ValueError, match="R2 sync is disabled"):
        await target.push(_doc("d1"), b"data")


async def test_r2_missing_optional_dependency_does_not_break_module_import(
    r2_config: R2SyncConfig,
) -> None:
    with patch.dict(sys.modules, {"boto3": None, "botocore": None}):
        target = R2SyncTarget(r2_config)
        with pytest.raises(RuntimeError, match="requirements-additional.txt"):
            await target.push(_doc("d1"), b"data")
