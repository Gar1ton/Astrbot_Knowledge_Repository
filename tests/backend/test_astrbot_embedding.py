"""AstrBot Embedding 适配器：provider 解析、返回值校验、脱敏、生命周期边界、身份漂移。"""
from __future__ import annotations

import copy
import traceback
from types import SimpleNamespace
from typing import Any

import pytest
from astrbot_fakes import (
    FAKE_SECRET,
    FakeAstrChatProvider,
    FakeAstrContext,
    FakeAstrDuckTypedProvider,
    FakeAstrEmbeddingBase,
    FakeAstrEmbeddingProvider,
)

from kacore.repository.embedding import astrbot_resolver as resolver_mod
from kacore.repository.embedding.astrbot import (
    STAGE_DIMENSION,
    STAGE_EMBED_DOCUMENTS,
    STAGE_EMBED_QUERY,
    STAGE_RESOLVE,
    AstrBotEmbeddingError,
    AstrBotEmbeddingProvider,
    resolve_astrbot_embedding_provider,
)


def _adapter(
    context: FakeAstrContext, provider_id: str = "emb-a"
) -> AstrBotEmbeddingProvider:
    return AstrBotEmbeddingProvider(context, provider_id, embedding_type=FakeAstrEmbeddingBase)


# ── Provider 解析规则 ────────────────────────────────────────────


def test_explicit_id_resolves_the_configured_embedding_provider() -> None:
    other = FakeAstrEmbeddingProvider("emb-b")
    wanted = FakeAstrEmbeddingProvider("emb-a")

    provider, resolved = resolve_astrbot_embedding_provider(
        FakeAstrContext(other, wanted), " emb-a ", embedding_type=FakeAstrEmbeddingBase
    )

    assert provider is wanted
    assert resolved == "emb-a"


def test_missing_provider_id_is_a_clear_diagnostic_with_available_ids() -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        _adapter(ctx, "typo")

    message = str(excinfo.value)
    assert excinfo.value.stage == STAGE_RESOLVE
    assert "provider_id='typo'" in message
    assert "不存在" in message
    assert "emb-a" in message  # 可执行的修复建议：列出真正存在的 ID


@pytest.mark.parametrize(
    "wrong",
    [FakeAstrChatProvider("chat-a"), FakeAstrDuckTypedProvider()],
    ids=["chat-provider", "duck-typed-lookalike"],
)
def test_non_embedding_provider_is_rejected_even_if_it_looks_similar(wrong: Any) -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))
    ctx._inst_map[wrong.meta().id] = wrong

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        _adapter(ctx, wrong.meta().id)

    assert "不是 Embedding Provider" in str(excinfo.value)
    assert "emb-a" in str(excinfo.value)


def test_no_provider_id_auto_selects_the_only_live_embedding_provider() -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("only-one"), FakeAstrChatProvider())

    adapter = AstrBotEmbeddingProvider(ctx, "", embedding_type=FakeAstrEmbeddingBase)

    assert adapter.provider_id == "only-one"


def test_no_provider_id_and_no_embedding_provider_is_a_clear_diagnostic() -> None:
    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        AstrBotEmbeddingProvider(
            FakeAstrContext(FakeAstrChatProvider()), "", embedding_type=FakeAstrEmbeddingBase
        )

    assert excinfo.value.stage == STAGE_RESOLVE
    assert "没有已启用的 Embedding Provider" in str(excinfo.value)
    assert "embedding.astrbot_provider_id" in str(excinfo.value)


def test_no_provider_id_with_several_providers_requires_explicit_id() -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"), FakeAstrEmbeddingProvider("emb-b"))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        AstrBotEmbeddingProvider(ctx, "", embedding_type=FakeAstrEmbeddingBase)

    message = str(excinfo.value)
    assert "emb-a" in message and "emb-b" in message
    assert "不会静默选第一个" in message


def test_auto_select_ignores_stale_instance_left_behind_by_astrbot_reload() -> None:
    """AstrBot 的 terminate_provider 不会把旧实例移出 embedding 列表：不能因此误判成「多个」。"""
    old = FakeAstrEmbeddingProvider("emb-a")
    ctx = FakeAstrContext(old)
    fresh = FakeAstrEmbeddingProvider("emb-a")
    ctx.replace(fresh)
    assert len(ctx.get_all_embedding_providers()) == 2

    provider, resolved = resolve_astrbot_embedding_provider(
        ctx, "", embedding_type=FakeAstrEmbeddingBase
    )

    assert provider is fresh
    assert resolved == "emb-a"


