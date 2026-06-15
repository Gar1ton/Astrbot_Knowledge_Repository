import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def parse_samples(samples: list[str]) -> list[list[dict[str, str]]]:
    if shutil.which("node") is None:
        pytest.skip("node is not available")
    if not (ROOT / "web/frontend/node_modules/typescript").exists():
        pytest.skip("frontend TypeScript dependency is not installed")

    script = textwrap.dedent(
        r"""
        const fs = require("node:fs");
        const path = require("node:path");
        const ts = require(path.join(process.cwd(), "web/frontend/node_modules/typescript"));
        const sourcePath = path.join(process.cwd(), "web/frontend/lib/chunkText.ts");
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
        const samples = JSON.parse(process.argv[1]);
        process.stdout.write(JSON.stringify(samples.map((text) => module.exports.parseChunkText(text))));
        """
    )

    result = subprocess.run(
        ["node", "-e", script, json.dumps(samples)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_parse_chunk_text_renders_structural_headings_without_losing_body() -> None:
    parsed = parse_samples(
        [
            "**T14**",
            "**T14**\n\nbody",
            "**T14** body",
            "**2.** **Materials and methods**",
            "_2.1._ _Study area_",
            "A regular **value** appears in the body.",
        ]
    )

    assert parsed[0] == [{"type": "heading", "kind": "thesis", "label": "T14"}]
    assert parsed[1] == [
        {"type": "heading", "kind": "thesis", "label": "T14"},
        {"type": "paragraph", "text": "body"},
    ]
    assert parsed[2] == [
        {"type": "heading", "kind": "thesis", "label": "T14"},
        {"type": "paragraph", "text": "body"},
    ]
    assert parsed[3] == [
        {"type": "heading", "kind": "section", "label": "2.", "title": "Materials and methods"},
    ]
    assert parsed[4] == [
        {"type": "heading", "kind": "subsection", "label": "2.1.", "title": "Study area"},
    ]
    assert parsed[5] == [
        {"type": "paragraph", "text": "A regular **value** appears in the body."},
    ]
