"""embedding.provider=astr 的接线：配置、缓存 namespace、索引指纹、工厂、API 重建标记、组合根。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from astrbot_fakes import (
    FAKE_SECRET,
    FakeAstrChatProvider,
    FakeAstrContext,
    FakeAstrEmbeddingBase,
    FakeAstrEmbeddingProvider,
)

from kacore.api import KnowledgeRepositoryApi
from kacore.capabilities import detect_pipeline
from kacore.config import (
    CONFIG_KEY_POLICY,
    CONSEQUENCE_REBUILD,
    ENV_EMBEDDING_API_KEY,
    Config,
    EmbeddingConfig,
    api_writable_keys,
    change_consequence,
    runtime_persistable_keys,
)
from kacore.domain.models import DocumentChunk, SourceDocument
from kacore.index_compatibility import IndexCompatibilityStore, embedding_fingerprint
from kacore.plugin_initializer import PluginInitializer
from kacore.repository.embedding.astrbot import AstrBotEmbeddingError, AstrBotEmbeddingProvider
from kacore.repository.embedding.cached import CachedEmbeddingProvider
from kacore.repository.embedding.external import ExternalEmbeddingProvider
from kacore.repository.embedding.factory import EmbeddingProviderFactory
from kacore.repository.embedding.local import LocalEmbeddingProvider
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.runtime_config import RuntimeConfigStore
from tests.backend.test_embedding import MockEmbeddingProvider


def _adapter(ctx: FakeAstrContext, provider_id: str) -> AstrBotEmbeddingProvider:
    return AstrBotEmbeddingProvider(ctx, provider_id, embedding_type=FakeAstrEmbeddingBase)


@pytest.fixture
def astr_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试环境没有 AstrBot：让适配器的默认判型类取到测试替身基类。"""
    monkeypatch.setattr(
        "kacore.repository.embedding.astrbot.load_astrbot_embedding_type",
        lambda: FakeAstrEmbeddingBase,
    )


# ── 配置：读取 / 展示 / 写入策略 / schema ─────────────────────────


def test_embedding_config_reads_astrbot_provider_id_and_strips_it() -> None:
    assert EmbeddingConfig().astrbot_provider_id == ""
    assert Config({}).get_embedding_config().astrbot_provider_id == ""
    null_id = Config({"embedding": {"astrbot_provider_id": None}})
    assert null_id.get_embedding_config().astrbot_provider_id == ""
    cfg = Config(
        {"embedding": {"provider": "astr", "astrbot_provider_id": "  my_embedding_provider "}}
    )
    assert cfg.get_embedding_config().astrbot_provider_id == "my_embedding_provider"
    assert cfg.get_embedding_config().uses_astrbot is True
    assert Config({"embedding": {"provider": " ASTR "}}).get_embedding_config().uses_astrbot is True
    assert EmbeddingConfig(provider="external").uses_astrbot is False


def test_effective_config_shows_provider_id_and_runtime_identity_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_EMBEDDING_API_KEY, raising=False)
    cfg = Config({"embedding": {"provider": "astr"}})  # 未填 ID：自动选择
    assert cfg.to_public_dict()["embedding"]["runtime_identity"] is None
    assert cfg.describe_embedding() == "astr:<auto>"

    cfg.set_embedding_identity(
        {"astrbot_provider_id": "auto-picked", "adapter_type": "openai_embedding", "model": "m-1"}
    )

    shown = cfg.to_public_dict()["embedding"]
    assert shown["provider"] == "astr"
    assert shown["astrbot_provider_id"] == ""
    assert shown["runtime_identity"]["astrbot_provider_id"] == "auto-picked"
    assert shown["api_key"] == ""  # astr 模式本插件不持有任何密钥
    assert cfg.describe_embedding() == "astr:auto-picked:m-1"
    assert FAKE_SECRET not in json.dumps(cfg.to_public_dict())


def test_describe_embedding_keeps_legacy_format_for_local_and_external() -> None:
    assert Config({}).describe_embedding() == "local:intfloat/multilingual-e5-small"
    assert (
        Config({"embedding": {"provider": "external", "model": "m"}}).describe_embedding()
        == "external:m"
    )


