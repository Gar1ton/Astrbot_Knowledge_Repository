"""R2SyncTarget 单元测试。

使用 unittest.mock 模拟 boto3.client 交互细节，
验证 R2SyncTarget 文件的上传、删除、存储桶用量计算与关闭配置下的边界表现。
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from core.config import R2SyncConfig
from core.domain.models import SourceDocument, SyncTargetKind
from core.repository.sync_targets.r2 import R2SyncTarget


@contextmanager
def _patched_boto_client(mock_s3: MagicMock):
    """无论本机是否安装可选依赖，都提供隔离的 boto3 client 替身。"""
    try:
        import boto3  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        boto3_module = types.ModuleType("boto3")
        boto3_module.client = MagicMock(return_value=mock_s3)  # type: ignore[attr-defined]
        botocore_module = types.ModuleType("botocore")
        config_module = types.ModuleType("botocore.config")

        class BotoConfig:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

        config_module.Config = BotoConfig  # type: ignore[attr-defined]
        botocore_module.config = config_module  # type: ignore[attr-defined]
        with patch.dict(
            sys.modules,
            {
                "boto3": boto3_module,
                "botocore": botocore_module,
                "botocore.config": config_module,
            },
        ):
            yield boto3_module.client  # type: ignore[attr-defined]
    else:
        with patch("boto3.client", return_value=mock_s3) as mock_boto:
            yield mock_boto


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
    with _patched_boto_client(mock_s3) as mock_boto:
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
    mock_s3.put_object.side_effect = RuntimeError("AccessDenied")
    with _patched_boto_client(mock_s3):
        target = R2SyncTarget(r2_config)
        with pytest.raises(RuntimeError, match="R2 upload failed"):
            await target.push(_doc("d1"), b"payload")


async def test_r2_delete_success(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    with _patched_boto_client(mock_s3):
        target = R2SyncTarget(r2_config)
        assert await target.delete("papers/d1.pdf") is True
        mock_s3.delete_object.assert_called_once_with(Bucket="mock-bucket", Key="papers/d1.pdf")


async def test_r2_backup_preserves_explicit_key(r2_config: R2SyncConfig) -> None:
    mock_s3 = MagicMock()
    with _patched_boto_client(mock_s3):
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

    with _patched_boto_client(mock_s3):
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


async def test_r2_backup_object_operations_are_streamed_and_paginated(
    r2_config: R2SyncConfig,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    destination = tmp_path / "nested" / "download.pdf"
    mock_s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "p/a", "Size": 3, "LastModified": "t1"}]},
        {"Contents": [{"Key": "p/b", "Size": 4, "LastModified": "t2"}]},
    ]
    mock_s3.get_paginator.return_value = paginator
    mock_s3.head_object.return_value = {
        "ContentLength": 3,
        "Metadata": {"sha256": "abc"},
    }
    mock_s3.delete_objects.return_value = {}

    with _patched_boto_client(mock_s3):
        target = R2SyncTarget(r2_config)
        await target.upload_backup_file(
            "p/a", source, content_type="application/pdf", sha256="abc"
        )
        await target.download_backup_file("p/a", destination)
        rows = await target.list_backup_objects("p/")
        stat = await target.stat_backup_object("p/a")
        await target.delete_backup_objects(["p/a", "p/b"])

    mock_s3.upload_file.assert_called_once_with(
        str(source),
        "mock-bucket",
        "p/a",
        ExtraArgs={"ContentType": "application/pdf", "Metadata": {"sha256": "abc"}},
    )
    mock_s3.download_file.assert_called_once_with(
        "mock-bucket", "p/a", str(destination)
    )
    paginator.paginate.assert_called_once_with(Bucket="mock-bucket", Prefix="p/")
    assert [row["key"] for row in rows] == ["p/a", "p/b"]
    assert stat == {"key": "p/a", "size": 3, "metadata": {"sha256": "abc"}}
    mock_s3.delete_objects.assert_called_once_with(
        Bucket="mock-bucket",
        Delete={"Objects": [{"Key": "p/a"}, {"Key": "p/b"}], "Quiet": True},
    )


async def test_r2_bucket_listing_failure_blocks_quota_check(
    r2_config: R2SyncConfig,
) -> None:
    mock_s3 = MagicMock()
    mock_s3.get_paginator.side_effect = RuntimeError("network unavailable")
    with _patched_boto_client(mock_s3):
        target = R2SyncTarget(r2_config)
        with pytest.raises(RuntimeError, match="quota calculation failed"):
            await target.check_quota()
