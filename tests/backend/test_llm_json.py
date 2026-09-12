"""llm_json_call 的 token 计账测试：真实用量优先、重试耗尽不丢失已消费的 calls/tokens。"""
from __future__ import annotations

from kacore.domain.llm_generation import GenerationResult
from kacore.pipelines.deep_thinking_prompts import JsonContractError
from kacore.pipelines.llm_json import llm_json_call


class _StubLLM:
    def __init__(self, results: list[GenerationResult]) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    async def generate_result(
        self, prompt: str, *, system_prompt: str = "", allow_mock: bool = True
    ) -> GenerationResult:
        self.calls.append(prompt)
        return self._results[len(self.calls) - 1]


def _parse_ok(text: str) -> str:
    return text


def _parse_always_fails(text: str) -> str:
    raise JsonContractError("always invalid")


async def test_uses_real_provider_usage_when_available() -> None:
    llm = _StubLLM([GenerationResult(text="ok", prompt_tokens=100, completion_tokens=20)])

    _, calls, tokens = await llm_json_call(llm, "prompt", "system", _parse_ok, max_retries=1)

    assert calls == 1
    assert tokens == 120  # 100 + 20，不是字符估算


async def test_falls_back_to_char_estimate_when_usage_missing() -> None:
    llm = _StubLLM([GenerationResult(text="ok", prompt_tokens=None, completion_tokens=None)])

    _, calls, tokens = await llm_json_call(llm, "prompt", "system", _parse_ok, max_retries=1)

    assert calls == 1
    assert tokens > 0  # 退化为字符估算，但仍产生非零消费


async def test_retry_exhaustion_preserves_accumulated_calls_and_tokens() -> None:
    """W0 核实到的真实 bug：重试耗尽后异常曾经把已消费的 calls/tokens 丢弃为 0。"""
    llm = _StubLLM(
        [
            GenerationResult(text="bad1", prompt_tokens=50, completion_tokens=10),
            GenerationResult(text="bad2", prompt_tokens=50, completion_tokens=10),
        ]
    )

    try:
        await llm_json_call(llm, "prompt", "system", _parse_always_fails, max_retries=1)
        raise AssertionError("expected JsonContractError")
    except JsonContractError as exc:
        assert exc.calls == 2
        assert exc.tokens == 120  # 两次调用各 60 token 的真实用量，不是 0
        assert exc.measurement == "actual"


async def test_retry_exhaustion_with_estimated_usage_marks_measurement() -> None:
    llm = _StubLLM(
        [
            GenerationResult(text="bad1", prompt_tokens=None, completion_tokens=None),
        ]
    )

    try:
        await llm_json_call(llm, "prompt", "system", _parse_always_fails, max_retries=0)
        raise AssertionError("expected JsonContractError")
    except JsonContractError as exc:
        assert exc.calls == 1
        assert exc.tokens > 0
        assert exc.measurement == "estimated"


async def test_plain_json_contract_error_defaults_are_zero() -> None:
    """未经 llm_json_call 包装、由 parse_fn 之外直接构造的异常保持默认值，向后兼容。"""
    exc = JsonContractError("standalone")
    assert exc.calls == 0
    assert exc.tokens == 0
    assert exc.measurement == "estimated"
