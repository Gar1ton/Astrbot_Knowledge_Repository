"""单元测试：PerformanceTracker（core/metrics.py）。"""

from core.metrics import PerformanceTracker


def test_record_and_summary_empty():
    tracker = PerformanceTracker()
    summary = tracker.summary()
    assert summary["ops"] == {}
    assert summary["total_records"] == 0


def test_record_and_summary_single():
    tracker = PerformanceTracker()
    tracker.record("embed_query", 123.4)
    summary = tracker.summary()
    assert "embed_query" in summary["ops"]
    stat = summary["ops"]["embed_query"]
    assert stat["count"] == 1
    assert stat["avg_ms"] == 123.4
    assert stat["p95_ms"] == 123.4
    assert stat["last_ms"] == 123.4
    assert summary["total_records"] == 1


def test_record_multiple_ops():
    tracker = PerformanceTracker()
    tracker.record("embed_query", 100.0)
    tracker.record("embed_query", 200.0)
    tracker.record("vector_search", 50.0)
    summary = tracker.summary()
    assert summary["ops"]["embed_query"]["count"] == 2
    assert summary["ops"]["embed_query"]["avg_ms"] == 150.0
    assert summary["ops"]["vector_search"]["count"] == 1
    assert summary["total_records"] == 3


def test_p95_calculation():
    tracker = PerformanceTracker(maxlen=200)
    for i in range(100):
        tracker.record("op", float(i + 1))
    summary = tracker.summary()
    stat = summary["ops"]["op"]
    # p95 index = int(100 * 0.95) - 1 = 94, sorted values[94] = 95
    assert stat["p95_ms"] == 95.0
    assert stat["avg_ms"] == 50.5


def test_maxlen_eviction():
    tracker = PerformanceTracker(maxlen=5)
    for i in range(10):
        tracker.record("op", float(i))
    summary = tracker.summary()
    # 只保留最后 5 条：5, 6, 7, 8, 9
    assert summary["ops"]["op"]["count"] == 5
    assert summary["total_records"] == 5


def test_meta_does_not_break_summary():
    tracker = PerformanceTracker()
    tracker.record("ask_total", 1500.0, meta={"hits": 3})
    summary = tracker.summary()
    assert summary["ops"]["ask_total"]["count"] == 1


def test_thread_safety():
    """多线程并发写入不抛异常。"""
    import threading
    tracker = PerformanceTracker()
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(50):
                tracker.record("op", 1.0)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    summary = tracker.summary()
    assert summary["ops"]["op"]["count"] == 200
