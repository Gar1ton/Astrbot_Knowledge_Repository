"""Ask 对话进度存储（横切工具，无业务依赖）。

供前端轮询 /api/ask/progress/{cid} 时读取当前阶段与百分比。
GC：超过 TTL_SEC 秒未更新的记录自动清除。
"""
from __future__ import annotations

import time
from typing import Any

TTL_SEC = 300  # 5 分钟未活跃则清除


class ProgressStore:
    """存储各对话的召回进度。

    线程安全：aiohttp 单线程事件循环内调用，无需额外锁；
    如在多线程场景使用请自行加锁。
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def set(
        self,
        conversation_id: str,
        stage: str,
        pct: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """更新进度。

        Args:
            conversation_id: 对话 ID（与 ask() 返回的 conversation_id 一致）。
            stage: 阶段标识，如 "embed_query", "vector_search", "llm_generate", "done"。
            pct: 完成百分比（0–100）。
            detail: 可选的结构化进度详情（如 deep thinking 的逐轮增量 trace），
                供前端实时渲染推演过程；None 时不携带（向后兼容）。
        """
        entry: dict[str, Any] = {
            "stage": stage,
            "pct": pct,
            "updated_at": time.time(),
        }
        if detail is not None:
            entry["detail"] = detail
        self._store[conversation_id] = entry
        self._gc()

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        """获取进度，不存在时返回 None。detail 仅在曾写入时出现（向后兼容）。"""
        entry = self._store.get(conversation_id)
        if entry is None:
            return None
        if time.time() - entry["updated_at"] > TTL_SEC:
            del self._store[conversation_id]
            return None
        result: dict[str, Any] = {"stage": entry["stage"], "pct": entry["pct"]}
        if "detail" in entry:
            result["detail"] = entry["detail"]
        return result

    def _gc(self) -> None:
        """清除超时记录。"""
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v["updated_at"] > TTL_SEC]
        for k in expired:
            del self._store[k]


__all__ = ["ProgressStore"]