def test_missing_context_is_a_clear_diagnostic() -> None:
    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        resolve_astrbot_embedding_provider(None, "emb-a", embedding_type=FakeAstrEmbeddingBase)

    assert "没有 AstrBot Context" in str(excinfo.value)


def test_embedding_type_loader_prefers_public_facade_then_core_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = {
        "astrbot.api.provider": SimpleNamespace(),  # 门面未导出（4.26/4.27 现状）
        "astrbot.core.provider.provider": SimpleNamespace(EmbeddingProvider=FakeAstrEmbeddingBase),
    }

    def fake_import(name: str) -> Any:
        if name in modules:
            return modules[name]
        raise ImportError(name)

    monkeypatch.setattr(resolver_mod.importlib, "import_module", fake_import)
    assert resolver_mod.load_astrbot_embedding_type() is FakeAstrEmbeddingBase

    modules["astrbot.api.provider"] = SimpleNamespace(EmbeddingProvider=FakeAstrChatProvider)
    assert resolver_mod.load_astrbot_embedding_type() is FakeAstrChatProvider  # 门面优先


def test_embedding_type_loader_fails_closed_when_astrbot_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_import(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(resolver_mod.importlib, "import_module", broken_import)

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        resolver_mod.load_astrbot_embedding_type()

    assert "无法从 AstrBot 导入 EmbeddingProvider" in str(excinfo.value)


# ── 委托与空输入 ─────────────────────────────────────────────────


async def test_query_and_documents_go_through_the_astrbot_abstraction() -> None:
    provider = FakeAstrEmbeddingProvider("emb-a", declared_dim=4)
    adapter = _adapter(FakeAstrContext(provider))

    query = await adapter.embed_query("hello")
    docs = await adapter.embed_documents(["a", "b", "c"])

    assert query == [0.1] * 4
    assert [len(v) for v in docs] == [4, 4, 4]
    assert docs[0] != docs[1]  # 顺序即输入顺序
    assert provider.called("get_embedding") == ["hello"]  # query 只走单文本接口
    assert provider.called("get_embeddings") == [["a", "b", "c"]]  # documents 只走批量接口


async def test_empty_documents_return_empty_list_without_any_remote_call() -> None:
    provider = FakeAstrEmbeddingProvider()
    adapter = _adapter(FakeAstrContext(provider))

    assert await adapter.embed_documents([]) == []
    assert provider.calls == []


# ── 返回值检查 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("bad_vector", "type_name"),
    [([], "list"), (None, "NoneType"), ("abcd", "str"), ({"embedding": [0.1]}, "dict")],
    ids=["empty-list", "none", "string", "dict"],
)
async def test_query_rejects_empty_or_non_list_vectors(bad_vector: Any, type_name: str) -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=4)
    adapter = _adapter(FakeAstrContext(provider))

    async def bad_get_embedding(text: str) -> Any:
        return bad_vector

    provider.get_embedding = bad_get_embedding  # type: ignore[method-assign]

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_query("x")

    assert excinfo.value.stage == STAGE_EMBED_QUERY
    assert f"第 0 条向量不是非空数值列表（类型 {type_name}" in str(excinfo.value)


@pytest.mark.parametrize("bad_result", [None, {"data": []}, "abc"], ids=["none", "dict", "str"])
async def test_documents_result_must_be_a_list_of_vectors(bad_result: Any) -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=4)
    adapter = _adapter(FakeAstrContext(provider))

    async def bad_get_embeddings(texts: list[str]) -> Any:
        return bad_result

    provider.get_embeddings = bad_get_embeddings  # type: ignore[method-assign]

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a"])

    assert excinfo.value.stage == STAGE_EMBED_DOCUMENTS
    assert f"返回值类型是 {type(bad_result).__name__}，应为向量列表" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad_value", ["0.1", None, True, float("nan"), float("inf"), [0.1]], ids=repr
)
async def test_vectors_must_contain_only_finite_numbers(bad_value: Any) -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=3)
    provider.query_result = [0.1, bad_value, 0.3]
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_query("x")

    assert "第 1 个元素" in str(excinfo.value)


