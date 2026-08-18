"""Web 运行事件记录器（横切工具，无业务依赖）。

把业务门面的开始、阶段进度与终态写入可选 RuntimeEventSink。事件仅进入 Web 内存缓冲，
不调用 logging，因而不会扩大 AstrBot 宿主终端输出。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from kacore.log_capture import RuntimeEventSink

_PROGRESS_STEP = 10
_PROGRESS_INTERVAL_SECONDS = 30.0


@dataclass
class _OperationState:
    started_at: float
    last_emit_at: float
    phase: str = ""
    percent: int | None = None


class RuntimeEventRecorder:
    """记录运行操作并按阶段、百分比或时间间隔节流进度。"""

    def __init__(self, sink: RuntimeEventSink | None) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self._states: dict[str, _OperationState] = {}

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def start(
        self,
        *,
        category: str,
        operation: str,
        msg: str,
        operation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """开始操作并返回稳定 operation_id。"""
        op_id = operation_id or secrets.token_hex(6)
        now = time.monotonic()
        with self._lock:
            self._states = {
                key: state
                for key, state in self._states.items()
                if now - state.started_at < 3600.0
            }
            self._states[op_id] = _OperationState(started_at=now, last_emit_at=now)
        self._emit(
            category=category,
            operation=operation,
            status="started",
            msg=msg,
            metadata={"operation_id": op_id, **(metadata or {})},
        )
        return op_id

    def progress(
        self,
        *,
        operation_id: str,
        category: str,
        operation: str,
        phase: str,
        msg: str,
        percent: int | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:
        """阶段变化立即记录；同阶段每增加 10% 或等待 30s 后记录。"""
        now = time.monotonic()
        normalized = None if percent is None else max(0, min(100, int(percent)))
        should_emit = force
        with self._lock:
            state = self._states.get(operation_id)
            if state is None:
                state = _OperationState(started_at=now, last_emit_at=now)
                self._states[operation_id] = state
            if phase != state.phase:
                should_emit = True
            elif normalized is not None and (
                state.percent is None or normalized >= state.percent + _PROGRESS_STEP
            ):
                should_emit = True
            elif now - state.last_emit_at >= _PROGRESS_INTERVAL_SECONDS:
                should_emit = True
            if should_emit:
                state.phase = phase
                state.percent = normalized
                state.last_emit_at = now
        if not should_emit:
            return False
        event_metadata = {
            "operation_id": operation_id,
            "phase": phase,
            **(metadata or {}),
        }
        if normalized is not None:
            event_metadata["progress_percent"] = normalized
        self._emit(
            category=category,
            operation=operation,
            status="running",
            msg=msg,
            metadata=event_metadata,
        )
        return True

    def finish(
        self,
        *,
        operation_id: str,
        category: str,
        operation: str,
        msg: str,
        status: str = "ok",
        level: str = "INFO",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录终态；无论节流状态如何都必达。"""
        elapsed_ms = self._pop_elapsed_ms(operation_id)
        self._emit(
            category=category,
            operation=operation,
            status=status,
            level=level,
            msg=msg,
            metadata={
                "operation_id": operation_id,
                "elapsed_ms": elapsed_ms,
                **(metadata or {}),
            },
        )

    def fail(
        self,
        *,
        operation_id: str,
        category: str,
        operation: str,
        msg: str,
        error: BaseException | str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录失败终态与异常类型。"""
        error_type = type(error).__name__ if isinstance(error, BaseException) else "RuntimeError"
        self.finish(
            operation_id=operation_id,
            category=category,
            operation=operation,
            status="error",
            level="ERROR",
            msg=msg,
            metadata={
                "exception_type": error_type,
                "error": str(error),
                **(metadata or {}),
            },
        )

    def emit(
        self,
        *,
        category: str,
        operation: str,
        status: str,
        msg: str,
        level: str = "INFO",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """写入不参与节流的独立事件，例如单文档失败。"""
        self._emit(
            category=category,
            operation=operation,
            status=status,
            msg=msg,
            level=level,
            metadata=metadata or {},
        )

    def _pop_elapsed_ms(self, operation_id: str) -> float | None:
        with self._lock:
            state = self._states.pop(operation_id, None)
        if state is None:
            return None
        return round((time.monotonic() - state.started_at) * 1000, 1)

    def _emit(
        self,
        *,
        category: str,
        operation: str,
        status: str,
        msg: str,
        metadata: dict[str, Any],
        level: str = "INFO",
    ) -> None:
        if self._sink is None:
            return
        self._sink.add_event(
            source="runtime",
            category=category,
            operation=operation,
            status=status,
            msg=msg,
            level=level,
            metadata=metadata,
        )


__all__ = ["RuntimeEventRecorder"]
