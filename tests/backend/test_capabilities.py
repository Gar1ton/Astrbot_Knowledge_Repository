"""能力注册表单测：环节状态机、依赖清单、安装白名单。

只构造 Config 即可断言各环节状态——detect_pipeline 是纯函数，无 I/O。
通过 monkeypatch `kacore.capabilities.module_available` 模拟可选依赖的安装与缺失。
"""
from __future__ import annotations

import pytest

from kacore.capabilities import (
    OPTIONAL_DEPENDENCIES,
    STATUS_DEGRADED,
    STATUS_OFF,
    STATUS_READY,
    dependency_statuses,
    detect_pipeline,
    milvus_runtime_status,
    resolve_install_spec,
)
from kacore.config import Config


def _cfg(raw: dict | None = None, dim: int | None = None) -> Config:
    cfg = Config(raw or {})
    if dim is not None:
        cfg.set_embedding_dimension(dim)
    return cfg


def _stage(pipeline: list[dict], stage_id: str) -> dict:
    return next(s for s in pipeline if s["id"] == stage_id)


def _patch_modules(monkeypatch: pytest.MonkeyPatch, available: set[str]) -> None:
    monkeypatch.setattr(
        "kacore.capabilities.module_available", lambda name: name in available
    )
    monkeypatch.setattr("kacore.config._module_available", lambda name: name in available)


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
    assert "ask" in next(d for d in deps if d["key"] == "local_embedding")["stages"]
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
    _patch_modules(monkeypatch, {"sentence_transformers", "pymilvus", "milvus_lite"})
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


def test_milvus_not_ready_when_only_pymilvus_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归 v1.0.9：装了 pymilvus 但没有 milvus-lite ≠ 可用。

    `pymilvus[milvus_lite]` 的 extra 带 `sys_platform != "win32"` 标记，Windows 上 pip
    静默跳过 milvus-lite 且退出码为 0。旧实现只探 pymilvus，于是面板显示绿灯、装配却抛
    `ConnectionConfigException`，用户被引导去重复安装同一个包。
    """
    _patch_modules(monkeypatch, {"sentence_transformers", "pymilvus"})
    cfg = _cfg({"vector_db": {"backend": "milvus"}, "embedding": {"provider": "local"}}, dim=384)

    stage = _stage(detect_pipeline(cfg), "vector_store")
    assert stage["status"] == STATUS_DEGRADED
    assert stage["detail"]["milvus_runtime_ready"] is False
    assert "milvus-lite" in stage["detail"]["milvus_runtime_hint"]

    milvus_dep = next(d for d in dependency_statuses() if d["key"] == "milvus")
    assert milvus_dep["installed"] is True  # 顶层包确实在
    assert milvus_dep["runtime_ready"] is False  # 但功能跑不起来
    assert "milvus-lite" in milvus_dep["runtime_hint"]


def test_milvus_hint_points_to_platform_fallback_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows 上 milvus-lite 根本没有发行版：提示必须给替代路径，而不是叫用户再装一次。"""
    _patch_modules(monkeypatch, {"pymilvus"})
    monkeypatch.setattr("kacore.capabilities.sys.platform", "win32")

    status = milvus_runtime_status()
    assert status["ready"] is False
    assert status["platform_supported"] is False
    assert "astr" in status["hint"]
    assert "WSL" in status["hint"]


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


def test_ask_rerank_detail_ready_when_st_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, {"sentence_transformers"})
    ask = _stage(detect_pipeline(_cfg(dim=384)), "ask")
    assert ask["detail"]["rerank_provider"] == "cross_encoder"
    assert ask["detail"]["rerank_model"] == "Alibaba-NLP/gte-reranker-modernbert-base"
    assert ask["detail"]["rerank_status"] == STATUS_READY
    assert ask["detail"]["rerank_dependency_ready"] is True


def test_ask_rerank_detail_off_when_no_st(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_modules(monkeypatch, set())
    ask = _stage(detect_pipeline(_cfg(dim=384)), "ask")
    assert ask["detail"]["rerank_provider"] == "noop"
    assert ask["detail"]["rerank_status"] == STATUS_OFF
    assert ask["required_deps"] == []


def test_ask_rerank_degraded_when_explicit_cross_encoder_without_st(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_modules(monkeypatch, set())
    ask = _stage(
        detect_pipeline(_cfg({"rerank": {"provider": "cross_encoder"}}, dim=384)),
        "ask",
    )
    assert ask["status"] == STATUS_DEGRADED
    assert ask["detail"]["rerank_provider"] == "cross_encoder"
    assert "local_embedding" in ask["required_deps"]
