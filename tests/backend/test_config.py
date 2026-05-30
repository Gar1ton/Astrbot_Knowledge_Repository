"""Config 解析契约测试：默认值、字段覆盖、机密环境变量优先、派生量。"""
from __future__ import annotations

import pytest

from core.config import ENV_R2_SECRET_ACCESS_KEY, ENV_WEB_PASSWORD, Config


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
    n = Config({"notion_sync": {"max_upload_mib": 5}}).get_notion_sync_config()
    assert n.max_upload_bytes == 5 * 1024 * 1024


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
