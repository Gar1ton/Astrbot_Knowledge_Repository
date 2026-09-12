"""Token 预算配置与保守估算的纯函数测试（无 I/O）。

覆盖验收矩阵 C04 相关场景：中英文混排的 token 估算不低估，配置 digest 稳定且随预算变化。
"""
from __future__ import annotations

from kacore.managers.token_budget import (
    ConservativeCharTokenizer,
    TokenBudgetConfig,
    default_tokenizer,
)


def test_ascii_text_counts_roughly_chars_over_four() -> None:
    tokenizer = ConservativeCharTokenizer()
    # 16 ASCII chars / 4 = 4，无余数。
    assert tokenizer.count("a" * 16) == 4


def test_ascii_text_rounds_up_not_down() -> None:
    tokenizer = ConservativeCharTokenizer()
    # 17 chars / 4 = 4.25 → 必须向上取整为 5，绝不能低估。
    assert tokenizer.count("a" * 17) == 5


def test_cjk_text_counts_one_token_per_character() -> None:
    tokenizer = ConservativeCharTokenizer()
    assert tokenizer.count("你好世界") == 4


def test_mixed_cjk_and_ascii_text_counts_separately() -> None:
    tokenizer = ConservativeCharTokenizer()
    # 2 个中文字符（=2 token）+ 8 个 ASCII 字符（=2 token）。
    assert tokenizer.count("你好abcdefgh") == 4


def test_empty_text_counts_zero() -> None:
    tokenizer = ConservativeCharTokenizer()
    assert tokenizer.count("") == 0


def test_measurement_is_always_estimated() -> None:
    tokenizer = ConservativeCharTokenizer()
    assert tokenizer.measurement == "estimated"


def test_default_tokenizer_is_conservative_char_based() -> None:
    tokenizer = default_tokenizer()
    assert tokenizer.measurement == "estimated"
    assert tokenizer.tokenizer_id == "conservative-char-v1"


def test_config_digest_is_stable_for_same_values() -> None:
    a = TokenBudgetConfig(target_chunk_tokens=400)
    b = TokenBudgetConfig(target_chunk_tokens=400)
    assert a.digest() == b.digest()


def test_config_digest_changes_with_budget_value() -> None:
    a = TokenBudgetConfig(target_chunk_tokens=400)
    b = TokenBudgetConfig(target_chunk_tokens=500)
    assert a.digest() != b.digest()


def test_config_digest_changes_with_tokenizer_id() -> None:
    a = TokenBudgetConfig(tokenizer_id="conservative-char-v1")
    b = TokenBudgetConfig(tokenizer_id="tiktoken-cl100k")
    assert a.digest() != b.digest()
