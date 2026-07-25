"""真实开发入口的离线契约测试：配置翻译与 MemEcho 装配均不得访问网络。"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace

from kacore.config import Config
from kacore.pipelines.memecho_recall import MemEchoRecall

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _ROOT / "tests" / "mocks" / "run_dev_realtime.py"
_CONFIG_EXAMPLE = _ROOT / "tests" / "mock_data" / "Config" / "config.example.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_test_run_dev_realtime", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeApi:
    def __init__(self, key: str) -> None:
        self.key = key
        self._memecho_recall = None

    def _memecho_api_key(self) -> str:
        return self.key


def test_memecho_raw_config_defaults_are_safe() -> None:
    script = _load_script()

    raw = script._memecho_raw_config(SimpleNamespace())

    assert raw == {
        "enabled": False,
        "base_url": "https://api.artific.social",
        "default_vault_id": "",
        "query_readonly": True,
        "write_back_enabled": False,
        "timeout_seconds": 30,
        "import_preset": "default",
    }
    assert "api_key" not in raw


def test_memecho_raw_config_maps_explicit_values() -> None:
    script = _load_script()
    cfg = SimpleNamespace(
        MEMECHO_ENABLED=True,
        MEMECHO_BASE_URL="https://memory.example.test/",
        MEMECHO_DEFAULT_VAULT_ID="vault-1",
        MEMECHO_QUERY_READONLY=False,
        MEMECHO_WRITE_BACK_ENABLED=True,
        MEMECHO_TIMEOUT_SECONDS=45,
        MEMECHO_IMPORT_PRESET="research",
    )

    raw = script._memecho_raw_config(cfg)

    assert raw["enabled"] is True
    assert raw["base_url"] == "https://memory.example.test/"
    assert raw["default_vault_id"] == "vault-1"
    assert raw["query_readonly"] is False
    assert raw["write_back_enabled"] is True
    assert raw["timeout_seconds"] == 45
    assert raw["import_preset"] == "research"


def test_attach_memecho_is_off_without_enablement() -> None:
    script = _load_script()
    api = _FakeApi("as_present")
    config = Config({"memecho": {"enabled": False}})

    diagnostic = script._attach_memecho(api, config)

    assert "未启用" in diagnostic
    assert config.runtime_memecho_key_present is True
    assert api._memecho_recall is None


def test_attach_memecho_reports_missing_key_without_network() -> None:
    script = _load_script()
    api = _FakeApi("")
    config = Config({"memecho": {"enabled": True}})

    diagnostic = script._attach_memecho(api, config)

    assert "未找到 API Key" in diagnostic
    assert config.runtime_memecho_key_present is False
    assert api._memecho_recall is None


def test_attach_memecho_builds_dynamic_client_without_network() -> None:
    script = _load_script()
    api = _FakeApi("as_initial")
    config = Config(
        {
            "memecho": {
                "enabled": True,
                "base_url": "https://memory.example.test",
                "default_vault_id": "vault-1",
                "timeout_seconds": 9,
            }
        }
    )

    diagnostic = script._attach_memecho(api, config)

    assert "MemEcho 已装配" in diagnostic
    assert config.runtime_memecho_key_present is True
    assert isinstance(api._memecho_recall, MemEchoRecall)
    assert api._memecho_recall._client._resolve_key() == "as_initial"
    api.key = "as_rotated"
    assert api._memecho_recall._client._resolve_key() == "as_rotated"


def test_config_template_never_defines_plaintext_memecho_key() -> None:
    text = _CONFIG_EXAMPLE.read_text(encoding="utf-8")

    assert "MEMECHO_ENABLED = False" in text
    assert re.search(r"^\s*MEMECHO_API_KEY\s*=", text, flags=re.MULTILINE) is None
