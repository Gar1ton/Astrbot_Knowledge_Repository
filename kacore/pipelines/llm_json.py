"""LLM JSON 调用公共 helper（pipelines 层）。

deep_thinking 与 enhanced_recall 两条管线共用的「调 LLM → 严格解析 → 不合格重试」
逻辑与 token 估算。独立成文件的目的：避免 enhanced 管线反向 import deep 编排器，
保持两条管线只在此处共享调用纪律。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from kacore.domain.llm_generation import STATUS_LENGTH
from kacore.pipelines.deep_thinking_prompts import JsonContractError

if TYPE_CHECKING:
    from kacore.adapters.llm import LLMAdapter

logger = logging.getLogger("LLMJsonCall")

T = TypeVar("T")

# 默认重试后缀：针对纯 JSON 步骤（PLAN/SEA/VERIFY 等）。
_DEFAULT_RETRY_SUFFIX = "\n\n只输出合法 JSON，不要任何额外文字。"


def est_tokens(*texts: str) -> int:
    """字符近似的 token 估算（≈ len/4）。非精确，仅用于成本可观测与安全阀。"""
    return sum(len(t) for t in texts) // 4


async def llm_json_call(
    llm: LLMAdapter,
    prompt: str,
    system: str,
    parse_fn: Callable[[str], T],
    max_retries: int,
    *,
    retry_suffix: str = _DEFAULT_RETRY_SUFFIX,
) -> tuple[T, int, int]:
    """调 LLM 并解析：解析不合格重试 max_retries 次后抛最后一次 JsonContractError；
    LLM 调用异常向上抛（由调用方决定回退策略）。返回 (parsed, calls, est_tokens)。

    用 `generate_result()` 而非 `generate()`——空响应/reasoning-only 时
    `allow_mock=False` 已在 LLMAdapter 层抛异常（向上传播，行为不变）；这里额外要的是
    成功拿到文本、但 JSON 解析仍失败时的 status，用来区分「模型输出被长度截断导致
    JSON 不完整」与普通的格式错误，日志更好定位。

    retry_suffix 允许非纯 JSON 契约（如「markdown 正文 + 尾部 verdict 标记」）自定义
    重试提示，避免默认后缀扭曲输出格式要求。
    """
    calls = 0
    tokens = 0
    last_err: JsonContractError | None = None
    for attempt in range(max_retries + 1):
        text = prompt if attempt == 0 else prompt + retry_suffix
        result = await llm.generate_result(text, system_prompt=system, allow_mock=False)
        calls += 1
        tokens += est_tokens(system, text, result.text)
        try:
            return parse_fn(result.text), calls, tokens
        except JsonContractError as exc:
            if result.status == STATUS_LENGTH:
                logger.warning(
                    "LLM JSON 调用输出疑似被长度截断（finish_reason=length）导致解析失败：%s",
                    exc,
                )
            last_err = exc
    raise last_err or JsonContractError("unparseable")


__all__ = ["est_tokens", "llm_json_call"]
