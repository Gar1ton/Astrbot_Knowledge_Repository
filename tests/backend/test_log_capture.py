"""单元测试：MemoryLogHandler（core/log_capture.py）。"""

from __future__ import annotations

import logging
from threading import Thread

from kacore.log_capture import MemoryLogHandler, _categorize


def _record(
    name: str = "TestLogger",
    level: int = logging.INFO,
    msg: str = "hello",
    lineno: int = 42,
    exc_info=None,
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname="/project/core/some_module.py",
        lineno=lineno,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )


# ── 分类：logger 名前缀优先 ──────────────────────────────────


def test_categorize_by_logger_prefix():
    assert _categorize("LightRAGCore", "anything") == "graph"
    assert _categorize("lightrag", "anything") == "graph"
    assert _categorize("LLMAdapter", "anything") == "llm"
    assert _categorize("Reranker", "anything") == "llm"
    assert _categorize("LocalEmbeddingProvider", "anything") == "embedding"
    assert _categorize("RetrievalOrchestrator", "anything") == "retrieval"
    assert _categorize("MilvusLiteVectorStore", "anything") == "retrieval"
    assert _categorize("KRWebServer", "anything") == "web"
    assert _categorize("SyncPipeline", "anything") == "sync"
    assert _categorize("NotionSyncTarget", "anything") == "sync"
    assert _categorize("PluginInitializer", "anything") == "system"


def test_categorize_keyword_fallback_for_cross_domain_logger():
    # KnowledgeRepositoryApi 覆盖多领域，靠消息关键词回退
    assert _categorize("KnowledgeRepositoryApi", "Document ingest start: title='x'") == "ingest"
    assert _categorize("KnowledgeRepositoryApi", "search_kb: collection='a' top_k=5") == "retrieval"
    assert _categorize("KnowledgeRepositoryApi", "Zotero annotations unavailable") == "sync"
    # 项目 logger 无关键词命中 → system；未知三方 logger → other
    assert _categorize("KnowledgeRepositoryApi", "plain message") == "system"
    assert _categorize("some.third.party", "plain message") == "other"


# ── emit：location / exc / 降噪 ──────────────────────────────


def test_emit_captures_location():
    handler = MemoryLogHandler()
    handler.emit(_record(lineno=123))
    [entry] = handler.get_lines()
    assert entry["location"] == "some_module:123"
    assert entry["source"] == "backend"


def test_emit_separates_traceback_from_msg():
    handler = MemoryLogHandler()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        handler.emit(_record(msg="operation failed", exc_info=sys.exc_info()))
    [entry] = handler.get_lines()
    assert entry["msg"] == "operation failed"
    assert "ValueError: boom" in entry["exc"]
    assert "Traceback" in entry["exc"]


def test_emit_drops_third_party_debug_keeps_project_debug():
    handler = MemoryLogHandler()
    handler.emit(_record(name="faiss.loader", level=logging.DEBUG))
    assert handler.get_lines() == []
    handler.emit(_record(name="faiss.loader", level=logging.INFO))
    assert len(handler.get_lines()) == 1
    handler.emit(_record(name="LightRAGCore", level=logging.DEBUG))
    assert len(handler.get_lines()) == 2


def test_emit_drops_noisy_chatter_but_keeps_warnings_and_errors():
    handler = MemoryLogHandler()
    handler.emit(_record(name="httpx", level=logging.INFO))
    handler.emit(_record(name="aiohttp.access", level=logging.WARNING, msg="slow client"))
    handler.emit(_record(name="aiohttp.server", level=logging.ERROR, msg="connection failed"))
    assert [line["msg"] for line in handler.get_lines()] == ["slow client", "connection failed"]


# ── add_event / get_lines ────────────────────────────────────


def test_add_event_structure():
    handler = MemoryLogHandler()
    handler.add_event(
        source="frontend",
        category="toast",
        operation="notify",
        status="error",
        level="ERROR",
        msg="upload failed",
        metadata={"route": "/documents", "elapsed_ms": 12.5},
    )
    [entry] = handler.get_lines()
    assert entry["name"] == "frontend.toast"
    assert entry["location"] == ""
    assert entry["exc"] == ""
    assert entry["status"] == "error"
    assert entry["elapsed_ms"] == 12.5
    assert entry["metadata"] == {"route": "/documents"}


def test_get_lines_after_and_limit():
    handler = MemoryLogHandler()
    for i in range(5):
        handler.add_event(
            source="backend", category="system", operation="op",
            status="ok", msg=f"m{i}",
        )
    lines = handler.get_lines()
    assert [line["msg"] for line in lines] == ["m0", "m1", "m2", "m3", "m4"]
    after = lines[1]["ts"]
    assert all(line["ts"] > after for line in handler.get_lines(after_ts=after))
    assert [line["msg"] for line in handler.get_lines(limit=2)] == ["m3", "m4"]


