"""切片质量回归：保守去噪、结构恢复、预算与偏移不变量。"""
from __future__ import annotations

import pytest

from kacore.managers.chunk_boundaries import sentence_boundaries
from kacore.managers.chunk_token_limits import limit_chunk_spans
from kacore.managers.chunking import ChunkSpan, build_structural_chunk_spans, parse_markdown_blocks
from kacore.managers.markdown_extractor import (
    _detect_repeated_marginal_headers,
    _remove_marginal_noise,
    join_cleaned_markdown_pages,
)
from kacore.managers.structural_protection import repair_wrapped_text_preserving_blocks
from kacore.managers.token_budget import ConservativeCharTokenizer, TokenBudgetConfig


def test_single_publication_footer_removed_without_deleting_citations():
    footer = (
        'ISSN 0969-725X print/ISSN 1469-2899 online/20/040054-13 '
        '© 2020 Informa UK Limited, trading as Taylor & Francis Group '
        'https://doi.org/10.1080/0969725X.2020.1790835'
    )
    prose = 'We discuss copyright and ISSN 0969-725X with https://doi.org/example.'
    raw = f'{prose}\n\n{footer}'
    assert _remove_marginal_noise(raw, set()).strip() == prose
    masked = _remove_marginal_noise(raw, set(), preserve_offsets=True)
    assert len(masked) == len(raw)
    assert masked.index(prose) == raw.index(prose)
    assert _remove_marginal_noise(f'```\n{footer}\n```', set()).count(footer) == 1
    wrapped = footer.rsplit(' https://', 1)[0] + '\n\nhttps://' + footer.rsplit(' https://', 1)[1]
    assert _remove_marginal_noise(f'{prose}\n\n{wrapped}', set()).strip() == prose
    standalone = 'https://doi.org/example'
    assert _remove_marginal_noise(standalone, set()) == standalone


def test_database_access_stamp_removed_anywhere_but_literal_examples_are_protected():
    stamp = "This content downloaded from 131.111.98.148 on Fri, 11 Sep 2026 03:07:28 UTC"
    prose = "The argument continues across the page."
    raw = f"Opening paragraph.\n\n{stamp}\n\n{prose}"
    cleaned_raw = _remove_marginal_noise(raw, set())
    assert stamp not in cleaned_raw
    assert cleaned_raw.startswith("Opening paragraph.")
    assert cleaned_raw.endswith(prose)

    wrapped = (
        "Opening paragraph.\n\nThis content downloaded from 131.111.98.148 on Fri,\n"
        f"11 Sep 2026 03:07:28 UTC\n\n{prose}"
    )
    cleaned_wrapped = _remove_marginal_noise(wrapped, set())
    assert "This content downloaded" not in cleaned_wrapped
    assert "All use subject" not in _remove_marginal_noise(
        f"{prose}\nAll use subject to https://about.jstor.org/terms", set()
    )

    code = f"```text\n{stamp}\n```"
    assert _remove_marginal_noise(code, set()) == code
    discussion = "The phrase ‘This content downloaded from’ is discussed as a watermark."
    assert _remove_marginal_noise(discussion, set()) == discussion

    flattened = f"The planetary argument is {stamp} continued by this clause."
    assert _remove_marginal_noise(flattened, set()) == (
        "The planetary argument is   continued by this clause."
    )

    interrupted = f"The planetary argument is\n\n{stamp}\n\ncontinued by this clause."
    cleaned_interrupted = _remove_marginal_noise(interrupted, set())
    assert "\n" not in cleaned_interrupted
    assert cleaned_interrupted.startswith("The planetary argument is ")
    assert cleaned_interrupted.endswith(" continued by this clause.")


def test_database_access_stamp_offset_mask_is_length_preserving():
    stamp = "This content downloaded from 131.111.98.148 on Fri, 11 Sep 2026 03:07:28 UTC"
    raw = f"Before.\n{stamp}\nAfter."
    masked = _remove_marginal_noise(raw, set(), preserve_offsets=True)
    assert len(masked) == len(raw)
    assert masked.index("After.") == raw.index("After.")
    assert stamp not in masked


def test_alternating_short_running_headings_removed_but_real_headings_kept():
    pages = [f'#### {"hui" if i % 2 else "machine and ecology"}\nBody {i}.' for i in range(8)]
    repeated = _detect_repeated_marginal_headers(pages)
    assert all('####' not in _remove_marginal_noise(p, repeated) for p in pages)
    body = 'Body.\n\n#### machine and ecology\n\nActual section.'
    assert _remove_marginal_noise(body, repeated) == body
    numbered = '#### 2 Methods\nBody.'
    assert _remove_marginal_noise(numbered, {'2 METHODS'}) == numbered


@pytest.mark.parametrize('left,right', [
    ('like what Hans', 'Jonas says in his book.'),
    ('also describes the', '1957 launch of Sputnik.'),
    ('This opposition has', 'resulted from some stereotypes.'),
])
def test_cross_page_continuation_keeps_offsets(left, right):
    text, pages = join_cleaned_markdown_pages([left, right])
    assert text == left + ' ' + right
    assert pages[0].end == pages[1].start
    assert pages[-1].end == len(text)
    assert text[pages[1].start:pages[1].end] == right


