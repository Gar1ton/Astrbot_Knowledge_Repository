"""能力与可选依赖管理 API 子门面。

本 mixin 只暴露系统能力查询、依赖列表、安装与重检能力；运行时依赖由
KnowledgeRepositoryApi 通过构造器注入。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.capabilities import dependency_statuses, detect_capabilities, resolve_install_spec
from core.milvus_build import (
    MILVUS_BUILD_RUNNING,
    MILVUS_BUILD_STAGE_CLEANING,
    MILVUS_BUILD_STAGE_FINALIZING,
    MILVUS_BUILD_STAGE_INDEXING,
)

if TYPE_CHECKING:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.milvus_build import MilvusBuildJob
    from core.pipelines.zotero_sync_pipeline import ZoteroSyncPipeline
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.vector_store.base import VectorStore

logger = logging.getLogger("KnowledgeRepositoryApi")


class CapabilitiesApiMixin:
    """系统能力查询与可选依赖安装/重检；组合进 KnowledgeRepositoryApi 使用。"""

    _config: Config | None
    _source_store: SourceDocumentStore
    _vector_store: VectorStore | None
    _embedding_provider: EmbeddingProvider | None
    _index_compatibility: IndexCompatibilityStore | None
    _embedding_fingerprint: str | None
    _zotero_pipeline: ZoteroSyncPipeline | None
    _milvus_build_job: MilvusBuildJob | None

    async def get_capabilities(self) -> dict[str, Any]:
        """返回数据流各环节、依赖状态与运行态诊断。"""
        if self._config is None:
            raise NotImplementedError("get_capabilities: config unavailable")
        data = detect_capabilities(self._config)
        await self._overlay_milvus_runtime_health(data)
        self._overlay_zotero_availability(data)
        self._overlay_reranker_runtime_status(data)
        return data

    def list_dependencies(self) -> list[dict[str, Any]]:
        """列出可选依赖及其安装版本状态。"""
        return dependency_statuses()

    async def recheck_dependencies(self) -> dict[str, Any]:
        """清除 import 缓存后重新探测，并返回最新能力快照。"""
        import importlib

        importlib.invalidate_caches()
        if self._config is None:
            return {"dependencies": dependency_statuses()}
        data = detect_capabilities(self._config)
        await self._overlay_milvus_runtime_health(data)
        self._overlay_zotero_availability(data)
        self._overlay_reranker_runtime_status(data)
        return data

    def _overlay_reranker_runtime_status(self, data: dict[str, Any]) -> None:
        orchestrator = getattr(self, "_deep_thinking_orchestrator", None)
        if orchestrator is None:
            return
        status = getattr(orchestrator, "reranker_status", None)
        if status is None:
            return
        for stage in data.get("pipeline", []):
            if not isinstance(stage, dict) or stage.get("id") != "ask":
                continue
            detail = stage.setdefault("detail", {})
            if not isinstance(detail, dict):
                detail = {}
                stage["detail"] = detail
            detail["rerank_runtime"] = status
            detail["rerank_status"] = status.get("status", detail.get("rerank_status"))
            if status.get("model"):
                detail["rerank_model"] = status.get("model")
            if status.get("provider"):
                detail["rerank_provider"] = status.get("provider")
            if status.get("status") == "failed":
                stage["status"] = "degraded"
            return

    def _overlay_zotero_availability(self, data: dict[str, Any]) -> None:
        """若 Zotero 已启用但数据目录探针未就绪，将状态降为 degraded（黄色）。"""
        if getattr(self, "_zotero_pipeline", None) is None:
            return
        for stage in data.get("pipeline", []):
            if not isinstance(stage, dict) or stage.get("id") != "zotero":
                continue
            if stage.get("status") != "ready":
                return
            avail = self._zotero_pipeline.is_available()
            if not avail.get("available", False):
                stage["status"] = "degraded"
                detail = stage.setdefault("detail", {})
                if isinstance(detail, dict):
                    detail["availability_reason"] = avail.get("reason", "")
            return

    async def _overlay_milvus_runtime_health(self, data: dict[str, Any]) -> None:
        """把 Milvus 的真实可检索状态叠加到静态能力快照。"""
        if self._config is None or self._config.get_vector_db_config().backend != "milvus":
            return

        health = await self._milvus_runtime_health()
        for stage in data.get("pipeline", []):
            if not isinstance(stage, dict):
                continue
            detail = stage.setdefault("detail", {})
            if not isinstance(detail, dict):
                detail = {}
                stage["detail"] = detail

            if stage.get("id") == "vector_store":
                detail.update(health)
                if health["rebuild_required"]:
                    stage["status"] = "degraded"
            elif stage.get("id") == "retrieval":
                detail["milvus_reason"] = health["reason"]
                detail["milvus_rebuild_required"] = health["rebuild_required"]
                if health["rebuild_required"]:
                    engines = detail.get("engines")
                    if isinstance(engines, list):
                        detail["engines"] = [engine for engine in engines if engine != "milvus"]
                    stage["status"] = "degraded"
            elif stage.get("id") == "ask" and health["rebuild_required"]:
                detail["fallback_reason"] = health["reason"]

    async def _milvus_runtime_health(self) -> dict[str, Any]:
        docs = await self._source_store.list_documents()
        pending_count = sum(1 for doc in docs if getattr(doc, "needs_reindex", False))
        chunk_count = 0
        for doc in docs:
            chunk_count += len(await self._source_store.list_chunks(doc.doc_id))

        compatible = bool(
            self._vector_store
            and self._embedding_provider
            and self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_milvus_compatible(self._embedding_fingerprint)
        )
        reason = ""
        if self._vector_store is None:
            reason = "Milvus vector store is not initialized."
        elif self._embedding_provider is None:
            reason = "Embedding provider is not initialized."
        elif self._index_compatibility is None or not self._embedding_fingerprint:
            reason = "Milvus index compatibility state is unavailable."
        elif not compatible:
            reason = (
                self._index_compatibility.reason("milvus")
                or "Milvus index is not compatible with the active embedding."
            )
        elif pending_count:
            reason = f"{pending_count} document(s) still require Milvus reindex."

        # 构建进行中强制保持 degraded（黄）：避免最后一个文档清除 needs_reindex 后过早变绿。
        build_job = getattr(self, "_milvus_build_job", None)
        building = bool(build_job is not None and build_job.status == MILVUS_BUILD_RUNNING)
        build_stage = ""
        build_progress_percent = 0
        if building and build_job is not None:
            snapshot = build_job.to_dict()
            build_stage = str(snapshot.get("stage") or "")
            build_progress_percent = int(snapshot.get("progress_percent") or 0)
            if build_stage == MILVUS_BUILD_STAGE_CLEANING:
                done = build_job.processed_clean_docs + build_job.failed_docs
                total = build_job.total_clean_docs or build_job.total_docs
                reason = f"正在清洗数据…（{done}/{total}，{build_progress_percent}%）"
            elif build_stage == MILVUS_BUILD_STAGE_INDEXING:
                done = build_job.processed_index_docs
                total = build_job.total_index_docs or build_job.total_docs
                reason = f"正在构建向量库索引…（{done}/{total}，{build_progress_percent}%）"
            elif build_stage == MILVUS_BUILD_STAGE_FINALIZING:
                reason = f"正在收尾向量库构建…（{build_progress_percent}%）"
            else:
                done = build_job.processed_docs + build_job.failed_docs
                reason = f"正在构建向量库索引…（{done}/{build_job.total_docs}）"

        return {
            "compatible": compatible,
            "rebuild_required": bool(reason or pending_count or building),
            "pending_reindex_count": pending_count,
            "document_count": len(docs),
            "chunk_count": chunk_count,
            "reason": reason,
            "building": building,
            "build_stage": build_stage,
            "build_progress_percent": build_progress_percent,
        }

    async def install_dependency(self, package: str) -> dict[str, Any]:
        """安装白名单内可选依赖，并把 pip 输出转发到 logger。"""
        spec = resolve_install_spec(package)
        return await self._run_pip_install(spec)

    async def _run_pip_install(self, spec: str) -> dict[str, Any]:
        """以当前解释器运行 pip install。"""
        import sys

        logger.info("Installing optional dependency: %s", spec)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                spec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:
            logger.error("Failed to launch pip for %s: %s", spec, exc)
            return {"status": "error", "package": spec, "message": str(exc)}

        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                logger.info("[pip] %s", line)
        returncode = await proc.wait()
        ok = returncode == 0
        if ok:
            logger.info("pip install succeeded: %s (restart plugin to load)", spec)
        else:
            logger.error("pip install failed (exit %s): %s", returncode, spec)
        return {
            "status": "ok" if ok else "error",
            "package": spec,
            "returncode": returncode,
            "restart_required": ok,
            "message": (
                "已安装，需重启插件生效；Docker 部署请注意依赖持久化。"
                if ok
                else f"安装失败，退出码 {returncode}，详见终端日志。"
            ),
        }


__all__ = ["CapabilitiesApiMixin"]
