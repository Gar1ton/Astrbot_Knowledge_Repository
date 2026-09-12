"""LLMAdapter 对 AstrBot 运行态 Provider 的兼容测试。"""

from __future__ import annotations

from typing import Any

from kacore.adapters.llm import LLMAdapter
from kacore.domain.llm_generation import (
    STATUS_CONTENT_FILTER,
    STATUS_EMPTY,
    STATUS_LENGTH,
    STATUS_OK,
    STATUS_REASONING_ONLY,
    STATUS_TIMEOUT,
)


async def test_independent_endpoint_supports_json_contract_and_counts_http_retries():
    import json

    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from kacore.adapters.llm import LMStudioLLMAdapter
    from kacore.pipelines.llm_json import llm_json_call
    from kacore.utils.usage_ledger import current_usage, usage_request

    attempts = 0

    async def respond(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.json_response({"error": "busy"}, status=503)
        return web.json_response({
            "model": "test-model",
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 2},
        })

    app = web.Application()
    app.router.add_post("/v1/chat/completions", respond)
    server = TestServer(app)
    await server.start_server()

    @usage_request
    async def run():
        adapter = LMStudioLLMAdapter(str(server.make_url("/v1")), "test-model",
                                     retry_backoff_seconds=0, max_retries=1)
        parsed, calls, tokens = await llm_json_call(adapter, "q", "sys", json.loads, 0)
        return parsed, calls, tokens, current_usage.get().summary()

    try:
        parsed, calls, tokens, usage = await run()
        assert parsed == {"ok": True} and calls == 1 and tokens == 42
        assert usage["call_count"] == 2 and usage["unknown_calls"] == 1
        assert usage["calls"][1]["model"] == "test-model"
        assert usage["calls"][1]["measurement"] == "actual"
    finally:
        await server.close()


class _ProviderMeta:
    id = "default-chat"


class _Provider:
    def meta(self) -> _ProviderMeta:
        return _ProviderMeta()


class _ProviderManager:
    curr_provider_inst = _Provider()


class _LLMResponse:
    def __init__(
        self,
        completion_text: str = "",
        reasoning_content: str = "",
        finish_reason: str = "",
    ) -> None:
        self.completion_text = completion_text
        self.reasoning_content = reasoning_content
        self.finish_reason = finish_reason


class _ResultChain:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_plain_text(self) -> str:
        return self._text


class _LLMResponseWithChain:
    def __init__(self, text: str) -> None:
        self.completion_text = ""
        self.result_chain = _ResultChain(text)


class _AstrBotContext:
    provider_manager = _ProviderManager()

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def llm_generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class _ProviderWithTextChat(_Provider):
    def __init__(self, text_chat_response: Any = None) -> None:
        self.text_chat_response = text_chat_response
        self.text_chat_calls: list[dict[str, Any]] = []

    async def text_chat(self, **kwargs: Any) -> Any:
        self.text_chat_calls.append(kwargs)
        return self.text_chat_response


class _ProviderManagerWith:
    def __init__(self, provider: Any) -> None:
        self.curr_provider_inst = provider


class _QueuedAstrBotContext:
    """llm_generate() 按调用顺序依次返回 responses 中的项，供「首次 reasoning-only、
    重试后拿到真答案」这类多次调用场景使用。provider_manager 携带的 provider 可选配
    text_chat，用于验证 reasoning-only 重试后仍失败时才会落到 text_chat 兜底。"""

    def __init__(self, responses: list[Any], provider: Any | None = None) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.provider_manager = _ProviderManagerWith(provider or _Provider())

    async def llm_generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


async def test_generate_uses_astrbot_llm_generate_completion_text() -> None:
    context = _AstrBotContext(_LLMResponse("real answer"))
    adapter = LLMAdapter(context)

    answer = await adapter.generate("question", system_prompt="system", allow_mock=False)

    assert answer == "real answer"
    assert context.calls == [
        {
            "chat_provider_id": "default-chat",
            "prompt": "question",
            "system_prompt": "system",
        }
    ]


