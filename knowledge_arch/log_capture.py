"""内存日志与运行事件捕获（横切工具，无业务依赖）。

将 Python logging 与前端运行事件存入同一个环形缓冲区，供 /api/logs 端点读取。
线程安全：使用 threading.Lock 保护 deque。

字段契约（每条记录）：
- ts/level/name/msg：基础字段（向后兼容）。
- location：产生日志的代码位置 ``module:lineno``（事件来源为空串）。
- exc：完整 traceback 文本（无异常时为空串），与 msg 分离供前端折叠。
- category/source/operation/status/metadata：结构化字段，供 terminal 分类筛选。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

# ── 噪声控制 ──────────────────────────────────────────────────

# 完全丢弃的三方 logger（高频且对本插件 debug 无信号）。
_SKIP_PREFIXES = (
    "aiohttp.access",
    "aiohttp.server",
    "aiohttp.web",
    "charset_normalizer",
    "httpx",
    "hpack",
    "httpcore",
    "urllib3",
    "asyncio",
    "sentence_transformers",
    "filelock",
    "grpc",
    "PIL",
)

# 项目自有 logger 前缀：DEBUG 级别予以保留；名单外的三方 DEBUG 直接丢弃。
_PROJECT_PREFIXES = (
    "astrbot_plugin_knowledge_repository",
    "AstrBotKnowledgeBaseReader",
    "CachedEmbeddingProvider",
    "DeepThinking",
    "EmbeddingProviderFactory",
    "EnhancedRecall",
    "EventHandler",
    "ExternalEmbeddingProvider",
    "IndexCompatibilityStore",
    "KnowledgeRepositoryApi",
    "KRWebServer",
    "LightRAGCore",
    "LLMAdapter",
    "LocalEmbeddingProvider",
    "log_capture",
    "MilvusLiteVectorStore",
    "NotionMCPAdapter",
    "NotionSyncTarget",
    "PluginInitializer",
    "QuotaManager",
    "R2SyncTarget",
    "Reranker",
    "ResearchService",
    "RetrievalOrchestrator",
    "RuntimeConfigStore",
    "SyncPipeline",
)

# ── 分类映射 ──────────────────────────────────────────────────

# logger 名前缀 → 分类（首选，稳定）；未命中时回退消息关键词猜测。
_CATEGORY_BY_PREFIX: tuple[tuple[tuple[str, ...], str], ...] = (
    (("LightRAGCore", "lightrag"), "graph"),
    (("LLMAdapter", "Reranker", "DeepThinking", "EnhancedRecall"), "llm"),
    (
        (
            "LocalEmbeddingProvider",
            "ExternalEmbeddingProvider",
            "CachedEmbeddingProvider",
            "EmbeddingProviderFactory",
        ),
        "embedding",
    ),
    (("RetrievalOrchestrator", "MilvusLiteVectorStore", "AstrBotKnowledgeBaseReader"), "retrieval"),
    (("KRWebServer",), "web"),
    (("SyncPipeline", "Notion", "R2", "Zotero"), "sync"),
    (("IngestManager", "MarkdownExtractor", "CategoryManager"), "ingest"),
    (
        (
            "PluginInitializer",
            "RuntimeConfigStore",
            "QuotaManager",
            "IndexCompatibilityStore",
            "MigrationRunner",
            "log_capture",
            "astrbot_plugin_knowledge_repository",
        ),
        "system",
    ),
)

# 消息关键词 → 分类（fallback，覆盖 KnowledgeRepositoryApi 等跨领域 logger）。
_CATEGORY_BY_KEYWORD: tuple[tuple[tuple[str, ...], str], ...] = (
    (("lightrag", "graph"), "graph"),
    (("ingest", "upload", "chunk"), "ingest"),
    (("embedding",), "embedding"),
    (("search", "query", "rerank", "recall", "rrf", "vector", "milvus", "rebuild"), "retrieval"),
    (("zotero", "notion", "backup", "sync"), "sync"),
    (("llm", "lmstudio"), "llm"),
    (("dependency", "install", "config"), "system"),
)


class MemoryLogHandler(logging.Handler):
    """将日志记录存入内存环形缓冲区。

    记录同时保留旧字段（ts/level/name/msg）与结构化字段
    （location/exc/category/source/operation/status/metadata），便于 terminal 定位与筛选。
    """

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_SKIP_PREFIXES):
            return
        # 三方 DEBUG 噪声（faiss/pymilvus 等）不进缓冲区；项目自有 DEBUG 保留。
        if record.levelno <= logging.DEBUG and not record.name.startswith(_PROJECT_PREFIXES):
            return
        exc = ""
        try:
            msg = record.getMessage()
            if record.exc_info:
                import traceback

                exc = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        except Exception:
            msg = str(record.msg)
        self._append(
            _make_entry(
                ts=record.created,
                level=record.levelname,
                name=record.name,
                msg=msg,
                location=f"{record.module}:{record.lineno}",
                exc=exc,
                source="backend",
                category=_categorize(record.name, msg),
                operation=_operation(record.name, msg),
                status=_status_from_level(record.levelname),
                metadata={},
            )
        )

    def add_event(
        self,
        *,
        source: str,
        category: str,
        operation: str,
        status: str,
        msg: str,
        level: str = "INFO",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一个非 logging 来源的结构化运行事件。"""
        self._append(
            _make_entry(
                ts=time.time(),
                level=level,
                name=f"{source}.{category}",
                msg=msg,
                location="",
                exc="",
                source=source,
                category=category,
                operation=operation,
                status=status,
                metadata=metadata or {},
            )
        )

    def _append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(entry)

    def get_lines(self, after_ts: float = 0.0, limit: int = 200) -> list[dict[str, Any]]:
        """返回 after_ts 之后的日志行，最多 limit 条（按时间升序）。"""
        with self._lock:
            records = list(self._records)
        filtered = [r for r in records if r["ts"] > after_ts]
        return filtered[-limit:]