async def test_integer_components_are_accepted_and_returned_as_floats() -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=3)
    provider.query_result = [1, 2, 3]

    vector = await _adapter(FakeAstrContext(provider)).embed_query("x")

    assert vector == [1.0, 2.0, 3.0]
    assert all(type(v) is float for v in vector)


async def test_batch_count_mismatch_is_reported_with_both_numbers() -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=4)
    provider.documents_result = [[0.1] * 4, [0.2] * 4]  # 3 条输入只回 2 条
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a", "b", "c"])

    assert excinfo.value.stage == STAGE_EMBED_DOCUMENTS
    assert "数量 2 与输入数量 3 不一致" in str(excinfo.value)


async def test_dimensions_inside_one_batch_must_agree() -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=0)
    provider.documents_result = [[0.1] * 4, [0.1] * 3]
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a", "b"])

    assert "第 1 条向量维度 3 与第 0 条的 4 不一致" in str(excinfo.value)


async def test_actual_dimension_must_match_declared_dimension_and_is_never_padded() -> None:
    provider = FakeAstrEmbeddingProvider(declared_dim=8, actual_dim=4)
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_query("x")

    message = str(excinfo.value)
    assert "实际向量维度 4 与 provider 声明维度 8" in message
    assert "embedding_dimensions" in message  # 可执行建议
    assert "不会截断或填充" in message


async def test_undeclared_dimension_is_locked_by_the_first_real_vector() -> None:
    """OpenAI 源未配 embedding_dimensions 时 get_dim()==0：以首个实测向量为准并锁定。"""
    provider = FakeAstrEmbeddingProvider(declared_dim=0, actual_dim=6)
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as before:
        adapter.get_dimension()
    assert before.value.stage == STAGE_DIMENSION

    assert len(await adapter.embed_query("probe")) == 6
    assert adapter.get_dimension() == 6  # 维度探针来自实际返回向量

    provider.actual_dim = 5  # 之后 provider 悄悄换了输出维度
    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a"])
    assert "与此前观测到的 6 不一致" in str(excinfo.value)


# ── 错误信息：内容与脱敏 ─────────────────────────────────────────


async def test_provider_failure_message_has_id_type_model_stage_and_advice_but_no_secret() -> None:
    provider = FakeAstrEmbeddingProvider("emb-a", adapter_type="openai_embedding", model="m-1")
    provider.raise_error = RuntimeError(
        f"Error code: 401 - Incorrect API key provided: {FAKE_SECRET}. "
        f"headers: Authorization: Bearer {FAKE_SECRET}; url=https://x.test/v1?api_key={FAKE_SECRET}"
    )
    adapter = _adapter(FakeAstrContext(provider))

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a"])

    error = excinfo.value
    message = str(error)
    assert "provider_id='emb-a'" in message
    assert "type=openai_embedding" in message
    assert "model=m-1" in message
    assert f"阶段 {STAGE_EMBED_DOCUMENTS}" in message
    assert "建议：" in message and "AstrBot" in message
    assert "RuntimeError" in message  # 保留异常类型帮助排查
    assert FAKE_SECRET not in message
    # 原始异常链被切断：完整堆栈文本里也不能带出凭据。
    assert error.__cause__ is None and error.__suppress_context__ is True
    assert FAKE_SECRET not in "".join(traceback.format_exception(error))
    assert FAKE_SECRET not in str(adapter.runtime_status)


async def test_model_is_omitted_from_error_when_provider_does_not_report_it() -> None:
    provider = FakeAstrEmbeddingProvider("emb-a", model="")
    provider.raise_error = RuntimeError("boom")

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await _adapter(FakeAstrContext(provider)).embed_query("x")

    assert "model=" not in str(excinfo.value)
    assert "provider_id='emb-a'" in str(excinfo.value)


# ── 生命周期边界 ─────────────────────────────────────────────────