def test_astr_needs_no_static_diagnostics_and_no_embedding_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_EMBEDDING_API_KEY, raising=False)
    diagnostics = Config({"embedding": {"provider": "astr"}}).get_diagnostics()

    assert not any("embedding" in item.lower() and "astr" in item.lower() for item in diagnostics)
    assert not any("KR_EMBEDDING_API_KEY" in item for item in diagnostics)


def test_astrbot_provider_id_write_policy_is_api_writable_persistable_and_rebuild() -> None:
    policy = CONFIG_KEY_POLICY["embedding"]["astrbot_provider_id"]
    assert (policy.api_writable, policy.runtime_persistable, policy.structural) == (
        True,
        True,
        False,
    )
    assert change_consequence("embedding", "astrbot_provider_id") == CONSEQUENCE_REBUILD
    assert "astrbot_provider_id" in api_writable_keys()["embedding"]
    assert "astrbot_provider_id" in runtime_persistable_keys()["embedding"]


def test_astrbot_provider_id_persists_through_runtime_config(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime_config.json")
    store.set_value("embedding", "provider", "astr")
    store.set_value("embedding", "astrbot_provider_id", "my_embedding_provider")

    merged = Config(RuntimeConfigStore(tmp_path / "runtime_config.json").merged_with({}))

    assert merged.get_embedding_config().provider == "astr"
    assert merged.get_embedding_config().astrbot_provider_id == "my_embedding_provider"


def test_conf_schema_offers_astr_and_never_asks_for_a_duplicate_api_key() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text("utf-8"))
    items = schema["embedding"]["items"]

    assert items["provider"]["options"] == ["local", "external", "astr"]
    assert items["astrbot_provider_id"]["type"] == "string"
    assert items["astrbot_provider_id"]["default"] == ""
    assert "Embedding Provider 的 ID" in items["astrbot_provider_id"]["hint"]
    assert not any("key" in name.lower() for name in items)  # 不在本插件里重复保存 API key


def test_pipeline_snapshot_lists_astr_as_a_supported_embedding_source() -> None:
    cfg = Config({"embedding": {"provider": "astr", "astrbot_provider_id": "emb-a"}})
    cfg.set_embedding_dimension(1024)
    cfg.set_embedding_identity({"astrbot_provider_id": "emb-a", "adapter_type": "x", "model": ""})

    stage = next(s for s in detect_pipeline(cfg) if s["id"] == "embedding")

    assert "astr" in stage["candidates"]
    assert stage["configured"] is True
    assert stage["status"] == "ready"  # 探针拿到了实际维度
    assert stage["detail"]["astrbot_identity"]["astrbot_provider_id"] == "emb-a"
    assert stage["required_deps"] == []


# ── 缓存 namespace ───────────────────────────────────────────────


def test_cache_namespace_of_non_astr_providers_is_byte_identical_to_before() -> None:
    cached = CachedEmbeddingProvider(MockEmbeddingProvider(), namespace="external:m:https://x")

    assert cached.identity == {}
    assert cached._get_hash("t") == hashlib.sha256(b"external:m:https://x\0t").hexdigest()


async def _cache_hits(cache_db: str, adapter: AstrBotEmbeddingProvider, texts: list[str]) -> int:
    provider = adapter._context.get_provider_by_id(adapter.provider_id)
    before = len(provider.called("get_embeddings"))
    cached = CachedEmbeddingProvider(adapter, db_path=cache_db, namespace="astr")
    await cached.embed_documents(texts)
    return len(provider.called("get_embeddings")) - before


async def test_cache_distinguishes_astrbot_provider_model_and_dimension(tmp_path: Path) -> None:
    db = str(tmp_path / "cache.db")

    def build(pid: str, *, model: str = "m-1", dim: int = 4) -> AstrBotEmbeddingProvider:
        ctx = FakeAstrContext(FakeAstrEmbeddingProvider(pid, model=model, declared_dim=dim))
        adapter = _adapter(ctx, pid)
        return adapter

    # 首次写入：必然调用一次 provider。
    assert await _cache_hits(db, build("emb-a"), ["same text"]) == 1
    # 同一身份（新进程/新实例）：命中缓存，不再请求。
    assert await _cache_hits(db, build("emb-a"), ["same text"]) == 0
    # provider ID / 模型 / 维度任一不同：不得复用旧向量。
    assert await _cache_hits(db, build("emb-b"), ["same text"]) == 1
    assert await _cache_hits(db, build("emb-a", model="m-2"), ["same text"]) == 1
    assert await _cache_hits(db, build("emb-a", dim=8), ["same text"]) == 1


