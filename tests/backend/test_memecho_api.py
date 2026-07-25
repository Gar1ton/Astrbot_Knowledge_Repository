"""MemEcho 在 API / 配置 / 能力探针 / 检索模式层的接入单测（分支 Experiment-with-MemEcho-API）。

覆盖 ask(memecho) 分支（二选一独立、不触本地 orchestrator）、错误路径、密钥门面（secret_store
永不回传明文）、能力三态与配置策略。
"""

from __future__ import annotations

import json

import pytest

from kacore.adapters.memecho.client import MemEchoClient
from kacore.api import KnowledgeRepositoryApi
from kacore.capabilities import detect_pipeline
from kacore.config import Config, api_writable_keys
from kacore.pipelines.memecho_recall import MemEchoRecall
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.retrieval_modes import MODE_MEMECHO, STRICT_COLLECTION_MODES, VALID_RETRIEVAL_MODES
from kacore.secret_store import EncryptedSecretStore


class _FakeLLM:
    async def generate(self, prompt: str, system_prompt: str = "", **_kwargs) -> str:
        assert "Recalled memories" in prompt
        return "答案：来自记忆库。"


def _transport(routes: dict):
    async def transport(method, url, *, headers, json_body, params, timeout_seconds):
        key = (method, url.split("/api/")[-1])
        return routes.get(key, routes.get("*", (200, "{}")))

    return transport


def _api(config, *, recall=None, llm=None, secret_store=None) -> KnowledgeRepositoryApi:
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=config,
        secret_store=secret_store,
    )
    api._memecho_recall = recall
    api._llm_adapter = llm
    return api


def _recall(routes: dict) -> MemEchoRecall:
    return MemEchoRecall(MemEchoClient("x", "k", transport=_transport(routes)))


# ── ask(memecho) 分支 ──────────────────────────────────────────────


async def test_ask_memecho_recall_and_synthesize() -> None:
    cfg = Config(
        {"memecho": {"enabled": True, "default_vault_id": "v1", "write_back_enabled": True}}
    )
    recall = _recall(
        {"*": (200, json.dumps({"results": [{"content": "喜欢深色"}], "degraded": False}))}
    )
    api = _api(cfg, recall=recall, llm=_FakeLLM())
    res = await api.ask("偏好？", retrieval_mode="memecho")
    assert res["actual_retrieval_mode"] == "memecho"
    assert res["retrieval_engines"] == ["memecho"]
    assert res["degraded"] is False
    assert res["sources"] and res["sources"][0]["origin"] == "memecho"
    # 二选一独立：未装配任何本地 orchestrator 也能完成（证明不触本地检索）。
    assert api._retrieval_orchestrator is None


async def test_ask_memecho_passes_degraded_through() -> None:
    cfg = Config({"memecho": {"enabled": True, "default_vault_id": "v1"}})
    recall = _recall({"*": (200, json.dumps({"results": [], "degraded": True, "messages": []}))})
    api = _api(cfg, recall=recall, llm=_FakeLLM())
    res = await api.ask("q", retrieval_mode="memecho")
    assert res["degraded"] is True


async def test_ask_memecho_requires_vault() -> None:
    api = _api(Config({"memecho": {"enabled": True}}), recall=_recall({}))
    with pytest.raises(ValueError):
        await api.ask("q", retrieval_mode="memecho")


async def test_ask_memecho_not_wired_raises() -> None:
    api = _api(Config({"memecho": {"enabled": True, "default_vault_id": "v1"}}), recall=None)
    with pytest.raises(RuntimeError):
        await api.ask("q", retrieval_mode="memecho")


async def test_ask_memecho_disabled_raises() -> None:
    api = _api(Config({"memecho": {"enabled": False}}), recall=_recall({}))
    with pytest.raises(ValueError):
        await api.ask("q", retrieval_mode="memecho")


# ── 密钥门面（secret_store，永不回传明文）───────────────────────────


async def test_save_and_delete_api_key(tmp_path) -> None:
    store = EncryptedSecretStore(tmp_path / "secrets")
    cfg = Config({"memecho": {"enabled": True, "default_vault_id": "v1"}})
    api = _api(cfg, secret_store=store)
    out = await api.save_memecho_api_key("as_secret_123")
    assert out["api_key_present"] is True
    assert out["api_key_masked"]
    assert cfg.runtime_memecho_key_present is True
    assert store.get_secret("memecho.api_key") == "as_secret_123"
    out2 = await api.delete_memecho_api_key()
    assert out2["api_key_present"] is False
    assert cfg.runtime_memecho_key_present is False


async def test_get_memecho_config_never_returns_plaintext(tmp_path) -> None:
    store = EncryptedSecretStore(tmp_path / "s")
    store.set_secret("memecho.api_key", "as_xyz_plain")
    cfg = Config({"memecho": {"enabled": True, "default_vault_id": "v1"}})
    api = _api(cfg, secret_store=store)
    out = await api.get_memecho_config()
    assert out["api_key_present"] is True
    assert "api_key" not in out
    assert out["api_key_masked"] and "as_xyz_plain" not in out["api_key_masked"]


async def test_save_empty_key_rejected(tmp_path) -> None:
    api = _api(Config({}), secret_store=EncryptedSecretStore(tmp_path / "s"))
    with pytest.raises(ValueError):
        await api.save_memecho_api_key("   ")


async def test_probe_without_key_reports_not_configured() -> None:
    api = _api(Config({"memecho": {"enabled": True}}))
    p = await api.probe_memecho()
    assert p["ok"] is False
    assert "未配置" in p["error"]


async def test_probe_with_injected_client() -> None:
    cfg = Config({"memecho": {"enabled": True, "default_vault_id": "v1"}})
    api = _api(cfg)
    client = MemEchoClient(
        "x",
        "k",
        transport=_transport(
            {
                ("GET", "v1/memory/vaults"): (200, json.dumps([{"id": "a"}])),
                ("GET", "v1/dashboard/services/memory/usage"): (200, "{}"),
            }
        ),
    )
    api._build_memecho_client = lambda: client  # type: ignore[method-assign]
    p = await api.probe_memecho()
    assert p["ok"] is True
    assert p["vault_count"] == 1


async def test_import_collection_requires_key() -> None:
    api = _api(Config({"memecho": {"enabled": True, "default_vault_id": "v1"}}))
    with pytest.raises(ValueError):
        await api.import_collection_to_memecho("coll")


# ── 能力探针 / 配置策略 / 模式登记 ─────────────────────────────────


def _memecho_stage(caps):
    return next(s for s in caps if s["id"] == "memecho")


def test_memecho_capability_three_states() -> None:
    assert _memecho_stage(detect_pipeline(Config({})))["status"] == "off"
    assert (
        _memecho_stage(detect_pipeline(Config({"memecho": {"enabled": True}})))["status"]
        == "degraded"
    )
    ready = Config({"memecho": {"enabled": True, "default_vault_id": "v"}})
    ready.runtime_memecho_key_present = True
    assert _memecho_stage(detect_pipeline(ready))["status"] == "ready"


def test_memecho_policy_excludes_api_key() -> None:
    writable = api_writable_keys()["memecho"]
    assert "api_key" not in writable
    assert "enabled" in writable
    assert "default_vault_id" in writable


def test_memecho_mode_valid_but_not_strict_collection() -> None:
    assert MODE_MEMECHO in VALID_RETRIEVAL_MODES
    assert MODE_MEMECHO not in STRICT_COLLECTION_MODES
