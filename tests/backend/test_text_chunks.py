"""core/utils/text_chunks 纯函数契约测试。

重点覆盖 v0.30.0 治本修复：中文句读（无尾随空格）不再触发字符硬切；
超长句先按子句边界切；字符硬切仅作无标点长 token 的最后兜底。
"""
from __future__ import annotations

from kacore.utils.text_chunks import (
    clip_at_sentence,
    paragraphize,
    split_by_sentences,
    split_message_text,
)


def test_chinese_sentences_split_at_full_stops_not_mid_sentence():
    # 旧正则要求「。」后跟空白 → 本段整体不可切 → 字符硬切；新实现按句读切。
    text = "第一句讲方法论。第二句讲实验设置。第三句讲结论与展望。"
    chunks = split_by_sentences(text, max_chars=12)
    assert chunks == ["第一句讲方法论。", "第二句讲实验设置。", "第三句讲结论与展望。"]


def test_chinese_closing_quote_stays_with_sentence():
    text = "他说：「结果显著。」后续分析证实了这一点。"
    chunks = split_by_sentences(text, max_chars=15)
    assert chunks[0].endswith("」")


def test_ascii_period_still_requires_whitespace():
    # 小数点/版本号不拆句：3.5 不能被当成句界。
    text = "Model v3.5 performs well. It beats the baseline."
    chunks = split_by_sentences(text, max_chars=30)
    assert chunks[0] == "Model v3.5 performs well."


def test_oversized_sentence_splits_at_clause_boundaries():
    # 单句超长但含逗号 → 按子句切，不在字中间截断。
    text = "这项研究提出了一个新框架，覆盖了数据构建，模型训练，以及评测协议的全部环节"
    chunks = split_by_sentences(text, max_chars=16)
    assert all(len(c) <= 16 for c in chunks)
    # 每个片段都以子句边界或文本末尾收尾，无句中截断。
    assert all(c.endswith("，") or c == chunks[-1] for c in chunks)


def test_hard_cut_only_for_unpunctuated_token():
    text = "A" * 50  # 无任何标点的长 token → 只能字符硬切兜底。
    chunks = split_by_sentences(text, max_chars=20)
    assert chunks == ["A" * 20, "A" * 20, "A" * 10]


def test_paragraphize_keeps_structured_blocks_and_splits_long_runs():
    structured = "已有段落一。\n\n- 列表项"
    assert paragraphize(structured, max_chars=10) == structured
    long_run = "第一句完整表述观点。第二句继续展开论证。"
    out = paragraphize(long_run, max_chars=12)
    assert out == "第一句完整表述观点。\n\n第二句继续展开论证。"


def test_split_message_text_paginates_with_prefix():
    text = "段落甲。" * 40 + "\n\n" + "段落乙。" * 40
    parts = split_message_text(text, limit=100)
    assert len(parts) > 1
    assert parts[0].startswith("（1/")
    assert all(len(p) <= 100 for p in parts)


def test_split_message_text_short_passthrough():
    assert split_message_text("短消息", limit=100) == ["短消息"]
    assert split_message_text("   ", limit=100) == []


def test_clip_at_sentence_prefers_sentence_boundary():
    text = "第一句到此结束。第二句会被截掉的部分很长很长很长很长很长很长"
    clipped = clip_at_sentence(text, 20)
    assert clipped == "第一句到此结束。…"


def test_clip_at_sentence_falls_back_to_clause_then_hard():
    clause_text = "前半句内容颇多，后半句还要更长更长更长更长更长更长"
    clipped = clip_at_sentence(clause_text, 20)
    assert clipped.endswith("，…")
    hard_text = "B" * 40
    assert clip_at_sentence(hard_text, 10) == "B" * 10 + "…"
    assert clip_at_sentence("短文本。", 100) == "短文本。"
