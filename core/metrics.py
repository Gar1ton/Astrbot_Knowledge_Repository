"""性能指标收集器（横切工具，无业务依赖）。

记录近期操作的执行时间，供 /api/metrics 端点聚合后返回给前端性能面板。
线程安全：使用 threading.Lock 保护 deque。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class PerformanceTracker:
    """收集并聚合近期操作延迟指标。

    maxlen=200 保留最近 200 条记录，足够展示趋势且不占用太多内存。
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, op: str, duration_ms: float, meta: dict[str, Any] | None = None) -> None:
        """记录一次操作延迟。

        Args:
            op: 操作标识，如 "embed_query", "vector_search", "llm_generate", "ask_total"。
            duration_ms: 耗时（毫秒）。
            meta: 可选附加信息（chunk 命中数等）。
        """
        entry: dict[str, Any] = {
            "op": op,
            "ms": round(duration_ms, 2),
            "ts": time.time(),
        }
        if meta:
            entry["meta"] = meta
        with self._lock:
            self._records.append(entry)

    def summary(self) -> dict[str, Any]:
        """按操作类型聚合：count、avg_ms、p95_ms、last_ms。

        Returns:
            {
                "ops": {
                    "embed_query":  {"count": N, "avg_ms": X, "p95_ms": Y, "last_ms": Z},
                    ...
                },
                "total_records": N,
            }
        """
        with self._lock:
            records = list(self._records)

        by_op: dict[str, list[float]] = {}
        for r in records:
            by_op.setdefault(r["op"], []).append(r["ms"])

        ops: dict[str, dict[str, Any]] = {}
        for op, ms_list in by_op.items():
            sorted_ms = sorted(ms_list)
            n = len(sorted_ms)
            avg = sum(sorted_ms) / n
            p95_idx = max(0, int(n * 0.95) - 1)
            ops[op] = {
                "count": n,
                "avg_ms": round(avg, 2),
                "p95_ms": round(sorted_ms[p95_idx], 2),
                "last_ms": round(sorted_ms[-1], 2),
            }

        return {
            "ops": ops,
            "total_records": len(records),
        }


__all__ = ["PerformanceTracker"]
