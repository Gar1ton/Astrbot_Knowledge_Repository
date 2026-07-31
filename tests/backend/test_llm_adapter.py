"""LLMAdapter 对 AstrBot 运行态 Provider 的兼容测试。"""

from __future__ import annotations

from typing import Any

from kacore.adapters.llm import LLMAdapter


class _ProviderMeta:
    id = "default-chat"


class _Provider:
    def meta(self) -> _ProviderMeta:
        return _ProviderMeta()


class _ProviderManager:
    curr_provider_inst = _Provider()


class _LLMResponse:
    def __init__(self, completion_text: str = "") -> None:
        self.completion_text = completion_text


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