async def test_generate_reads_astrbot_result_chain_text() -> None:
    adapter = LLMAdapter(_AstrBotContext(_LLMResponseWithChain("chain answer")))

    assert await adapter.generate("question", allow_mock=False) == "chain answer"


async def test_extract_graph_uses_astrbot_llm_generate() -> None:
    payload = (
        '{"entities":[{"name":"Transformer","type":"Method",'
        '"description":"model"}],"relations":[]}'
    )
    context = _AstrBotContext(_LLMResponse(payload))
    adapter = LLMAdapter(context)

    graph = await adapter.extract_graph("Transformer model", ["Method"])

    assert graph["entities"][0]["name"] == "Transformer"
    assert context.calls
    assert context.calls[0]["chat_provider_id"] == "default-chat"


# ── 失败可见性（v1.0.9）──────────────────────────────────────────


async def test_offline_stub_fallback_is_logged_as_warning(caplog: Any) -> None:
    """回归：主 LLM 不通时会返回离线占位答案——这必须是显眼的 WARNING。

    此前记 INFO，用户看到的是一段「像模像样但完全是假的」回答，终端页却几乎无痕迹。
    """
    import logging

    caplog.set_level(logging.INFO, logger="LLMAdapter")
    adapter = LLMAdapter(context=None)

    answer = await adapter.generate("问题：知识库里有什么？")

    assert "离线测试占位答案" in answer
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("离线占位" in r.getMessage() for r in warnings)


async def test_provider_exception_is_logged_with_traceback(caplog: Any) -> None:
    """provider 抛异常时必须留 traceback；调用方只会拿到空串，日志是唯一线索。"""
    import logging

    class _ExplodingContext:
        async def llm_generate(self, **_kwargs: Any) -> Any:
            raise RuntimeError("provider exploded")

        provider_manager = _ProviderManager()

    caplog.set_level(logging.INFO, logger="LLMAdapter")
    adapter = LLMAdapter(context=_ExplodingContext())

    assert await adapter._call_context_llm("hi") == ""
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("provider exploded" in r.getMessage() for r in errors)
    assert any(r.exc_info for r in errors)


async def test_main_llm_call_is_time_boxed(caplog: Any) -> None:
    """回归：AstrBot provider 挂死时，ask 必须放弃等待而不是永远不返回。

    没有这道闸，整条问答链路会一直挂着——前端只看到「请求超时」，服务端却还在等，
    重试再叠一份负载。
    """
    import asyncio
    import logging

    class _HangingContext:
        async def llm_generate(self, **_kwargs: Any) -> Any:
            await asyncio.sleep(30)
            return _LLMResponse("never")

        provider_manager = _ProviderManager()

    caplog.set_level(logging.INFO, logger="LLMAdapter")
    adapter = LLMAdapter(context=_HangingContext(), timeout_seconds=1)

    assert await adapter._call_context_llm("hi") == ""
    assert any("超时" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)


async def test_llm_timeout_zero_keeps_unbounded_wait() -> None:
    """timeout_seconds<=0 保留旧的不设限行为（给自建慢模型的用户）。"""

    class _SlowContext:
        async def llm_generate(self, **_kwargs: Any) -> Any:
            import asyncio

            await asyncio.sleep(0.05)
            return _LLMResponse("slow but fine")

        provider_manager = _ProviderManager()

    adapter = LLMAdapter(context=_SlowContext(), timeout_seconds=0)
    assert await adapter._call_context_llm("hi") == "slow but fine"


# ── reasoning-only 识别与重复调用治理（v1.0.12）──────────────────────