def test_cached_wrapper_exposes_inner_identity_and_unload_never_terminates() -> None:
    provider = FakeAstrEmbeddingProvider("emb-a")
    adapter = _adapter(FakeAstrContext(provider), "emb-a")
    cached = CachedEmbeddingProvider(adapter, db_path=":memory:", namespace="astr")

    assert cached.identity["astrbot_provider_id"] == "emb-a"
    cached.unload()  # 面板「卸载模型」经缓存层透传到适配器
    assert provider.called("terminate") == [] and provider.called("close") == []
    assert cached.runtime_status["state"] == "external"


# ── 索引指纹 ─────────────────────────────────────────────────────


def test_local_and_external_fingerprints_are_frozen_against_pre_astr_values() -> None:
    """升级不得让既有 local/external 索引被误判为不兼容：值取自改动前的实现。"""
    local = EmbeddingConfig(
        provider="local", model="intfloat/multilingual-e5-small", base_url="https://api.openai.com/v1"
    )
    external = EmbeddingConfig(
        provider="external", model="text-embedding-3-small", base_url="https://api.example.test/v1"
    )

    assert embedding_fingerprint(local, 384) == (
        "901fa583ba316a6ba3174b92a009840be8e4708296a12de9b23e8dba41a5351e"
    )
    assert embedding_fingerprint(external, 1536) == (
        "70a10d12bb9494ebd1dacea230f7d594fb38f1eb14c8a6e6f4c0c30db3166304"
    )
    # 传入 identity 对非 astr 无影响。
    assert embedding_fingerprint(local, 384, {"astrbot_provider_id": "x"}) == embedding_fingerprint(
        local, 384
    )


def test_astr_fingerprint_changes_with_provider_type_model_and_dimension() -> None:
    cfg = EmbeddingConfig(provider="astr")
    base_identity = {
        "astrbot_provider_id": "emb-a",
        "adapter_type": "openai_embedding",
        "model": "m",
    }
    base = embedding_fingerprint(cfg, 4, base_identity)

    assert embedding_fingerprint(cfg, 4, dict(base_identity)) == base
    assert embedding_fingerprint(cfg, 5, base_identity) != base
    for field, value in (
        ("astrbot_provider_id", "emb-b"),
        ("adapter_type", "ollama_embedding"),
        ("model", "m2"),
    ):
        assert embedding_fingerprint(cfg, 4, {**base_identity, field: value}) != base


def test_astr_fingerprint_ignores_the_unused_model_and_base_url_settings() -> None:
    identity = {"astrbot_provider_id": "emb-a", "adapter_type": "t", "model": "m"}
    one = EmbeddingConfig(provider="astr", model="ignored-1", base_url="https://ignored-1")
    two = EmbeddingConfig(provider="astr", model="ignored-2", base_url="https://ignored-2")

    assert embedding_fingerprint(one, 4, identity) == embedding_fingerprint(two, 4, identity)


def test_astr_fingerprint_is_not_the_same_as_any_local_or_external_fingerprint() -> None:
    astr = embedding_fingerprint(
        EmbeddingConfig(provider="astr"), 384, {"astrbot_provider_id": "emb-a"}
    )
    assert astr != embedding_fingerprint(EmbeddingConfig(provider="local"), 384)
    assert astr != embedding_fingerprint(EmbeddingConfig(provider="external"), 384)


# ── 工厂 ─────────────────────────────────────────────────────────


def test_factory_builds_a_cached_astrbot_provider(astr_type: None, tmp_path: Path) -> None:
    provider = FakeAstrEmbeddingProvider("emb-a")
    config = Config({"embedding": {"provider": "astr", "astrbot_provider_id": "emb-a"}})

    created = EmbeddingProviderFactory.create_provider(
        config, db_dir=str(tmp_path), context=FakeAstrContext(provider)
    )

    assert isinstance(created, CachedEmbeddingProvider)
    assert isinstance(created._inner, AstrBotEmbeddingProvider)
    assert created.identity["astrbot_provider_id"] == "emb-a"
    assert created.get_dimension() == 4


