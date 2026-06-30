"""Cloudflare R2 对象存储同步目标实现（repository 层）。

使用 boto3 库基于 S3 兼容协议实现原件二进制流上传、删除与 R2 存储桶用量计算。
支持自定义域名前缀及免费额度动态阈值判定。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
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
            # 兼容旧逐文档接口；阻塞调用下放线程，完整备份改走 managed transfer。
            await asyncio.to_thread(
                s3.put_object,
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

    async def upload_backup_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str = "application/octet-stream",
        sha256: str = "",
    ) -> str:
        """使用 boto3 managed transfer 流式上传，自动采用 multipart。"""
        s3 = self._get_client()

        def _upload() -> None:
            extra = {"ContentType": content_type}
            if sha256:
                extra["Metadata"] = {"sha256": sha256}
            s3.upload_file(str(path), self._config.bucket, key, ExtraArgs=extra)

        try:
            await asyncio.to_thread(_upload)
            return key
        except Exception as exc:
            raise RuntimeError(f"R2 backup file upload failed: {exc}") from exc

    async def download_backup_file(self, key: str, path: Path) -> None:
        """使用 boto3 managed transfer 流式下载。"""
        s3 = self._get_client()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(
                s3.download_file, self._config.bucket, key, str(path)
            )
        except Exception as exc:
            raise RuntimeError(f"R2 backup file download failed: {exc}") from exc

    async def list_backup_objects(self, prefix: str = "") -> list[dict[str, object]]:
        """分页列出 Bucket 对象；网络错误向上抛出，配额检查不得 fail-open。"""
        s3 = self._get_client()

        def _list() -> list[dict[str, object]]:
            rows: list[dict[str, object]] = []
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._config.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    rows.append(
                        {
                            "key": str(obj.get("Key") or ""),
                            "size": int(obj.get("Size") or 0),
                            "last_modified": str(obj.get("LastModified") or ""),
                        }
                    )
            return rows

        try:
            return await asyncio.to_thread(_list)
        except Exception as exc:
            raise RuntimeError(f"R2 object listing failed: {exc}") from exc

    async def stat_backup_object(self, key: str) -> dict[str, object] | None:
        s3 = self._get_client()
        try:
            response = await asyncio.to_thread(
                s3.head_object, Bucket=self._config.bucket, Key=key
            )
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise RuntimeError(f"R2 object stat failed: {exc}") from exc
        return {
            "key": key,
            "size": int(response.get("ContentLength") or 0),
            "metadata": dict(response.get("Metadata") or {}),
        }

    async def delete_backup_objects(self, keys: list[str]) -> None:
        if not keys:
            return
        s3 = self._get_client()
        try:
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                response = await asyncio.to_thread(
                    s3.delete_objects,
                    Bucket=self._config.bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
                errors = response.get("Errors") or []
                if errors:
                    raise RuntimeError(str(errors))
        except Exception as exc:
            raise RuntimeError(f"R2 object cleanup failed: {exc}") from exc

    async def delete(self, remote_ref: str) -> bool:
        s3 = self._get_client()
        try:
            await asyncio.to_thread(
                s3.delete_object, Bucket=self._config.bucket, Key=remote_ref
            )
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
            await asyncio.to_thread(
                s3.put_object,
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
            response = await asyncio.to_thread(
                s3.get_object, Bucket=self._config.bucket, Key=key
            )
            return await asyncio.to_thread(response["Body"].read)
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
            objects = await self.list_backup_objects()
            total_used_bytes = sum(int(obj.get("size") or 0) for obj in objects)

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
            raise RuntimeError(f"R2 quota calculation failed: {e}") from e


__all__ = ["R2SyncTarget"]
