"""LLMAdapter 对 AstrBot 运行态 Provider 的兼容测试。"""

from __future__ import annotations

from typing import Any

from core.adapters.llm import LLMAdapter


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