async def test_adapter_never_terminates_closes_reconfigures_or_reads_the_client() -> None:
    provider = FakeAstrEmbeddingProvider("emb-a")
    config_before = copy.deepcopy(provider.provider_config)
    adapter = _adapter(FakeAstrContext(provider))

    await adapter.embed_query("q")
    await adapter.embed_documents(["a", "b"])
    adapter.unload()  # 「卸载模型」操作不得卸载共享 provider
    adapter.unload()
    _ = adapter.runtime_status, adapter.identity  # 读状态也不得触发任何调用

    assert {name for name, _ in provider.calls} == {"get_embedding", "get_embeddings"}
    assert provider.provider_config == config_before  # 不改其配置（含密钥字段原样未动）
    assert provider.get_model() == "model-a"  # 也没有 set_model


def test_runtime_status_marks_an_astrbot_managed_external_provider() -> None:
    adapter = _adapter(FakeAstrContext(FakeAstrEmbeddingProvider("emb-a", model="m-1")))

    status = adapter.runtime_status

    assert status["provider"] == "astr"
    assert status["state"] == "external"  # 无本地模型可驻留
    assert status["model"] == "m-1"
    assert status["astrbot_provider_id"] == "emb-a"
    assert status["last_error"] is None
    assert FAKE_SECRET not in str(status)


async def test_runtime_status_records_last_error_until_next_success() -> None:
    provider = FakeAstrEmbeddingProvider()
    adapter = _adapter(FakeAstrContext(provider))
    provider.raise_error = RuntimeError("boom")
    with pytest.raises(AstrBotEmbeddingError):
        await adapter.embed_query("x")
    assert "boom" in str(adapter.runtime_status["last_error"])

    provider.raise_error = None
    await adapter.embed_query("x")
    assert adapter.runtime_status["last_error"] is None


# ── 身份与热重载 ─────────────────────────────────────────────────


async def test_identity_is_non_secret_and_includes_observed_dimension() -> None:
    provider = FakeAstrEmbeddingProvider(
        "emb-a", adapter_type="ollama_embedding", model="nomic", declared_dim=0, actual_dim=7
    )
    adapter = _adapter(FakeAstrContext(provider))
    assert adapter.identity["dimension"] == ""  # 尚未探针

    await adapter.embed_query("probe")

    assert adapter.identity == {
        "astrbot_provider_id": "emb-a",
        "adapter_type": "ollama_embedding",
        "model": "nomic",
        "dimension": "7",
    }
    assert FAKE_SECRET not in str(adapter.identity)


async def test_hot_reloaded_instance_with_same_identity_is_followed_not_the_closed_one() -> None:
    old = FakeAstrEmbeddingProvider("emb-a")
    ctx = FakeAstrContext(old)
    adapter = _adapter(ctx)
    await adapter.embed_query("before")

    fresh = FakeAstrEmbeddingProvider("emb-a")
    ctx.replace(fresh)  # AstrBot 重载：旧实例已 terminate，新实例可用
    await adapter.embed_query("after")

    assert old.called("get_embedding") == ["before"]
    assert fresh.called("get_embedding") == ["after"]


@pytest.mark.parametrize(
    "change",
    [
        {"model": "model-b"},
        {"declared_dim": 8},
    ],
    ids=["model-changed", "declared-dimension-changed"],
)
async def test_identity_drift_after_startup_refuses_to_mix_vector_spaces(
    change: dict[str, Any],
) -> None:
    provider = FakeAstrEmbeddingProvider("emb-a", declared_dim=4)
    adapter = _adapter(FakeAstrContext(provider))
    await adapter.embed_query("ok")

    provider.reconfigure(**change)

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_documents(["a"])
    assert "被 AstrBot 重新配置" in str(excinfo.value)
    assert "重建向量索引" in str(excinfo.value)
    assert provider.called("get_embeddings") == []  # 拒绝发生在发请求之前


async def test_provider_removed_after_startup_is_a_resolve_error_not_a_crash() -> None:
    ctx = FakeAstrContext(FakeAstrEmbeddingProvider("emb-a"))
    adapter = _adapter(ctx)
    ctx.remove("emb-a")

    with pytest.raises(AstrBotEmbeddingError) as excinfo:
        await adapter.embed_query("x")

    assert excinfo.value.stage == STAGE_RESOLVE
    assert "不存在" in str(excinfo.value)
