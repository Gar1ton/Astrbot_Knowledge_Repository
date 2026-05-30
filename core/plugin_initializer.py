"""组合根（Composition Root，见 ../ARCHITECTURE.md §3）。

【唯一】把零件 new 出来并接起来的地方：按依赖顺序构造、构造器注入、生命周期对称。
业务层不出现在本文件之外的任何「装配代码」。

v0.3.0 生产实现：装配数据库、仓储、PDF抽取、分类管理、R2同步和配额预警。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite

from core.api import KnowledgeRepositoryApi
from core.config import Config
from core.domain.models import SyncTargetKind
from core.managers.category_manager import CategoryManager
from core.managers.ingest_manager import IngestManager
from core.managers.quota_manager import QuotaManager
from core.pipelines.sync_pipeline import SyncPipeline
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from core.repository.sync_targets.r2 import R2SyncTarget
from migrations.runner import run_migrations

if TYPE_CHECKING:
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("PluginInitializer")


class PluginInitializer:
    """装配全部子系统并拥有其生命周期。"""

    def __init__(self, context: Any, raw_config: dict[str, Any], data_dir: Path) -> None:
        self._context = context
        self._config = Config(raw_config)
        self._data_dir = data_dir
        self._exit_stack: AsyncExitStack | None = None
        self._backup_task: asyncio.Task[Any] | None = None

        # 子系统句柄 —— 在 initialize() 中按依赖顺序赋值，供 event_handler / web 引用。
        self.source_store: SourceDocumentStore | None = None
        self.kb_reader: KnowledgeBaseReader | None = None
        self.api: KnowledgeRepositoryApi | None = None

        # 依赖句柄
        self.ingest_manager: IngestManager | None = None
        self.category_manager: CategoryManager | None = None
        self.quota_manager: QuotaManager | None = None
        self.sync_pipeline: SyncPipeline | None = None

    @property
    def config(self) -> Config:
        """对外暴露 typed config 门面（只读）。"""
        return self._config

    # ── 启动：按依赖顺序构造 ────────────────────────────────────
    async def initialize(self) -> None:
        self._exit_stack = AsyncExitStack()

        # 1) 解析各子系统专属 typed config（此处已可用，供后续构造使用）。
        source_cfg = self._config.get_source_store_config()
        r2_cfg = self._config.get_r2_sync_config()
        notion_cfg = self._config.get_notion_sync_config()

        # 2) 无依赖层先行：DB 连接 + 迁移 + 仓储生产实现（v0.3.0 接入 sqlite）。
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._data_dir / source_cfg.db_filename

        db = await self._exit_stack.enter_async_context(aiosqlite.connect(str(db_path)))
        await db.execute("PRAGMA foreign_keys = ON")
        await run_migrations(db)

        self.source_store = SQLiteSourceDocumentStore(db)
        from core.repository.kb_reader.astrbot import AstrBotKnowledgeBaseReader
        self.kb_reader = AstrBotKnowledgeBaseReader(self._context)

        # 3) 构造同步目标
        from core.repository.sync_targets.base import SyncTarget
        sync_targets: dict[SyncTargetKind, SyncTarget] = {}
        # R2SyncTarget 延迟初始化 boto3.client，故总是先实例化并配置。
        r2_target = R2SyncTarget(r2_cfg)
        sync_targets[SyncTargetKind.R2] = r2_target

        from core.repository.sync_targets.notion import NotionSyncTarget
        notion_target = NotionSyncTarget(
            config=notion_cfg,
            source_store=self.source_store,
            context=self._context,
        )
        sync_targets[SyncTargetKind.NOTION] = notion_target

        # 4) 依赖前者的编排层 managers/pipelines
        self.ingest_manager = IngestManager(
            source_store=self.source_store,
            config=source_cfg,
            data_dir=self._data_dir,
        )
        self.category_manager = CategoryManager(source_store=self.source_store)
        self.quota_manager = QuotaManager(sync_targets=sync_targets, r2_config=r2_cfg)
        self.sync_pipeline = SyncPipeline(
            source_store=self.source_store,
            sync_targets=sync_targets,
            quota_manager=self.quota_manager,
            db_path=db_path,
        )

        # 5) 业务门面（依赖已装配的仓储/managers）。
        self.api = KnowledgeRepositoryApi(
            source_store=self.source_store,
            kb_reader=self.kb_reader,
            sync_targets=sync_targets,
            ingest_manager=self.ingest_manager,
            category_manager=self.category_manager,
            quota_manager=self.quota_manager,
            sync_pipeline=self.sync_pipeline,
        )

        # 6) 周期任务（如 R2 周期备份，v0.3.0 起注册）。
        if r2_cfg.enabled and r2_cfg.backup_interval_sec > 0:
            self._backup_task = asyncio.create_task(
                self._periodic_backup(r2_cfg.backup_interval_sec)
            )

    async def _periodic_backup(self, interval_sec: int) -> None:
        """周期性触发 R2 同步备份任务的后台循环。"""
        logger.info(f"Background periodic backup scheduled every {interval_sec} seconds.")
        try:
            while True:
                await asyncio.sleep(interval_sec)
                if self.sync_pipeline is not None:
                    logger.info("Triggering periodic background backup to R2...")
                    await self.sync_pipeline.sync(SyncTargetKind.R2)
        except asyncio.CancelledError:
            logger.info("Background periodic backup task cancelled.")
        except Exception as e:
            logger.error(f"Error in background periodic backup: {e}")

    # ── 关闭：与构造顺序相反释放 ────────────────────────────────
    async def teardown(self) -> None:
        if self._backup_task is not None:
            self._backup_task.cancel()
            try:
                await self._backup_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._backup_task = None

        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None


__all__ = ["PluginInitializer"]
