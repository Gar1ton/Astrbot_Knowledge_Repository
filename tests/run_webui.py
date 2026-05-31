#!/usr/bin/env python3
"""一键启动 Web 控制台用于审阅/调试（见 ../web/README.md）。

用现有的内存实现（core/repository/*/memory.py）并播种示例数据装配 KnowledgeRepositoryApi，
直接拉起独立端口的 aiohttp 服务，无需 SQLite/R2/Notion 等真实后端——纯前端审阅用。
真实后端（v0.3.0/v0.4.0）就绪后，组合根换注入即可，前端与本脚本逻辑不变。

用法：
    python tests/run_webui.py                 # 端口 6520，需登录（默认 admin / 111111）
    python tests/run_webui.py --no-auth       # 跳过登录，直接进入（仅本地调试）
    python tests/run_webui.py --port 8000     # 指定端口
    python tests/run_webui.py --empty         # 不播种示例数据
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 让脚本可直接运行：把仓库根加入 import 路径。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiohttp import web  # noqa: E402

from core.api import KnowledgeRepositoryApi  # noqa: E402
from core.config import Config  # noqa: E402
from core.domain.models import (  # noqa: E402
    Collection,
    DocumentChunk,
    SourceDocument,
    SyncTargetKind,
)
from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader  # noqa: E402
from core.repository.source_store.memory import InMemorySourceDocumentStore  # noqa: E402
from core.repository.sync_targets.memory import InMemorySyncTarget  # noqa: E402
from web.server import build_app  # noqa: E402

_DEFAULT_PASSWORD = "111111"
_GB = 1024 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_store() -> InMemorySourceDocumentStore:
    store = InMemorySourceDocumentStore()
    for name, desc in [("papers", "学术论文"), ("manuals", "产品手册"), ("default", "默认集合")]:
        await store.upsert_collection(Collection(name=name, description=desc, created_at=_now()))
    samples = [
        ("Attention Is All You Need.pdf", "papers", ["transformer", "2017"], 2_400_000),
        ("LightRAG 论文.pdf", "papers", ["rag", "graph"], 1_800_000),
        ("AstrBot 部署手册.pdf", "manuals", ["astrbot", "deploy"], 900_000),
    ]
    for i, (title, col, tags, size) in enumerate(samples):
        await store.add_document(
            SourceDocument(
                doc_id=f"seed-{i}",
                title=title,
                file_path=f"/data/seed/{title}",
                content_type="application/pdf",
                size_bytes=size,
                content_hash=f"seedhash{i}",
                collection=col,
                tags=tags,
                created_at=_now(),
                updated_at=_now(),
            )
        )
    return store


def _seed_kb() -> InMemoryKnowledgeBaseReader:
    return InMemoryKnowledgeBaseReader(
        {
            "papers": [
                DocumentChunk("k0", "seed-0", 0, "The Transformer relies on self-attention.", "h0"),
                DocumentChunk("k1", "seed-1", 0, "LightRAG builds an incremental KG.", "h1"),
            ],
            "manuals": [
                DocumentChunk("k2", "seed-2", 0, "Run AstrBot via docker, init data dir.", "h2"),
            ],
        }
    )


def _seed_targets(empty: bool) -> dict[SyncTargetKind, InMemorySyncTarget]:
    # 非空时给 R2 一个 ~7.5GB 基线用量（不真分配字节），便于看到配额条接近阈值。
    base = 0 if empty else int(7.5 * _GB)
    r2 = InMemorySyncTarget(kind=SyncTargetKind.R2, limit_bytes=10 * _GB, base_used_bytes=base)
    notion = InMemorySyncTarget(kind=SyncTargetKind.NOTION, limit_bytes=0)  # 不以字节计
    return {SyncTargetKind.R2: r2, SyncTargetKind.NOTION: notion}


class _DebugSyncPipeline:
    async def sync(
        self,
        target_kind: SyncTargetKind,
        doc_ids: list[str] | None = None,
    ) -> dict:
        return {
            "status": "success",
            "target": target_kind.value,
            "synced_count": 0,
            "failed_count": 0,
            "message": "Debug pipeline: no remote writes performed.",
        }

    async def restore(self, target_kind: SyncTargetKind) -> dict:
        return {
            "status": "success",
            "target": target_kind.value,
            "message": "Debug pipeline: restore preview only.",
        }

    async def initialize_notion_database(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> dict:
        return {
            "status": "success",
            "database_id": "debug-notion-database",
            "parent_page_id": parent_page_id or "debug-parent-page",
            "database_title": database_title or "Knowledge Repository",
            "created": True,
            "message": "Debug pipeline: mocked Notion database creation.",
        }

    async def pull_notion_metadata(self) -> dict:
        return {
            "status": "success",
            "updated_count": 0,
            "skipped_count": 0,
            "warnings": ["Debug pipeline: no Notion pages queried."],
        }


async def _make_app(args: argparse.Namespace) -> web.Application:
    store = InMemorySourceDocumentStore() if args.empty else await _seed_store()
    kb = InMemoryKnowledgeBaseReader({}) if args.empty else _seed_kb()
    targets = _seed_targets(args.empty)
    config = Config({
        "source_store": {"default_collection": "default"},
        "r2_sync": {"enabled": True, "bucket": "debug-bucket", "free_tier_gb": 10},
        "notion_sync": {
            "enabled": True,
            "database_id": "debug-notion-database",
            "parent_page_id": "debug-parent-page",
            "database_title": "Knowledge Repository",
        },
        "web_console": {"enabled": True, "host": args.host, "port": args.port, "username": "admin"},
        "graph": {"enabled": True},
    })
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        sync_targets=targets,
        sync_pipeline=_DebugSyncPipeline(),  # type: ignore[arg-type]
        config=config,
    )
    upload_dir = Path(tempfile.gettempdir()) / "kr_webui_uploads"
    return build_app(
        api=api,
        static_dir=_ROOT / "web" / "frontend",
        upload_dir=upload_dir,
        auth_required=not args.no_auth,
        username="admin",
        password=_DEFAULT_PASSWORD,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Knowledge Repository Web 控制台（调试用）")
    parser.add_argument("--port", type=int, default=6520)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-auth", action="store_true", help="跳过登录（仅本地调试）")
    parser.add_argument("--empty", action="store_true", help="不播种示例数据")
    args = parser.parse_args()

    print("=" * 56)
    print("  Knowledge Repository · Web 控制台（预览/调试）")
    print(f"  地址:  http://{args.host}:{args.port}")
    if args.no_auth:
        print("  认证:  已禁用（--no-auth）")
    else:
        print(f"  登录:  admin / {_DEFAULT_PASSWORD}")
    print("  数据:  内存实现 + 示例数据" + ("（空）" if args.empty else ""))
    print("  退出:  Ctrl+C")
    print("=" * 56)

    web.run_app(_make_app(args), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