def _make_entry(
    *,
    ts: float,
    level: str,
    name: str,
    msg: str,
    location: str,
    exc: str,
    source: str,
    category: str,
    operation: str,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ts": ts,
        "level": level,
        "name": name,
        "msg": msg,
        "location": location,
        "exc": exc,
        "source": source,
        "category": category,
        "operation": operation,
        "status": status,
        "elapsed_ms": metadata.pop("elapsed_ms", None),
        "metadata": metadata,
    }


def _status_from_level(level: str) -> str:
    if level in {"ERROR", "CRITICAL"}:
        return "error"
    if level == "WARNING":
        return "warning"
    return "ok"


def _categorize(name: str, msg: str) -> str:
    for prefixes, category in _CATEGORY_BY_PREFIX:
        if name.startswith(prefixes):
            return category
    text = f"{name} {msg}".lower()
    for keywords, category in _CATEGORY_BY_KEYWORD:
        if any(k in text for k in keywords):
            return category
    if name.startswith(_PROJECT_PREFIXES):
        return "system"
    return "other"


def _operation(name: str, msg: str) -> str:
    text = msg.lower()
    if "ainsert" in text or "build" in text:
        return "build"
    if "aquery" in text or "query" in text:
        return "query"
    if "upload" in text:
        return "upload"
    if "delete" in text:
        return "delete"
    if "install" in text:
        return "install"
    return name.split(".")[-1] or "log"


def install(maxlen: int = 1000) -> MemoryLogHandler:
    """安装 MemoryLogHandler 到 root logger 并返回句柄。

    幂等：若 root logger 上已有同类 handler 则直接返回已有实例。
    """
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, MemoryLogHandler):
            return h

    handler = MemoryLogHandler(maxlen=maxlen)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)

    logging.getLogger("log_capture").info("MemoryLogHandler installed (maxlen=%d)", maxlen)
    return handler


__all__ = ["MemoryLogHandler", "install"]