def test_factory_astr_failures_surface_as_clear_errors(astr_type: None, tmp_path: Path) -> None:
    config = Config({"embedding": {"provider": "astr", "astrbot_provider_id": "nope"}})

    with pytest.raises(AstrBotEmbeddingError):
        EmbeddingProviderFactory.create_provider(
            config, db_dir=str(tmp_path), context=FakeAstrContext(FakeAstrChatProvider("nope"))
        )
    with pytest.raises(AstrBotEmbeddingError):
        EmbeddingProviderFactory.create_provider(config, db_dir=str(tmp_path))  # 没传 Context


def test_factory_local_and_external_paths_ignore_the_context(tmp_path: Path) -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))

    local = EmbeddingProviderFactory.create_provider(
        Config({"embedding": {"provider": "local"}}), db_dir=str(tmp_path), context=ctx
    )
    external = EmbeddingProviderFactory.create_provider(
        Config({"embedding": {"provider": "external", "model": "m", "base_url": "https://x/v1"}}),
        db_dir=str(tmp_path),
    )

    assert isinstance(local._inner, LocalEmbeddingProvider)  # type: ignore[attr-defined]
    assert isinstance(external._inner, ExternalEmbeddingProvider)  # type: ignore[attr-defined]
    assert local._namespace.startswith("local:")  # type: ignore[attr-defined]
    assert external._namespace == "external:m:https://x/v1"  # type: ignore[attr-defined]
    assert ctx.get_provider_by_id("emb-a").calls == []  # 完全没碰 AstrBot provider


def test_factory_rejects_unknown_provider_names_all_three_choices() -> None:
    with pytest.raises(ValueError, match="'local', 'external' or 'astr'"):
        EmbeddingProviderFactory.create_provider(Config({"embedding": {"provider": "bogus"}}))


# ── API：改 provider / provider ID → 索引标记重建 ─────────────────


async def _api_with_compatible_index(tmp_path: Path, raw: dict[str, Any]) -> tuple[Any, ...]:
    from kacore.repository.vector_store.memory import InMemoryVectorStore

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument("d1", "d1", "/d1.pdf", "application/pdf", 1, "h", "papers")
    )
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compat = IndexCompatibilityStore(tmp_path / "compat.json")
    compat.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config(raw),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compat,
        embedding_fingerprint="fp",
    )
    return api, store, compat


async def test_switching_to_astr_or_changing_provider_id_marks_indexes_for_rebuild(
    tmp_path: Path,
) -> None:
    api, store, compat = await _api_with_compatible_index(
        tmp_path,
        {
            "vector_db": {"backend": "milvus"},
            "embedding": {"provider": "local", "astrbot_provider_id": "emb-a"},
        },
    )

    switched = await api.update_config_value("embedding", "provider", "astr")

    assert switched["rebuild_required"] is True and switched["restart_required"] is True
    assert not compat.is_milvus_compatible("fp")
    assert [d.doc_id for d in await store.list_pending_reindex_documents()] == ["d1"]

    compat.mark_milvus_compatible("fp")  # 模拟一次重建完成后再改 provider ID

    changed = await api.update_config_value("embedding", "astrbot_provider_id", "emb-b")
    assert changed["rebuild_required"] is True
    assert not compat.is_milvus_compatible("fp")


async def test_resaving_the_same_provider_id_does_not_invalidate_indexes(tmp_path: Path) -> None:
    api, _store, compat = await _api_with_compatible_index(
        tmp_path,
        {
            "vector_db": {"backend": "milvus"},
            "embedding": {"provider": "astr", "astrbot_provider_id": "emb-a"},
        },
    )

    same = await api.update_config_value("embedding", "astrbot_provider_id", "  emb-a  ")

    assert same["rebuild_required"] is False and same["restart_required"] is False
    assert compat.is_milvus_compatible("fp")