def test_ring_buffer_maxlen():
    handler = MemoryLogHandler(maxlen=3)
    for i in range(5):
        handler.emit(_record(msg=f"m{i}"))
    assert [line["msg"] for line in handler.get_lines()] == ["m2", "m3", "m4"]


def test_status_from_level():
    handler = MemoryLogHandler()
    handler.emit(_record(level=logging.ERROR))
    handler.emit(_record(level=logging.WARNING))
    handler.emit(_record(level=logging.INFO))
    statuses = [line["status"] for line in handler.get_lines()]
    assert statuses == ["error", "warning", "ok"]


# ── 模型下载栈：WARNING+ 必须留下（v1.0.9）──────────────────────


def test_model_stack_warnings_are_kept_but_chatter_is_dropped():
    """回归：`sentence_transformers`/`huggingface_hub` 曾被整体丢弃。

    本地模型名写错时 huggingface_hub 的 401 是唯一的一手证据，被丢掉后终端页只剩「卡住」。
    契约：这些 logger 的 INFO/DEBUG 仍然不进缓冲区，WARNING+ 必须进。
    """
    handler = MemoryLogHandler()
    handler.emit(_record(name="sentence_transformers", level=logging.INFO, msg="chatter"))
    handler.emit(
        _record(name="huggingface_hub.file_download", level=logging.INFO, msg="downloading")
    )
    handler.emit(
        _record(
            name="huggingface_hub.utils._http",
            level=logging.ERROR,
            msg="401 Client Error: Unauthorized for url",
        )
    )

    lines = handler.get_lines()
    assert [line["msg"] for line in lines] == ["401 Client Error: Unauthorized for url"]
    assert lines[0]["category"] == "embedding"


# ── v1.0.10：严格序号、缺口与异常诊断 ───────────────────────────


def test_sequence_cursor_is_monotonic_and_reports_rotation_gap():
    handler = MemoryLogHandler(maxlen=3)
    for i in range(5):
        handler.emit(_record(msg=f"m{i}"))

    batch = handler.get_batch(after_seq=0, limit=2)
    assert [line["seq"] for line in batch["lines"]] == [4, 5]
    assert [line["msg"] for line in batch["lines"]] == ["m3", "m4"]
    assert batch["oldest_seq"] == 3
    assert batch["latest_seq"] == 5
    assert batch["dropped_count"] == 3

    incremental = handler.get_batch(after_seq=4, limit=10)
    assert [line["seq"] for line in incremental["lines"]] == [5]
    assert incremental["dropped_count"] == 0


def test_sequence_is_unique_under_concurrent_appends():
    handler = MemoryLogHandler()

    def emit_batch(worker: int) -> None:
        for item in range(100):
            handler.emit(_record(msg=f"{worker}:{item}"))

    threads = [Thread(target=emit_batch, args=(worker,)) for worker in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    seqs = [line["seq"] for line in handler.get_lines(limit=1000)]
    assert seqs == list(range(1, 501))


def test_sequence_cursor_does_not_depend_on_unique_timestamps():
    handler = MemoryLogHandler()
    first = _record(msg="first")
    second = _record(msg="second")
    first.created = second.created = 123.0
    handler.emit(first)
    handler.emit(second)

    initial = handler.get_batch(after_seq=0)
    assert [line["seq"] for line in initial["lines"]] == [1, 2]
    assert [line["msg"] for line in handler.get_batch(after_seq=1)["lines"]] == ["second"]


def test_event_metadata_is_copied_not_mutated():
    handler = MemoryLogHandler()
    metadata = {"elapsed_ms": 12.5, "request_id": "req"}
    handler.add_event(
        source="web", category="web", operation="http_request",
        status="ok", msg="done", metadata=metadata,
    )
    assert metadata == {"elapsed_ms": 12.5, "request_id": "req"}


def test_milvus_data_dir_lock_gets_actionable_diagnostic():
    class DataDirLockedError(RuntimeError):
        pass

    handler = MemoryLogHandler()
    try:
        try:
            raise PermissionError("denied")
        except PermissionError as cause:
            raise DataDirLockedError("another process holds the lock on vector_store.db") from cause
    except DataDirLockedError:
        import sys

        handler.emit(
            _record(
                name="milvus_lite.server_manager",
                level=logging.ERROR,
                msg="Failed to start MilvusLite server",
                exc_info=sys.exc_info(),
            )
        )

    [line] = handler.get_lines()
    assert line["metadata"]["exception_type"] == "DataDirLockedError"
    assert line["metadata"]["root_cause_type"] == "PermissionError"
    assert line["metadata"]["diagnostic_code"] == "milvus_data_dir_locked"
    assert "不要直接删除锁文件" in line["metadata"]["hint"]
