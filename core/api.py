"""业务门面（框架无关，见 api.README.md 与 ../ARCHITECTURE.md §7）。

为 WebUI / CLI / 其它入口提供统一的纯业务调用面：不含 HTTP 概念，只收发普通数据/domain 对象。
`web/` 把请求翻译后委派到这里，再把返回包装成 HTTP 响应。

落地策略：本门面当前直接依赖仓储端口（source_store/kb_reader/sync_targets）。后续版本引入
managers/pipelines（ingest/category/sync/quota）后，对应写操作改为委派到 manager，门面签名不变。
依赖经构造器注入，自身不创建依赖（装配在组合根）。
"""

from __future__ import annotations

import asyncio
import html
import inspect
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.api_capabilities import CapabilitiesApiMixin
from core.config import (
    CONSEQUENCE_REBUILD,
    CONSEQUENCE_RESTART,
    api_writable_keys,
    change_consequence,
    structural_keys,
)
from core.domain.models import (
    Collection,
    ConsoleScopeState,
    DocumentOrigin,
    ScopedNote,
    SourceDocument,
    SyncTargetKind,
)
from core.ingest_job import (
    INGEST_ERROR,
    INGEST_STAGE_INDEXING,
    INGEST_SUCCESS,
    IngestJob,
)
from core.milvus_build import (
    MILVUS_BUILD_ERROR,
    MILVUS_BUILD_PARTIAL,
    MILVUS_BUILD_RUNNING,
    MILVUS_BUILD_STAGE_CLEANING,
    MILVUS_BUILD_STAGE_FINALIZING,
    MILVUS_BUILD_STAGE_INDEXING,
    MILVUS_BUILD_SUCCESS,
    MilvusBuildJob,
)
from core.pipelines.retrieval_orchestrator import RetrievalScope
from core.zotero_sync_job import (
    ZOTERO_SYNC_ERROR,
    ZOTERO_SYNC_PARTIAL,
    ZOTERO_SYNC_RUNNING,
    ZOTERO_SYNC_SUCCESS,
    ZoteroSyncJob,
)

logger = logging.getLogger("KnowledgeRepositoryApi")

SYSTEM_COLLECTION_UNCATEGORIZED = "_uncategorized"
MILVUS_INDEX_MAX_ATTEMPTS = 3
MILVUS_INDEX_RETRY_DELAYS = (0.5, 1.5)
ZOTERO_SERVER_KEY_SECRET = "zotero.server_api_key"
ACTIVE_BUILD_STATUSES = {"queued", "running", "pause_requested", "paused"}
TERMINAL_BUILD_STATUSES = {"success", "partial_failure", "error", "interrupted"}
ZOTERO_SYNC_TERMINAL_VISIBLE_SECONDS = 30.0


def _build_scope(scope_type: str, scope_key: str, scope_library_id: str) -> RetrievalScope | None:
    """构造检索作用域；scope_type 为空返回 None（无 doc 级硬过滤）。"""
    if not scope_type:
        return None
    return RetrievalScope(
        scope_type=scope_type, scope_key=scope_key, library_id=scope_library_id
    )


def _serialize_deep_thinking(outcome: Any) -> dict:
    """把 DeepThinkingOutcome 序列化为前端可渲染的「思考过程」字典。

    与 orchestrator 实时进度的 live_detail 共用 deep_thinking_view 的底层序列化，
    从根上保证「实时进度格式 == 最终 thinking_trace 格式」。
    """
    from core.pipelines.deep_thinking_view import serialize_outcome

    return serialize_outcome(outcome)


def _uses_chinese(text: str) -> bool:
    """粗略判断文本是否包含中文，用于 answer_language=auto 的警告语言。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _deep_warning_prefix(outcome: Any, answer_language: str, question: str) -> str:
    """为 deep thinking 证据不足/未验证答案生成正文警告前缀。"""
    zh = answer_language == "zh" or (answer_language == "auto" and _uses_chinese(question))
    if getattr(outcome, "degraded", False):
        reason = str(getattr(outcome, "degraded_reason", "") or "").strip()
        if zh:
            reason_part = f"原因：{reason}。" if reason else ""
            return (
                f"**提示：深度思考证据不足，已降级为基线证据。** {reason_part}"
                "以下回答仅基于当前检索片段，可能不完整。\n\n"
            )
        reason_part = f" Reason: {reason}." if reason else ""
        return (
            "**Note: Deep Thinking found insufficient evidence and fell back to baseline "
            "evidence.**"
            f"{reason_part} The answer below is limited to the currently retrieved "
            "passages and may be incomplete.\n\n"
        )
    missing = [
        str(item).strip()
        for item in (getattr(outcome, "verify_missing", []) or [])
        if str(item).strip()
    ]
    notes = [
        str(item).strip()
        for item in (getattr(outcome, "verify_notes", []) or [])
        if str(item).strip()
    ]
    if getattr(outcome, "verified", False):
        # 通过校验：含「有据推断」软项时给一行温和说明（不报数字、不全盘否定）；否则无前缀。
        if not notes:
            return ""
        if zh:
            return (
                "**提示：部分结论为基于证据的有限推断，已在文中标注。** "
                "详见下方「思考过程」。\n\n"
            )
        return (
            "**Note: Some conclusions are limited, evidence-grounded inferences "
            "(flagged inline).** See “Thinking process” below.\n\n"
        )
    if zh:
        if missing:
            return (
                "**提示：以下回答未完全通过证据校验。** "
                f"共 {len(missing)} 项缺失或未被支撑，详见下方「思考过程」。"
                "请将后文视为基于当前证据的有限回答。\n\n"
            )
        return (
            "**提示：以下回答尚未完成证据校验。** "
            "请将后文视为基于当前证据的有限回答。\n\n"
        )
    if missing:
        return (
            "**Note: The answer below did not fully pass evidence verification.** "
            f"{len(missing)} point(s) are missing or unsupported; see “Thinking process” below. "
            "Treat the rest as a limited answer based on the current evidence.\n\n"
        )
    return (
        "**Note: The answer below has not completed evidence verification.** "
        "Treat the rest as a limited answer based on the current evidence.\n\n"
    )


def _apply_deep_answer_warning(
    answer: str, outcome: Any | None, answer_language: str, question: str
) -> str:
    """deep thinking 证据不足/未验证时，把警告写进答案正文。"""
    if outcome is None or not answer:
        return answer
    prefix = _deep_warning_prefix(outcome, answer_language, question)
    return f"{prefix}{answer}" if prefix else answer


def _note_html(content: str) -> str:
    """把纯文本笔记转为 Zotero note 可接受的基础 HTML。"""
    escaped = html.escape(content.strip())
    paragraphs = [p for p in escaped.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    return "".join(f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in paragraphs)


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def _scoped_note_dict(note: ScopedNote) -> dict[str, Any]:
    """领域笔记转前端稳定 JSON shape。"""
    created_at = note.created_at.isoformat() if note.created_at else None
    updated_at = note.updated_at.isoformat() if note.updated_at else None
    return {
        "id": note.id,
        "scope_type": note.scope_type,
        "scope_key": note.scope_key,
        "doc_id": note.doc_id,
        "collection_name": note.collection_name,
        "content": note.content,
        "body": note.content,
        "note_html": note.note_html,
        "library_id": note.library_id,
        "parent_item_key": note.parent_item_key,
        "parent_attachment_key": note.parent_attachment_key,
        "zotero_note_key": note.zotero_note_key,
        "zotero_version": note.zotero_version,
        "tags": note.tags,
        "collections": note.collections,
        "relations": note.relations,
        "linked": note.linked,
        "source": note.source,
        "chat_conversation_id": note.chat_conversation_id,
        "chat_message_id": note.chat_message_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "raw_zotero_json": note.raw_zotero_json,
    }


def _console_scope_state_dict(state: ConsoleScopeState) -> dict[str, Any]:
    return {
        "scope_type": state.scope_type,
        "scope_key": state.scope_key,
        "selected_collection": state.selected_collection,
        "selected_doc_id": state.selected_doc_id,
        "note_doc_id": state.note_doc_id,
        "right_panel": state.right_panel,
        "reading_mode": state.reading_mode,
        "payload": state.payload,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


def _assert_doc_writable(doc: SourceDocument) -> None:
    """service 层只读强制：Zotero 同步来源禁止用户侧修改/删除（review #7）。"""
    if doc.read_only or doc.origin is DocumentOrigin.ZOTERO:
        raise ReadOnlyError(
            f"文档 {doc.doc_id} 来自 Zotero 同步，处于只读状态；"
            "请在 Zotero 中修改后重新同步，或切换同步模式。"
        )

if TYPE_CHECKING:
    from collections.abc import Callable

    from core.adapters.llm import LLMAdapter
    from core.ask_progress import ProgressStore
    from core.config import Config
    from core.domain.models import DocumentChunk, QuotaUsage
    from core.index_compatibility import IndexCompatibilityStore
    from core.lightrag_core import BuildJob, LightRAGCoreRegistry
    from core.managers.base import BaseCategoryManager, BaseIngestManager, BaseQuotaManager
    from core.metrics import PerformanceTracker
    from core.pipelines.deep_thinking_orchestrator import DeepThinkingOrchestrator
    from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
    from core.pipelines.sync_pipeline import SyncPipeline
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.reranker.base import Reranker
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.sync_targets.base import SyncTarget
    from core.repository.vector_store.base import VectorStore
    from core.secret_store import EncryptedSecretStore


def _get_astrbot_persona_prompt(context: Any) -> str:
    """从 AstrBot context 中动态检索当前的 persona prompt。"""
    if context is None:
        return ""
    try:
        get_active_prompt = getattr(context, "get_active_persona_prompt", None)
        if callable(get_active_prompt):
            return str(get_active_prompt())

        active_persona = getattr(context, "active_persona", None)
        if active_persona is not None:
            prompt = getattr(active_persona, "prompt", None) or getattr(
                active_persona, "system_prompt", None
            )
            if prompt:
                return str(prompt)

        get_active_persona = getattr(context, "get_active_persona", None)
        if callable(get_active_persona):
            persona_obj = get_active_persona()
            if persona_obj:
                prompt = getattr(persona_obj, "prompt", None) or getattr(
                    persona_obj, "system_prompt", None
                )
                if prompt:
                    return str(prompt)

        config_obj = getattr(context, "config", None)
        if config_obj:
            get_cfg = getattr(config_obj, "get", None)
            if callable(get_cfg):
                p = get_cfg("persona") or get_cfg("active_persona")
                if isinstance(p, dict):
                    return str(p.get("prompt") or p.get("system_prompt") or "")
                elif isinstance(p, str):
                    return p
    except Exception as e:
        logger.warning(f"Failed to fetch AstrBot persona dynamically: {e}")
    return ""


class LightRAGNotReadyError(RuntimeError):
    def __init__(self, collection: str, reason: str, *, build_available: bool = False) -> None:
        super().__init__(reason)
        self.collection = collection
        self.reason = reason
        self.build_available = build_available


class HighPrecisionQueryError(RuntimeError):
    def __init__(self, collection: str, reason: str) -> None:
        super().__init__(reason)
        self.collection = collection
        self.reason = reason