@pytest.mark.parametrize("bad", [123, None, "a\nb", "x" * 201])
async def test_astrbot_provider_id_rejects_non_ids(tmp_path: Path, bad: Any) -> None:
    api, _store, _compat = await _api_with_compatible_index(tmp_path, {})

    with pytest.raises(ValueError, match="astrbot_provider_id"):
        await api.update_config_value("embedding", "astrbot_provider_id", bad)


# ── 组合根（PluginInitializer）───────────────────────────────────


class _Milvus:
    """记录装配维度的 Milvus 桩；created_collection 控制「是已有索引」还是「新建」。"""

    created_collection = True
    dims: list[int] = []

    def __init__(self, *, db_path: str, dim: int) -> None:
        type(self).dims.append(dim)

    def validate_schema(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _astr_raw(provider_id: str = "emb-a") -> dict[str, Any]:
    return {
        "vector_db": {"backend": "milvus"},
        "graph": {"enabled": False},
        "embedding": {"provider": "astr", "astrbot_provider_id": provider_id},
    }


async def _boot(tmp_path: Path, raw: dict[str, Any], ctx: object) -> PluginInitializer:
    initializer = PluginInitializer(ctx, raw, tmp_path)
    await initializer.initialize()
    return initializer


@pytest.fixture
def milvus_stub():
    _Milvus.dims = []
    _Milvus.created_collection = True
    with (
        patch("kacore.repository.vector_store.milvus_lite.MilvusLiteVectorStore", _Milvus),
        patch("kacore.plugin_initializer._module_available", return_value=True),
    ):
        yield _Milvus


async def test_initializer_resolves_astr_probes_real_vector_and_builds_identity_fingerprint(
    tmp_path: Path, astr_type: None, milvus_stub: type[_Milvus]
) -> None:
    # 声明维度 0（OpenAI 源未配 embedding_dimensions）：维度必须来自探针实际返回的向量。
    provider = FakeAstrEmbeddingProvider("emb-a", declared_dim=0, actual_dim=6, model="m-1")
    initializer = await _boot(tmp_path, _astr_raw(), FakeAstrContext(provider))
    try:
        assert initializer.embedding_provider is not None
        assert initializer.embedding_dimension == 6
        assert milvus_stub.dims == [6]
        assert provider.called("get_embedding")  # 探针走 AstrBot 抽象
        expected = embedding_fingerprint(
            EmbeddingConfig(provider="astr"),
            6,
            {"astrbot_provider_id": "emb-a", "adapter_type": "openai_embedding", "model": "m-1"},
        )
        assert initializer.embedding_fingerprint == expected
        shown = initializer.config.to_public_dict()["embedding"]
        assert shown["actual_dimension"] == 6
        assert shown["runtime_identity"]["astrbot_provider_id"] == "emb-a"
        assert FAKE_SECRET not in json.dumps(shown)
    finally:
        await initializer.teardown()
    # 插件退出只释放自身资源：共享 provider 没被 terminate / 关闭。
    assert provider.called("terminate") == [] and provider.called("close") == []


async def test_initializer_auto_selects_the_only_provider_and_reports_it(
    tmp_path: Path, astr_type: None, milvus_stub: type[_Milvus]
) -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("only-one"), FakeAstrChatProvider())
    initializer = await _boot(tmp_path, _astr_raw(""), ctx)
    try:
        assert initializer.embedding_provider is not None
        assert initializer.config.runtime_embedding_identity["astrbot_provider_id"] == "only-one"
        assert initializer.config.describe_embedding().startswith("astr:only-one")
    finally:
        await initializer.teardown()


