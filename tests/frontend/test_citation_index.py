"""前端 citationIndex.ts 的契约测试（node 转译后直接调用，无 node 则跳过）。"""
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def split_samples(
    sources: list[dict], samples: list[str]
) -> list[list[dict]]:
    """用给定 sources 建索引，再对每段文本切分，返回 `[{text, n}]` 列表。"""
    if shutil.which("node") is None:
        pytest.skip("node is not available")
    if not (ROOT / "web/frontend/node_modules/typescript").exists():
        pytest.skip("frontend TypeScript dependency is not installed")

    script = textwrap.dedent(
        r"""
        const fs = require("node:fs");
        const path = require("node:path");
        const ts = require(path.join(process.cwd(), "web/frontend/node_modules/typescript"));
        const sourcePath = path.join(process.cwd(), "web/frontend/lib/citationIndex.ts");
        const source = fs.readFileSync(sourcePath, "utf8");
        const output = ts.transpileModule(source, {
          compilerOptions: {
            module: ts.ModuleKind.CommonJS,
            target: ts.ScriptTarget.ES2020,
          },
        }).outputText;
        const module = { exports: {} };
        const exports = module.exports;
        eval(output);
        const sources = JSON.parse(process.argv[1]);
        const samples = JSON.parse(process.argv[2]);
        const index = module.exports.buildCitationIndex(sources);
        process.stdout.write(
            JSON.stringify(samples.map((text) => module.exports.splitByCitations(text, index)))
        );
        """
    )

    result = subprocess.run(
        ["node", "-e", script, json.dumps(sources), json.dumps(samples)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


_SOURCES = [
    {"n": 1, "harvard_in_text": "Smith, 2020, p. 3"},
    {"n": 2, "harvard_in_text": "Smith, 2020"},
    {"n": 3, "harvard_in_text": "Vaswani et al., 2017, pp. 3-4"},
]


def test_longest_match_wins_so_paged_citations_do_not_link_to_the_wrong_chunk() -> None:
    """`Smith, 2020` 绝不能遮蔽 `Smith, 2020, p. 3`——否则每条带页引用都链错 chunk。"""
    parsed = split_samples(_SOURCES, ["前 (Smith, 2020, p. 3) 后", "前 (Smith, 2020) 后"])

    assert [p for p in parsed[0] if p["n"] is not None] == [
        {"text": "Smith, 2020, p. 3", "n": 1}
    ]
    assert [p for p in parsed[1] if p["n"] is not None] == [{"text": "Smith, 2020", "n": 2}]


def test_merged_citation_group_splits_into_independent_matches() -> None:
    """合并形式 `(A; B)` 无需解析括号：内层串各自最长匹配。"""
    parsed = split_samples(
        _SOURCES, ["结论 (Smith, 2020, p. 3; Vaswani et al., 2017, pp. 3-4)。"]
    )

    assert [p["n"] for p in parsed[0] if p["n"] is not None] == [1, 3]


def test_legacy_bare_marker_stays_clickable_for_replayed_history() -> None:
    """v1.1.0 之前落库的历史消息仍是裸 `[n]`，兜底分支必须一直保留。"""
    parsed = split_samples(_SOURCES, ["旧答案 [2] 尾。"])

    assert [p for p in parsed[0] if p["n"] is not None] == [{"text": "[2]", "n": 2}]


def test_empty_sources_still_supports_legacy_markers() -> None:
    parsed = split_samples([], ["答案 [1]。"])

    assert [p for p in parsed[0] if p["n"] is not None] == [{"text": "[1]", "n": 1}]


def test_blank_harvard_string_is_skipped() -> None:
    """空串会变成在任意位置命中的空正则分支，必须跳过。"""
    parsed = split_samples([{"n": 1, "harvard_in_text": ""}], ["纯文本无引用"])

    assert parsed[0] == [{"text": "纯文本无引用", "n": None}]


def test_duplicate_string_resolves_to_smallest_n() -> None:
    """同文档同页的两个 chunk 产出相同短引；首次出现者胜，落到较小的 n。"""
    sources = [
        {"n": 2, "harvard_in_text": "Li, 2025, p. 1"},
        {"n": 5, "harvard_in_text": "Li, 2025, p. 1"},
    ]
    parsed = split_samples(sources, ["见 (Li, 2025, p. 1)。"])

    assert [p for p in parsed[0] if p["n"] is not None] == [{"text": "Li, 2025, p. 1", "n": 2}]


def test_text_without_citations_is_returned_intact() -> None:
    parsed = split_samples(_SOURCES, ["完全没有引用的一段话。"])

    assert parsed[0] == [{"text": "完全没有引用的一段话。", "n": None}]
