"""请求级 LLM 用量记录；只在真实 provider 尝试边界累计，不保存 prompt 或密钥。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any
from uuid import uuid4


@dataclass
class UsageLedger:
    """每个请求独立；unknown 不转换成零消费，已知值仅报告为已知部分总量。"""

    request_id: str = field(default_factory=lambda: uuid4().hex)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "calls": list(self.calls),
            "call_count": len(self.calls),
            "known_tokens": sum(
                (c["input_tokens"] or 0) + (c["output_tokens"] or 0) for c in self.calls
            ),
            "unknown_calls": sum(c["measurement"] == "unknown" for c in self.calls),
            "estimated_calls": sum(c["measurement"] == "estimated" for c in self.calls),
        }


current_usage: ContextVar[UsageLedger | None] = ContextVar("usage_ledger", default=None)
usage_stage: ContextVar[str] = ContextVar("usage_stage", default="generation")


def usage_request(fn: Any) -> Any:
    """嵌套编排共用账本；后台子任务继承自己的容器，不污染后续请求。"""

    @wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        if current_usage.get() is not None:
            return await fn(*args, **kwargs)
        token = current_usage.set(UsageLedger())
        try:
            return await fn(*args, **kwargs)
        finally:
            current_usage.reset(token)

    return wrapped
