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
from core.ask_progress import ProgressStore
from core.config import Config, merge_config_dicts
from core.domain.models import Collection, SyncTargetKind
from core.managers.category_manager import CategoryManager
from core.managers.ingest_manager import IngestManager
from core.managers.quota_manager import QuotaManager
from core.metrics import PerformanceTracker
from core.pipelines.sync_pipeline import SyncPipeline
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from core.repository.sync_targets.r2 import R2SyncTarget
from core.runtime_config import RuntimeConfigStore
from migrations.runner import run_migrations

if TYPE_CHECKING:
    from core.index_compatibility import IndexCompatibilityStore
    from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.vector_store.base import VectorStore

logger = logging.getLogger("PluginInitializer")


class PluginInitializer:
    """装配全部子系统并拥有其生命周期。"""

    def __init__(self, context: Any, raw_config: dict[str, Any], data_dir: Path) -> None:
        self._context = context
        self._data_dir = data_dir
        self._raw_config = raw_config
        self._runtime_config = RuntimeConfigStore(
            data_dir / "runtime_config.json",
            framework_persist_cb=self._astrbot_config_persist,
        )
        self._config = Config(self._runtime_config.merged_with(raw_config))
        self._exit_stack: AsyncExitStack | None = None
        self._backup_task: asyncio.Task[Any] | None = None
        self._web_runner: Any | None = None

        # 子系统句柄 —— 在 initialize() 中按依赖顺序赋值，供 event_handler / web 引用。
        self.source_store: SourceDocumentStore | None = None
        self.kb_reader: KnowledgeBaseReader | None = None
        self.api: KnowledgeRepositoryApi | None = None
        self.lightrag_registry: Any | None = None
        self.vector_store: VectorStore | None = None
        self.embedding_provider: EmbeddingProvider | None = None
        self.embedding_dimension: int | None = None
        self.embedding_fingerprint: str | None = None
        self.index_compatibility: IndexCompatibilityStore | None = None
        self.retrieval_orchestrator: RetrievalOrchestrator | None = None
        self.agent_enabled: bool = False
        self.metrics: PerformanceTracker = PerformanceTracker()
        self.progress_store: ProgressStore = ProgressStore()

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
        existing_collections = {
            collection.name for collection in await self.source_store.list_collections()
        }
        if source_cfg.default_collection not in existing_collections:
            await self.source_store.upsert_collection(
                Collection(
                    name=source_cfg.default_collection,
                    description="Default collection",
                )
            )
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
        graph_cfg = self._config.get_graph_config()

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

        # 4.5) 官方 LightRAG Core 是唯一图谱实现。
        from core.adapters.llm import LLMAdapter

        llm_adapter = LLMAdapter(self._context)

        # 4.6) 构造共享 Embedding，并用真实探针维度装配 Milvus/LightRAG。
        vdb_cfg = self._config.get_vector_db_config()
        embedding_cfg = self._config.get_embedding_config()
        from core.index_compatibility import IndexCompatibilityStore, embedding_fingerprint

        self.index_compatibility = IndexCompatibilityStore(
            self._data_dir / "index_compatibility.json"
        )
        if vdb_cfg.backend == "milvus" or graph_cfg.enabled:
            from core.repository.embedding.factory import EmbeddingProviderFactory

            try:
                self.embedding_provider = EmbeddingProviderFactory.create_provider(
                    self._config, db_dir=str(self._data_dir)
                )
                probe = await self.embedding_provider.embed_query(
                    "knowledge-repository-dimension-probe"
                )
                if not probe:
                    raise RuntimeError("Embedding dimension probe returned an empty vector")
                self.embedding_dimension = len(probe)
                self.embedding_fingerprint = embedding_fingerprint(
                    embedding_cfg, self.embedding_dimension
                )
                self._config.set_embedding_dimension(self.embedding_dimension)
            except NotImplementedError as exc:
                logger.warning(
                    "Embedding provider 初始化失败，图谱/向量检索功能已禁用：%s", exc
                )
                self._config.add_diagnostic(f"Embedding provider unavailable: {exc}")
                self.embedding_provider = None
            except Exception as exc:
                logger.error(
                    "Embedding provider 初始化异常，图谱/向量检索功能已禁用：%s", exc, exc_info=True
                )
                self._config.add_diagnostic(f"Embedding dimension probe failed: {exc}")
                self.embedding_provider = None

        if (
            vdb_cfg.backend == "milvus"
            and self.embedding_provider is not None
            and self.embedding_dimension is not None
        ):
            from core.repository.vector_store.milvus_lite import (
                MilvusLiteVectorStore,
                MilvusSchemaMismatchError,
            )

            milvus_path = self._data_dir / vdb_cfg.db_filename
            is_new_index = not milvus_path.exists()
            try:
                milvus = MilvusLiteVectorStore(
                    db_path=str(milvus_path),
                    dim=self.embedding_dimension,
                )
                milvus.validate_schema()
                self.vector_store = milvus
                created_collection = bool(
                    getattr(milvus, "created_collection", is_new_index)
                )
                source_has_documents = bool(await self.source_store.list_documents())
                if (
                    created_collection
                    and source_has_documents
                    and self.embedding_fingerprint
                ):
                    self.index_compatibility.mark_milvus_incompatible(
                        "Milvus collection was recreated while SQLite contains documents."
                    )
                    self._config.add_diagnostic(
                        "Milvus collection is empty while SQLite contains documents; rebuild it."
                    )
                    await self._mark_all_documents_needs_reindex()
                elif created_collection and self.embedding_fingerprint:
                    self.index_compatibility.mark_milvus_compatible(
                        self.embedding_fingerprint
                    )
                elif (
                    self.embedding_fingerprint
                    and not self.index_compatibility.is_milvus_compatible(
                        self.embedding_fingerprint
                    )
                ):
                    self._config.add_diagnostic(
                        "Milvus index is incompatible with the active embedding; rebuild it."
                    )
                    await self._mark_all_documents_needs_reindex()
            except MilvusSchemaMismatchError as exc:
                logger.error(
                    "Milvus schema mismatch; retrieval is disabled until a full rebuild: %s",
                    exc,
                )
                self.index_compatibility.mark_milvus_incompatible(str(exc))
                self._config.add_diagnostic(str(exc))
                self.vector_store = milvus
                await self._mark_all_documents_needs_reindex()
            except Exception as exc:
                logger.error(
                    "Milvus initialization failed; AstrBot fallback remains active: %s", exc
                )
                self._config.add_diagnostic(f"Milvus unavailable: {exc}")
                self.vector_store = None

        # 4.6.5) 构造官方 LightRAG Core registry（按 collection 懒加载实例）。
        if (
            graph_cfg.enabled
            and self.embedding_provider is not None
            and self.embedding_dimension is not None
        ):
            from core.lightrag_core import LightRAGCoreRegistry

            self.lightrag_registry = LightRAGCoreRegistry(
                config=graph_cfg,
                data_dir=self._data_dir,
                llm_adapter=llm_adapter,
                embedding_provider=self.embedding_provider,
                embedding_dim=self.embedding_dimension,
                max_token_size=embedding_cfg.max_token_size,
                embedding_model=embedding_cfg.model,
            )
            incompatible_lightrag = [
                collection
                for collection in self.lightrag_registry.existing_collections()
                if not self.embedding_fingerprint
                or not self.index_compatibility.is_lightrag_compatible(
                    collection, self.embedding_fingerprint
                )
            ]
            if incompatible_lightrag:
                self._config.add_diagnostic(
                    "LightRAG indexes are incompatible with the active embedding; "
                    "rebuild affected collections."
                )
        elif graph_cfg.enabled and self.embedding_provider is None:
            logger.warning(
                "graph.enabled=true 但 embedding provider 不可用，LightRAG Core 已跳过。"
                " 请在配置中将 embedding.provider 改为 'local' 或 'external'。"
            )

        # 4.7) 构造统一检索编排器 (RetrievalOrchestrator)
        from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator

        self.retrieval_orchestrator = RetrievalOrchestrator(
            source_store=self.source_store,
            kb_reader=self.kb_reader,
            config=self._config,
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            lightrag_registry=self.lightrag_registry,
            index_compatibility=self.index_compatibility,
            embedding_fingerprint=self.embedding_fingerprint,
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
            lightrag_registry=self.lightrag_registry,
            config=self._config,
            config_persist=self._persist_config_value,
            llm_adapter=llm_adapter,
            managed_documents_dir=self._data_dir / "documents",
            vector_store=self.vector_store,
            embedding_provider=self.embedding_provider,
            retrieval_orchestrator=self.retrieval_orchestrator,
            metrics=self.metrics,
            progress_store=self.progress_store,
            index_compatibility=self.index_compatibility,
            embedding_fingerprint=self.embedding_fingerprint,
        )

        # 6) 周期任务（如 R2 周期备份，v0.3.0 起注册）。
        if r2_cfg.enabled and r2_cfg.backup_interval_sec > 0:
            self._backup_task = asyncio.create_task(
                self._periodic_backup(r2_cfg.backup_interval_sec)
            )

        # 7) 独立 Web 控制台（enabled=true 时自动启动，端口/认证由 web_console 配置管辖）。
        web_cfg = self._config.get_web_console_config()
        if web_cfg.enabled:
            await self._start_web_console(web_cfg)

    def _persist_config_value(self, section: str, key: str, value: object) -> None:
        self._runtime_config.set_value(section, key, value)

    def _astrbot_config_persist(self, override: dict[str, Any]) -> None:
        """尝试将合并后的运行时配置写回 AstrBot 原生配置系统。"""
        if self._context is None:
            return
        merged = merge_config_dicts(self._raw_config, override)
        # 自适应调用 AstrBot 原生配置存储与更新 API
        for method_name in ("save_config", "update_config", "persist_config"):
            save_cb = getattr(self._context, method_name, None)
            if callable(save_cb):
                try:
                    save_cb(merged)
                    self._raw_config = merged
                    logger.info(
                        f"Successfully persisted runtime config back via context.{method_name}"
                    )
                    return
                except Exception as e:
                    logger.debug(f"Attempt via context.{method_name} failed: {e}")

    async def _start_web_console(self, web_cfg: Any) -> None:
        """启动插件独立 Web 控制台（aiohttp + Next.js 静态文件）。"""
        from aiohttp import web as aiohttp_web

        from web.server import build_app

        if not web_cfg.password:
            logger.error(
                "web_console.password 为空，Web 控制台未启动。请在配置中设置密码后重启插件。"
            )
            return

        plugin_root = Path(__file__).parent.parent
        static_dir = plugin_root / "pages"
        upload_dir = self._data_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        try:
            app = build_app(
                api=self.api,
                static_dir=static_dir,
                upload_dir=upload_dir,
                auth_required=True,
                username=web_cfg.username,
                password=web_cfg.password,
            )
            runner = aiohttp_web.AppRunner(app)
            await runner.setup()
            site = aiohttp_web.TCPSite(runner, web_cfg.host, web_cfg.port)
            await site.start()
            self._web_runner = runner
            logger.info(f"Web 控制台已启动：http://{web_cfg.host}:{web_cfg.port}")
        except OSError as e:
            logger.error(f"Web 控制台启动失败（端口 {web_cfg.port} 可能被占用）：{e}")
        except Exception as e:
            logger.error(f"Web 控制台启动异常：{e}")

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

    async def _mark_all_documents_needs_reindex(self) -> None:
        if self.source_store is None:
            return
        for doc in await self.source_store.list_documents():
            if not doc.needs_reindex:
                doc.needs_reindex = True
                try:
                    await self.source_store.update_document(doc)
                except Exception as exc:
                    logger.error("Failed to mark document %s for reindex: %s", doc.doc_id, exc)

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

        if self._web_runner is not None:
            try:
                await self._web_runner.cleanup()
            except Exception as e:
                logger.warning(f"Web 控制台关闭异常：{e}")
            self._web_runner = None

        if self.lightrag_registry is not None:
            try:
                await self.lightrag_registry.close()
            except Exception as e:
                logger.error(f"Failed to close LightRAG Core on teardown: {e}")
            self.lightrag_registry = None

        if self.vector_store is not None:
            try:
                await self.vector_store.close()
            except Exception as e:
                logger.error(f"Failed to close vector store on teardown: {e}")
            self.vector_store = None

        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None


__all__ = ["PluginInitializer"]
