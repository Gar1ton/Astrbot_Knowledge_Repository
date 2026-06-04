"""Cloudflare R2 对象存储同步目标实现（repository 层）。

使用 boto3 库基于 S3 兼容协议实现原件二进制流上传、删除与 R2 存储桶用量计算。
支持自定义域名前缀及免费额度动态阈值判定。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.domain.models import QuotaUsage, SyncTargetKind
from core.repository.sync_targets.base import SyncTarget

if TYPE_CHECKING:
    from core.config import R2SyncConfig
    from core.domain.models import SourceDocument

logger = logging.getLogger("R2SyncTarget")


class R2SyncTarget(SyncTarget):
    """基于 boto3 的 Cloudflare R2 对象存储实现。"""

    def __init__(self, config: R2SyncConfig) -> None:
        self._config = config
        self._s3_client = None

    @property
    def kind(self) -> SyncTargetKind:
        return SyncTargetKind.R2

    def _get_client(self):
        """延迟初始化 S3 客户端，防止未启用 R2 时抛出配置错误。"""
        if self._s3_client is None:
            if not self._config.enabled:
                raise ValueError("R2 sync is disabled in configuration.")
            if not self._config.account_id:
                raise ValueError("Cloudflare Account ID is required for R2.")
            if not self._config.bucket:
                raise ValueError("R2 bucket name is required.")

            try:
                import boto3
                from botocore.config import Config as BotoConfig
            except ImportError as exc:
                raise RuntimeError(
                    "R2 sync requires optional dependencies. Install requirements-additional.txt "
                    "into the AstrBot Python environment and restart."
                ) from exc

            self._s3_client = boto3.client(
                service_name="s3",
                endpoint_url=self._config.endpoint,
                aws_access_key_id=self._config.access_key_id,
                aws_secret_access_key=self._config.secret_access_key,
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._s3_client

    async def push(self, document: SourceDocument, payload: bytes) -> str:
        s3 = self._get_client()
        # 稳定的 R2 Key: {collection}/{doc_id}.pdf
        key = f"{document.collection}/{document.doc_id}.pdf"

        try:
            # 采用 S3 put_object 接口直接上传字节流
            s3.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=payload,
                ContentType=document.content_type or "application/octet-stream",
            )
            logger.info(
                f"Successfully pushed document {document.title} to R2 "
                f"bucket {self._config.bucket} as {key}."
            )
            return key
        except Exception as e:
            logger.error(f"Failed to push to R2: {e}")
            raise RuntimeError(f"R2 upload failed: {e}") from e

    async def delete(self, remote_ref: str) -> bool:
        s3 = self._get_client()
        try:
            s3.delete_object(Bucket=self._config.bucket, Key=remote_ref)
            logger.info(f"Successfully deleted object {remote_ref} from R2 bucket.")
            return True
        except Exception as e:
            # S3 delete_object 通常是幂等的，但如果网络/鉴权异常则抛错
            logger.error(f"Failed to delete object from R2: {e}")
            return False

    async def push_backup(self, key: str, payload: bytes, content_type: str) -> str:
        """上传灾备对象，不套用普通文档的 `.pdf` key 规则。"""
        s3 = self._get_client()
        try:
            s3.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
            )
            return key
        except Exception as e:
            raise RuntimeError(f"R2 backup upload failed: {e}") from e

    async def pull_backup(self, key: str) -> bytes:
        """读取灾备对象字节。"""
        s3 = self._get_client()
        try:
            response = s3.get_object(Bucket=self._config.bucket, Key=key)
            return response["Body"].read()
        except Exception as e:
            raise RuntimeError(f"R2 backup download failed: {e}") from e

    async def check_quota(self, pending_bytes: int = 0) -> QuotaUsage:
        if not self._config.enabled:
            return QuotaUsage(
                target=self.kind,
                used_bytes=0,
                limit_bytes=self._config.free_tier_bytes,
                pending_bytes=pending_bytes,
                detail="R2 同步服务已关闭",
            )

        try:
            s3 = self._get_client()
            total_used_bytes = 0

            # 遍历桶内所有对象以汇总计算当前已用字节量
            paginator = s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self._config.bucket)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        total_used_bytes += obj["Size"]

            detail = "Cloudflare R2 对象存储"
            if self._config.cdn_domain:
                detail += f" (自定义域名: {self._config.cdn_domain})"

            return QuotaUsage(
                target=self.kind,
                used_bytes=total_used_bytes,
                limit_bytes=self._config.free_tier_bytes,
                pending_bytes=pending_bytes,
                detail=detail,
            )
        except Exception as e:
            logger.error(f"Failed to calculate R2 quota: {e}")
            # 计算用量失败时，回退到 safe 0 字节，防止阻断正常流程，但给出说明
            return QuotaUsage(
                target=self.kind,
                used_bytes=0,
                limit_bytes=self._config.free_tier_bytes,
                pending_bytes=pending_bytes,
                detail=f"配额计算异常: {e}",
            )


__all__ = ["R2SyncTarget"]
