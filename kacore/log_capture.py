"""内存日志与运行事件捕获（横切工具，无业务依赖）。

将 Python logging 与前端运行事件存入同一个环形缓冲区，供 /api/logs 端点读取。
线程安全：使用 threading.Lock 保护 deque。

字段契约（每条记录）：
- seq：进程内严格递增序号，用于可靠增量游标与稳定去重。
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
from typing import Any, Protocol

LOG_BUFFER_MAXLEN = 2000

# ── 噪声控制 ──────────────────────────────────────────────────

# 高频三方 logger：低级别不进入 Web 缓冲，但 WARNING/ERROR 是故障的一手证据，必须保留。
_WARN_ONLY_PREFIXES = (
    "aiohttp.access",
    "aiohttp.server",
    "aiohttp.web",
    "charset_normalizer",
    "httpx",
    "hpack",
    "httpcore",
    "urllib3",
    "asyncio",
    "filelock",
    "grpc",
    "PIL",
    # 模型下载/推理栈平时话痨，但出问题时是唯一的一手证据。
    # 典型场景：模型名错误时 huggingface_hub 的 401 必须保留。
    "sentence_transformers",
    "huggingface_hub",
    "transformers",
    "torch",
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
            # 模型下载栈的 WARNING+ 归入 embedding，与本地 provider 的日志排在一起。
            "sentence_transformers",
            "huggingface_hub",
            "transformers",
            "torch",
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


class RuntimeEventSink(Protocol):
    """框架无关运行事件写入契约；实现不得把事件反向写入宿主终端。"""

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
        """写入一条结构化运行事件。"""
        ...


class MemoryLogHandler(logging.Handler):
    """将日志记录存入内存环形缓冲区。

    记录同时保留旧字段（ts/level/name/msg）与结构化字段
    （location/exc/category/source/operation/status/metadata），便于 terminal 定位与筛选。
    """

    def __init__(self, maxlen: int = LOG_BUFFER_MAXLEN) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._next_seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        # 高频三方栈只放行 WARNING+（401、磁盘满、连接失败等一手证据）。
        if record.name.startswith(_WARN_ONLY_PREFIXES) and record.levelno < logging.WARNING:
            return
        # 三方 DEBUG 噪声（faiss/pymilvus 等）不进缓冲区；项目自有 DEBUG 保留。
        if record.levelno <= logging.DEBUG and not record.name.startswith(_PROJECT_PREFIXES):
            return
        exc = ""
        metadata: dict[str, Any] = {}
        try:
            msg = record.getMessage()
            if record.exc_info:
                import traceback

                exc = "".join(traceback.format_exception(*record.exc_info)).rstrip()
                metadata.update(_exception_metadata(record, exc))
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
                metadata=metadata,
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
            self._next_seq += 1
            entry["seq"] = self._next_seq
            self._records.append(entry)

    def get_lines(self, after_ts: float = 0.0, limit: int = 200) -> list[dict[str, Any]]:
        """兼容旧调用：返回 after_ts 之后最多 limit 条日志。"""
        return self.get_batch(after_ts=after_ts, limit=limit)["lines"]

    def get_batch(
        self,
        *,
        after_seq: int | None = None,
        after_ts: float = 0.0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """返回增量日志与游标状态，并显式报告因轮转/限制造成的缺口。"""
        safe_limit = max(1, min(int(limit), LOG_BUFFER_MAXLEN))
        with self._lock:
            records = list(self._records)
            latest_seq = self._next_seq
        oldest_seq = int(records[0]["seq"]) if records else latest_seq
        if after_seq is not None:
            filtered = [r for r in records if int(r["seq"]) > after_seq]
            lines = filtered[-safe_limit:]
            if lines:
                dropped_count = max(0, int(lines[0]["seq"]) - after_seq - 1)
            else:
                dropped_count = max(0, oldest_seq - after_seq - 1) if records else 0
        else:
            filtered = [r for r in records if r["ts"] > after_ts]
            lines = filtered[-safe_limit:]
            dropped_count = max(0, len(filtered) - len(lines))
        return {
            "lines": lines,
            "oldest_seq": oldest_seq,
            "latest_seq": latest_seq,
            "dropped_count": dropped_count,
        }


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
    event_metadata = dict(metadata)
    return {
        "seq": 0,
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
        "elapsed_ms": event_metadata.pop("elapsed_ms", None),
        "metadata": event_metadata,
    }


def _exception_metadata(record: logging.LogRecord, exc_text: str) -> dict[str, Any]:
    """提取异常链根因，并为已知且可安全处理的问题提供诊断建议。"""
    exc = record.exc_info[1] if record.exc_info else None
    chain: list[BaseException] = []
    seen: set[int] = set()
    while isinstance(exc, BaseException) and id(exc) not in seen:
        seen.add(id(exc))
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    metadata: dict[str, Any] = {}
    if chain:
        metadata["exception_type"] = type(chain[0]).__name__
        metadata["root_cause_type"] = type(chain[-1]).__name__
    diagnostic_text = f"{record.name} {record.getMessage()} {exc_text}".lower()
    if (
        "datadirlockederror" in diagnostic_text
        or "another process holds the lock" in diagnostic_text
    ):
        metadata.update(
            {
                "diagnostic_code": "milvus_data_dir_locked",
                "hint": (
                    "Milvus 数据目录正被其他进程占用；请先确认没有第二个 AstrBot/插件进程，"
                    "正常停止占用者后重启。若确认无重复进程，再检查目录 ACL 或安全软件；"
                    "不要直接删除锁文件或向量数据目录。"
                ),
            }
        )
    return metadata


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


def install(maxlen: int = LOG_BUFFER_MAXLEN) -> MemoryLogHandler:
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


__all__ = ["LOG_BUFFER_MAXLEN", "MemoryLogHandler", "RuntimeEventSink", "install"]