@pytest.mark.parametrize(
    ("ctx_factory", "expected"),
    [
        (lambda: FakeAstrContext(FakeAstrEmbeddingProvider("emb-a")), "emb-x"),
        (lambda: FakeAstrContext(FakeAstrChatProvider("emb-x")), "不是 Embedding Provider"),
        (lambda: FakeAstrContext(), "没有已启用的 Embedding Provider"),
        (
            lambda: FakeAstrContext(
                FakeAstrEmbeddingProvider("a"), FakeAstrEmbeddingProvider("b")
            ),
            "不会静默选第一个",
        ),
    ],
    ids=["missing-id", "wrong-type", "none-available", "ambiguous"],
)
async def test_initializer_degrades_with_a_clear_diagnostic_when_astr_cannot_resolve(
    tmp_path: Path,
    astr_type: None,
    milvus_stub: type[_Milvus],
    ctx_factory: Any,
    expected: str,
) -> None:
    raw = _astr_raw("emb-x" if expected in {"emb-x", "不是 Embedding Provider"} else "")
    initializer = await _boot(tmp_path, raw, ctx_factory())
    try:
        # 不阻止插件其它基础功能启动，只是向量/图谱不可用。
        assert initializer.api is not None and initializer.source_store is not None
        assert initializer.embedding_provider is None
        assert initializer.vector_store is None
        diagnostics = initializer.config.get_diagnostics()
        assert any("Embedding provider unavailable" in d and expected in d for d in diagnostics)
    finally:
        await initializer.teardown()


async def test_initializer_degrades_when_the_probe_vector_contradicts_declared_dimension(
    tmp_path: Path, astr_type: None, milvus_stub: type[_Milvus]
) -> None:
    provider = FakeAstrEmbeddingProvider("emb-a", declared_dim=8, actual_dim=4)
    initializer = await _boot(tmp_path, _astr_raw(), FakeAstrContext(provider))
    try:
        assert initializer.embedding_provider is None and initializer.vector_store is None
        assert any(
            "声明维度 8" in d and "Embedding provider unavailable" in d
            for d in initializer.config.get_diagnostics()
        )
    finally:
        await initializer.teardown()


async def test_initializer_flags_existing_index_incompatible_after_provider_identity_change(
    tmp_path: Path, astr_type: None, milvus_stub: type[_Milvus]
) -> None:
    first = await _boot(
        tmp_path, _astr_raw("emb-a"), FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))
    )
    fingerprint_a = first.embedding_fingerprint
    await first.teardown()
    assert fingerprint_a is not None

    milvus_stub.created_collection = False  # 之后的启动面对的是「已有索引」

    # 同一个 provider 重启：仍兼容。
    same = await _boot(
        tmp_path, _astr_raw("emb-a"), FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))
    )
    assert same.index_compatibility.is_milvus_compatible(same.embedding_fingerprint)
    assert not any("incompatible" in d for d in same.config.get_diagnostics())
    await same.teardown()

    # 换 provider ID / 换模型 / 换维度：旧索引必须被判不兼容，进入既有重建流程。
    variants = {
        "provider-id": ("emb-b", FakeAstrEmbeddingProvider("emb-b")),
        "model": ("emb-a", FakeAstrEmbeddingProvider("emb-a", model="model-z")),
        "dimension": ("emb-a", FakeAstrEmbeddingProvider("emb-a", declared_dim=8)),
    }
    for name, (configured_id, changed) in variants.items():
        booted = await _boot(tmp_path, _astr_raw(configured_id), FakeAstrContext(changed))
        try:
            assert booted.embedding_fingerprint != fingerprint_a, name
            assert not booted.index_compatibility.is_milvus_compatible(
                booted.embedding_fingerprint
            ), name
            assert any(
                "Milvus index is incompatible with the active embedding" in d
                for d in booted.config.get_diagnostics()
            ), name
        finally:
            await booted.teardown()


async def test_non_astr_startup_is_unaffected_and_never_touches_the_astrbot_context(
    tmp_path: Path, milvus_stub: type[_Milvus]
) -> None:
    class Provider:  # 没有 identity 属性的旧式桩
        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * 7

    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))
    raw = {"vector_db": {"backend": "milvus"}, "graph": {"enabled": False}}
    with patch(
        "kacore.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
        return_value=Provider(),
    ) as create:
        initializer = await _boot(tmp_path, raw, ctx)
        try:
            assert initializer.embedding_dimension == 7
            assert initializer.embedding_fingerprint == embedding_fingerprint(
                initializer.config.get_embedding_config(), 7
            )
            assert initializer.config.runtime_embedding_identity is None
            assert create.call_args.kwargs["context"] is ctx  # 组合根传入 Context，非 astr 时被忽略
        finally:
            await initializer.teardown()
    assert ctx.get_provider_by_id("emb-a").calls == []
