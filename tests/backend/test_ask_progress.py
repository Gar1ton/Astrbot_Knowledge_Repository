"""单元测试：ProgressStore（core/ask_progress.py）。"""

from core.ask_progress import TTL_SEC, ProgressStore


def test_set_and_get():
    store = ProgressStore()
    store.set("cid-1", "embed_query", 20)
    result = store.get("cid-1")
    assert result == {"stage": "embed_query", "pct": 20}


def test_get_nonexistent():
    store = ProgressStore()
    assert store.get("missing") is None


def test_overwrite():
    store = ProgressStore()
    store.set("cid-1", "embed_query", 0)
    store.set("cid-1", "vector_search", 50)
    result = store.get("cid-1")
    assert result is not None
    assert result["stage"] == "vector_search"
    assert result["pct"] == 50


def test_ttl_expiry():
    store = ProgressStore()
    store.set("cid-ttl", "done", 100)
    # 手动把 updated_at 调回过去以触发 GC
    store._store["cid-ttl"]["updated_at"] -= TTL_SEC + 1
    result = store.get("cid-ttl")
    assert result is None
    assert "cid-ttl" not in store._store


def test_gc_removes_expired_on_set():
    store = ProgressStore()
    store.set("cid-old", "done", 100)
    store._store["cid-old"]["updated_at"] -= TTL_SEC + 1
    # 插入新记录会触发 GC
    store.set("cid-new", "embed_query", 0)
    assert "cid-old" not in store._store
    assert "cid-new" in store._store


def test_multiple_conversations():
    store = ProgressStore()
    store.set("a", "embed_query", 10)
    store.set("b", "llm_generate", 80)
    assert store.get("a")["stage"] == "embed_query"
    assert store.get("b")["stage"] == "llm_generate"


def test_done_stage():
    store = ProgressStore()
    store.set("cid-done", "done", 100)
    result = store.get("cid-done")
    assert result is not None
    assert result["pct"] == 100
