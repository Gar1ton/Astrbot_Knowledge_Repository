"""只读预览脚本：用当前切片管线处理一个 PDF，输出 clean.md/chunks.json/chunks_preview.md。

不写入任何数据库、制品包或索引；只用来人工核对切片质量（噪声残留、标题边界、
段落完整性、token 预算、offset 不变量），流程和产物见 docs/chunk_preview_samples/README.md。

用法：
    .venv/bin/python tools/chunk_preview.py <pdf_path> <out_dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kacore.managers.chunk_token_limits import limit_chunk_spans
from kacore.managers.chunking import build_structural_chunk_spans
from kacore.managers.markdown_extractor import extract_pdf_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    artifact = extract_pdf_markdown(str(args.pdf_path))
    md = artifact.clean_markdown
    (args.out_dir / "clean.md").write_text(md, encoding="utf-8")

    chunk_spans, _sections, _subsections = build_structural_chunk_spans(
        md, chunk_size=args.chunk_size
    )
    chunk_spans = limit_chunk_spans(md, chunk_spans)

    chunks_payload = []
    for idx, span in enumerate(chunk_spans):
        text = md[span.start : span.end]
        pages = [
            s.page
            for s in artifact.page_spans
            if s.start < span.end and s.end > span.start
        ]
        chunks_payload.append(
            {
                "ordinal": idx,
                "start_char": span.start,
                "end_char": span.end,
                "char_len": span.end - span.start,
                "pages": pages,
                "metadata": span.metadata,
                "text": text,
            }
        )
    (args.out_dir / "chunks.json").write_text(
        json.dumps(chunks_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# Chunk preview: {args.pdf_path.name}",
        "",
        f"- converter: {artifact.converter} {artifact.converter_version}",
        f"- pages: {len(artifact.page_spans)}",
        f"- chunk_size policy: {args.chunk_size} "
        f"(target_min={int(args.chunk_size * 0.7)}, target_max={int(args.chunk_size * 1.6)}, "
        f"soft_max={int(args.chunk_size * 2.2)}, hard_limit={int(args.chunk_size * 3.0)})",
        f"- total chunks: {len(chunks_payload)}",
        f"- footnotes detected: {len(artifact.footnotes)}",
        "",
        "---",
        "",
    ]
    for c in chunks_payload:
        meta = c["metadata"]
        section_path = " > ".join(meta.get("section_path", [])) or meta.get(
            "section_label", ""
        )
        lines.append(
            f"## Chunk {c['ordinal']:04d}  (chars {c['start_char']}–{c['end_char']}, "
            f"len={c['char_len']}, pages={c['pages']}, tokens={meta.get('token_count', '?')})"
        )
        lines.append(f"- section: {section_path or '(none)'}")
        if meta.get("subsection_label"):
            lines.append(f"- subsection: {meta['subsection_label']}")
        if meta.get("anchor_label"):
            lines.append(f"- anchor: {meta['anchor_label']}")
        if meta.get("anchor_labels"):
            lines.append(f"- anchors: {meta['anchor_labels']}")
        lines.append(f"- block_types: {meta.get('block_types')}")
        lines.append("")
        lines.append("```text")
        lines.append(c["text"])
        lines.append("```")
        lines.append("")
    (args.out_dir / "chunks_preview.md").write_text("\n".join(lines), encoding="utf-8")

    print(
        f"pages={len(artifact.page_spans)} chunks={len(chunks_payload)} "
        f"footnotes={len(artifact.footnotes)}"
    )
    print(f"clean.md chars={len(md)}")


if __name__ == "__main__":
    main()
