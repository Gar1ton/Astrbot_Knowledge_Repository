"""RuntimeEventRecorder 阶段与节流契约。"""
from __future__ import annotations

from typing import Any

import kacore.runtime_events as runtime_events
from kacore.runtime_events import RuntimeEventRecorder


class Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add_event(self, **event: Any) -> None:
        self.events.append(event)


def test_progress_emits_on_phase_ten_percent_and_thirty_seconds(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(runtime_events.time, "monotonic", lambda: clock[0])
    sink = Sink()
    recorder = RuntimeEventRecorder(sink)
    op_id = recorder.start(category="sync", operation="job", msg="start", operation_id="job-1")

    assert recorder.progress(
        operation_id=op_id, category="sync", operation="job",
        phase="reading", percent=0, msg="reading",
    )
    assert not recorder.progress(
        operation_id=op_id, category="sync", operation="job",
        phase="reading", percent=9, msg="reading",
    )
    assert recorder.progress(
        operation_id=op_id, category="sync", operation="job",
        phase="reading", percent=10, msg="reading",
    )
    assert recorder.progress(
        operation_id=op_id, category="sync", operation="job",
        phase="writing", percent=11, msg="writing",
    )
    clock[0] = 31.0
    assert recorder.progress(
        operation_id=op_id, category="sync", operation="job",
        phase="writing", percent=12, msg="still writing",
    )

    recorder.finish(
        operation_id=op_id, category="sync", operation="job", msg="done"
    )
    assert [event["status"] for event in sink.events] == [
        "started", "running", "running", "running", "running", "ok"
    ]
    assert sink.events[-1]["metadata"]["elapsed_ms"] == 31000.0


def test_failure_is_terminal_even_without_prior_progress():
    sink = Sink()
    recorder = RuntimeEventRecorder(sink)
    op_id = recorder.start(category="retrieval", operation="build", msg="start")
    recorder.fail(
        operation_id=op_id,
        category="retrieval",
        operation="build",
        msg="failed",
        error=ValueError("boom"),
    )
    assert sink.events[-1]["level"] == "ERROR"
    assert sink.events[-1]["status"] == "error"
    assert sink.events[-1]["metadata"]["exception_type"] == "ValueError"