class ReadOnlyError(RuntimeError):
    """Zotero 同步来源（只读）被尝试修改/删除时抛出。

    本轮单向同步保证：origin=zotero 的文档/集合/标签在文档系统中只读，
    仅 Zotero Pull 这一特权服务可变更；用户侧 delete/classify/移动一律拒绝。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _extract_raw_doc_text(doc: SourceDocument) -> str | None:
    """读取制品包内的干净 Markdown（clean.md），供 LightRAG 使用（避免双重切块）。

    与 Milvus 路径（预切 chunk）完全分离：LightRAG 拿到连续的 clean.md 文本后由其内部切块器
    决定粒度，且 clean.md 已由 PyMuPDF4LLM 清洗（无可见页码/页眉页脚噪声），实体边界更干净。

    降级策略：制品包缺 markdown_rel_path / clean.md 不存在 → 返回 None，
    由调用方回退到 chunk 拼接路径。不再回退 fitz 手写抽取。
    """
    from pathlib import Path

    rel = getattr(doc, "markdown_rel_path", "") or ""
    if not rel:
        return None
    md_path = Path(doc.file_path).parent / rel
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


class KnowledgeRepositoryApi(CapabilitiesApiMixin):
    """知识库应用的业务门面。依赖经构造器注入，自身不创建依赖（装配在组合根）。

    公共方法面按职责拆分到 mixin（如 CapabilitiesApiMixin 承载能力/依赖管理），
    本类负责 __init__ 装配与文档/检索/图谱/同步核心方法及其共享私有助手。
    """

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        kb_reader: KnowledgeBaseReader,
        sync_targets: dict[SyncTargetKind, SyncTarget] | None = None,
        ingest_manager: BaseIngestManager | None = None,
        category_manager: BaseCategoryManager | None = None,
        quota_manager: BaseQuotaManager | None = None,
        sync_pipeline: SyncPipeline | None = None,
        lightrag_registry: LightRAGCoreRegistry | None = None,
        config: Config | None = None,
        config_persist: Callable[[str, str, object], None] | None = None,
        llm_adapter: LLMAdapter | None = None,
        managed_documents_dir: Path | None = None,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
        deep_thinking_orchestrator: DeepThinkingOrchestrator | None = None,
        reranker: Reranker | None = None,
        metrics: PerformanceTracker | None = None,
        progress_store: ProgressStore | None = None,
        index_compatibility: IndexCompatibilityStore | None = None,
        embedding_fingerprint: str | None = None,
        secret_store: EncryptedSecretStore | None = None,
        reload_callback: Callable[[], Any] | None = None,
    ) -> None:
        self._source_store = source_store
        self._kb_reader = kb_reader
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._retrieval_orchestrator = retrieval_orchestrator
        self._deep_thinking_orchestrator = deep_thinking_orchestrator
        self._reranker = reranker  # default 路径研究召回的重排器（与 deep_thinking 共享同一实例）
        self._sync_targets = sync_targets or {}
        self._ingest_manager = ingest_manager
        self._category_manager = category_manager
        self._quota_manager = quota_manager
        self._sync_pipeline = sync_pipeline
        self._lightrag_registry = lightrag_registry
        self._graph_build_jobs: dict[str, BuildJob] = {}
        self._build_pause_events: dict[str, asyncio.Event] = {}
        self._build_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        # Milvus 向量库重建：全局单任务的进度快照 + 后台任务句柄（无暂停）。
        self._milvus_build_job: MilvusBuildJob | None = None
        self._milvus_build_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._config = config
        self._config_persist = config_persist
        self._llm_adapter = llm_adapter
        self._managed_documents_dir = managed_documents_dir
        self._metrics = metrics
        self._progress_store = progress_store
        self._index_compatibility = index_compatibility
        self._embedding_fingerprint = embedding_fingerprint
        self._secret_store = secret_store
        # 软重启回调（组合根注入 PluginInitializer.reload；为空表示当前环境不支持程序化重启）。
        self._reload_callback = reload_callback
        # Zotero 同步管线（组合根在 api 构造后注入，避免回调循环依赖）。
        self._zotero_pipeline: Any | None = None
        self._last_zotero_sync: dict[str, Any] = {}
        # Zotero Pull：全局单任务的进度快照 + 后台任务句柄（与 Milvus 重建同构）。
        self._zotero_sync_job: ZoteroSyncJob | None = None
        self._zotero_sync_task: asyncio.Task | None = None  # type: ignore[type-arg]
        # 文档上传/摄入：最近一次摄入的进度快照（供统一进度面板，latest-wins）。
        self._ingest_job: IngestJob | None = None

    def attach_zotero_pipeline(self, pipeline: Any) -> None:
        """组合根注入 ZoteroSyncPipeline（其回调引用本 api 的索引/LRAG 助手）。"""
        self._zotero_pipeline = pipeline

    # ── 集合（分类）────────────────────────────────────────────

    async def list_collections(self) -> list[Collection]:
        """列出全部集合。"""
        return await self._source_store.list_collections()

    async def list_titles_by_collection(self) -> dict[str, list[str]]:
        """返回 {collection_name: [title, ...]}，供 research skill 的范围解析使用。

        复用 list_documents() 的 (collection, title)，按主集合名分组；纯读、零越层。
        """
        result: dict[str, list[str]] = {}
        docs = await self._source_store.list_documents()
        for doc in docs:
            col = doc.collection or ""
            if not col:
                continue
            result.setdefault(col, []).append(doc.title)
        return result

    def is_reranker_active(self) -> bool:
        """default 研究路径是否有可用的真实 cross-encoder 重排器（非 passthrough）。"""
        return self._reranker is not None and not self._reranker.is_passthrough

    async def create_collection(self, name: str, description: str = "") -> None:
        """新建或更新集合（按 name upsert）。v0.3.0 起委派 category_manager。"""
        if self._category_manager:
            await self._category_manager.create_collection(name, description)
        else:
            await self._source_store.upsert_collection(
                Collection(name=name, description=description, created_at=_now())
            )

    async def _ensure_system_collections(self) -> None:
        """确保系统集合（_uncategorized 等）存在，幂等。"""
        await self._source_store.upsert_collection(
            Collection(
                name=SYSTEM_COLLECTION_UNCATEGORIZED,
                description="未归档文档（系统集合，不可删除）",
                created_at=_now(),
            )
        )

    async def delete_collection(self, name: str) -> bool:
        """删除集合。非空集合的文档将迁入 _uncategorized 系统集合。返回 False 表示 name 不存在。

        只读保护：Zotero 同步来源的集合（origin=zotero）禁止用户侧删除，仅允许删除手动创建的集合。
        """
        if name == SYSTEM_COLLECTION_UNCATEGORIZED:
            raise ValueError(f"系统集合 '{SYSTEM_COLLECTION_UNCATEGORIZED}' 不可删除。")
        existing = {c.name: c for c in await self._source_store.list_collections()}
        target = existing.get(name)
        if target is not None and target.origin is DocumentOrigin.ZOTERO:
            raise ReadOnlyError(
                f"集合 '{name}' 来自 Zotero 同步，处于只读状态，不能手动删除。"
            )

        await self._ensure_system_collections()
        moving_docs = await self._source_store.list_documents(collection=name)
        if self._lightrag_registry is not None and self._lightrag_registry.has_workspace(name):
            try:
                await self._lightrag_registry.reset_workspace(name)
            except Exception as exc:
                logger.error("Failed to remove LightRAG workspace %s: %s", name, exc)
        if self._index_compatibility is not None:
            self._index_compatibility.remove_lightrag_collection(name)
        await self._source_store.move_documents_to_collection(name, SYSTEM_COLLECTION_UNCATEGORIZED)
        for doc in moving_docs:
            await self._mark_lightrag_pending(doc.doc_id, SYSTEM_COLLECTION_UNCATEGORIZED)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus":
                if self._milvus_index_is_compatible():
                    try:
                        assert self._vector_store is not None
                        await self._vector_store.delete_collection(name)
                        for doc in moving_docs:
                            await self._sync_milvus_collection_move(
                                doc.doc_id, SYSTEM_COLLECTION_UNCATEGORIZED
                            )
                    except Exception as exc:
                        self._mark_milvus_incompatible(
                            f"Milvus collection delete failed: {exc}"
                        )
                        for doc in moving_docs:
                            await self._mark_document_needs_reindex(doc.doc_id)
                else:
                    for doc in moving_docs:
                        await self._mark_document_needs_reindex(doc.doc_id)

        if self._category_manager:
            return await self._category_manager.delete_collection(name)
        return await self._source_store.delete_collection(name)

    # ── 本地集合树编辑（仅 LOCAL 可改；Zotero 只读）─────────────

    async def _assert_name_unique_under_parent(
        self, name: str, parent_key: str, *, exclude_key: str = ""
    ) -> None:
        for c in await self._source_store.list_collections():
            if (
                c.parent_key == parent_key
                and c.name == name
                and c.coll_key != exclude_key
            ):
                raise ValueError(f"同级已存在同名集合：{name}")

    async def _assert_local_editable(self, coll_key: str) -> Collection:
        col = await self._source_store.get_collection(coll_key)
        if col is None:
            raise ValueError(f"集合不存在：{coll_key}")
        if col.origin is DocumentOrigin.ZOTERO:
            raise ReadOnlyError(f"集合 '{col.name}' 来自 Zotero 同步，只读，不能编辑。")
        if col.name == SYSTEM_COLLECTION_UNCATEGORIZED:
            raise ValueError(f"系统集合 '{SYSTEM_COLLECTION_UNCATEGORIZED}' 不可编辑。")
        return col

    async def create_subcollection(
        self, name: str, parent_key: str = "", description: str = ""
    ) -> str:
        """新建本地集合（parent_key 为空=顶层）。返回新集合的 coll_key。"""
        name = name.strip()
        if not name:
            raise ValueError("集合名不能为空。")
        if parent_key:
            parent = await self._source_store.get_collection(parent_key)
            if parent is None:
                raise ValueError(f"父集合不存在：{parent_key}")
            if parent.origin is DocumentOrigin.ZOTERO:
                raise ReadOnlyError("不能在 Zotero 只读集合下创建子集合。")
        await self._assert_name_unique_under_parent(name, parent_key)
        col = Collection(
            name=name,
            description=description,
            parent_key=parent_key,
            created_at=_now(),
            origin=DocumentOrigin.LOCAL,
        )
        await self._source_store.upsert_collection(col)
        return col.coll_key

    async def rename_collection(self, coll_key: str, new_name: str) -> None:
        """重命名本地集合（同 parent 下唯一）。"""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("集合名不能为空。")
        col = await self._assert_local_editable(coll_key)
        await self._assert_name_unique_under_parent(
            new_name, col.parent_key, exclude_key=coll_key
        )
        col.name = new_name
        await self._source_store.upsert_collection(col)

    async def move_collection(self, coll_key: str, new_parent_key: str = "") -> None:
        """移动本地集合到新父级（new_parent_key 为空=提升为顶层）。防环 + 只读校验。"""
        col = await self._assert_local_editable(coll_key)
        if new_parent_key:
            if new_parent_key == coll_key:
                raise ValueError("不能把集合移动到自身下。")
            parent = await self._source_store.get_collection(new_parent_key)
            if parent is None:
                raise ValueError(f"目标父集合不存在：{new_parent_key}")
            if parent.origin is DocumentOrigin.ZOTERO:
                raise ReadOnlyError("不能移动到 Zotero 只读集合下。")
            descendants = await self._source_store.get_local_collection_descendants(coll_key)
            if new_parent_key in descendants:
                raise ValueError("不能把集合移动到其自身的后代下（会形成环）。")
        await self._assert_name_unique_under_parent(
            col.name, new_parent_key, exclude_key=coll_key
        )
        col.parent_key = new_parent_key
        await self._source_store.upsert_collection(col)

    async def delete_collection_by_key(self, coll_key: str) -> bool:
        """按 coll_key 删除本地集合：子集合提升到其父级，本级文档归属迁入 _uncategorized。

        只读保护：Zotero 来源集合禁止删除。返回 False 表示 coll_key 不存在。
        """
        col = await self._source_store.get_collection(coll_key)
        if col is None:
            return False
        await self._assert_local_editable(coll_key)

        await self._ensure_system_collections()
        uncategorized = await self._source_store.get_collection_by_name(
            SYSTEM_COLLECTION_UNCATEGORIZED
        )
        assert uncategorized is not None

        # 1) 子集合提升到被删节点的父级。
        for child in await self._source_store.list_collections():
            if child.parent_key == coll_key:
                child.parent_key = col.parent_key
                await self._source_store.upsert_collection(child)

        # 2) 本级文档：移除该归属；若文档因此无归属则落入 _uncategorized。
        members = await self._source_store.list_documents_by_collection_key(
            coll_key, descendants=False
        )
        for doc in members:
            keys = [k for k in (doc.collection_keys or []) if k != coll_key]
            if not keys:
                keys = [uncategorized.coll_key]
                if doc.collection == col.name:
                    doc.collection = SYSTEM_COLLECTION_UNCATEGORIZED
                    await self._source_store.update_document(doc)
                    await self._mark_lightrag_pending(
                        doc.doc_id, SYSTEM_COLLECTION_UNCATEGORIZED
                    )
            await self._source_store.set_document_collections(doc.doc_id, keys)

        # 3) 清理该集合 name 关联的 LightRAG workspace（与既有按 name 清理一致）。
        if self._lightrag_registry is not None and self._lightrag_registry.has_workspace(col.name):
            try:
                await self._lightrag_registry.reset_workspace(col.name)
            except Exception as exc:
                logger.error("Failed to remove LightRAG workspace %s: %s", col.name, exc)
        if self._index_compatibility is not None:
            self._index_compatibility.remove_lightrag_collection(col.name)

        return await self._source_store.delete_collection_by_key(coll_key)

    # ── 文档（管理）────────────────────────────────────────────

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        """列出文档，可按集合与单标签过滤（AND）。"""
        return await self._source_store.list_documents(collection=collection, tag=tag)

    async def list_documents_by_collection_key(
        self, coll_key: str, *, descendants: bool = False
    ) -> list[SourceDocument]:
        """按 coll_key 列出归属文档（descendants=False 仅本级，供 DocumentsPanel）。"""
        return await self._source_store.list_documents_by_collection_key(
            coll_key, descendants=descendants
        )

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        """取单个文档；不存在返回 None。"""
        return await self._source_store.get_document(doc_id)

    async def list_document_chunks(self, doc_id: str) -> list[DocumentChunk]:
        """列出单个文档的本地文本分块，供管理端展示摘要统计。"""
        chunks = await self._source_store.list_chunks(doc_id)
        return await self._ensure_document_chunks_current(doc_id, chunks)

    async def get_document_markdown_content(self, doc_id: str) -> str | None:
        """读取文档制品包中的 clean.md；文档不存在返回 None。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return None
        rel_path = doc.markdown_rel_path or "clean.md"
        artifact_path = self._resolve_document_artifact_path(doc, rel_path)
        if artifact_path is None:
            raise FileNotFoundError(f"Markdown artifact not found for {doc_id}: {rel_path}")
        return await asyncio.to_thread(artifact_path.read_text, encoding="utf-8")

    async def list_document_annotations(self, doc_id: str) -> list[dict[str, Any]] | None:
        """经 Zotero Local API 只读列出某文档 PDF attachment 的 annotations。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return None
        if doc.origin is not DocumentOrigin.ZOTERO or not doc.attachment_key:
            return []

        from core.adapters.zotero import local_api

        port = local_api.DEFAULT_PORT
        if self._config is not None:
            port = self._config.get_zotero_sync_config().api_port
        client = local_api.ZoteroLocalApiClient(port=port)
        try:
            items = await asyncio.to_thread(
                client.list_items, item_type="annotation", include="data"
            )
        except local_api.ZoteroLocalApiError as exc:
            logger.info("Zotero Local API annotations unavailable for %s: %s", doc_id, exc)
            return []

        annotations: list[dict[str, Any]] = []
        for item in items:
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if str(data.get("parentItem") or "") != doc.attachment_key:
                continue
            annotations.append(local_api.normalize_zotero_annotation(doc.doc_id, item))
        return annotations

    async def list_document_notes(self, doc_id: str) -> list[dict[str, Any]] | None:
        """列出某文档的本地笔记；字段兼容 Zotero note 形态。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return None
        notes = await self._source_store.list_scoped_notes("document", doc.doc_id)
        return [_scoped_note_dict(note) for note in notes]

    async def create_document_note(
        self,
        doc_id: str,
        content: str,
        *,
        linked: bool = False,
        source: str = "manual",
        chat_conversation_id: str = "",
        chat_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        """为文档创建一条 Zotero-shaped note；只写本地，不回写 Zotero。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return None
        body = content.strip()
        note_html = _note_html(body)
        parent_item = doc.zotero_item_key or doc.attachment_key
        raw_zotero_json = {
            "itemType": "note",
            "note": note_html,
            "tags": [{"tag": tag} for tag in doc.tags],
            "collections": [doc.collection] if doc.collection else [],
        }
        if parent_item:
            raw_zotero_json["parentItem"] = parent_item
        if doc.attachment_key:
            raw_zotero_json["parentAttachment"] = doc.attachment_key
        note = ScopedNote(
            id=uuid.uuid4().hex,
            scope_type="document",
            scope_key=doc.doc_id,
            content=body,
            note_html=note_html,
            doc_id=doc.doc_id,
            library_id=doc.library_id,
            parent_item_key=doc.zotero_item_key,
            parent_attachment_key=doc.attachment_key,
            tags=list(doc.tags),
            collections=[doc.collection] if doc.collection else [],
            linked=linked,
            source=source,
            chat_conversation_id=chat_conversation_id,
            chat_message_id=chat_message_id,
            created_at=_now(),
            updated_at=_now(),
            raw_zotero_json=raw_zotero_json,
        )
        await self._source_store.add_scoped_note(note)
        return _scoped_note_dict(note)

    async def update_document_note(
        self,
        doc_id: str,
        note_id: str,
        *,
        content: str | None = None,
        linked: bool | None = None,
    ) -> dict[str, Any] | None:
        """更新文档笔记；note 不属于该文档时返回 None。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return None
        note = await self._source_store.get_scoped_note(note_id)
        if note is None or note.scope_type != "document" or note.scope_key != doc.doc_id:
            return None
        if content is not None:
            note.content = content.strip()
            note.note_html = _note_html(note.content)
            note.raw_zotero_json = {**note.raw_zotero_json, "note": note.note_html}
        if linked is not None:
            note.linked = bool(linked)
        note.updated_at = _now()
        ok = await self._source_store.update_scoped_note(note)
        return _scoped_note_dict(note) if ok else None

    async def list_collection_notes(self, collection_name: str) -> list[dict[str, Any]] | None:
        """列出某集合的本地笔记。"""
        collections = {c.name: c for c in await self._source_store.list_collections()}
        if collection_name not in collections:
            return None
        notes = await self._source_store.list_scoped_notes("collection", collection_name)
        return [_scoped_note_dict(note) for note in notes]

    async def create_collection_note(
        self,
        collection_name: str,
        content: str,
        *,
        linked: bool = False,
        source: str = "manual",
        chat_conversation_id: str = "",
        chat_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        """为集合创建一条本地 note，collections 字段优先使用 Zotero collection key。"""
        collections = {c.name: c for c in await self._source_store.list_collections()}
        collection = collections.get(collection_name)
        if collection is None:
            return None
        body = content.strip()
        note_html = _note_html(body)
        collection_key = collection.zotero_collection_key or collection.name
        raw_zotero_json = {
            "itemType": "note",
            "note": note_html,
            "collections": [collection_key] if collection_key else [],
            "tags": [],
        }
        note = ScopedNote(
            id=uuid.uuid4().hex,
            scope_type="collection",
            scope_key=collection.name,
            content=body,
            note_html=note_html,
            collection_name=collection.name,
            collections=[collection_key] if collection_key else [],
            linked=linked,
            source=source,
            chat_conversation_id=chat_conversation_id,
            chat_message_id=chat_message_id,
            created_at=_now(),
            updated_at=_now(),
            raw_zotero_json=raw_zotero_json,
        )
        await self._source_store.add_scoped_note(note)
        return _scoped_note_dict(note)

    async def update_collection_note(
        self,
        collection_name: str,
        note_id: str,
        *,
        content: str | None = None,
        linked: bool | None = None,
    ) -> dict[str, Any] | None:
        """更新集合笔记；note 不属于该集合时返回 None。"""
        collections = {c.name for c in await self._source_store.list_collections()}
        if collection_name not in collections:
            return None
        note = await self._source_store.get_scoped_note(note_id)
        if note is None or note.scope_type != "collection" or note.scope_key != collection_name:
            return None
        if content is not None:
            note.content = content.strip()
            note.note_html = _note_html(note.content)
            note.raw_zotero_json = {**note.raw_zotero_json, "note": note.note_html}
        if linked is not None:
            note.linked = bool(linked)
        note.updated_at = _now()
        ok = await self._source_store.update_scoped_note(note)
        return _scoped_note_dict(note) if ok else None

    def _resolve_document_artifact_path(self, doc: SourceDocument, rel_path: str) -> Path | None:
        candidates: list[Path] = []
        if self._managed_documents_dir is not None:
            candidates.append(self._managed_documents_dir / doc.doc_id / rel_path)
        candidates.append(Path(doc.file_path).parent / rel_path)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    async def get_zotero_item_meta(self, library_id: str, item_key: str) -> dict[str, Any] | None:
        """返回某 Zotero 条目的归一化引用字段（供文档界面一等展示）。"""
        if not library_id or not item_key:
            return None
        item = await self._source_store.get_zotero_item(library_id, item_key)
        if item is None:
            return None
        return {
            "item_type": item.item_type,
            "creators": item.creators,
            "year": item.year,
            "venue": item.venue,
            "doi": item.doi,
            "url": item.url,
            "abstract": item.abstract,
        }

    async def get_lightrag_index_status(self, doc_id: str) -> dict[str, str] | None:
        return await self._source_store.get_lightrag_index_status(doc_id)

    async def register_document(
        self,
        *,
        title: str,
        file_path: str,
        content_type: str,
        size_bytes: int,
        content_hash: str,
        collection: str,
        tags: list[str] | None = None,
    ) -> str:
        """登记一个原件（生成 doc_id），返回 doc_id。

        预览级登记：仅写入源库元数据。v0.3.0 起本操作委派 ingest_manager（含 PyMuPDF 抽取/分块）。
        """
        auto_index = True
        if self._config:
            auto_index = self._config.get_vector_db_config().auto_index_enabled

        if self._ingest_manager:
            # 上传/摄入进度（供统一进度面板）：parsing → indexing → done。
            job = IngestJob(title=title)
            job.start()
            self._ingest_job = job
            logger.info("Document ingest start: title=%r collection=%r", title, collection)
            try:
                doc_id = await self._ingest_manager.ingest(
                    title=title,
                    file_path=file_path,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    collection=collection,
                    tags=tags,
                )
            except Exception as exc:
                job.recent_error = str(exc)
                job.finish(INGEST_ERROR)
                logger.error("Document ingest failed for %r: %s", title, exc, exc_info=True)
                raise
            job.doc_id = doc_id
            job.set_stage(INGEST_STAGE_INDEXING)
            # 同步写入 Milvus 向量库（仅在 auto_index_enabled=True 时执行）
            if auto_index and self._config and self._milvus_index_is_compatible():
                vdb = self._config.get_vector_db_config()
                if vdb.backend == "milvus" and self._vector_store and self._embedding_provider:
                    try:
                        await self._index_document_chunks_with_retry(
                            doc_id, collection, context="auto upload"
                        )
                        await self._clear_document_needs_reindex(doc_id)
                    except Exception as exc:
                        logger.error(
                            "Milvus indexing failed after retries for %s: %s",
                            doc_id,
                            exc,
                            exc_info=True,
                        )
                        await self._mark_document_needs_reindex(doc_id)
            elif not auto_index or (
                self._config
                and self._config.get_vector_db_config().backend == "milvus"
                and not self._milvus_index_is_compatible()
            ):
                await self._mark_document_needs_reindex(doc_id)
            await self._mark_lightrag_pending(doc_id, collection)
            job.finish(INGEST_SUCCESS)
            logger.info("Document ingest done: doc_id=%s title=%r", doc_id, title)
            return doc_id

        doc_id = uuid.uuid4().hex
        await self._source_store.add_document(
            SourceDocument(
                doc_id=doc_id,
                title=title,
                file_path=file_path,
                content_type=content_type,
                size_bytes=size_bytes,
                content_hash=content_hash,
                collection=collection,
                tags=list(tags or []),
                created_at=_now(),
                updated_at=_now(),
            )
        )
        await self._mark_lightrag_pending(doc_id, collection)
        return doc_id

    async def classify_document(
        self, doc_id: str, *, collection: str | None = None, tags: list[str] | None = None
    ) -> bool:
        """调整文档的集合/标签（手动分类）。返回 False 表示 doc_id 不存在。

        仅改动传入的维度：collection/tags 为 None 时该维度保持不变。
        """
        old_doc = await self._source_store.get_document(doc_id)
        if old_doc is None:
            return False
        _assert_doc_writable(old_doc)
        old_collection = old_doc.collection
        if (
            collection is not None
            and collection != old_collection
            and self._lightrag_registry
            and self._lightrag_index_is_compatible(old_collection)
        ):
            try:
                await self._lightrag_registry.delete_doc(old_doc.collection, doc_id)
                logger.info(
                    "LightRAG old workspace delete completed before moving doc %s from %s to %s",
                    doc_id,
                    old_collection,
                    collection,
                )
            except Exception as exc:
                logger.error("LightRAG document move delete failed for %s: %s", doc_id, exc)
                self._mark_lightrag_collection_incompatible(old_collection)

        if self._category_manager:
            updated = await self._category_manager.classify_document(
                doc_id, collection=collection, tags=tags
            )
            if updated and collection is not None and collection != old_collection:
                await self._mark_lightrag_pending(doc_id, collection)
                await self._sync_milvus_collection_move(doc_id, collection)
            return updated

        doc = old_doc
        if doc is None:
            return False
        if collection is not None:
            doc.collection = collection
        if tags is not None:
            doc.tags = tags
        doc.updated_at = _now()
        updated = await self._source_store.update_document(doc)
        if updated and collection is not None and collection != old_collection:
            await self._mark_lightrag_pending(doc_id, collection)
            await self._sync_milvus_collection_move(doc_id, collection)
        return updated

    async def update_document_meta(
        self, doc_id: str, meta: dict[str, Any]
    ) -> SourceDocument | None:
        """更新本地文档的富元数据（作者、年份、期刊、DOI 等）。

        仅限 origin=LOCAL 文档；Zotero 文档元数据由同步管道维护，不允许手动覆盖。
        返回 None 表示文档不存在或不可编辑。
        """
        doc = await self._source_store.get_document(doc_id)
        if doc is None or doc.origin != DocumentOrigin.LOCAL:
            return None
        allowed = {"title", "creators", "year", "venue", "doi", "url", "abstract"}
        cleaned: dict[str, Any] = {k: v for k, v in meta.items() if k in allowed}
        doc.local_meta = cleaned
        if "title" in cleaned and cleaned["title"]:
            doc.title = str(cleaned["title"])
        doc.updated_at = _now()
        await self._source_store.update_document(doc)
        return doc

    async def delete_document(self, doc_id: str) -> bool:
        """删除文档、图谱贡献、远端镜像和插件托管原件。

        只读保护：Zotero 同步来源（origin=zotero）禁止用户侧删除（仅 Zotero Pull 可变更）。
        """
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return False
        _assert_doc_writable(doc)

        chunks = await self._source_store.list_chunks(doc_id)
        if self._lightrag_registry is not None and self._lightrag_index_is_compatible(
            doc.collection
        ):
            try:
                await self._lightrag_registry.delete_doc(doc.collection, doc_id)
            except Exception as exc:
                logger.error("LightRAG document delete failed for %s: %s", doc_id, exc)
                self._mark_lightrag_collection_incompatible(doc.collection)
        records = [
            record
            for record in await self._source_store.list_sync_records()
            if record.doc_id == doc_id and record.remote_ref
        ]
        for record in records:
            target = self._sync_targets.get(record.target)
            if target is None:
                continue
            try:
                await target.delete(record.remote_ref or "")
            except Exception as exc:
                logger.warning("Failed to delete remote mirror %s: %s", record.remote_ref, exc)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus" and self._milvus_index_is_compatible():
                chunk_ids = [c.chunk_id for c in chunks]
                if chunk_ids:
                    try:
                        assert self._vector_store is not None
                        await self._vector_store.delete_chunks(chunk_ids)
                    except Exception as exc:
                        logger.error("Milvus document delete failed for %s: %s", doc_id, exc)

        deleted = await self._source_store.delete_document(doc_id)
        if deleted:
            self._unlink_managed_document(doc.file_path)
        return deleted

    async def reextract_document(self, doc_id: str) -> dict:
        """从制品包中已存储的原件重新提取 Markdown，覆写 clean.md/pages.json，并重新分块。

        适用于提取代码升级后修复已摄入文档的陈旧内容（如 ignore_alpha=True 修复后）。
        返回 {"chunk_count": int, "converter_version": str}。
        """
        if self._ingest_manager is None:
            raise RuntimeError("IngestManager not configured")
        return await self._ingest_manager.reextract_document(doc_id)

    # ── AstrBot 知识库（调用 / 检索）────────────────────────────

    async def list_kb_collections(self) -> list[str]:
        """列出 AstrBot 知识库中的集合名。"""
        return await self._kb_reader.list_collections()

    async def search_kb(
        self,
        collection: str,
        query: str,
        top_k: int,
        scope_type: str = "",
        scope_key: str = "",
        scope_library_id: str = "",
    ) -> list[DocumentChunk]:
        """在某 AstrBot 知识库集合内检索，可选 item/collection/tag/library 作用域硬过滤。"""
        t0 = time.monotonic()
        logger.info("search_kb: collection=%r top_k=%d query=%r", collection, top_k, query[:80])
        if self._retrieval_orchestrator is not None:
            scope = _build_scope(scope_type, scope_key, scope_library_id)
            result = await self._retrieval_orchestrator.retrieve(collection, query, top_k, scope)
        else:
            result = await self._kb_reader.search(collection, query, top_k)
        logger.info(
            "search_kb done: collection=%r hits=%d elapsed=%.0fms",
            collection,
            len(result),
            (time.monotonic() - t0) * 1000,
        )
        return result

    async def get_chunk_context(
        self, doc_id: str, chunk_id: str, window: int = 2
    ) -> dict:
        """返回指定 chunk 及其前后 window 个相邻 chunk（按 ordinal 排序）。"""
        all_chunks = await self._ensure_document_chunks_current(doc_id)
        all_chunks.sort(key=lambda c: c.ordinal)
        matched_idx = next(
            (i for i, c in enumerate(all_chunks) if c.chunk_id == chunk_id), None
        )
        if matched_idx is None:
            return {"context_before": [], "context_after": [], "matched_chunk_id": chunk_id}
        before = all_chunks[max(0, matched_idx - window):matched_idx]
        after = all_chunks[matched_idx + 1:min(len(all_chunks), matched_idx + window + 1)]
        return {
            "context_before": [
                {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "ordinal": c.ordinal, "text": c.text}
                for c in before
            ],
            "context_after": [
                {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "ordinal": c.ordinal, "text": c.text}
                for c in after
            ],
            "matched_chunk_id": chunk_id,
        }

    async def rebuild_vector_store(self, job: MilvusBuildJob | None = None) -> dict[str, Any]:
        """清除并从 SQLite 事实源全量 rebuild 本地向量数据库。

        可选 `job`：传入则在 data cleaning 与 indexing 两个阶段更新进度供轮询；
        不传则返回值/签名兼容，但仍会在索引前修复 legacy chunks。
        """
        if not self._config or not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

        self._mark_milvus_incompatible("Milvus full rebuild is in progress.")

        # 1. 清空向量库
        await self._vector_store.clear()

        # 2. 从 SQLite 中读取所有的文档
        docs = await self._source_store.list_documents()
        if job is not None:
            job.mode = "full"
            job.total_docs = len(docs)
        failed_doc_ids, errors = await self._run_milvus_data_cleaning(
            docs, job, context="full rebuild"
        )
        index_docs = [doc for doc in docs if doc.doc_id not in failed_doc_ids]
        if job is not None:
            job.stage = MILVUS_BUILD_STAGE_INDEXING
            job.total_index_docs = len(index_docs)
        total_chunks = 0

        # 3. 逐个文档批量进行 Embedding 计算与 upsert
        for doc in index_docs:
            try:
                chunks = await self._index_document_chunks_with_retry(
                    doc.doc_id, doc.collection, context="full rebuild"
                )
                total_chunks += chunks
                if job is not None:
                    job.processed_docs += 1
                    job.processed_index_docs += 1
                    job.total_chunks += chunks
            except Exception as exc:
                logger.error(
                    "Milvus indexing failed after retries for %s during full rebuild: %s",
                    doc.doc_id,
                    exc,
                )
                await self._mark_document_needs_reindex(doc.doc_id)
                failed_doc_ids.add(doc.doc_id)
                errors.append(
                    {
                        "doc_id": doc.doc_id,
                        "stage": MILVUS_BUILD_STAGE_INDEXING,
                        "error": str(exc),
                    }
                )
                if job is not None:
                    job.failed_docs += 1
                    job.errors.append(
                        {
                            "doc_id": doc.doc_id,
                            "stage": MILVUS_BUILD_STAGE_INDEXING,
                            "error": str(exc),
                        }
                    )

        if job is not None:
            job.stage = MILVUS_BUILD_STAGE_FINALIZING

        if errors:
            failed_ids = {e["doc_id"] for e in errors}
            for doc in docs:
                if doc.doc_id not in failed_ids:
                    await self._clear_document_needs_reindex(doc.doc_id)
            if self._index_compatibility and self._embedding_fingerprint:
                self._index_compatibility.mark_milvus_compatible(self._embedding_fingerprint)
            logger.error(
                "Milvus rebuild partial failure: %d doc(s) failed, marking compatible "
                "for incremental retry",
                len(errors),
            )
            return {
                "rebuilt_chunks": total_chunks,
                "failed_docs": len(errors),
                "errors": errors[:5],
            }

        logger.info("Successfully rebuilt vector store index: %d chunks", total_chunks)
        if self._index_compatibility and self._embedding_fingerprint:
            self._index_compatibility.mark_milvus_compatible(self._embedding_fingerprint)
        for doc in docs:
            await self._clear_document_needs_reindex(doc.doc_id)
        return {"rebuilt_chunks": total_chunks, "failed_docs": 0, "errors": []}

    async def rebuild_index_pending(self, job: MilvusBuildJob | None = None) -> dict[str, Any]:
        """仅对 needs_reindex=True 的文档进行增量索引重建，完成后清除标记。

        可选 `job`：传入则在 data cleaning 与 indexing 两个阶段更新进度供轮询；不兼容触发的全量
        rebuild 分支会把同一 `job` 透传给 `rebuild_vector_store`。
        """
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError(
                "VectorStore 未配置（请安装 Milvus 并重启插件，或配置 embedding provider）"
            )

        if (
            self._config
            and self._config.get_vector_db_config().backend == "milvus"
            and self._index_compatibility
            and self._embedding_fingerprint
            and not self._index_compatibility.is_milvus_compatible(
                self._embedding_fingerprint
            )
        ):
            docs = await self._source_store.list_documents()
            result = await self.rebuild_vector_store(job)
            return {"rebuilt_docs": len(docs), **result}

        docs = await self._source_store.list_pending_reindex_documents()
        if job is not None:
            job.mode = "pending"
            job.total_docs = len(docs)
        failed_doc_ids, errors = await self._run_milvus_data_cleaning(
            docs, job, context="pending rebuild"
        )
        index_docs = [doc for doc in docs if doc.doc_id not in failed_doc_ids]
        if job is not None:
            job.stage = MILVUS_BUILD_STAGE_INDEXING
            job.total_index_docs = len(index_docs)
        total_chunks = 0
        rebuilt_docs = 0
        logger.info("rebuild_index_pending: %d 个文档待重建", len(docs))

        for doc in index_docs:
            try:
                chunks = await self._index_document_chunks_with_retry(
                    doc.doc_id, doc.collection, context="pending rebuild"
                )
                total_chunks += chunks
                await self._clear_document_needs_reindex(doc.doc_id)
                rebuilt_docs += 1
                if job is not None:
                    job.processed_docs += 1
                    job.processed_index_docs += 1
                    job.total_chunks += chunks
            except Exception as exc:
                logger.error(
                    "Milvus indexing failed after retries for %s during pending rebuild: %s",
                    doc.doc_id,
                    exc,
                )
                await self._mark_document_needs_reindex(doc.doc_id)
                failed_doc_ids.add(doc.doc_id)
                errors.append(
                    {
                        "doc_id": doc.doc_id,
                        "stage": MILVUS_BUILD_STAGE_INDEXING,
                        "error": str(exc),
                    }
                )
                if job is not None:
                    job.failed_docs += 1
                    job.errors.append(
                        {
                            "doc_id": doc.doc_id,
                            "stage": MILVUS_BUILD_STAGE_INDEXING,
                            "error": str(exc),
                        }
                    )

        if job is not None:
            job.stage = MILVUS_BUILD_STAGE_FINALIZING

        logger.info(
            "rebuild_index_pending 完成: %d docs, %d chunks, %d failed",
            rebuilt_docs,
            total_chunks,
            len(errors),
        )
        return {
            "rebuilt_docs": rebuilt_docs,
            "rebuilt_chunks": total_chunks,
            "failed_docs": len(errors),
            "errors": errors[:5],
        }

    async def get_pending_reindex_count(self) -> int:
        """返回待重建索引的文档数量。"""
        docs = await self._source_store.list_pending_reindex_documents()
        return len(docs)

    # ── Milvus 后台重建（进度条）─────────────────────────────────

    async def start_milvus_rebuild(self) -> dict[str, Any]:
        """在后台启动一次 Milvus 增量重建并立即返回任务快照。

        全局单任务：已有 running 任务时直接返回当前任务（防并发）。进度由后台任务在
        `rebuild_index_pending` 的逐文档循环中更新，前端经 `get_active_milvus_build_job`
        轮询。终态（success/partial_failure/error）由 `_run_milvus_rebuild` 写回。
        """
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError(
                "VectorStore 未配置（请安装 Milvus 并重启插件，或配置 embedding provider）"
            )
        current = self._milvus_build_job
        if current is not None and current.status == MILVUS_BUILD_RUNNING:
            return current.to_dict()

        job = MilvusBuildJob(
            mode="pending",
            stage=MILVUS_BUILD_STAGE_CLEANING,
            started_at_iso=_now_iso(),
        )
        self._milvus_build_job = job
        self._milvus_build_task = asyncio.create_task(self._run_milvus_rebuild(job))
        return job.to_dict()

    async def _run_milvus_rebuild(self, job: MilvusBuildJob) -> None:
        """后台执行 rebuild_index_pending，并把终态写回 job（不打崩任务循环）。"""
        try:
            await self.rebuild_index_pending(job)
            job.status = MILVUS_BUILD_PARTIAL if job.failed_docs > 0 else MILVUS_BUILD_SUCCESS
            if job.errors:
                job.recent_error = job.errors[0].get("error", "")
        except asyncio.CancelledError:
            job.status = MILVUS_BUILD_ERROR
            job.recent_error = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - 终态统一兜底，后台任务不应抛出
            logger.error("Milvus 后台重建失败: %s", exc, exc_info=True)
            job.status = MILVUS_BUILD_ERROR
            job.recent_error = str(exc)
        finally:
            job.finished_at = time.monotonic()
            job.finished_at_iso = _now_iso()

    def get_active_milvus_build_job(self) -> dict[str, Any] | None:
        """返回当前需展示的 Milvus 构建任务快照（无则 None）。

        running / partial_failure / error → 返回（后两者供前端显示「重试」）；
        success 或无任务 → 返回 None（前端隐藏进度条）。
        """
        job = self._milvus_build_job
        if job is None or job.status == MILVUS_BUILD_SUCCESS:
            return None
        return job.to_dict()

    def get_active_ingest_job(self) -> dict[str, Any] | None:
        """返回当前需展示的文档摄入任务快照（running/error 返回，success/无任务 → None）。"""
        job = self._ingest_job
        if job is None or job.status == INGEST_SUCCESS:
            return None
        return job.to_dict()

    async def get_chat_history(self, conversation_id: str) -> list[dict]:
        """返回某会话的全部消息记录，按时间升序。"""
        return await self._source_store.get_chat_messages(conversation_id)

    async def set_chat_message_locked(
        self, conversation_id: str, msg_idx: int, locked: bool = True
    ) -> dict | None:
        """设置某条聊天消息的锁定/固定状态。msg_idx 为前端展示序号（0-based）。"""
        return await self._source_store.set_chat_message_locked(conversation_id, msg_idx, locked)

    async def clear_chat_history(
        self, conversation_id: str, preserve_locked: bool = False
    ) -> None:
        """删除某会话消息；preserve_locked=True 时保留已锁定回答。"""
        await self._source_store.clear_chat_messages(
            conversation_id, preserve_locked=preserve_locked
        )

    async def get_console_scope_state(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        """读取控制台右侧上下文状态。"""
        state = await self._source_store.get_console_scope_state(scope_type, scope_key)
        return _console_scope_state_dict(state) if state is not None else None

    async def upsert_console_scope_state(
        self,
        scope_type: str,
        scope_key: str,
        *,
        selected_collection: str = "",
        selected_doc_id: str = "",
        note_doc_id: str = "",
        right_panel: str = "",
        reading_mode: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """持久化控制台右侧上下文状态。"""
        state = ConsoleScopeState(
            scope_type=scope_type,
            scope_key=scope_key,
            selected_collection=selected_collection,
            selected_doc_id=selected_doc_id,
            note_doc_id=note_doc_id,
            right_panel=right_panel,
            reading_mode=reading_mode,
            payload=dict(payload or {}),
            updated_at=_now(),
        )
        await self._source_store.upsert_console_scope_state(state)
        return _console_scope_state_dict(state)

    async def ask(
        self,
        question: str,
        collection: str | None = None,
        top_k: int = 5,
        conversation_id: str | None = None,
        persona_enabled: bool = False,
        retrieval_mode: str = "default",
        use_english_retrieval: bool = False,
        answer_language: str = "auto",
        scope_type: str = "",
        scope_key: str = "",
        scope_library_id: str = "",
        candidate_k: int | None = None,
        use_reranker: bool = False,
    ) -> dict:
        """Retrieve evidence and generate one final answer.

        candidate_k / use_reranker：研究路径用——候选池宽召回 + cross-encoder 重排再取 top_k
        （仅 default 模式生效；默认 answer top_k 不变）。reranker 为 passthrough 时自动退回 RRF。
        """
        scope = _build_scope(scope_type, scope_key, scope_library_id)
        # 未显式传 scope 但选了集合：默认按「选中集合 + 所有子目录」检索（含后代），
        # 由 coll_key 派生 collection scope，覆盖统一树的整棵子树。
        if scope is None and collection:
            _sel = await self._source_store.get_collection_by_name(collection)
            if _sel is not None:
                scope = RetrievalScope(
                    scope_type="collection",
                    scope_key=_sel.coll_key,
                    library_id=_sel.library_id,
                )
        if retrieval_mode not in {"default", "high_precision", "graph_only", "deep_thinking"}:
            raise ValueError(
                "retrieval_mode must be 'default', 'high_precision', 'graph_only', "
                "or 'deep_thinking'"
            )
        if retrieval_mode in {"high_precision", "graph_only", "deep_thinking"} and not collection:
            raise ValueError(f"{retrieval_mode} retrieval requires a collection")
        if answer_language not in {"auto", "zh", "en"}:
            answer_language = "auto"

        cid = conversation_id or uuid.uuid4().hex
        ask_start = time.monotonic()
        logger.info(
            "ask: mode=%s collection=%r top_k=%d question=%r",
            retrieval_mode,
            collection,
            top_k,
            question[:80],
        )

        def _progress(stage: str, pct: int, detail: dict | None = None) -> None:
            if self._progress_store is not None:
                self._progress_store.set(cid, stage, pct, detail)

        def _record(op: str, t0: float, **meta: object) -> None:
            if self._metrics is not None:
                self._metrics.record(op, (time.monotonic() - t0) * 1000, meta or None)

        _progress("embed_query", 0)
        t0 = time.monotonic()

        # 翻译召回查询（当 use_english_retrieval=True 时，将用户问题翻译为英语再送入向量检索）
        retrieval_question = question
        if use_english_retrieval and self._llm_adapter is not None:
            try:
                prompt = (
                    "Translate the following query to English for document retrieval."
                    " Output only the English translation, nothing else:\n\n"
                    f"{question}"
                )
                translated = await self._llm_adapter.generate(
                    prompt,
                    system_prompt=(
                        "You are a translation assistant."
                        " Output only the English translation, concisely."
                    ),
                    allow_mock=False,
                )
                if translated and translated.strip():
                    retrieval_question = translated.strip()
                    logger.info(
                        "Query translated for retrieval: %r → %r",
                        question,
                        retrieval_question,
                    )
            except Exception as exc:
                logger.warning("Query translation failed, using original: %s", exc)

        if retrieval_mode in {"high_precision", "graph_only"}:
            readiness = await self.get_lightrag_readiness(collection or "")
            if not readiness["ready"]:
                raise LightRAGNotReadyError(
                    collection or "",
                    readiness["reason"],
                    build_available=readiness["build_available"],
                )

        chunks: list[DocumentChunk] = []
        engines: list[str] = []
        fallback_reason: str | None = None
        milvus_fallback_reason = await self._milvus_retrieval_fallback_reason()

        # graph_only: 跳过向量/词法召回，仅走图谱路径
        if retrieval_mode == "graph_only":
            _progress("lightrag_context", 30)
            try:
                if self._retrieval_orchestrator is None:
                    raise RuntimeError("RetrievalOrchestrator is not configured")
                lightrag_context = await self._retrieval_orchestrator.retrieve_lightrag_context(
                    collection or "", question, scope
                )
                engines.append("lightrag")
            except Exception as exc:
                logger.warning("LightRAG graph_only retrieval failed [%s]: %s", collection, exc)
                raise HighPrecisionQueryError(collection or "", str(exc)) from exc
            _progress("llm_generate", 80)
            t_llm = time.monotonic()
            if self._llm_adapter is not None and lightrag_context:
                if answer_language == "zh":
                    lang_instr = "Answer in Chinese (中文)."
                elif answer_language == "en":
                    lang_instr = "Answer in English."
                else:
                    lang_instr = "Answer in the same language as the question."
                system_prompt = (
                    "You are a helpful academic assistant. "
                    "Answer the question based solely on the provided context. "
                    "If the context is insufficient, state the limitation clearly "
                    "and only answer what the context supports. "
                    "Do not fill gaps with outside knowledge. "
                    f"{lang_instr}"
                )
                user_prompt = f"Context:\n\n{lightrag_context}\n\nQuestion: {question}"
                answer = await self._llm_adapter.generate(user_prompt, system_prompt=system_prompt)
            else:
                answer = lightrag_context or "未在知识图谱中找到与该问题相关的内容。"
            _record("llm_generate", t_llm)
            _record("ask_total", ask_start, sources=0)
            _progress("done", 100)
            try:
                await self._source_store.add_chat_message(cid, "user", question)
                await self._source_store.add_chat_message(
                    cid, "assistant", answer, sources=[], retrieval_mode="lightrag_only"
                )
            except Exception as exc:
                logger.warning("Failed to persist chat history: %s", exc)
            return {
                "conversation_id": cid,
                "answer": answer,
                "sources": [],
                "requested_retrieval_mode": retrieval_mode,
                "actual_retrieval_mode": "lightrag_only",
                "retrieval_engines": ["lightrag"],
                "fallback_reason": None,
            }

        deep_outcome = None  # DeepThinkingOutcome | None（仅 deep_thinking 路径非空）。
        if retrieval_mode == "deep_thinking" and self._deep_thinking_orchestrator is None:
            raise RuntimeError("DeepThinkingOrchestrator is not configured")
        if retrieval_mode == "deep_thinking":
            _progress("deep_thinking", 20)
            t_dt = time.monotonic()
            deep_outcome = await self._deep_thinking_orchestrator.run(
                collection or "",
                retrieval_question,
                scope,
                progress=_progress,
                answer_language=answer_language,
                answer_question=question,
            )
            chunks = list(deep_outcome.evidence)
            engines.append("deep_thinking")
            _record(
                "deep_thinking_total",
                t_dt,
                rounds=len(deep_outcome.trace),
                degraded=deep_outcome.degraded,
                est_tokens=deep_outcome.est_total_tokens,
            )
        else:
            _progress("vector_search", 20)
            t_vs = time.monotonic()
            seen_ids: set[str] = set()
            for col in await self._resolve_ask_collections(collection, scope):
                try:
                    if self._retrieval_orchestrator is not None:
                        outcome = await self._retrieval_orchestrator.retrieve_with_outcome(
                            col,
                            retrieval_question,
                            top_k,
                            scope,
                            candidate_k=candidate_k,
                            reranker=self._reranker if use_reranker else None,
                        )
                        current_chunks = outcome.chunks
                        engines.extend(outcome.engines)
                        fallback_reason = fallback_reason or outcome.fallback_reason
                    else:
                        fallback_reason = fallback_reason or milvus_fallback_reason
                        current_chunks = await self._kb_reader.search(
                            col, retrieval_question, top_k
                        )
                        engines.append("astrbot")
                except Exception as exc:
                    logger.warning("Ask retrieval failed for collection %s: %s", col, exc)
                    fallback_reason = fallback_reason or f"collection_error:{col}"
                    continue
                for chunk in current_chunks:
                    if chunk.chunk_id not in seen_ids:
                        seen_ids.add(chunk.chunk_id)
                        chunks.append(chunk)
                    if len(chunks) >= top_k:
                        break
                if len(chunks) >= top_k:
                    break
            _record("vector_search", t_vs, hits=len(chunks))

        _record("embed_query", t0)

        lightrag_context = ""
        if retrieval_mode == "high_precision":
            _progress("lightrag_context", 50)
            try:
                if self._retrieval_orchestrator is None:
                    raise RuntimeError("RetrievalOrchestrator is not configured")
                lightrag_context = await self._retrieval_orchestrator.retrieve_lightrag_context(
                    collection or "", question, scope
                )
                engines.append("lightrag")
            except Exception as exc:
                logger.warning("LightRAG high-precision retrieval failed [%s]: %s", collection, exc)
                raise HighPrecisionQueryError(collection or "", str(exc)) from exc

        _progress("rrf_fusion", 65)

        sources = []
        context_parts = []
        for i, chunk in enumerate(chunks):
            n = i + 1
            doc = await self.get_document(chunk.doc_id)
            title = doc.title if doc else chunk.doc_id
            meta = chunk.metadata or {}
            source = {
                "n": n,
                "doc_id": chunk.doc_id,
                "document_id": chunk.doc_id,
                "title": title,
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "metadata": meta,
                "pages": meta.get("pages", []),
                "origin": doc.origin.value if doc else "local",
            }
            # Zotero provenance：跳转链接 + 归一化引用（Li 2025）。
            if doc and doc.origin is DocumentOrigin.ZOTERO:
                source["zotero_item_uri"] = meta.get("zotero_item_uri", "")
                source["zotero_pdf_uri"] = meta.get("zotero_pdf_uri", "")
                zmeta = await self.get_zotero_item_meta(doc.library_id, doc.zotero_item_key)
                if zmeta:
                    first_author = (zmeta["creators"][0].split(",")[0] if zmeta["creators"] else "")
                    source["author"] = first_author
                    source["year"] = zmeta["year"]
                    source["citation"] = " ".join(
                        x for x in [first_author, zmeta["year"]] if x
                    ).strip()
            sources.append(source)
            has_page = chunk.metadata and "page_number" in chunk.metadata
            page_info = f" (Page {chunk.metadata['page_number']})" if has_page else ""
            context_parts.append(f"[{n}] {title}{page_info}\n{chunk.text}")

        _progress("llm_generate", 80)
        t_llm = time.monotonic()

        has_evidence = bool(context_parts or lightrag_context)
        deep_answer = deep_outcome.answer if deep_outcome is not None else None
        if (
            not deep_answer
            and deep_outcome is not None
            and self._llm_adapter is not None
            and chunks
        ):
            # deep 模式但 verify 关闭/synth 失败：仍走 deep 合成，避免答案深度退回普通风格（P2-b）；
            # 失败则优雅退回下方通用合成。[n] 与 sources 同序对齐（均按 chunks 顺序）。
            from core.pipelines.answer_synthesis import synthesize_answer

            # 每条证据标注来源文档（Zotero 优先短引「作者 年份」，否则标题），防跨文档串线。
            source_labels = {
                s["doc_id"]: (s.get("citation") or s["title"]) for s in sources
            }
            try:
                deep_answer = await synthesize_answer(
                    self._llm_adapter,
                    question,
                    chunks,
                    answer_language,
                    style="deep",
                    source_labels=source_labels,
                )
            except Exception as exc:
                logger.warning("deep fallback synth failed, falling back to generic: %s", exc)

        if deep_answer:
            # deep 答案（verification 闭环合成或上面的 deep fallback 合成）直接用，不套 persona。
            answer = deep_answer
        elif self._llm_adapter is not None and has_evidence:
            if answer_language == "zh":
                lang_instr = "Answer in Chinese (中文)."
            elif answer_language == "en":
                lang_instr = "Answer in English."
            else:
                lang_instr = "Answer in the same language as the question."
            system_prompt = (
                "You are a helpful academic assistant. "
                "Answer the question based solely on the provided context. "
                "If the context is insufficient, state the limitation clearly "
                "and only answer what the context supports. "
                "Do not fill gaps with outside knowledge. "
                f"Cite sources using [n] notation (e.g. [1], [2]). "
                f"{lang_instr}"
            )
            if persona_enabled:
                bot_persona = _get_astrbot_persona_prompt(self._llm_adapter._context)
                if bot_persona:
                    system_prompt = f"{bot_persona}\n\n[RAG Constraints]\n{system_prompt}"

            graph_header = (
                f"[LightRAG Context]\n{lightrag_context}\n\n---\n\n"
                if lightrag_context
                else ""
            )
            user_prompt = (
                "Context:\n\n"
                + graph_header
                + "\n\n---\n\n".join(context_parts)
                + f"\n\nQuestion: {question}"
            )
            answer = await self._llm_adapter.generate(user_prompt, system_prompt=system_prompt)
        elif context_parts:
            answer = f"根据知识库检索到 {len(chunks)} 个相关片段：\n\n" + "\n\n".join(
                f"**[{s['n']}] {s['title']}**\n"
                f"{s['text'][:300]}{'…' if len(s['text']) > 300 else ''}"
                for s in sources
            )
        elif lightrag_context:
            answer = lightrag_context
        else:
            answer = "未在知识库中找到与该问题相关的内容。请尝试其他关键词或上传相关文档。"

        answer = _apply_deep_answer_warning(answer, deep_outcome, answer_language, question)

        _record("llm_generate", t_llm)
        _record("ask_total", ask_start, sources=len(sources))
        _progress("done", 100)

        engines = list(dict.fromkeys(engines))
        if retrieval_mode == "deep_thinking" and deep_outcome is not None:
            actual_mode = deep_outcome.actual_mode
        elif retrieval_mode == "high_precision":
            if "astrbot" in engines:
                actual_mode = "astrbot_lightrag"
            elif "milvus" in engines:
                actual_mode = "milvus_lightrag"
            elif "sqlite_lexical" in engines:
                actual_mode = "lexical_lightrag"
            else:
                actual_mode = "lightrag"
        elif "astrbot" in engines:
            actual_mode = "astrbot_fallback" if fallback_reason else "astrbot"
        elif "milvus" in engines:
            actual_mode = "milvus"
        elif "sqlite_lexical" in engines:
            actual_mode = "sqlite_lexical"
        else:
            actual_mode = "none"

        # 自动持久化聊天记录（source_store 支持时）
        try:
            await self._source_store.add_chat_message(cid, "user", question)
            await self._source_store.add_chat_message(
                cid, "assistant", answer,
                sources=[s for s in sources],
                retrieval_mode=actual_mode,
            )
        except Exception as exc:
            logger.warning("Failed to persist chat history: %s", exc)

        return {
            "conversation_id": cid,
            "answer": answer,
            "sources": sources,
            "requested_retrieval_mode": retrieval_mode,
            "actual_retrieval_mode": actual_mode,
            "retrieval_engines": engines,
            "fallback_reason": fallback_reason,
            "thinking_trace": _serialize_deep_thinking(deep_outcome) if deep_outcome else None,
        }

    async def _resolve_ask_collections(
        self, collection: str | None, scope: RetrievalScope | None = None
    ) -> list[str]:
        # collection scope（含后代）：把检索集合扩展为「选中集合 + 全部后代」的 name 列表，
        # 各引擎按 primary collection_tag 覆盖子树；scope 的 allowed_document_ids 再精确过滤。
        if scope is not None and scope.scope_type == "collection" and scope.scope_key:
            keys = await self._source_store.get_local_collection_descendants(scope.scope_key)
            names: list[str] = []
            for ck in keys:
                col = await self._source_store.get_collection(ck)
                if col:
                    names.append(col.name)
            names = list(dict.fromkeys(names))
            if names:
                return names
        if collection:
            return [collection]
        collections = [item.name for item in await self.list_collections()]
        if not collections:
            collections = await self.list_kb_collections()
        return collections[:5]

    async def get_lightrag_readiness(self, collection: str) -> dict[str, Any]:
        if not collection:
            return {
                "ready": False,
                "reason": "A collection is required.",
                "build_available": False,
            }
        if self._lightrag_registry is None:
            return {
                "ready": False,
                "reason": "LightRAG Core is not enabled or configured.",
                "build_available": False,
            }
        # 含后代：父集合的就绪度按「父 + 全部后代」的文档集判定（与 build 合并 workspace 一致）。
        col = await self._source_store.get_collection_by_name(collection)
        if col is not None:
            docs = await self._source_store.list_documents_by_collection_key(
                col.coll_key, descendants=True
            )
        else:
            docs = await self._source_store.list_documents(collection=collection)
        if not docs:
            return {
                "ready": False,
                "reason": "The collection has no documents.",
                "build_available": False,
            }
        if not self._lightrag_registry.has_workspace(collection):
            return {
                "ready": False,
                "reason": "LightRAG workspace has not been built.",
                "build_available": True,
            }
        if (
            not self._index_compatibility
            or not self._embedding_fingerprint
            or not self._index_compatibility.is_lightrag_compatible(
                collection, self._embedding_fingerprint
            )
        ):
            return {
                "ready": False,
                "reason": "LightRAG index is incompatible with the active embedding.",
                "build_available": True,
            }
        indexed = 0
        unindexed = 0
        for doc in docs:
            status = await self._source_store.get_lightrag_index_status(doc.doc_id)
            if (
                status is not None
                and status.get("collection") == collection
                and status.get("status") == "indexed"
            ):
                indexed += 1
            else:
                unindexed += 1
        # 至少有一篇文档被成功索引就认为可用；全部失败才阻止
        if indexed == 0 and unindexed > 0:
            return {
                "ready": False,
                "reason": f"No documents have been indexed yet ({unindexed} pending).",
                "build_available": True,
            }
        return {
            "ready": True,
            "reason": "",
            "build_available": False,
            "indexed_docs": indexed,
            "unindexed_docs": unindexed,
        }

    # ── 在线服务（配额）────────────────────────────────────────

    async def list_quota(self) -> list[QuotaUsage]:
        """汇总各已配置同步目标的用量快照（配额仪表盘用）。

        无同步目标时返回空列表。warning 级别由调用方（quota_manager / 前端）按阈值判定。
        """
        usages = []
        for target in self._sync_targets.values():
            usages.append(await target.check_quota())
        return usages

    # ── 预留端口（Reserved）：契约先定，实现随对应版本接入 ──────────
    #
    # 以下方法是「接口先行」在 api 门面的体现：签名/语义现在钉死，前端与 web 路由据此预留入口，
    # 真实实现到对应版本接入（届时本类构造器注入对应 manager，方法体改为委派，签名不变）。
    # 现阶段统一抛 NotImplementedError，web 层捕获后回 501 + available_in，前端展示「将接入」。

    async def sync_documents(
        self, target: str, doc_ids: list[str] | None = None, force: bool = False
    ) -> dict:
        """把文档同步到在线目标（target=r2|notion|all）。doc_ids=None 表示全量。

        force=True：跳过增量过滤，全量强制重传（覆盖云端）。
        Reserved（v0.3.0 R2 / v0.4.0 Notion 接入）：返回逐文档同步结果汇总 + 配额预警。
        """
        if self._sync_pipeline:
            if target == "all":
                results = {
                    kind.value: await self._sync_pipeline.sync(kind, doc_ids, force=force)
                    for kind in SyncTargetKind
                }
                return {
                    "status": (
                        "success"
                        if all(result.get("status") == "success" for result in results.values())
                        else "error"
                    ),
                    "targets": results,
                }
            try:
                kind = SyncTargetKind(target)
            except ValueError:
                return {"status": "error", "message": f"未知的同步目标: {target}"}
            return await self._sync_pipeline.sync(kind, doc_ids, force=force)

        raise NotImplementedError("sync_documents: available in v0.3.0 (r2) / v0.4.0 (notion)")

    async def initialize_notion_database(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> dict:
        """自动创建 Notion 数据库，并回写生成的 database_id。"""
        if not self._sync_pipeline:
            raise NotImplementedError("initialize_notion_database: available in v0.8.0")

        result = await self._sync_pipeline.initialize_notion_database(
            parent_page_id=parent_page_id,
            database_title=database_title,
        )
        if result.get("status") == "success":
            database_id = result.get("database_id")
            if isinstance(database_id, str) and database_id:
                self._persist_config_value("notion_sync", "database_id", database_id)
            parent = result.get("parent_page_id")
            if isinstance(parent, str) and parent:
                self._persist_config_value("notion_sync", "parent_page_id", parent)
            title = result.get("database_title")
            if isinstance(title, str) and title:
                self._persist_config_value("notion_sync", "database_title", title)
        return result

    async def pull_notion_metadata(self) -> dict:
        """从 Notion 反向拉取 Collection/Tags 元数据。"""
        if self._sync_pipeline:
            return await self._sync_pipeline.pull_notion_metadata()
        raise NotImplementedError("pull_notion_metadata: available in v0.8.0")

    async def get_effective_config(self) -> dict:
        """返回前端可展示的有效配置。"""
        if self._config is None:
            raise NotImplementedError("get_effective_config: available in v0.8.0")
        return self._config.to_public_dict()

    async def get_service_status(self) -> dict[str, Any]:
        """返回服务框架概览：所用模型与各服务启用状态（供 /ka status 展示）。

        仅给静态框架视图（模型 + 各服务 enabled）；运行时开关（agent/research/persona/webui）
        的实时状态由命令层从 PluginInitializer 叠加，避免读到未刷新的持久化配置。
        """
        if self._config is None:
            return {}
        emb = self._config.get_embedding_config()
        vdb = self._config.get_vector_db_config()
        rerank = self._config.get_rerank_config()
        deep = self._config.get_deep_thinking_config()
        graph = self._config.get_graph_config()
        r2 = self._config.get_r2_sync_config()
        notion = self._config.get_notion_sync_config()
        zotero = self._config.get_zotero_sync_config()
        web = self._config.get_web_console_config()
        return {
            "models": {
                "embedding": f"{emb.provider}:{emb.model}",
                "vector_db": vdb.backend,
                "rerank": (
                    "noop" if rerank.provider == "noop" else f"{rerank.provider}:{rerank.model}"
                ),
                "deep_thinking_llm": deep.llm_model or "AstrBot 主 LLM",
                "lightrag_llm": (
                    (graph.lightrag_llm_model or graph.lightrag_llm_provider)
                    if graph.enabled
                    else "未启用"
                ),
            },
            "services": {
                "graph": graph.enabled,
                "r2_sync": r2.enabled,
                "notion_sync": notion.enabled,
                "zotero_sync": zotero.enabled,
                "zotero_auto_sync": zotero.auto_sync_enabled,
            },
            "web_console": {"enabled": web.enabled, "host": web.host, "port": web.port},
        }

    _SECRET_KEYS: frozenset[str] = frozenset(
        {
            "api_key",
            "secret_access_key",
            "access_key_id",
            "password",
        }
    )

    # 可写键与结构键从 config.py 的单一登记表派生（不再手抄，重启/重建后果亦由登记表决定）。
    _CONFIG_UPDATE_KEYS: dict[str, frozenset[str]] = api_writable_keys()
    _STRUCTURAL_KEYS: dict[str, frozenset[str]] = structural_keys()

    async def update_config_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Persist a safe config value without hot-swapping embedding-backed runtime state."""
        logger.info("update_config: %s.%s", section, key)
        if section not in self._CONFIG_UPDATE_KEYS:
            raise ValueError(f"Section '{section}' is write-protected or read-only.")
        if key not in self._CONFIG_UPDATE_KEYS.get(section, frozenset()):
            raise ValueError(f"runtime config key is not allowed: {section}.{key}")
        if key in self._SECRET_KEYS and value:
            raise ValueError(f"'{key}' 为机密字段，必须通过环境变量注入，不可经此接口写入。")
        if key in self._STRUCTURAL_KEYS.get(section, frozenset()):
            raise ValueError(
                f"'{section}.{key}' 为结构性参数，修改后需手动重建索引。"
                "请直接修改插件配置文件并重启插件，而非通过此接口写入。"
            )
        if section == "embedding" and key == "provider" and value not in {"local", "external"}:
            raise ValueError("embedding.provider must be 'local' or 'external'.")
        if section == "vector_db" and key == "backend" and value not in {"milvus", "astr"}:
            raise ValueError("vector_db.backend must be 'milvus' or 'astr'.")
        if section == "rerank" and key == "provider" and value not in {"cross_encoder", "noop"}:
            raise ValueError("rerank.provider must be 'cross_encoder' or 'noop'.")

        changed = self._current_config_value(section, key) != value
        self._persist_config_value(section, key, value)
        consequence = change_consequence(section, key)
        rebuild_required = changed and consequence == CONSEQUENCE_REBUILD
        restart_required = changed and consequence in (CONSEQUENCE_RESTART, CONSEQUENCE_REBUILD)
        if rebuild_required:
            await self._invalidate_embedding_indexes(
                f"Configuration changed: {section}.{key}"
            )
        if changed and section == "rerank":
            self._apply_rerank_runtime_config()

        logger.info("update_config ok: %s.%s persisted", section, key)
        return {
            "status": "success",
            "restart_required": restart_required,
            "rebuild_required": rebuild_required,
            "message": (
                "Configuration saved. Restart and rebuild indexes."
                if rebuild_required
                else (
                    "Configuration saved. Restart required."
                    if restart_required
                    else "Configuration saved."
                )
            ),
        }

    async def restart_plugin(self) -> dict[str, Any]:
        """软重启插件运行时：teardown 后重新 initialize（重读持久化配置）。

        重启会拆掉并重建 Web 控制台连接，故先立即返回，再以后台任务延迟执行重启，
        让本响应得以发送给前端；前端随后轮询探活并刷新状态、清空「待重启」标记。
        """
        if self._reload_callback is None:
            return {
                "status": "unsupported",
                "message": "当前环境不支持程序化重启，请手动重启插件。",
            }

        async def _deferred_reload() -> None:
            await asyncio.sleep(0.4)
            try:
                await self._reload_callback()
            except Exception as exc:  # noqa: BLE001 - 后台任务需吞掉异常并记录
                logger.error("plugin soft restart failed: %s", exc, exc_info=True)

        asyncio.create_task(_deferred_reload())
        logger.info("plugin soft restart scheduled")
        return {"status": "restarting", "message": "插件正在重启，稍后将自动重连。"}

    async def test_embedding_connection(self, base_url: str, model_name: str) -> dict:
        """临时创建一个 ExternalEmbeddingProvider 并发送测试请求，验证云端 API 可连通性。"""
        from core.repository.embedding.external import ExternalEmbeddingProvider

        provider = ExternalEmbeddingProvider(
            base_url=base_url,
            model_name=model_name,
        )
        try:
            vec = await provider.embed_query("ping")
            return {"status": "ok", "dimension": len(vec), "model": model_name}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    async def get_sync_status(self) -> list[dict]:
        """列出各文档在各目标的同步状态（SyncRecord 视图）。

        Reserved（v0.3.0 起）：现返回空，接入后返回 doc_id/target/status/synced_at。
        """
        records = await self._source_store.list_sync_records()
        return [
            {
                "doc_id": r.doc_id,
                "target": r.target.value,
                "remote_ref": r.remote_ref,
                "status": r.status.value,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
                "message": r.message,
            }
            for r in records
        ]

    async def backup_now(self) -> dict:
        """立即触发一次 R2 全量备份（插件托管原件 + knowledge_repository.db 快照）。

        Reserved（v0.3.0）：返回备份对象数与用量；接近 10GB 时含警告。
        """
        if self._sync_pipeline:
            return await self._sync_pipeline.sync(SyncTargetKind.R2)

        raise NotImplementedError("backup_now: available in v0.3.0")

    async def restore_from_backup(self, snapshot: str | None = None) -> dict:
        """从 R2 备份恢复本地（snapshot=None 取最新）。对应「本地崩溃可恢复」。

        Reserved（v0.3.0）：返回恢复的文档数。
        """
        if self._sync_pipeline:
            return await self._sync_pipeline.restore(SyncTargetKind.R2)

        raise NotImplementedError("restore_from_backup: available in v0.3.0")

    async def estimate_graph_build(self, collection: str | None = None) -> dict:
        """Dry-run LightRAG build estimate. This never calls LLM or Embedding."""
        from core.lightrag_core import estimate_lightrag_build

        col = await self._resolve_collection(collection)
        docs = await self._lightrag_docs_for_build(col)
        chunks_by_doc = {
            doc.doc_id: await self._source_store.list_chunks(doc.doc_id) for doc in docs
        }
        graph_cfg = self._config.get_graph_config() if self._config else None
        max_chars = graph_cfg.max_doc_chars if graph_cfg else 0
        estimate = estimate_lightrag_build(
            docs,
            chunks_by_doc,
            max_doc_chars=max_chars,
            is_local_lightrag_llm=bool(
                graph_cfg and graph_cfg.lightrag_llm_provider == "local"
            ),
            seconds_per_chunk_local=(
                graph_cfg.lightrag_seconds_per_chunk_local if graph_cfg else 90.0
            ),
            seconds_per_chunk_remote=(
                graph_cfg.lightrag_seconds_per_chunk_remote if graph_cfg else 20.0
            ),
        )
        return {"collection": col, **estimate}

    async def build_graph(self, collection: str | None = None, *, confirmed: bool = False) -> dict:
        """Start a manually confirmed LightRAG Core build job."""
        if not confirmed:
            raise ValueError(
                "LightRAG build requires confirmed=true because it triggers LLM indexing"
            )
        if self._lightrag_registry is None:
            raise RuntimeError("LightRAG Core registry is not configured")

        from core.lightrag_core import BuildJob

        col = await self._resolve_collection(collection)

        # 线性单队列：任意集合有活动/暂停任务时，都不启动第二个构建。
        for job in self._graph_build_jobs.values():
            if job.status in ACTIVE_BUILD_STATUSES:
                raise RuntimeError(
                    f"已有构建任务正在进行中（collection={job.collection!r}, job_id={job.job_id}）"
                )

        job_id = uuid.uuid4().hex
        docs = await self._lightrag_docs_for_build(col)
        job = BuildJob(
            job_id=job_id,
            collection=col,
            total_docs=len(docs),
            started_at_iso=_now_iso(),
        )
        self._refresh_build_progress(job)
        self._graph_build_jobs[job_id] = job
        ev = asyncio.Event()
        ev.set()
        self._build_pause_events[job_id] = ev
        await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
        task = asyncio.create_task(self._run_lightrag_build_job(job_id))
        self._build_tasks[job_id] = task
        return job.to_dict()

    async def cancel_build_tasks(self) -> None:
        """取消所有进行中的构建任务并等待其完成（teardown 时调用）。"""
        for job_id, task in list(self._build_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._build_tasks.clear()

    async def get_graph_build_job(self, job_id: str) -> dict | None:
        job = self._graph_build_jobs.get(job_id)
        return job.to_dict() if job else None

    async def get_active_build_job(self) -> dict | None:
        """返回当前正在运行或暂停的构建任务，没有则返回 None。"""
        for job in self._graph_build_jobs.values():
            if job.status in ACTIVE_BUILD_STATUSES:
                return job.to_dict()
        return None

    async def get_build_job_history(self, collection: str | None = None) -> list[dict]:
        """返回构建任务历史（来自持久化表）。"""
        return await self._source_store.list_build_jobs(collection=collection)

    async def pause_build_job(self, job_id: str) -> None:
        """暂停指定构建任务。"""
        job = self._graph_build_jobs.get(job_id)
        if job is None:
            raise KeyError(f"Build job {job_id!r} not found")
        if job.status not in ("queued", "running", "pause_requested", "paused"):
            raise ValueError(f"Job {job_id!r} is not active (status={job.status!r})")
        if job.status == "paused":
            return
        ev = self._build_pause_events.get(job_id)
        if job.in_llm_call:
            job.pause_requested = True
            job.status = "pause_requested"
            job.stage = "pause_requested"
            self._refresh_build_progress(job, label="waiting_current_llm")
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
            if ev is not None:
                ev.clear()
            return
        await self._enter_build_paused(job)

    async def resume_build_job(self, job_id: str) -> None:
        """继续被暂停的构建任务。"""
        job = self._graph_build_jobs.get(job_id)
        if job is None:
            raise KeyError(f"Build job {job_id!r} not found")
        if job.status not in ("pause_requested", "paused"):
            raise ValueError(f"Job {job_id!r} is not paused (status={job.status!r})")
        if job.paused and job.paused_at is not None:
            job.paused_seconds += max(0.0, time.monotonic() - job.paused_at)
        job.paused_at = None
        job.paused_at_iso = None
        job.paused = False
        job.pause_requested = False
        job.status = "running"
        if job.stage in ("paused", "pause_requested"):
            job.stage = "resuming"
        self._refresh_build_progress(job, label="resuming")
        ev = self._build_pause_events.get(job_id)
        if ev is None:
            ev = asyncio.Event()
            self._build_pause_events[job_id] = ev
        ev.set()
        await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
        task = self._build_tasks.get(job_id)
        if task is None or task.done():
            self._build_tasks[job_id] = asyncio.create_task(
                self._run_lightrag_build_job(job_id)
            )

    async def restore_paused_build_job(self) -> None:
        """启动时恢复最新 paused job 到内存队列，但不自动继续执行。"""
        if self._lightrag_registry is None:
            return
        row = await self._source_store.get_latest_resumable_build_job()
        if row is None:
            return

        job = self._build_job_from_snapshot(row, paused=True)
        self._graph_build_jobs[job.job_id] = job
        self._build_pause_events[job.job_id] = asyncio.Event()

    def _build_job_db_snapshot(
        self, job: BuildJob, started_iso: str | None = None, finished_iso: str | None = None
    ) -> dict:
        if started_iso is not None:
            job.started_at_iso = started_iso
        if finished_iso is not None:
            job.finished_at_iso = finished_iso
        return {
            "job_id": job.job_id, "collection": job.collection,
            "status": job.status, "stage": job.stage,
            "processed_docs": job.processed_docs, "failed_docs": job.failed_docs,
            "total_docs": job.total_docs,
            "processed_chunks": job.processed_chunks, "failed_chunks": job.failed_chunks,
            "total_chunks": job.total_chunks,
            "recent_error": job.recent_error,
            "started_at": job.started_at_iso, "finished_at": job.finished_at_iso,
            "pause_requested": job.pause_requested,
            "paused_at": job.paused_at_iso,
            "paused_seconds": job.paused_seconds,
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
        }

    def _build_job_from_snapshot(self, row: dict, *, paused: bool = False) -> BuildJob:
        from core.lightrag_core import BuildJob

        now_mono = time.monotonic()
        paused_seconds = float(row.get("paused_seconds", 0) or 0)
        started_dt = _parse_iso(row.get("started_at"))
        paused_dt = _parse_iso(row.get("paused_at")) or _now()
        paused_gap = max(0.0, (_now() - paused_dt).total_seconds()) if paused else 0.0
        paused_mono = now_mono - paused_gap if paused else None
        elapsed = 0.0
        if started_dt is not None:
            elapsed = max(0.0, (paused_dt - started_dt).total_seconds() - paused_seconds)
        started_mono = (
            (paused_mono or now_mono) - elapsed - paused_seconds
            if paused
            else now_mono - elapsed - paused_seconds
        )
        job = BuildJob(
            job_id=str(row["job_id"]),
            collection=str(row["collection"]),
            status=str(row.get("status") or "paused"),
            stage=str(row.get("stage") or "paused"),
            processed_docs=int(row.get("processed_docs", 0) or 0),
            failed_docs=int(row.get("failed_docs", 0) or 0),
            total_docs=int(row.get("total_docs", 0) or 0),
            processed_chunks=int(row.get("processed_chunks", 0) or 0),
            failed_chunks=int(row.get("failed_chunks", 0) or 0),
            total_chunks=int(row.get("total_chunks", 0) or 0),
            recent_error=str(row.get("recent_error", "") or ""),
            paused=paused,
            pause_requested=bool(row.get("pause_requested", False)),
            paused_at=paused_mono,
            paused_at_iso=row.get("paused_at") if paused else None,
            paused_seconds=paused_seconds,
            started_at=started_mono,
            started_at_iso=str(row.get("started_at") or _now_iso()),
            progress_current=int(row.get("progress_current", 0) or 0),
            progress_total=int(row.get("progress_total", 0) or 0),
        )
        self._refresh_build_progress(job)
        return job

    def _refresh_build_progress(self, job: BuildJob, label: str | None = None) -> None:
        finalize_done = 1 if job.status in ("success", "partial_failure") else 0
        total = max(1, job.total_chunks + job.total_docs + 1)
        current = (
            job.processed_chunks
            + job.failed_chunks
            + job.processed_docs
            + job.failed_docs
            + finalize_done
        )
        job.progress_total = total
        job.progress_current = min(total, max(0, current))
        job.progress_label = label or job.stage

    async def _enter_build_paused(self, job: BuildJob) -> None:
        ev = self._build_pause_events.get(job.job_id)
        if ev is None:
            ev = asyncio.Event()
            self._build_pause_events[job.job_id] = ev
        ev.clear()
        job.pause_requested = False
        job.paused = True
        job.status = "paused"
        job.stage = "paused"
        job.paused_at = time.monotonic()
        job.paused_at_iso = _now_iso()
        self._refresh_build_progress(job, label="paused")
        await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))

    async def _build_pause_gate(self, job: BuildJob, label: str) -> None:
        if job.pause_requested:
            await self._enter_build_paused(job)
        if job.paused:
            ev = self._build_pause_events.get(job.job_id)
            if ev is None:
                ev = asyncio.Event()
                self._build_pause_events[job.job_id] = ev
            await ev.wait()
            self._refresh_build_progress(job, label=label)

    async def _run_lightrag_build_job(self, job_id: str) -> None:
        job = self._graph_build_jobs[job_id]
        assert self._lightrag_registry is not None
        try:
            await self._build_pause_gate(job, "reading_documents")
            job.status = "running"
            job.stage = "reading_documents"
            job.paused = False
            job.pause_requested = False
            job.finished_at = None
            job.finished_at_iso = None
            if not job.started_at_iso:
                job.started_at_iso = _now_iso()
            self._refresh_build_progress(job, label="reading_documents")
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))

            docs = await self._lightrag_docs_for_build(job.collection)
            if job.total_docs <= 0 or job.processed_docs + len(docs) > job.total_docs:
                job.total_docs = job.processed_docs + len(docs)
            self._refresh_build_progress(job, label="reading_documents")
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
            if (
                self._index_compatibility is not None
                and self._embedding_fingerprint
                and self._lightrag_registry.has_workspace(job.collection)
                and not self._index_compatibility.is_lightrag_compatible(
                    job.collection, self._embedding_fingerprint
                )
            ):
                await self._build_pause_gate(job, "before_workspace_reset")
                job.stage = "resetting_workspace"
                self._refresh_build_progress(job, label="resetting_workspace")
                await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
                await self._lightrag_registry.reset_workspace(job.collection)

            max_chars = 0
            if self._config is not None:
                max_chars = self._config.get_graph_config().max_doc_chars

            prepared: list[tuple[SourceDocument, str, list[str], str]] = []
            for doc in docs:
                await self._build_pause_gate(job, "planning_chunks")
                text = await self._lightrag_text_for_doc(doc)
                if max_chars > 0 and len(text) > max_chars:
                    text = text[:max_chars]
                if not text.strip():
                    prepared.append((doc, "", [], "lrag_chunks"))
                    continue
                chunk_document = getattr(self._lightrag_registry, "chunk_document", None)
                if callable(chunk_document):
                    chunks, basis = await chunk_document(job.collection, text)
                else:
                    chunks, basis = [text], "estimated_lrag_chunks"
                prepared.append((doc, text, chunks, basis))

            remaining_chunks = sum(
                len(chunks) for _, text, chunks, _ in prepared if text.strip()
            )
            if (
                job.total_chunks <= 0
                or job.processed_chunks + remaining_chunks > job.total_chunks
            ):
                job.total_chunks = job.processed_chunks + remaining_chunks
            bases = {basis for _, _, _, basis in prepared}
            job.progress_basis = (
                "lrag_chunks" if bases <= {"lrag_chunks"} else "estimated_lrag_chunks"
            )
            job.stage = "indexing"
            self._refresh_build_progress(job, label="indexing")
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))

            for doc, text, lrag_chunks, _basis in prepared:
                await self._build_pause_gate(job, "before_document")
                job.stage = "indexing"
                job.current_doc_id = doc.doc_id
                self._refresh_build_progress(job, label="indexing")
                await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
                if not text.strip():
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                    self._refresh_build_progress(job, label="document_indexed")
                    await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
                    await self._build_pause_gate(job, "after_document")
                    continue

                chunk_start = job.processed_chunks
                chunk_target = min(job.total_chunks, chunk_start + len(lrag_chunks))

                def _on_lightrag_llm(event: dict[str, Any]) -> None:
                    status = event.get("status")
                    if status == "start":
                        job.in_llm_call = True
                        if job.pause_requested:
                            self._refresh_build_progress(job, label="waiting_current_llm")
                    elif status == "ok":
                        job.in_llm_call = False
                        if job.total_chunks > 0:
                            job.processed_chunks = min(
                                job.total_chunks,
                                max(job.processed_chunks + 1, chunk_start + 1),
                            )
                            job.current_chunk_index = job.processed_chunks
                        self._refresh_build_progress(job, label="indexing")
                    elif status == "error":
                        job.in_llm_call = False
                        job.failed_chunks += 1
                        self._refresh_build_progress(job, label="indexing")

                try:
                    insert_document = self._lightrag_registry.insert_document
                    kwargs: dict[str, Any] = {
                        "lrag_chunks": lrag_chunks,
                        "progress_callback": _on_lightrag_llm,
                    }
                    try:
                        params = inspect.signature(insert_document).parameters
                        if "pause_gate" in params or any(
                            p.kind == inspect.Parameter.VAR_KEYWORD
                            for p in params.values()
                        ):
                            kwargs["pause_gate"] = (
                                lambda label: self._build_pause_gate(
                                    job, str(label or "before_llm")
                                )
                            )
                    except (TypeError, ValueError):
                        kwargs["pause_gate"] = (
                            lambda label: self._build_pause_gate(
                                job, str(label or "before_llm")
                            )
                        )
                    await insert_document(job.collection, doc.doc_id, text, **kwargs)
                    job.in_llm_call = False
                    if job.processed_chunks < chunk_target:
                        job.processed_chunks = chunk_target
                        job.current_chunk_index = job.processed_chunks
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                    self._refresh_build_progress(job, label="document_indexed")
                    await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
                    await self._build_pause_gate(job, "after_document")
                except Exception as exc:
                    job.in_llm_call = False
                    job.failed_docs += 1
                    remaining = max(0, chunk_target - job.processed_chunks)
                    job.failed_chunks += remaining
                    job.recent_error = str(exc)
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "error", str(exc)
                    )
                    self._refresh_build_progress(job, label="document_error")
                    await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
                    logger.error("LightRAG build failed for doc %s: %s", doc.doc_id, exc)
            await self._build_pause_gate(job, "before_finalize")
            job.stage = "finalizing"
            self._refresh_build_progress(job, label="finalizing")
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))
            await self._build_pause_gate(job, "before_compatibility")

            final_status = "success" if job.failed_docs == 0 else "partial_failure"
            if (
                final_status in ("success", "partial_failure")
                and job.processed_docs > 0
                and self._index_compatibility is not None
                and self._embedding_fingerprint
            ):
                self._index_compatibility.mark_lightrag_compatible(
                    job.collection, self._embedding_fingerprint
                )
            job.stage = "done"
            job.status = final_status
            self._refresh_build_progress(job, label="done")
        except asyncio.CancelledError:
            job.in_llm_call = False
            if job.status != "paused":
                job.stage = "interrupted"
                job.status = "interrupted"
            raise  # 重抛，让 asyncio 正确完成取消流程
        except Exception as exc:
            job.in_llm_call = False
            job.stage = "error"
            job.status = "error"
            job.recent_error = str(exc)
            logger.error("LightRAG build job %s failed: %s", job_id, exc)
        finally:
            if job.status in TERMINAL_BUILD_STATUSES:
                job.finished_at = job.finished_at or time.monotonic()
                job.finished_at_iso = job.finished_at_iso or _now_iso()
                job.paused = False
                job.pause_requested = False
                job.paused_at = None
                job.paused_at_iso = None
                self._build_pause_events.pop(job_id, None)
                self._refresh_build_progress(job, label=job.stage)
            self._build_tasks.pop(job_id, None)
            await self._source_store.upsert_build_job(self._build_job_db_snapshot(job))

    async def _lightrag_text_for_doc(self, doc: SourceDocument) -> str:
        raw = _extract_raw_doc_text(doc)
        if raw is not None:
            return raw
        chunks = await self._source_store.list_chunks(doc.doc_id)
        return "\n\n".join(chunk.text for chunk in chunks if chunk.text.strip())

    async def _lightrag_docs_for_build(self, collection: str) -> list[SourceDocument]:
        # 合并单 workspace：以选中集合为根，纳入「父 + 全部后代」的文档（多归属去重）。
        col = await self._source_store.get_collection_by_name(collection)
        if col is not None:
            docs = await self._source_store.list_documents_by_collection_key(
                col.coll_key, descendants=True
            )
        else:
            docs = await self._source_store.list_documents(collection=collection)
        if (
            self._lightrag_registry is None
            or not self._lightrag_registry.has_workspace(collection)
            or not self._lightrag_index_is_compatible(collection)
        ):
            return docs
        pending = []
        for doc in docs:
            status = await self._source_store.get_lightrag_index_status(doc.doc_id)
            if (
                status is None
                or status.get("collection") != collection
                or status.get("status") != "indexed"
            ):
                pending.append(doc)
        return pending

    async def probe_lightrag_core(
        self, collection: str, text: str, doc_id: str, query: str
    ) -> dict:
        """Deployment manual probe for AstrBot terminal verification."""
        if self._lightrag_registry is None:
            raise RuntimeError("LightRAG Core registry is not configured")
        return await self._lightrag_registry.manual_probe(
            collection=collection, text=text, doc_id=doc_id, query=query
        )

    async def query_graph(
        self,
        query: str,
        top_k: int = 5,
        collection: str | None = None,
        debug: bool = False,
    ) -> dict:
        """Run the independent full-answer LightRAG query endpoint."""
        del top_k, debug
        if self._lightrag_registry is None:
            raise NotImplementedError("query_graph requires LightRAG Core")
        col = await self._resolve_collection(collection)
        readiness = await self.get_lightrag_readiness(col)
        if not readiness["ready"]:
            raise RuntimeError(readiness["reason"])
        payload = await self._lightrag_registry.query(col, query)
        payload["status"] = "success"
        payload["query"] = query
        return payload

    async def get_graph(self, collection: str | None = None) -> dict:
        """Export a graph or return a structured not-ready state.

        LightRAG Core 已落地；未启用、依赖缺失或 workspace 未构建都不是 reserved
        功能，而是运行态未就绪状态，供 WebUI 给出准确下一步。
        """
        col = await self._resolve_collection(collection)
        readiness = await self.get_lightrag_readiness(col)
        if not readiness["ready"]:
            return {
                "status": "not_ready",
                "ready": False,
                "collection": col,
                "engine": "lightrag_core",
                "reason": readiness["reason"],
                "build_available": readiness["build_available"],
            }
        assert self._lightrag_registry is not None
        return await self._lightrag_registry.export_graph(col)

    async def _resolve_collection(self, collection: str | None) -> str:
        if collection:
            return collection
        cols = await self.list_collections()
        return cols[0].name if cols else "default"

    # ── 性能指标与进度（供 WebUI 监控面板使用）─────────────────────

    def get_metrics_summary(self) -> dict:
        """返回近期操作延迟聚合统计。无 metrics 时返回空结构。"""
        if self._metrics is not None:
            return self._metrics.summary()
        return {"ops": {}, "total_records": 0}

    def get_ask_progress(self, conversation_id: str) -> dict | None:
        """返回指定对话的召回进度，不存在或已过期时返回 None。"""
        if self._progress_store is not None:
            return self._progress_store.get(conversation_id)
        return None

    async def get_graph_stats(self) -> dict:
        """返回图谱摘要统计（实体数、关系数、涉及集合数）。"""
        if self._lightrag_registry is None:
            return {"entities_count": 0, "relations_count": 0, "collections_covered": 0}
        nodes: set[str] = set()
        edges: set[str] = set()
        collections = 0
        for collection in self._lightrag_registry.existing_collections():
            readiness = await self.get_lightrag_readiness(collection)
            if not readiness["ready"]:
                continue
            try:
                graph = await self._lightrag_registry.export_graph(collection)
                nodes.update(f"{collection}:{item['id']}" for item in graph.get("nodes", []))
                edges.update(f"{collection}:{item['id']}" for item in graph.get("edges", []))
                collections += 1
            except Exception as exc:
                logger.warning("Skipping LightRAG stats for %s: %s", collection, exc)
        return {
            "entities_count": len(nodes),
            "relations_count": len(edges),
            "collections_covered": collections,
        }

    # ── 调试：系统信息 & 文件列表 ─────────────────────────────────

    def get_system_info(self) -> dict:
        """返回后端运行环境基础信息，供调试面板使用。"""
        import sys

        data_dir = (
            self._managed_documents_dir.parent if self._managed_documents_dir else Path("data")
        )
        source_cfg = self._config.get_source_store_config() if self._config else None
        db_file = source_cfg.db_filename if source_cfg else "knowledge_repository.db"
        return {
            "cwd": str(Path.cwd()),
            "data_dir": str(data_dir.resolve()),
            "db_file": db_file,
            "docs_dir": str((data_dir / "library").resolve()),
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        }

    def list_data_files(self, subdir: str = "") -> dict:
        """列出 data_dir 或其子目录的文件，路径严格限制在 data_dir 内。"""
        data_dir = (
            self._managed_documents_dir.parent if self._managed_documents_dir else Path("data")
        ).resolve()

        # 路径安全：拒绝包含 .. 的路径
        if ".." in subdir.replace("\\", "/").split("/"):
            raise ValueError("Path traversal not allowed")

        target = (data_dir / subdir).resolve()
        try:
            target.relative_to(data_dir)
        except ValueError:
            raise ValueError("Path is outside data directory")

        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {subdir!r}")

        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
            stat = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "type": "file" if item.is_file() else "dir",
                    "size_bytes": stat.st_size if item.is_file() else None,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        return {
            "path": str(target.relative_to(data_dir)),
            "entries": entries,
        }

    # ── HuggingFace 本地模型管理 ──────────────────────────────────

    def list_local_embedding_models(self) -> list[dict]:
        """列出 HuggingFace hub 缓存中的本地 embedding 模型目录。"""
        import os

        hf_cache = (
            Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"
        )
        if not hf_cache.is_dir():
            return []
        models = []
        for entry in sorted(hf_cache.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("models--"):
                continue
            raw_name = entry.name[len("models--") :]
            display_name = raw_name.replace("--", "/")
            size_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            try:
                mtime = max(f.stat().st_mtime for f in entry.rglob("*") if f.is_file())
                last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except ValueError:
                last_modified = None
            models.append(
                {
                    "name": display_name,
                    "dir_name": entry.name,
                    "size_bytes": size_bytes,
                    "last_modified": last_modified,
                    "path": str(entry),
                }
            )
        return models

    def delete_local_embedding_model(self, model_name: str) -> dict:
        """删除指定本地 embedding 模型缓存目录（不可逆）。

        model_name 格式为 org/model 或 model，只允许字母/数字/-/_/./ 。
        """
        import os
        import re
        import shutil

        if not re.fullmatch(r"[A-Za-z0-9\-_./]+", model_name) or ".." in model_name:
            raise ValueError("Invalid model name")
        hf_cache = (
            Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"
        )
        dir_name = "models--" + model_name.replace("/", "--")
        target = hf_cache / dir_name
        if not target.exists():
            raise FileNotFoundError(f"Model not found: {model_name!r}")
        target.relative_to(hf_cache)  # 二次路径安全确认
        shutil.rmtree(target)
        return {"deleted": model_name}

    def _persist_config_value(self, section: str, key: str, value: object) -> None:
        if self._config is not None:
            self._config.set_value(section, key, value)
        if self._config_persist is not None:
            self._config_persist(section, key, value)

    def _apply_rerank_runtime_config(self) -> None:
        if self._config is None:
            return
        from core.repository.reranker import build_reranker

        rerank_cfg = self._config.get_rerank_config()
        reranker = build_reranker(
            provider=rerank_cfg.provider,
            model=rerank_cfg.model,
            device=rerank_cfg.device,
            batch_size=rerank_cfg.batch_size,
            max_candidates=rerank_cfg.max_candidates,
        )
        # 同一实例同时供 default 研究路径与 deep_thinking 使用，热切换后两处都指向新实例。
        self._reranker = reranker
        if self._deep_thinking_orchestrator is not None:
            self._deep_thinking_orchestrator.update_reranker(reranker, rerank_cfg)
        logger.info(
            "reranker hot-swapped: provider=%s model=%s",
            rerank_cfg.provider,
            rerank_cfg.model,
        )

    def _current_config_value(self, section: str, key: str) -> object | None:
        if self._config is None:
            return None
        getters = {
            "vector_db": self._config.get_vector_db_config,
            "embedding": self._config.get_embedding_config,
            "ask": self._config.get_ask_agent_config,
            "rerank": self._config.get_rerank_config,
            "graph": self._config.get_graph_config,
            "r2_sync": self._config.get_r2_sync_config,
            "notion_sync": self._config.get_notion_sync_config,
            "source_store": self._config.get_source_store_config,
        }
        getter = getters.get(section)
        return getattr(getter(), key, None) if getter else None

    def _milvus_index_is_compatible(self) -> bool:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return False
        return bool(
            self._vector_store
            and self._embedding_provider
            and self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_milvus_compatible(self._embedding_fingerprint)
        )

    async def _milvus_retrieval_fallback_reason(self) -> str | None:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return None
        pending_count = len(await self._source_store.list_pending_reindex_documents())
        if not self._milvus_index_is_compatible():
            reason = ""
            if self._index_compatibility is not None:
                reason = self._index_compatibility.reason("milvus")
            return reason or "Milvus index is not compatible; rebuild index required."
        if pending_count:
            return f"{pending_count} document(s) still require Milvus reindex."
        return None

    def _lightrag_index_is_compatible(self, collection: str) -> bool:
        return bool(
            self._lightrag_registry
            and self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_lightrag_compatible(
                collection, self._embedding_fingerprint
            )
        )

    def _mark_milvus_incompatible(self, reason: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.mark_milvus_incompatible(reason)

    def _mark_lightrag_collection_incompatible(self, collection: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.remove_lightrag_collection(collection)

    async def _mark_document_needs_reindex(self, doc_id: str) -> None:
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return
        doc.needs_reindex = True
        await self._source_store.update_document(doc)

    async def _clear_document_needs_reindex(self, doc_id: str) -> None:
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return
        if doc.needs_reindex:
            doc.needs_reindex = False
            await self._source_store.update_document(doc)

    async def _run_milvus_data_cleaning(
        self,
        docs: list[SourceDocument],
        job: MilvusBuildJob | None,
        *,
        context: str,
    ) -> tuple[set[str], list[dict[str, str]]]:
        """在 Milvus 索引前显式执行 legacy chunk data cleaning。

        cleaning 只基于现有 `clean.md/pages.json` 重建 structural chunks；失败文档保留
        `needs_reindex=True` 并跳过后续向量 upsert，避免旧 chunks 进入 Milvus。
        """
        failed_doc_ids: set[str] = set()
        errors: list[dict[str, str]] = []
        if job is not None:
            job.stage = MILVUS_BUILD_STAGE_CLEANING
            job.total_clean_docs = 0

        rebuilder = getattr(self._ingest_manager, "rebuild_document_chunks_from_artifact", None)
        needs_rebuild = getattr(self._ingest_manager, "chunk_needs_rebuild", None)
        if not docs or not (callable(rebuilder) and callable(needs_rebuild)):
            return failed_doc_ids, errors

        cleaning_docs: list[SourceDocument] = []
        scan_failures: list[tuple[SourceDocument, Exception]] = []
        for doc in docs:
            try:
                chunks = await self._source_store.list_chunks(doc.doc_id)
                needs = needs_rebuild(doc.doc_id, chunks, doc.local_meta)
                if inspect.isawaitable(needs):
                    needs = await needs
                if needs:
                    cleaning_docs.append(doc)
            except Exception as exc:  # noqa: BLE001 - 单文档失败不应打断整批 rebuild
                scan_failures.append((doc, exc))

        if job is not None:
            job.total_clean_docs = len(cleaning_docs) + len(scan_failures)

        async def record_failure(doc: SourceDocument, exc: Exception) -> None:
            logger.error(
                "Milvus data cleaning failed for %s during %s: %s",
                doc.doc_id,
                context,
                exc,
            )
            await self._mark_document_needs_reindex(doc.doc_id)
            failed_doc_ids.add(doc.doc_id)
            error = {
                "doc_id": doc.doc_id,
                "stage": MILVUS_BUILD_STAGE_CLEANING,
                "error": str(exc),
            }
            errors.append(error)
            if job is not None:
                job.failed_docs += 1
                job.errors.append(error)

        for doc, exc in scan_failures:
            await record_failure(doc, exc)

        for doc in cleaning_docs:
            try:
                rebuilt = rebuilder(doc.doc_id)
                if inspect.isawaitable(rebuilt):
                    await rebuilt
                if job is not None:
                    job.processed_clean_docs += 1
            except Exception as exc:  # noqa: BLE001 - 单文档失败转 partial_failure
                await record_failure(doc, exc)

        return failed_doc_ids, errors

    async def _ensure_document_chunks_current(
        self, doc_id: str, chunks: list[DocumentChunk] | None = None
    ) -> list[DocumentChunk]:
        chunks = chunks if chunks is not None else await self._source_store.list_chunks(doc_id)
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return chunks
        rebuilder = getattr(self._ingest_manager, "rebuild_document_chunks_from_artifact", None)
        needs_rebuild = getattr(self._ingest_manager, "chunk_needs_rebuild", None)
        if not (callable(rebuilder) and callable(needs_rebuild)):
            return chunks
        try:
            if needs_rebuild(doc.doc_id, chunks, doc.local_meta):
                await rebuilder(doc.doc_id)
                return await self._source_store.list_chunks(doc_id)
        except FileNotFoundError as exc:
            logger.warning("Legacy chunk rebuild skipped for %s: %s", doc_id, exc)
        return chunks

    async def _index_document_chunks_with_retry(
        self, doc_id: str, collection: str, *, context: str
    ) -> int:
        chunks = await self._ensure_document_chunks_current(doc_id)
        if not chunks:
            return 0
        return await self._upsert_milvus_chunks_with_retry(
            chunks,
            collection=collection,
            context=f"{context}: doc={doc_id}",
        )

    async def _upsert_milvus_chunks_with_retry(
        self, chunks: list[DocumentChunk], *, collection: str, context: str
    ) -> int:
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

        doc_ids = sorted({chunk.doc_id for chunk in chunks})
        if hasattr(self._vector_store, "set_doc_collection_mapping"):
            for doc_id in doc_ids:
                self._vector_store.set_doc_collection_mapping(doc_id, collection)

        last_exc: Exception | None = None
        for attempt in range(1, MILVUS_INDEX_MAX_ATTEMPTS + 1):
            try:
                embeddings = await self._embedding_provider.embed_documents(
                    [chunk.text for chunk in chunks]
                )
                await self._vector_store.upsert_chunks(chunks, embeddings)
                if attempt > 1:
                    logger.info(
                        "Milvus indexing retry succeeded on attempt %d/%d: %s",
                        attempt,
                        MILVUS_INDEX_MAX_ATTEMPTS,
                        context,
                    )
                return len(chunks)
            except Exception as exc:
                last_exc = exc
                if attempt >= MILVUS_INDEX_MAX_ATTEMPTS:
                    break
                delay = MILVUS_INDEX_RETRY_DELAYS[
                    min(attempt - 1, len(MILVUS_INDEX_RETRY_DELAYS) - 1)
                ]
                logger.warning(
                    "Milvus indexing attempt %d/%d failed for %s: %s; retrying in %.1fs",
                    attempt,
                    MILVUS_INDEX_MAX_ATTEMPTS,
                    context,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"Milvus indexing failed after retries ({context}): {last_exc}")

    async def _mark_lightrag_pending(self, doc_id: str, collection: str) -> None:
        await self._source_store.set_lightrag_index_status(doc_id, collection, "pending")

    # ── Zotero 同步副作用回调（供 ZoteroSyncPipeline 注入）──────────

    async def _index_document(self, doc_id: str, collection: str) -> None:
        """把某文档的 chunk 嵌入并写入 Milvus（与 register_document 自动索引同语义）。"""
        if not (self._config and self._milvus_index_is_compatible()):
            await self._mark_document_needs_reindex(doc_id)
            return
        vdb = self._config.get_vector_db_config()
        if vdb.backend != "milvus" or not self._vector_store or not self._embedding_provider:
            return
        try:
            await self._index_document_chunks_with_retry(doc_id, collection, context="zotero")
            await self._clear_document_needs_reindex(doc_id)
        except Exception as exc:
            logger.error("Milvus indexing failed after retries for Zotero doc %s: %s", doc_id, exc)
            await self._mark_document_needs_reindex(doc_id)

    async def _remove_document_index(self, doc_id: str) -> None:
        """从 Milvus 移除某文档的全部 chunk（strict 脱管 / conservative 删除时调用）。"""
        if not self._vector_store:
            return
        try:
            chunks = await self._source_store.list_chunks(doc_id)
            ids = [c.chunk_id for c in chunks]
            if ids:
                await self._vector_store.delete_chunks(ids)
        except Exception as exc:
            logger.warning("Zotero remove index failed for %s: %s", doc_id, exc)

    async def _lightrag_cleanup(self, doc_id: str, collection: str) -> None:
        """删除某文档在 LightRAG workspace 的贡献（conservative 硬删除时调用）。"""
        if self._lightrag_registry is None:
            return
        try:
            await self._lightrag_registry.delete_doc(collection, doc_id)
        except Exception as exc:
            logger.warning("Zotero LRAG cleanup failed for %s: %s", doc_id, exc)

    # ── Zotero 同步公开门面 ──────────────────────────────────────

    async def get_zotero_config(self) -> dict[str, Any]:
        """返回 Zotero 同步配置 + 连接/数据目录/linked 探针状态（供设置与 sync 页）。"""
        from core.adapters.zotero import local_api
        from core.adapters.zotero import paths as zpaths
        from core.config import ZOTERO_ACCESS_SERVER, ZOTERO_STORAGE_LINKED

        if self._config is None:
            return {"enabled": False, "available": False}
        cfg = self._config.get_zotero_sync_config()
        resolved_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        out: dict[str, Any] = {
            "enabled": cfg.enabled,
            "access_mode": cfg.access_mode,
            "zotero_data_dir": cfg.zotero_data_dir,
            "resolved_data_dir": str(resolved_dir) if resolved_dir else "",
            "api_port": cfg.api_port,
            "storage_mode": cfg.storage_mode,
            "linked_root": cfg.linked_root,
            "sync_mode": cfg.sync_mode,
            "auto_sync_enabled": cfg.auto_sync_enabled,
            "auto_sync_interval_sec": cfg.auto_sync_interval_sec,
            "server_key_present": bool(self._zotero_server_key()),
            "server_key_masked": _mask_secret(self._zotero_server_key()),
            "server_user_id": "",
            "server_username": "",
            "server_access": {},
        }
        if cfg.access_mode != ZOTERO_ACCESS_SERVER:
            out["connection"] = await asyncio.to_thread(local_api.probe_connection, cfg.api_port)
        if self._zotero_pipeline is not None:
            try:
                availability = await asyncio.wait_for(
                    asyncio.to_thread(self._zotero_pipeline.is_available),
                    timeout=5.0,
                )
            except TimeoutError:
                availability = {
                    "available": False,
                    "access_mode": cfg.access_mode,
                    "reason": "Zotero availability probe timed out",
                }
            out["availability"] = availability
            if cfg.access_mode == ZOTERO_ACCESS_SERVER:
                out["server_user_id"] = str(availability.get("server_user_id") or "")
                out["server_username"] = str(availability.get("server_username") or "")
                access = availability.get("server_access")
                out["server_access"] = access if isinstance(access, dict) else {}
        if cfg.storage_mode == ZOTERO_STORAGE_LINKED:
            out["linked_probe"] = zpaths.probe_linked_root(cfg.linked_root)
        return out

    async def probe_zotero_local(self) -> dict[str, Any]:
        """本地离线探针：合并端口连通性 + zotero.sqlite 干读计数（供数据流面板调试）。"""
        from core.adapters.zotero import local_api

        if self._config is None:
            return {
                "connection": {"connected": False},
                "read": {"available": False, "reason": "未初始化"},
            }
        cfg = self._config.get_zotero_sync_config()
        connection = await asyncio.to_thread(local_api.probe_connection, cfg.api_port)
        if self._zotero_pipeline is None:
            read: dict[str, Any] = {"available": False, "reason": "Zotero 同步未启用或未装配"}
        else:
            read = await asyncio.to_thread(self._zotero_pipeline.probe_local_read)
        return {"connection": connection, "read": read}

    async def save_zotero_server_key(self, api_key: str) -> dict[str, Any]:
        """Validate and store Zotero Web API key without exposing plaintext again."""
        from core.adapters.zotero.web_api import (
            ZoteroWebApiClient,
            current_key_identity,
        )

        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("Zotero API key is required")
        if self._secret_store is None:
            raise RuntimeError("Secret store is unavailable")
        current_key_identity(ZoteroWebApiClient(cleaned).get_current_key())
        self._secret_store.set_secret(ZOTERO_SERVER_KEY_SECRET, cleaned)
        return await self.get_zotero_config()

    async def delete_zotero_server_key(self) -> dict[str, Any]:
        """Remove stored Zotero Web API key."""
        if self._secret_store is not None:
            self._secret_store.delete_secret(ZOTERO_SERVER_KEY_SECRET)
        return await self.get_zotero_config()

    def _zotero_server_key(self) -> str:
        if self._secret_store is not None:
            key = self._secret_store.get_secret(ZOTERO_SERVER_KEY_SECRET)
            if key:
                return key
        if self._config is None:
            return ""
        return self._config.get_zotero_sync_config().cloud_api_key

    async def sync_zotero_pull(self, incremental: bool = True) -> dict[str, Any]:
        """在后台启动一次 Zotero Pull 并立即返回任务快照（不再阻塞 HTTP 请求）。

        修复「失灵」：原实现 `await pull()` 整段阻塞（几十篇下载/清洗/embedding 数分钟易超时），
        且 `ZoteroSyncResult` 无 `status`、错误被静默吞掉。现改为全局单任务后台执行：已有 running
        任务直接返回当前快照；进度由 `ZoteroSyncPipeline.pull(progress=job)` 逐阶段/逐文档更新，
        前端经 `get_active_zotero_sync_job` 轮询；终态与错误由 `_run_zotero_pull` 写回。
        """
        if self._zotero_pipeline is None:
            return {"status": "error", "message": "Zotero 同步未启用或未装配"}
        current = self._zotero_sync_job
        if current is not None and current.status == ZOTERO_SYNC_RUNNING:
            return current.to_dict()

        job = ZoteroSyncJob(incremental=incremental)
        job.start()
        self._zotero_sync_job = job
        self._zotero_sync_task = asyncio.create_task(self._run_zotero_pull(job, incremental))
        return job.to_dict()

    async def _run_zotero_pull(self, job: ZoteroSyncJob, incremental: bool) -> None:
        """后台执行 pull，把终态与错误写回 job 及 `_last_zotero_sync`（后台任务不应抛出）。"""
        try:
            assert self._zotero_pipeline is not None
            result = await self._zotero_pipeline.pull(incremental=incremental, progress=job)
            if not result.errors:
                status = ZOTERO_SYNC_SUCCESS
            elif job.docs_processed > 0 or result.items_mirrored > 0:
                status = ZOTERO_SYNC_PARTIAL  # 有产出但部分失败（如个别文档未入向量库）。
            else:
                status = ZOTERO_SYNC_ERROR  # 整体失败（如快照不可用 / API key 缺失）。
            job.finish(status)
            # `_last_zotero_sync` 保持 ZoteroSyncResult 形状（供 /status 与前端摘要），仅补 status。
            payload = result.to_dict()
            payload["status"] = status
            if result.errors:
                payload["message"] = result.errors[0]
            if result.needs_milvus_rebuild:
                try:
                    payload["milvus_rebuild"] = await self.rebuild_vector_store()
                except Exception as exc:
                    logger.error("Zotero strict rebuild failed: %s", exc, exc_info=True)
                    payload["milvus_rebuild_error"] = str(exc)
            self._last_zotero_sync = payload
            logger.info("Zotero sync job %s finished: status=%s", job.job_id, status)
        except asyncio.CancelledError:
            job.finish(ZOTERO_SYNC_ERROR)
            job.note_error("cancelled")
            self._last_zotero_sync = {"status": ZOTERO_SYNC_ERROR, "message": "cancelled"}
            raise
        except Exception as exc:  # noqa: BLE001 - 终态统一兜底，后台任务不应抛出
            logger.error("Zotero sync job failed: %s", exc, exc_info=True)
            job.finish(ZOTERO_SYNC_ERROR)
            job.note_error(str(exc))
            self._last_zotero_sync = {"status": ZOTERO_SYNC_ERROR, "message": str(exc)}

    def get_active_zotero_sync_job(self) -> dict[str, Any] | None:
        """返回当前需展示的 Zotero 同步任务快照（无则 None）。

        running → 返回；success / partial_failure / error → 短暂返回，供前端捕获终态 notice；
        无任务或终态展示窗口过期 → 返回 None。
        """
        job = self._zotero_sync_job
        if job is None:
            return None
        if job.status == ZOTERO_SYNC_RUNNING:
            return job.to_dict()
        if (
            job.finished_at is not None
            and time.monotonic() - job.finished_at <= ZOTERO_SYNC_TERMINAL_VISIBLE_SECONDS
        ):
            return job.to_dict()
        return None

    async def get_zotero_sync_status(self) -> dict[str, Any]:
        """返回上一次 Zotero Pull 的结果摘要（含 status；无则空）。"""
        return dict(self._last_zotero_sync)

    async def _sync_milvus_collection_move(self, doc_id: str, collection: str) -> None:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return
        chunks = await self._source_store.list_chunks(doc_id)
        if not chunks:
            return
        if not self._milvus_index_is_compatible():
            await self._mark_document_needs_reindex(doc_id)
            return
        assert self._vector_store is not None
        assert self._embedding_provider is not None
        try:
            await self._vector_store.delete_chunks([chunk.chunk_id for chunk in chunks])
            await self._upsert_milvus_chunks_with_retry(
                chunks,
                collection=collection,
                context=f"collection move: doc={doc_id}",
            )
            await self._clear_document_needs_reindex(doc_id)
        except Exception as exc:
            logger.error("Milvus collection move sync failed for %s: %s", doc_id, exc)
            await self._mark_document_needs_reindex(doc_id)

    async def _invalidate_embedding_indexes(self, reason: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.mark_all_incompatible(reason)
        for doc in await self._source_store.list_documents():
            doc.needs_reindex = True
            await self._source_store.update_document(doc)
            await self._mark_lightrag_pending(doc.doc_id, doc.collection)
        if self._config:
            self._config.add_diagnostic(
                "Embedding configuration changed; restart and rebuild Milvus/LightRAG indexes."
            )

    def _unlink_managed_document(self, file_path: str) -> None:
        """删除制品包：移除 library/<document_id>/ 整个目录（含 clean.md/pages.json/meta.json）。

        安全边界：仅当原件路径落在 managed 根（library/）内才删除；删除其所在制品包目录，
        而非仅删 original.pdf，避免残留派生制品。
        """
        if self._managed_documents_dir is None:
            return
        import shutil

        managed_root = self._managed_documents_dir.resolve()
        try:
            path = Path(file_path).resolve()
            path.relative_to(managed_root)
            bundle_dir = path.parent
            # 仅当 parent 是 managed 根下的子目录（制品包目录）时整体删除。
            if bundle_dir != managed_root and bundle_dir.parent == managed_root:
                shutil.rmtree(bundle_dir, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to remove managed document %s: %s", file_path, exc)


def _now() -> datetime:
    """统一的 UTC aware 时间戳。"""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


__all__ = ["HighPrecisionQueryError", "KnowledgeRepositoryApi", "LightRAGNotReadyError"]
