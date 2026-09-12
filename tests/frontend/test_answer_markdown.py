"""answerMarkdown.ts 的结构解析回归（node 转译后直接调用，无 node 则跳过）。"""
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def parse(markdown: str) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("node is not available")
    if not (ROOT / "web/frontend/node_modules/typescript").exists():
        pytest.skip("frontend TypeScript dependency is not installed")
    script = textwrap.dedent(
        r"""
        const fs = require("node:fs");
        const path = require("node:path");
        const ts = require(path.join(process.cwd(), "web/frontend/node_modules/typescript"));
        const source = fs.readFileSync(
          path.join(process.cwd(), "web/frontend/lib/answerMarkdown.ts"), "utf8"
        );
        const output = ts.transpileModule(source, {
          compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
        }).outputText;
        const module = { exports: {} };
        const exports = module.exports;
        eval(output);
        process.stdout.write(JSON.stringify(module.exports.parseAnswerMarkdown(process.argv[1])));
        """
    )
    result = subprocess.run(
        ["node", "-e", script, markdown], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return json.loads(result.stdout)


def test_parses_headings_paragraphs_lists_and_code_without_html_execution() -> None:
    blocks = parse(
        "## 定义\n\n第一段 **重点** [1]。\n\n- 一\n- 二\n\n```html\n<script>x</script>\n```"
    )
    assert [block["type"] for block in blocks] == [
        "heading", "paragraph", "unordered-list", "code"
    ]
    assert blocks[0] == {"type": "heading", "level": 2, "text": "定义"}
    assert blocks[-1]["text"] == "<script>x</script>"


def test_reference_block_and_transport_escaped_markers_become_structure() -> None:
    blocks = parse(
        "正文。\\\n\\\n**参考文献**\\\n\\\n\\- Anon. (n.d.) Paper A.\\\n"
        "\\- Anon. (n.d.) Paper B."
    )
    assert blocks == [
        {"type": "paragraph", "text": "正文。"},
        {"type": "heading", "level": 3, "text": "参考文献"},
        {
            "type": "unordered-list",
            "items": ["Anon. (n.d.) Paper A.", "Anon. (n.d.) Paper B."],
        },
    ]
