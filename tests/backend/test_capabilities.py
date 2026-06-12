"""能力注册表单测：环节状态机、依赖清单、安装白名单。

只构造 Config 即可断言各环节状态——detect_pipeline 是纯函数，无 I/O。
通过 monkeypatch `core.capabilities.module_available` 模拟可选依赖的安装与缺失。
"""
from __future__ import annotations

import pytest

from core.capabilities import (
    OPTIONAL_DEPENDENCIES,
    STATUS_DEGRADED,
    STATUS_OFF,
    STATUS_READY,
    dependency_statuses,
    detect_pipeline,
    resolve_install_spec,
)
from core.config import Config


def _cfg(raw: dict | None = None, dim: int | None = None) -> Config:
    cfg = Config(raw or {})
    if dim is not None:
        cfg.set_embedding_dimension(dim)
    return cfg


def _stage(pipeline: list[dict], stage_id: str) -> dict:
    return next(s for s in pipeline if s["id"] == stage_id)


def _patch_modules(monkeypatch: pytest.MonkeyPatch, available: set[str]) -> None:
    monkeypatch.setattr("core.capabilities.module_available", lambda name: name in available)


# ── 安装白名单 ────────────────────────────────────────────────────


def test_resolve_install_spec_accepts_key_and_full_spec() -> None:
    assert resolve_install_spec("milvus") == "pymilvus[milvus_lite]>=2.5,<3.0"
    spec = OPTIONAL_DEPENDENCIES[0].pip_spec
    assert resolve_install_spec(spec) == spec


def test_resolve_install_spec_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        resolve_install_spec("evil-package; rm -rf /")


def test_dependency_statuses_cover_all_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, set())
    deps = dependency_statuses()
    assert {d["key"] for d in deps} == {
        "local_embedding", "milvus", "lightrag", "r2"
    }
    assert next(d for d in deps if d["key"] == "milvus")["required"] is True
    assert next(d for d in deps if d["key"] == "lightrag")["required"] is False
    assert all(d["installed"] is False for d in deps)


# ── 环节状态机 ────────────────────────────────────────────────────


def test_pipeline_has_ordered_stages_with_zotero_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(
        monkeypatch,
        {"pymupdf4llm", "sentence_transformers", "pymilvus", "lightrag", "boto3"},
    )
    ids = [s["id"] for s in detect_pipeline(_cfg(dim=384))]
    assert ids == [
        "zotero", "ingest", "embedding", "vector_store", "retrieval", "graph", "ask", "sync"
    ]


def test_zotero_stage_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"pymupdf4llm"})
    z = _stage(detect_pipeline(_cfg(dim=384)), "zotero")
    assert z["status"] == STATUS_OFF
    enabled = _stage(detect_pipeline(_cfg({"zotero_sync": {"enabled": True}}, dim=384)), "zotero")
    assert enabled["status"] == STATUS_READY


def test_ingest_reports_core_pdf_dependency_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, set())
    ingest = _stage(detect_pipeline(_cfg()), "ingest")
    assert ingest["status"] == STATUS_DEGRADED
    assert ingest["required_deps"] == []
    assert ingest["detail"]["dependency_source"] == "requirements.txt"


def test_local_embedding_degraded_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, set())
    emb = _stage(detect_pipeline(_cfg({"embedding": {"provider": "local"}})), "embedding")
    assert emb["status"] == STATUS_DEGRADED
    assert "local_embedding" in emb["required_deps"]


def test_milvus_ready_when_installed_and_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"sentence_transformers", "pymilvus"})
    cfg = _cfg({"vector_db": {"backend": "milvus"}, "embedding": {"provider": "local"}}, dim=384)
    pipeline = detect_pipeline(cfg)
    assert _stage(pipeline, "embedding")["status"] == STATUS_READY
    assert _stage(pipeline, "vector_store")["status"] == STATUS_READY
    assert "milvus" in _stage(pipeline, "retrieval")["detail"]["engines"]


def test_milvus_degraded_falls_back_to_astrbot(monkeypatch: pytest.MonkeyPatch) -> None:
    # 本地 embedding 在位，但缺 pymilvus：向量库降级，检索回退 AstrBot KB。
    _patch_modules(monkeypatch, {"sentence_transformers"})
    cfg = _cfg({"vector_db": {"backend": "milvus"}, "embedding": {"provider": "local"}}, dim=384)
    pipeline = detect_pipeline(cfg)
    assert _stage(pipeline, "vector_store")["status"] == STATUS_DEGRADED
    assert "astrbot_kb" in _stage(pipeline, "retrieval")["detail"]["engines"]


def test_graph_off_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"sentence_transformers", "lightrag"})
    graph = _stage(detect_pipeline(_cfg({"graph": {"enabled": False}}, dim=384)), "graph")
    assert graph["status"] == STATUS_OFF


def test_graph_degraded_when_enabled_without_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"sentence_transformers"})
    graph = _stage(detect_pipeline(_cfg({"graph": {"enabled": True}}, dim=384)), "graph")
    assert graph["status"] == STATUS_DEGRADED


def test_sync_off_when_no_target_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"sentence_transformers"})
    sync = _stage(detect_pipeline(_cfg(dim=384)), "sync")
    assert sync["status"] == STATUS_OFF
