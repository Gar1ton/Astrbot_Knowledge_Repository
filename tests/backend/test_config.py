"""Config 解析契约测试：默认值、字段覆盖、机密环境变量优先、派生量。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import ENV_R2_SECRET_ACCESS_KEY, ENV_WEB_PASSWORD, Config
from core.runtime_config import RuntimeConfigStore


def test_defaults_when_empty() -> None:
    cfg = Config({})
    assert cfg.get_source_store_config().db_filename == "knowledge_repository.db"
    assert cfg.get_r2_sync_config().free_tier_gb == 10
    assert cfg.get_notion_sync_config().mcp_server_name == "notion"
    assert cfg.get_web_console_config().port == 6520
    assert cfg.get_graph_config().rrf_k == 60


def test_section_overrides() -> None:
    cfg = Config({"r2_sync": {"enabled": True, "account_id": "acc", "free_tier_gb": 5}})
    r2 = cfg.get_r2_sync_config()
    assert r2.enabled is True
    assert r2.account_id == "acc"
    assert r2.free_tier_gb == 5


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
    assert cfg.get_graph_config().rrf_k == 60


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


def test_enabled_config_diagnostics_report_missing_values() -> None:
    cfg = Config({"r2_sync": {"enabled": True}, "notion_sync": {"enabled": True}})
    diagnostics = cfg.get_diagnostics()
    assert "r2_sync.account_id is required when r2_sync.enabled=true" in diagnostics
    assert (
        "notion_sync.database_id or notion_sync.parent_page_id is required "
        "when notion_sync.enabled=true"
    ) in diagnostics


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
