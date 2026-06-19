"""Config 解析契约测试：默认值、字段覆盖、机密环境变量优先、派生量。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import (
    ENV_DEEP_THINKING_LLM_API_KEY,
    ENV_EMBEDDING_API_KEY,
    ENV_R2_SECRET_ACCESS_KEY,
    ENV_WEB_PASSWORD,
    Config,
)
from core.runtime_config import RuntimeConfigStore


def test_astrbot_conf_schema_only_keeps_core_sections() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert list(schema.keys()) == [
        "web_console",
        "r2_sync",
        "notion_sync",
        "embedding",
        "ask",
    ]


def test_defaults_when_empty() -> None:
    cfg = Config({})
    assert cfg.get_source_store_config().db_filename == "knowledge_repository.db"
    assert cfg.get_r2_sync_config().free_tier_gb == 10
    assert cfg.get_notion_sync_config().mcp_server_name == "notion"
    assert cfg.get_web_console_config().port == 26618
    assert cfg.get_graph_config().query_mode == "mix"
    assert cfg.get_graph_config().lightrag_llm_provider == "main"
    assert cfg.get_vector_db_config().backend == "milvus"
    assert cfg.get_embedding_config().model == "intfloat/multilingual-e5-small"
    assert cfg.get_embedding_config().max_token_size == 512
    assert cfg.get_zotero_sync_config().access_mode == "local"


def test_section_overrides() -> None:
    cfg = Config({"r2_sync": {"enabled": True, "account_id": "acc", "free_tier_gb": 5}})
    r2 = cfg.get_r2_sync_config()
    assert r2.enabled is True
    assert r2.account_id == "acc"
    assert r2.free_tier_gb == 10


def test_r2_endpoint_and_free_tier_bytes() -> None:
    assert Config({}).get_r2_sync_config().endpoint == ""  # 无 account_id
    r2 = Config({"r2_sync": {"account_id": "abc"}}).get_r2_sync_config()
    assert r2.endpoint == "https://abc.r2.cloudflarestorage.com"
    assert r2.free_tier_bytes == 10 * 1024**3


def test_notion_max_upload_bytes() -> None:
    n = Config({
        "notion_sync": {
            "max_upload_mib": 5,
            "parent_page_id": "parent-1",
            "database_title": "KR",
        }
    }).get_notion_sync_config()
    assert n.max_upload_bytes == 5 * 1024 * 1024
    assert n.parent_page_id == "parent-1"
    assert n.database_title == "KR"


def test_secret_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_R2_SECRET_ACCESS_KEY, "from-env")
    cfg = Config({"r2_sync": {"secret_access_key": "from-config"}})
    assert cfg.get_r2_sync_config().secret_access_key == "from-env"


def test_secret_falls_back_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_R2_SECRET_ACCESS_KEY, raising=False)
    cfg = Config({"r2_sync": {"secret_access_key": "from-config"}})
    assert cfg.get_r2_sync_config().secret_access_key == "from-config"


def test_web_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_WEB_PASSWORD, "pw")
    assert Config({}).get_web_console_config().password == "pw"


def test_malformed_section_falls_back_to_defaults() -> None:
    # 子配置类型不符（非 dict）时应安全回退默认值
    cfg = Config({"graph": "not-a-dict"})
    assert cfg.get_graph_config().query_mode == "mix"

def test_graph_lightrag_llm_provider_modes_and_legacy_endpoint() -> None:
    explicit = Config(
        {
            "graph": {
                "lightrag_llm_provider": "api",
                "lightrag_llm_base_url": "https://llm.example/v1",
                "lightrag_llm_model": "model-a",
            }
        }
    ).get_graph_config()
    assert explicit.lightrag_llm_provider == "api"

    legacy = Config(
        {
            "graph": {
                "lightrag_llm_base_url": "http://localhost:1234/v1",
                "lightrag_llm_model": "phi4",
            }
        }
    ).get_graph_config()
    assert legacy.lightrag_llm_provider == "local"

    invalid = Config({"graph": {"lightrag_llm_provider": "bad"}}).get_graph_config()
    assert invalid.lightrag_llm_provider == "main"



def test_public_config_masks_secrets() -> None:
    cfg = Config({
        "r2_sync": {"access_key_id": "abcdef", "secret_access_key": "secret123"},
        "web_console": {"password": "password123"},
        "notion_sync": {"database_id": "db1", "parent_page_id": "parent1"},
    })
    public = cfg.to_public_dict()
    assert public["r2_sync"]["access_key_id"] == "ab****ef"
    assert public["r2_sync"]["secret_access_key"] == "se****23"
    assert public["web_console"]["password"] == "pa****23"
    assert public["notion_sync"]["database_id"] == "db1"


def test_public_config_exposes_webui_migrated_advanced_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_DEEP_THINKING_LLM_API_KEY, "deep-secret")
    cfg = Config(
        {
            "source_store": {"default_collection": "papers"},
            "graph": {
                "working_dir": "graphs",
                "lightrag_llm_provider": "api",
                "lightrag_llm_base_url": "https://llm.example/v1",
                "lightrag_llm_model": "model-a",
            },
            "deep_thinking": {
                "max_rounds": 5,
                "max_sub_queries": 6,
                "wide_top_k": 30,
                "rerank_weight": 0.4,
                "verify_enabled": False,
                "max_verify_rounds": 2,
                "llm_base_url": "https://deep.example/v1",
                "llm_model": "deep-model",
            },
        }
    )

    public = cfg.to_public_dict()
    assert public["source_store"]["default_collection"] == "papers"
    assert public["graph"]["working_dir"] == "graphs"
    assert public["graph"]["lightrag_llm_provider"] == "api"
    assert public["graph"]["lightrag_llm_base_url"] == "https://llm.example/v1"
    assert public["graph"]["lightrag_llm_model"] == "model-a"
    assert public["deep_thinking"] == {
        "max_rounds": 5,
        "max_sub_queries": 6,
        "wide_top_k": 30,
        "rerank_weight": 0.4,
        "verify_enabled": False,
        "max_verify_rounds": 2,
        "llm_base_url": "https://deep.example/v1",
        "llm_model": "deep-model",
        "llm_api_key": "de****et",
    }


def test_embedding_config_new_values_override_legacy_and_api_key_is_env_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_EMBEDDING_API_KEY, "embedding-secret")
    cfg = Config(
        {
            "embedding": {"provider": "external", "model": "new", "base_url": "https://new"},
            "vector_db": {
                "embedding_provider": "local",
                "embedding_model": "legacy",
                "base_url": "https://legacy",
            },
        }
    )

    embedding = cfg.get_embedding_config()
    assert (embedding.provider, embedding.model, embedding.base_url) == (
        "external",
        "new",
        "https://new",
    )
    assert cfg.to_public_dict()["embedding"]["api_key"] == "em****et"
    assert any("Legacy embedding settings" in item for item in cfg.get_diagnostics())


def test_enabled_config_diagnostics_report_missing_values() -> None:
    cfg = Config({"r2_sync": {"enabled": True}, "notion_sync": {"enabled": True}})
    diagnostics = cfg.get_diagnostics()
    assert "r2_sync.account_id is required when r2_sync.enabled=true" in diagnostics
    assert (
        "notion_sync.database_id or notion_sync.parent_page_id is required "
        "when notion_sync.enabled=true"
    ) in diagnostics


def test_embedding_diagnostics_report_unsupported_or_unconfigured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_EMBEDDING_API_KEY, raising=False)

    assert (
        "embedding.provider=astr is not implemented; choose local or external."
        in Config({"embedding": {"provider": "astr"}}).get_diagnostics()
    )
    assert (
        "KR_EMBEDDING_API_KEY is required when embedding.provider=external."
        in Config({"embedding": {"provider": "external"}}).get_diagnostics()
    )
    assert any(
        "graph.lightrag_llm_base_url and graph.lightrag_llm_model are required" in item
        for item in Config(
            {"graph": {"enabled": True, "lightrag_llm_provider": "api"}}
        ).get_diagnostics()
    )


def test_diagnostics_report_missing_optional_feature_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.config._module_available", lambda name: False)
    diagnostics = Config(
        {
            "r2_sync": {"enabled": True},
            "graph": {"enabled": True},
            "vector_db": {"backend": "milvus"},
            "embedding": {"provider": "local"},
        }
    ).get_diagnostics()

    assert sum("requirements-additional.txt" in item for item in diagnostics) == 3
    assert any("Milvus Lite is a required dependency" in item for item in diagnostics)


def test_runtime_config_store_only_persists_generated_notion_values(tmp_path: Path) -> None:
    path = tmp_path / "runtime_config.json"
    persisted = []
    store = RuntimeConfigStore(path, framework_persist_cb=persisted.append)

    store.save({
        "notion_sync": {"database_id": "db1", "secret": "drop-me"},
        "r2_sync": {"secret_access_key": "drop-me"},
    })

    assert json.loads(path.read_text()) == {"notion_sync": {"database_id": "db1"}}
    assert persisted == [{"notion_sync": {"database_id": "db1"}}]
    with pytest.raises(ValueError, match="runtime config key is not allowed"):
        store.set_value("r2_sync", "secret_access_key", "forbidden")


def test_runtime_config_store_permits_vector_db_and_ask_keys(tmp_path: Path) -> None:
    path = tmp_path / "runtime_config.json"
    store = RuntimeConfigStore(path)

    # These should pass successfully without raising ValueError
    store.set_value("vector_db", "backend", "milvus")
    store.set_value("embedding", "provider", "local")
    store.set_value("embedding", "model", "BAAI/bge-m3")
    store.set_value("ask", "conversation_enhancement_mode", "query_agent")
    store.set_value("source_store", "default_collection", "papers")
    store.set_value("deep_thinking", "verify_enabled", False)
    store.set_value("deep_thinking", "max_verify_rounds", 2)

    data = store.load()
    assert data["vector_db"]["backend"] == "milvus"
    assert data["embedding"]["provider"] == "local"
    assert data["embedding"]["model"] == "BAAI/bge-m3"
    assert data["ask"]["conversation_enhancement_mode"] == "query_agent"
    assert data["source_store"]["default_collection"] == "papers"
    assert data["deep_thinking"]["verify_enabled"] is False
    assert data["deep_thinking"]["max_verify_rounds"] == 2


# ── Deep Thinking / Rerank config ───────────────────────────
def test_deep_thinking_and_rerank_defaults_without_st(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.config._module_available", lambda name: False)
    cfg = Config({})
    r = cfg.get_rerank_config()
    assert r.provider == "noop"
    assert r.model == "Alibaba-NLP/gte-reranker-modernbert-base"
    assert r.keep == 8
    d = cfg.get_deep_thinking_config()
    assert d.max_rounds == 4
    assert d.max_sub_queries == 4
    assert d.wide_top_k == 24
    assert d.gap_ratio_threshold == 0.5
    # v0.25.9 新增字段默认值。
    assert d.sea_evidence_clip == 700
    assert d.verify_evidence_clip == 1500
    assert d.rerank_weight == 0.2
    assert d.deep_keep == 12
    assert d.max_discovered_per_round == 3
    assert d.max_discovered_total == 8


def test_rerank_default_auto_enables_cross_encoder_with_st(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.config._module_available",
        lambda name: name == "sentence_transformers",
    )
    r = Config({}).get_rerank_config()
    assert r.provider == "cross_encoder"
    assert r.model == "Alibaba-NLP/gte-reranker-modernbert-base"


def test_explicit_rerank_noop_stays_disabled_with_st(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.config._module_available",
        lambda name: name == "sentence_transformers",
    )
    assert Config({"rerank": {"provider": "noop"}}).get_rerank_config().provider == "noop"


def test_rerank_provider_falls_back_on_invalid() -> None:
    cfg = Config({"rerank": {"provider": "bogus"}})
    assert cfg.get_rerank_config().provider == "noop"


def test_rerank_explicit_auto_resolves_like_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式写入的 provider:"auto" 与缺省同义：装了 ST → cross_encoder，否则 noop。"""
    monkeypatch.setattr(
        "core.config._module_available",
        lambda name: name == "sentence_transformers",
    )
    assert Config({"rerank": {"provider": "auto"}}).get_rerank_config().provider == "cross_encoder"
    monkeypatch.setattr("core.config._module_available", lambda name: False)
    assert Config({"rerank": {"provider": "auto"}}).get_rerank_config().provider == "noop"


def test_rerank_legacy_mmr_normalized_to_noop() -> None:
    """历史值 mmr 归一到 noop（不再做 MMR provider）。"""
    assert Config({"rerank": {"provider": "mmr"}}).get_rerank_config().provider == "noop"


def test_deep_thinking_values_are_clamped() -> None:
    cfg = Config(
        {"deep_thinking": {"max_rounds": 0, "max_sub_queries": -2, "json_max_retries": -1}}
    )
    d = cfg.get_deep_thinking_config()
    assert d.max_rounds == 1
    assert d.max_sub_queries == 1
    assert d.json_max_retries == 0


def test_rerank_overrides_are_parsed() -> None:
    cfg = Config({"rerank": {"provider": "noop", "model": "BAAI/bge-reranker-base", "keep": 5}})
    r = cfg.get_rerank_config()
    assert r.provider == "noop"
    assert r.model == "BAAI/bge-reranker-base"
    assert r.keep == 5