def test_page_join_does_not_cross_real_structure():
    for right in ('#### Methods', '- item', '1. Item', '$$\nx=1\n$$', '```\nx\n```'):
        text, _ = join_cleaned_markdown_pages(['incomplete text', right])
        assert text == 'incomplete text\n\n' + right


def test_numeric_false_paragraph_break_repaired_but_new_paragraph_kept():
    text = 'Arendt describes the\n\n1957 launch.\n\nAnother paragraph.'
    assert repair_wrapped_text_preserving_blocks(text) == (
        'Arendt describes the 1957 launch.\n\nAnother paragraph.'
    )


def test_headings_need_no_blank_lines_and_fences_keep_internal_blank_lines():
    text = '#### 1 introduction\nFirst paragraph.\n#### 2 methods\nSecond paragraph.'
    _, sections, _ = build_structural_chunk_spans(text)
    assert [s.label for s in sections] == ['1', '2']
    code = '```python\n# Not a heading\n\nprint(1)\n```'
    blocks = parse_markdown_blocks(code + '\n\nActual paragraph.')
    assert blocks[0].text == code
    assert len(blocks) == 2
    assert len(parse_markdown_blocks('A line\nwrapped onto another line.')) == 1


def test_heading_marker_stays_attached_to_inline_bold_anchor_on_same_line():
    text = (
        'A life- value is a surplus- value of life.\n'
        '### **T30** \nCapitalist surplus- value, like all surplus- value.'
    )
    blocks = parse_markdown_blocks(text)
    assert not any(b.text.strip() == '###' for b in blocks)
    heading = next(b for b in blocks if b.kind == 'section_heading')
    assert heading.label == 'T30'
    assert heading.text.startswith('### **T30**')
    _, sections, _ = build_structural_chunk_spans(text)
    assert [s.label for s in sections] == ['front_matter', 'T30']

    inline_reference = 'As discussed in **T30**, capitalism recurs.'
    assert parse_markdown_blocks(inline_reference)[0].kind == 'paragraph'


def test_soft_token_target_does_not_split_fitting_paragraph():
    text = ('A detailed sentence about an argument. ' * 48).strip()
    assert 400 < ConservativeCharTokenizer().count(text) <= 480
    result = limit_chunk_spans(text, [ChunkSpan(0, len(text), {})])
    assert len(result) == 1
    assert not result[0].metadata['budget_split']
    assert result[0].metadata['ends_at_paragraph']


def test_oversized_paragraph_is_balanced_and_source_ranges_are_exact():
    text = ('This sentence explains the philosophical argument in detail. ' * 38).strip()
    result = limit_chunk_spans(text, [ChunkSpan(0, len(text), {})])
    assert len(result) == 2
    assert ''.join(text[s.start:s.end] for s in result) == text
    assert min(s.metadata['token_count'] for s in result) > 200
    assert all(s.metadata['token_count'] <= 480 for s in result)
    assert not result[0].metadata['ends_at_paragraph']
    assert result[-1].metadata['ends_at_paragraph']
    assert all(s.metadata['paragraph_ranges'] == [{'start_char': 0, 'end_char': len(text)}]
               for s in result)
    assert all(text[s.start:s.end].rstrip().endswith('.') for s in result)


def test_short_whole_paragraph_not_split_to_fill_budget():
    one = 'Opening paragraph. ' * 12
    two = 'Following paragraph. ' * 86
    text = one.strip() + '\n\n' + two.strip()
    result = limit_chunk_spans(text, [ChunkSpan(0, len(text), {})])
    assert result[0].end == len(one.strip())
    assert result[0].metadata['ends_at_paragraph']


def test_sentence_boundary_keeps_closing_quote_and_citation():
    text = 'Dr. Smith says “A result.”[12] A second result (Smith et al., 2020). Next.'
    boundaries = sentence_boundaries(text, 0, len(text))
    assert text[:boundaries[0]] == 'Dr. Smith says “A result.”[12]'
    assert all(text[:p].endswith(('[12]', '.', ')')) for p in boundaries)
    linked = 'Value 3.14 and https://example.org/path. Next.'
    ends = sentence_boundaries(linked, 0, len(linked))
    assert [linked[:p] for p in ends] == [linked[:-6], linked]


def test_unpunctuated_cjk_fallback_is_bounded_and_lossless():
    text = '汉' * 1050
    result = limit_chunk_spans(text, [ChunkSpan(0, len(text), {})])
    assert ''.join(text[s.start:s.end] for s in result) == text
    assert all(s.metadata['token_count'] <= 480 for s in result)
    assert result[0].metadata['split_reason'] == 'character_fallback'


def test_invalid_budget_fails_clearly():
    with pytest.raises(ValueError):
        limit_chunk_spans(
            'x', [ChunkSpan(0, 1, {})], budget=TokenBudgetConfig(embedding_input_limit=32),
        )
