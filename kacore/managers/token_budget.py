"""Token 预算配置与保守估算（managers 层，纯函数/轻量类，无 I/O）。

区分四种预算单位：target_chunk_tokens（切片期望大小）、embedding_input_limit（含元数据/
特殊 token 的输入上限）、rerank_pair_limit（随 query 变化的重排配对上限）、context_budget
（整次合成证据的总预算）。未知 tokenizer 时用保守估算并显式标注来源，不能声称精确保证
未知外部模型的输入上限。

依赖方向：只依赖 stdlib；不依赖任何 embedding/reranker 模型——加载完整模型才能拿到
tokenizer 正是本模块要避免的代价（见 docs/ingest-evidence-upgrade-plan.md Phase 0 与
W0 核实结论：当前依赖未安装 tiktoken/transformers/sentencepiece）。
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol


class Tokenizer(Protocol):
    """token 计数器协议：不同实现（真实模型 tokenizer / 保守估算）共用此接口。"""

    def count(self, text: str) -> int:
        """返回 text 的 token 数（真实计数或估算，由实现自行标注来源）。"""
        ...

    @property
    def measurement(self) -> str:
        """token 数的来源标注：'actual'（真实 tokenizer）或 'estimated'（保守估算）。"""
        ...

    @property
    def tokenizer_id(self) -> str:
        """稳定标识，用于 processing fingerprint 区分不同计数口径。"""
        ...


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF  # 中日韩统一表意文字扩展 A
        or 0x4E00 <= code <= 0x9FFF  # 中日韩统一表意文字
        or 0x3040 <= code <= 0x30FF  # 平假名/片假名
        or 0xAC00 <= code <= 0xD7A3  # 韩文音节
    )


@dataclass(frozen=True)
class ConservativeCharTokenizer:
    """无真实 tokenizer 时的保守估算实现。

    契约：中日韩文字按 1 字符 ≈ 1 token 估算（CJK 分词粒度接近字符），其余字符按
    chars_per_token（默认 4）估算并向上取整——设计精神与 `kacore/api.py` 现有
    `_est_context_tokens` 一致（宁可高估不可低估，故用 ceil 而非其现有的截断），
    覆盖范围更广（含假名/谚文），不复用 `llm_json.est_tokens()` 的纯 `len // 4`
    （后者对中文低估 4-6 倍，见 W0 核实结论）。measurement 恒为 'estimated'，
    调用方不得当作精确保证使用。
    """

    chars_per_token: float = 4.0
    tokenizer_id: str = "conservative-char-v1"

    @property
    def measurement(self) -> str:
        return "estimated"

    def count(self, text: str) -> int:
        if not text:
            return 0
        cjk_count = sum(1 for ch in text if _is_cjk(ch))
        other_count = len(text) - cjk_count
        return cjk_count + math.ceil(other_count / self.chars_per_token)


@dataclass(frozen=True)
class TokenBudgetConfig:
    """一次处理 fingerprint 所约束的 token 预算配置。

    契约：四个预算字段单位互相独立，不能用切片预算冒充重排/合成预算；旧版
    `chunk_size=1000` 是字符数，不是 token 数，迁移到本配置时必须显式换算，不能直接
    照搬数值。digest() 参与 ProcessingFingerprint 组装，预算变化即视为处理规则升级。
    """

    target_chunk_tokens: int = 400
    embedding_input_limit: int = 512
    rerank_pair_limit: int = 512
    context_budget: int = 8000
    tokenizer_id: str = "conservative-char-v1"

    def digest(self) -> str:
        """稳定摘要（前 16 位十六进制），供 ProcessingFingerprint 组装使用。"""
        payload = (
            f"{self.target_chunk_tokens}|{self.embedding_input_limit}|"
            f"{self.rerank_pair_limit}|{self.context_budget}|{self.tokenizer_id}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def default_tokenizer() -> Tokenizer:
    """返回当前环境下可用的 token 计数器。

    本轮未引入真实 tokenizer 依赖（tiktoken/transformers 均未安装，见 W0 核实结论），
    恒返回保守估算实现；引入真实依赖后应在此处切换，不改变调用方接口。
    """
    return ConservativeCharTokenizer()


__all__ = [
    "Tokenizer",
    "ConservativeCharTokenizer",
    "TokenBudgetConfig",
    "default_tokenizer",
]