async def test_reasoning_only_retries_once_before_falling_back() -> None:
    """首次 reasoning-only 时对同一 llm_generate 路径重试一次（带强制指令），

    重试拿到真答案就直接返回，不落到 text_chat/legacy 兜底链——杜绝对 reasoning
    模型无意义地重复调用整条 provider 兜底链。
    """
    reasoning_only = _LLMResponse(reasoning_content="……推理过程……")
    real_answer = _LLMResponse("real answer")
    provider = _ProviderWithTextChat()
    context = _QueuedAstrBotContext([reasoning_only, real_answer], provider=provider)
    adapter = LLMAdapter(context)

    answer = await adapter.generate("question", system_prompt="system", allow_mock=False)

    assert answer == "real answer"
    assert len(context.calls) == 2
    assert context.calls[0]["system_prompt"] == "system"
    assert "请直接输出最终结论" in context.calls[1]["system_prompt"]
    assert not provider.text_chat_calls  # 未滚到 text_chat 兜底


async def test_reasoning_only_persists_falls_back_to_text_chat_and_logs_distinctly(
    caplog: Any,
) -> None:
    """重试后仍 reasoning-only 才落到 text_chat 兜底；日志需明确写「reasoning_content」

    而不是笼统的空响应，方便和真正的空响应区分排查。
    """
    import logging

    reasoning_only_1 = _LLMResponse(reasoning_content="……", finish_reason="stop")
    reasoning_only_2 = _LLMResponse(reasoning_content="……仍是推理……", finish_reason="stop")
    provider = _ProviderWithTextChat(text_chat_response=_LLMResponse("from text_chat"))
    context = _QueuedAstrBotContext(
        [reasoning_only_1, reasoning_only_2], provider=provider
    )
    caplog.set_level(logging.INFO, logger="LLMAdapter")
    adapter = LLMAdapter(context)

    answer = await adapter.generate("question", allow_mock=False)

    assert answer == "from text_chat"
    assert len(context.calls) == 2  # 只重试一次，不无限重试
    assert len(provider.text_chat_calls) == 1
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("reasoning_content" in r.getMessage() for r in warnings)


async def test_true_empty_response_still_falls_back_to_text_chat() -> None:
    """两个字段都空的真空响应：行为不变，直接落到 text_chat 兜底（不做多余重试）。"""
    empty = _LLMResponse()
    provider = _ProviderWithTextChat(text_chat_response=_LLMResponse("from text_chat"))
    context = _QueuedAstrBotContext([empty], provider=provider)
    adapter = LLMAdapter(context)

    answer = await adapter.generate("question", allow_mock=False)

    assert answer == "from text_chat"
    assert len(context.calls) == 1  # 真空响应不重试 llm_generate
    assert len(provider.text_chat_calls) == 1


# ── GenerationResult 状态分流（v1.0.12）──────────────────────────────


async def test_generate_result_ok_carries_finish_reason_and_tokens() -> None:
    """正常完成：status=ok，finish_reason/tokens/provider_id 尽量透出。"""

    class _Usage:
        prompt_tokens = 120
        completion_tokens = 40

    class _RawCompletion:
        usage = _Usage()

    response = _LLMResponse("real answer", finish_reason="stop")
    response.raw_completion = _RawCompletion()
    response.model = "deepseek-v4-flash"
    adapter = LLMAdapter(_AstrBotContext(response))

    result = await adapter.generate_result("question", allow_mock=False)

    assert result.status == STATUS_OK
    assert result.text == "real answer"
    assert result.finish_reason == "stop"
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40
    assert result.provider_id == "default-chat"
    assert result.model == "deepseek-v4-flash"
    assert result.reasoning_present is False


async def test_generate_result_missing_usage_is_none_not_zero() -> None:
    """provider 完全没报用量时，prompt_tokens/completion_tokens 必须是 None（未知）
    而不是 0（已知为零）——二者语义不同，见 GenerationResult 契约。"""
    response = _LLMResponse("real answer", finish_reason="stop")
    adapter = LLMAdapter(_AstrBotContext(response))

    result = await adapter.generate_result("question", allow_mock=False)

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


