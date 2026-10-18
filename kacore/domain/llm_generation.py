"""LLM 单次生成结果的领域模型（依赖图圆心，零依赖）。

AstrBot 的 LLMResponse 到达适配器后若立即压成裸字符串，finish_reason / token 用量 /
是否只有 reasoning_content / provider·model 信息会全部丢失，下游只能靠「字符串是否为
空」判断成败——无法区分正常完成、reasoning-only、长度截断、内容过滤、超时。
GenerationResult 把这些信息保留下来，供需要按状态分流决策的调用方使用。
"""
from __future__ import annotations

from dataclasses import dataclass

# 生成状态三态之外的完整枚举（裸字符串多处比较，提为模块常量）。
STATUS_OK = "ok"  # 正常拿到最终答案文本
STATUS_EMPTY = "empty"  # 真空响应：无文本、无 reasoning_content
STATUS_REASONING_ONLY = "reasoning_only"  # 只有 reasoning_content，重试后仍未给出最终答案
STATUS_TIMEOUT = "timeout"  # 单次调用超过 LLMAdapter 的 timeout_seconds 闸门
STATUS_ERROR = "error"  # provider 调用抛异常
STATUS_LENGTH = "length"  # finish_reason 指示因长度截断
STATUS_CONTENT_FILTER = "content_filter"  # finish_reason 指示被内容策略过滤


@dataclass
class GenerationResult:
    """一次 LLM 生成调用的结构化结果。

    text 为空时不代表调用失败——status 才是判断依据（如 reasoning_only 时 text 也是
    空串，但语义与 empty/error 不同）。finish_reason/provider_id/model 均为 best-effort
    （AstrBot LLMResponse 演进/不同 provider 实现下可能取不到）。

    prompt_tokens/completion_tokens 为 None 表示 provider 未报告用量（真正未知，不能
    当作 0 计入台账）；为 int 表示 provider 确有报告，即便报告值恰好是 0 也如实保留——
    调用方靠 is None 区分「未知」与「已知为零」，不得混用。
    """

    text: str
    status: str = STATUS_OK
    finish_reason: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_present: bool = False
    provider_id: str = ""
    model: str = ""


__all__ = [
    "GenerationResult",
    "STATUS_OK",
    "STATUS_EMPTY",
    "STATUS_REASONING_ONLY",
    "STATUS_TIMEOUT",
    "STATUS_ERROR",
    "STATUS_LENGTH",
    "STATUS_CONTENT_FILTER",
]
