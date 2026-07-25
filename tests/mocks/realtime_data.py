"""真实开发环境的数据生命周期辅助：归档/恢复、PDF 制品生成与结构化分块。"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PDF_DIR = _ROOT / "tests" / "mock_data" / "Test_Library"
_TEST_DATA = _ROOT / ".test_data"
_ARCHIVE_DIR = _ROOT / "tests" / "archive"
_ARCHIVE_BASE = _ARCHIVE_DIR / ".test_data_archive"

# ── 阶段 2：归档旧测试数据 ────────────────────────────────────────


def _archive_step() -> None:
    if not _TEST_DATA.exists():
        return
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"{_ARCHIVE_BASE}_{ts}")
    try:
        shutil.move(str(_TEST_DATA), str(dest))
        print(f"[Archive] 已归档旧测试数据 → {dest.name}/")
    except Exception as e:
        print(f"[Archive] 警告：无法移动旧数据（{e}），将尝试直接覆盖")


# ── 启动模式：恢复归档 or 全新跑 ──────────────────────────────────


def _find_archives() -> list[Path]:
    """返回 tests/archive/ 下所有归档，按修改时间倒序（最新在前）。"""
    if not _ARCHIVE_DIR.exists():
        return []
    return sorted(
        _ARCHIVE_DIR.glob(".test_data_archive_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _inspect_archive(path: Path) -> str:
    """检查归档完整度，返回一行健康标注（用于列表展示）。"""
    has_milvus = (path / "milvus.db").exists()
    docs_dir = path / "managed_docs"
    doc_count = sum(1 for _ in docs_dir.iterdir()) if docs_dir.is_dir() else 0
    compat = path / "index_compatibility.json"
    fingerprint = ""
    if compat.exists():
        try:
            state = json.loads(compat.read_text(encoding="utf-8"))
            fingerprint = state.get("milvus", {}).get("fingerprint", "")
        except (OSError, json.JSONDecodeError):
            fingerprint = ""
    notes: list[str] = []
    if doc_count == 0:
        notes.append("⚠ 无文档（空归档，恢复后库为空）")
    if not has_milvus or not fingerprint:
        notes.append("⚠ 缺向量库/指纹（恢复后将重建）")
    if not docs_dir.exists():
        notes.append("⚠ 无 clean.md（早期归档，内容标签不可用）")
    if not notes:
        return f"✓ 完整（{doc_count} 文档）"
    return f"{doc_count} 文档  " + "  ".join(notes)


def _live_doc_count() -> int:
    """当前活动 .test_data/managed_docs 下的文档数（0 表示无活动数据）。"""
    docs_dir = _TEST_DATA / "managed_docs"
    return sum(1 for _ in docs_dir.iterdir()) if docs_dir.is_dir() else 0


def _choose_startup_mode() -> tuple[str, Path | None]:
    """决定本次启动模式：返回 ("keep"|"fresh", None) 或 ("restore", <归档 Path>)。

    - keep    ：直接用当前 .test_data/ 起服务（不归档、不种子、不重建）。
    - fresh   ：归档当前数据后重新种子 + 重建。
    - restore ：把所选归档提升为 .test_data/ 后起服务。

    CLI 参数优先（--keep / --fresh / --restore）；否则交互选择。
    当 .test_data/ 已有文档时，交互默认（回车）= keep，避免误弄丢现有构筑。
    """
    if "--keep" in sys.argv:
        return ("keep", None)
    if "--fresh" in sys.argv:
        return ("fresh", None)

    archives = _find_archives()

    if "--restore" in sys.argv:
        if not archives:
            print("[Restore] 错误：--restore 指定恢复，但 tests/archive/ 下无任何归档")
            sys.exit(1)
        return ("restore", archives[0])

    live = _live_doc_count()
    shown = archives[:10]

    print("-" * 65)
    if live > 0:
        print(f"  当前 .test_data/ 已有数据：{live} 文档（可直接继续，不归档不重建）")
    if shown:
        print("  历史归档（可恢复其数据继续跑，跳过 md 清洗与向量库重建）：")
        for idx, arc in enumerate(shown, start=1):
            mtime = datetime.fromtimestamp(arc.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"    [{idx:>2}] {arc.name}  ({mtime})  {_inspect_archive(arc)}")
    print("-" * 65)

    if live > 0:
        # 有活动数据：默认保持当前；全新需显式输入 f/new
        print("  回车 = 继续用当前数据；输入编号 = 恢复该归档；输入 f = 全新开始")
        try:
            raw = input("  请选择 [回车=继续当前]: ").strip()
        except EOFError:
            raw = ""
        if not raw or raw.lower() in {"c", "k", "keep", "continue"}:
            return ("keep", None)
        if raw.lower() in {"f", "fresh", "new", "n"}:
            return ("fresh", None)
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            return ("restore", shown[int(raw) - 1])
        print(f"[Start] 无效输入 {raw!r}，回退「继续当前数据」")
        return ("keep", None)

    # 无活动数据：沿用旧默认（回车=全新）
    if not shown:
        print("  未发现活动数据与历史归档，走全新流程")
        return ("fresh", None)
    print("  输入编号恢复对应归档；直接回车 / n 走全新流程。")
    try:
        raw = input("  请选择 [回车=全新]: ").strip()
    except EOFError:
        raw = ""
    if not raw or raw.lower() in {"n", "no", "fresh"}:
        return ("fresh", None)
    if raw.isdigit() and 1 <= int(raw) <= len(shown):
        return ("restore", shown[int(raw) - 1])
    print(f"[Start] 无效输入 {raw!r}，回退全新流程")
    return ("fresh", None)


# ── 阶段 4：读取 PDF，写入 source store + 生成 clean.md 制品 ──────


def _chunk_text(text: str, size: int = 2000, overlap: int = 200) -> list[str]:
    """简单定长分块，按 Unicode 字符计数。"""
    if not text.strip():
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
        if start >= len(text):
            break
    return [c for c in chunks if c.strip()]


def _extract_pages_with_fitz(pdf_path: Path) -> list[tuple[int, str]]:
    """用 fitz 逐页提取文本，返回 [(page_no_1based, text), ...]。"""
    import fitz

    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages.append((i + 1, text))
    doc.close()
    return pages


def _build_markdown_fallback(pages: list[tuple[int, str]]) -> str:
    """将逐页文本拼成基础 markdown，作为 pymupdf4llm 不可用时的降级。"""
    parts = []
    for page_no, text in pages:
        parts.append(f"## Page {page_no}\n\n{text.strip()}")
    return "\n\n".join(parts)


def _chunk_pages_with_metadata(
    pages: list[tuple[int, str]],
    size: int = 2000,
    overlap: int = 200,
) -> list[tuple[str, int]]:
    """将逐页文本定长切块，每块携带首页页码。

    返回 [(chunk_text, page_no_1based), ...]。
    """
    result: list[tuple[str, int]] = []
    for page_no, text in pages:
        sub_chunks = _chunk_text(text, size=size, overlap=overlap)
        for chunk in sub_chunks:
            result.append((chunk, page_no))
    return result


async def _seed_pdfs(store, managed_docs_dir: Path) -> int:
    """从 tests/mock_data/Test_Library/ 读取 PDF，写入 source store 并生成制品。

    同时生成 managed_docs_dir/<doc_id>/clean.md，供前端内容面板使用。
    每个 chunk 的 metadata 携带 page_number，供前端 chunks 面板显示页码。
    """
    try:
        importlib.import_module("fitz")  # PyMuPDF 可用性探针
    except ImportError:
        print("[Seed] 未找到 PyMuPDF (fitz)，跳过 PDF 导入。pip install PyMuPDF")
        return 0

    pdfs = sorted(_PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[Seed] 未在 {_PDF_DIR} 找到 PDF 文件")
        return 0

    from kacore.domain.models import DocumentChunk, SourceDocument
    from kacore.managers.chunking import CHUNK_SCHEMA, build_structural_chunk_spans
    from kacore.managers.markdown_extractor import build_single_page_artifact, extract_pdf_markdown

    now = datetime.now(timezone.utc)
    total_chunks = 0

    for pdf_path in pdfs:
        doc_id = hashlib.md5(pdf_path.name.encode()).hexdigest()[:16]
        print(f"[Seed] 处理 {pdf_path.name} (doc_id={doc_id})")

        # 提取逐页文本（用于分块 + 作为 markdown 生成的降级输入）
        pages = _extract_pages_with_fitz(pdf_path)
        if not pages:
            print("[Seed]   → 无可提取文本，跳过")
            continue

        content_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:32]

        # 生成 clean.md 制品
        artifact_dir = managed_docs_dir / doc_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        clean_md_path = artifact_dir / "clean.md"
        pages_json_path = artifact_dir / "pages.json"
        try:
            artifact = extract_pdf_markdown(str(pdf_path))
            print(
                f"[Seed]   → clean.md 由 structural extractor 生成"
                f"（{len(artifact.clean_markdown)} 字符）"
            )
        except Exception as e:
            print(f"[Seed]   → structural extractor 失败（{e}），降级为基础提取")
            artifact = build_single_page_artifact(_build_markdown_fallback(pages))
        clean_md_path.write_text(artifact.clean_markdown, encoding="utf-8")
        pages_payload = [
            {"page": span.page, "markdown_start_char": span.start, "markdown_end_char": span.end}
            for span in artifact.page_spans
        ]
        pages_json_path.write_text(
            json.dumps(pages_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 创建 SourceDocument（携带 markdown_rel_path 供内容端点使用）
        src_doc = SourceDocument(
            doc_id=doc_id,
            title=pdf_path.stem,
            file_path=str(
                pdf_path
            ),  # 直接指向原始 PDF（供 PDF 浏览器 /raw?disposition=inline 使用）
            content_type="application/pdf",
            size_bytes=pdf_path.stat().st_size,
            content_hash=content_hash,
            collection="default",
            tags=["test", "brian-massumi"],
            created_at=now,
            updated_at=now,
            needs_reindex=True,  # 标记待 Milvus 向量化（由阶段 9b 自动处理）
            markdown_rel_path="clean.md",  # 指向 managed_docs_dir/<doc_id>/clean.md
            pages_rel_path="pages.json",
            local_meta={"chunk_schema": CHUNK_SCHEMA},
        )
        await store.add_document(src_doc)

        # 分块并写入（与正式摄入路径共用 structural_v3 chunker）
        chunk_spans, _, _ = build_structural_chunk_spans(
            artifact.clean_markdown,
            chunk_size=1000,
        )
        chunks = []
        for i, chunk_span in enumerate(chunk_spans):
            text = artifact.clean_markdown[chunk_span.start : chunk_span.end]
            chunk_pages = [
                span.page
                for span in artifact.page_spans
                if span.start < chunk_span.end and span.end > chunk_span.start
            ]
            page_no = chunk_pages[0] if chunk_pages else 1
            chunk_hash = hashlib.sha256(text.encode()).hexdigest()[:24]
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc_id}_c{i:04d}",
                    doc_id=doc_id,
                    ordinal=i,
                    text=text,
                    content_hash=chunk_hash,
                    metadata={
                        **chunk_span.metadata,
                        "pages": chunk_pages,
                        "page_number": page_no,
                        "start_char": chunk_span.start,
                        "end_char": chunk_span.end,
                        "locator": f"page_{page_no}_o{chunk_span.start}",
                    },
                )
            )
        await store.replace_chunks(doc_id, chunks)
        total_chunks += len(chunks)
        print(
            f"[Seed]   → {len(chunks)} structural_v3 chunks 写入完成"
            f"（共 {len(artifact.page_spans)} 页）"
        )

    return total_chunks