async def test_generate_result_reported_zero_usage_is_preserved() -> None:
    """provider 明确报告 0 token（如极短 prompt）时应如实保留为 0，不视为「未知」。"""

    class _Usage:
        prompt_tokens = 0
        completion_tokens = 0

    class _RawCompletion:
        usage = _Usage()

    response = _LLMResponse("ok", finish_reason="stop")
    response.raw_completion = _RawCompletion()
    adapter = LLMAdapter(_AstrBotContext(response))

    result = await adapter.generate_result("question", allow_mock=False)

    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


async def test_generate_result_true_empty_status() -> None:
    """真空响应（无文本也无 reasoning）：status=empty。

    generate_result(allow_mock=False) 在文本为空时会抛异常（与 generate() 契约一致），
    所以按状态断言时改用不抛异常的内部结构化方法 `_call_context_llm_result`。
    """
    provider = _ProviderWithTextChat()  # 无 text_chat 兜底可用响应
    context = _QueuedAstrBotContext([_LLMResponse()], provider=provider)
    adapter = LLMAdapter(context)

    result = await adapter._call_context_llm_result("question")

    assert result.status == STATUS_EMPTY
    assert result.text == ""


async def test_generate_result_reasoning_only_after_retry_status() -> None:
    """重试后仍 reasoning-only：status=reasoning_only（而不是笼统的 empty）。"""
    reasoning_only = _LLMResponse(reasoning_content="……", finish_reason="stop")
    provider = _ProviderWithTextChat()  # text_chat 也拿不到东西
    context = _QueuedAstrBotContext([reasoning_only, reasoning_only], provider=provider)
    adapter = LLMAdapter(context)

    result = await adapter._call_context_llm_result("question")

    assert result.status == STATUS_REASONING_ONLY
    assert result.reasoning_present is True
    assert result.text == ""


async def test_generate_result_reasoning_only_mock_fallback_keeps_status() -> None:
    """allow_mock=True 时用离线占位文本兜底，但 status 仍如实反映真实调用的诊断结果

    （不能因为塞了假文本就让调用方误以为是 status=ok 的真实回答）。
    """
    reasoning_only = _LLMResponse(reasoning_content="……", finish_reason="stop")
    provider = _ProviderWithTextChat()
    context = _QueuedAstrBotContext([reasoning_only, reasoning_only], provider=provider)
    adapter = LLMAdapter(context)

    result = await adapter.generate_result("question")  # allow_mock=True（默认）

    assert result.status == STATUS_REASONING_ONLY
    assert result.text  # 已被离线占位文本填充，非空
    assert "占位" in result.text


async def test_generate_result_timeout_status() -> None:
    """provider 挂死超时：status=timeout。"""
    import asyncio

    class _HangingContext:
        async def llm_generate(self, **_kwargs: Any) -> Any:
            await asyncio.sleep(30)
            return _LLMResponse("never")

        provider_manager = _ProviderManager()

    adapter = LLMAdapter(context=_HangingContext(), timeout_seconds=1)

    result = await adapter._call_context_llm_result("question")

    assert result.status == STATUS_TIMEOUT
    assert result.text == ""


async def test_generate_result_length_and_content_filter_status() -> None:
    """finish_reason 指示截断/内容过滤时，即便有部分文本也要能识别出来。"""
    length_response = _LLMResponse("partial answer...", finish_reason="length")
    adapter = LLMAdapter(_AstrBotContext(length_response))
    result = await adapter.generate_result("question", allow_mock=False)
    assert result.status == STATUS_LENGTH
    assert result.text == "partial answer..."

    filtered_response = _LLMResponse("", finish_reason="content_filter")
    adapter2 = LLMAdapter(_AstrBotContext(filtered_response))
    result2 = await adapter2._call_context_llm_result("question")
    assert result2.status == STATUS_CONTENT_FILTER
