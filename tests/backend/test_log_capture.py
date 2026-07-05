"""单元测试：MemoryLogHandler（core/log_capture.py）。"""

from __future__ import annotations

import logging

from core.log_capture import MemoryLogHandler, _categorize


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


def test_emit_skips_noisy_prefixes_entirely():
    handler = MemoryLogHandler()
    handler.emit(_record(name="httpx", level=logging.INFO))
    handler.emit(_record(name="aiohttp.access", level=logging.ERROR))
    assert handler.get_lines() == []


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
