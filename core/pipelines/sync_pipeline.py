"""在线同步备份编排管道（pipelines 层）。

编排多文件增量对比、大文件配额安全预检、boto3 推送上传、
记账状态写入，以及本地 SQLite 数据库快照云端物理备份的完整闭环。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.domain.models import QuotaLevel, SyncRecord, SyncStatus, SyncTargetKind

if TYPE_CHECKING:
    from core.managers.quota_manager import QuotaManager
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.sync_targets.base import SyncTarget

logger = logging.getLogger("SyncPipeline")


class SyncPipeline:
    """文档与数据库备份的同步管线。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        sync_targets: dict[SyncTargetKind, SyncTarget],
        quota_manager: QuotaManager,
        db_path: Path | None = None,
    ) -> None:
        self._source_store = source_store
        self._sync_targets = sync_targets
        self._quota_manager = quota_manager
        self._db_path = db_path

    async def sync(
        self,
        target_kind: SyncTargetKind,
        doc_ids: list[str] | None = None,
    ) -> dict:
        target = self._sync_targets.get(target_kind)
        if target is None:
            return {"status": "error", "message": f"同步目标 {target_kind.value} 未配置"}

        # 1) 获取待处理的文档列表
        docs = []
        if doc_ids is not None:
            for d_id in doc_ids:
                doc = await self._source_store.get_document(d_id)
                if doc is not None:
                    docs.append(doc)
        else:
            docs = await self._source_store.list_documents()

        # 2) 增量对比过滤出待上传的文档列表，计算待传大小 (pending_bytes)
        pending_docs = []
        pending_bytes = 0

        for doc in docs:
            record = await self._source_store.get_sync_record(doc.doc_id, target_kind)
            # 增量判定：未曾记录同步、上次失败、或本地哈希发生了改变，才判定为需要上传
            if (
                record is None
                or record.status != SyncStatus.SYNCED
                or record.content_hash != doc.content_hash
            ):
                pending_docs.append(doc)
                pending_bytes += doc.size_bytes

        if not pending_docs:
            # 触发一次 R2 数据库快照备份，确保即使无文件更新，DB 也是最新的
            await self._backup_db_snapshot(target_kind)
            return {
                "status": "success",
                "message": "所有文档已是最新状态，无需同步。",
                "synced_count": 0,
                "failed_count": 0,
            }

        # 3) 进行大文件上传前的配额硬限制检测
        warning = await self._quota_manager.check_quota(target_kind.value, pending_bytes)
        if warning.level == QuotaLevel.BLOCK:
            # 硬额度超出，阻断执行
            return {
                "status": "blocked",
                "message": warning.message,
                "synced_count": 0,
                "failed_count": len(pending_docs),
            }

        synced_count = 0
        failed_count = 0
        now = datetime.now(timezone.utc)

        # 4) 循环处理批量推送与记账
        for doc in pending_docs:
            record = await self._source_store.get_sync_record(doc.doc_id, target_kind)
            if record is None:
                record = SyncRecord(doc_id=doc.doc_id, target=target_kind)

            try:
                # 读取本地原件二进制流
                file_path = Path(doc.file_path)
                if not file_path.exists():
                    raise FileNotFoundError(f"Local document file missing: {doc.file_path}")

                with open(file_path, "rb") as f:
                    payload = f.read()

                # 执行底层仓储上传
                remote_ref = await target.push(doc, payload)

                # 同步成功，修改记账
                status = SyncStatus.SYNCED
                msg = "同步成功"
                if remote_ref.startswith("skipped:"):
                    status = SyncStatus.SKIPPED
                    remote_ref = remote_ref[len("skipped:"):]
                    msg = "已跳过文件二进制镜像，仅推送元数据"

                record.status = status
                record.remote_ref = remote_ref
                record.content_hash = doc.content_hash
                record.synced_at = now
                record.message = msg
                synced_count += 1

            except Exception as e:
                logger.error(f"Failed to sync document {doc.title} ({doc.doc_id}): {e}")
                record.status = SyncStatus.FAILED
                record.message = str(e)
                failed_count += 1

            # 写入仓储持久化
            await self._source_store.upsert_sync_record(record)

        # 5) 推送完毕后，做一次本地 SQLite 数据库的云端快照备份（崩溃恢复）
        await self._backup_db_snapshot(target_kind)

        result = {
            "status": "success",
            "synced_count": synced_count,
            "failed_count": failed_count,
        }
        if warning.level == QuotaLevel.WARN:
            result["warning"] = warning.message

        return result

    async def initialize_notion_database(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> dict:
        target = self._sync_targets.get(SyncTargetKind.NOTION)
        if target is None:
            return {"status": "error", "message": "Notion 同步目标未配置"}
        initialize = getattr(target, "initialize_database", None)
        if not callable(initialize):
            return {"status": "error", "message": "Notion 目标不支持自动建库"}
        return await initialize(parent_page_id, database_title)

    async def pull_notion_metadata(self) -> dict:
        target = self._sync_targets.get(SyncTargetKind.NOTION)
        if target is None:
            return {"status": "error", "message": "Notion 同步目标未配置"}
        pull = getattr(target, "pull_metadata", None)
        if not callable(pull):
            return {"status": "error", "message": "Notion 目标不支持反向同步"}
        return await pull()

    async def _backup_db_snapshot(self, target_kind: SyncTargetKind) -> None:
        """打包本地 SQLite 数据库快照备份至 R2 归档槽。"""
        if self._db_path is None or not self._db_path.exists():
            return

        target = self._sync_targets.get(target_kind)
        if target is None or target_kind != SyncTargetKind.R2:
            return

        try:
            # 读取本地 knowledge_repository.db 二进制数据
            with open(self._db_path, "rb") as f:
                db_payload = f.read()

            # 构造虚拟文档载体，R2 实现会将其推送至 backups/ 路径
            from core.domain.models import SourceDocument
            fake_doc = SourceDocument(
                doc_id="knowledge_repository.db",
                title="SQLite 数据库备份",
                file_path=str(self._db_path),
                content_type="application/x-sqlite3",
                size_bytes=len(db_payload),
                content_hash="db-snapshot",
                collection="backups",
            )
            # 执行云端推送
            await target.push(fake_doc, db_payload)
            logger.info("Local SQLite database snapshot backed up to R2 cloud successfully.")
        except Exception as e:
            logger.error(f"Failed to backup database snapshot to R2: {e}")

    async def restore(self, target_kind: SyncTargetKind) -> dict:
        """从 R2 备份归档中拉取最新的数据库快照并覆盖恢复本地。"""
        if target_kind != SyncTargetKind.R2:
            return {"status": "error", "message": "目前仅支持从 R2 对象存储恢复"}

        target = self._sync_targets.get(target_kind)
        if target is None:
            return {"status": "error", "message": "R2 备份目标未配置"}

        if self._db_path is None:
            return {"status": "error", "message": "本地数据库路径未配置"}

        try:
            # 延迟导入 boto3 client 以防未启用异常
            s3 = target._get_client()
            logger.info("Fetching SQLite database snapshot from Cloudflare R2...")

            # 下载备份快照
            response = s3.get_object(
                Bucket=target._config.bucket,
                Key="backups/knowledge_repository.db"
            )
            payload = response["Body"].read()

            # 覆盖写入本地 SQLite 文件
            # 注意：aiosqlite 在写时是加锁的，直接写入二进制文件在非并发活动下可直接覆盖
            with open(self._db_path, "wb") as f:
                f.write(payload)

            logger.info("Successfully restored local database from cloud backup.")
            return {
                "status": "success",
                "message": "数据库成功恢复，本地文档元数据已刷新为最新云端版本。",
            }
        except Exception as e:
            logger.error(f"Failed to restore database from R2: {e}")
            return {"status": "error", "message": f"灾难恢复失败: {e}"}


__all__ = ["SyncPipeline"]
