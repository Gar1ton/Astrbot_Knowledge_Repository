"""web/server.py 路由 smoke 测试（aiohttp TestServer + 内存 api）。

验证 HTTP↔core/api 的翻译与认证中间件，不连真实后端。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from core.api import KnowledgeRepositoryApi
from core.domain.models import Collection, DocumentChunk, SourceDocument, SyncTargetKind
from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.sync_targets.memory import InMemorySyncTarget
from web.server import SESSION_COOKIE, build_app

_GB = 1024 * 1024 * 1024


async def _make_api() -> KnowledgeRepositoryApi:
    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="papers", description="d"))
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/p/d1.pdf", "application/pdf", 100, "h1", "papers", ["t"])
    )
    kb = InMemoryKnowledgeBaseReader(
        {"papers": [DocumentChunk("c0", "d1", 0, "alpha beta", "h0")]}
    )
    targets = {
        SyncTargetKind.R2: InMemorySyncTarget(SyncTargetKind.R2, 10 * _GB, base_used_bytes=8 * _GB),
        SyncTargetKind.NOTION: InMemorySyncTarget(SyncTargetKind.NOTION, 0),
    }
    return KnowledgeRepositoryApi(source_store=store, kb_reader=kb, sync_targets=targets)


async def _client(tmp_path: Path, *, auth_required: bool = False) -> TestClient:
    api = await _make_api()
    app = build_app(
        api=api,
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=auth_required,
        username="admin",
        password="pw",
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


# ── 配置校验 ────────────────────────────────────────────────────


def test_build_app_rejects_empty_password_when_auth_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_app(
            api=None,  # type: ignore[arg-type]
            static_dir=tmp_path,
            upload_dir=tmp_path,
            auth_required=True,
            password="",
        )


# ── 集合 / 文档（no-auth）──────────────────────────────────────


async def test_list_and_create_collection(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/collections")
        assert resp.status == 200
        assert [c["name"] for c in await resp.json()] == ["papers"]

        resp = await client.post("/api/collections", json={"name": "manuals", "description": "m"})
        assert resp.status == 200
        names = [c["name"] for c in await (await client.get("/api/collections")).json()]
        assert set(names) == {"papers", "manuals"}
    finally:
        await client.close()


async def test_create_collection_requires_name(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.post("/api/collections", json={"name": "  "})
        assert resp.status == 400
    finally:
        await client.close()


async def test_list_documents_and_filter(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/documents")
        assert [d["doc_id"] for d in await resp.json()] == ["d1"]
        resp = await client.get("/api/documents?collection=none")
        assert await resp.json() == []
    finally:
        await client.close()


async def test_upload_classify_delete_document(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        form = FormData()
        form.add_field("file", b"%PDF-1.4 demo", filename="new.pdf", content_type="application/pdf")
        form.add_field("collection", "papers")
        form.add_field("tags", "x, y")
        resp = await client.post("/api/documents", data=form)
        assert resp.status == 200
        doc_id = (await resp.json())["doc_id"]

        # 上传后列表 +1，且标签生效
        docs = await (await client.get("/api/documents")).json()
        uploaded = next(d for d in docs if d["doc_id"] == doc_id)
        assert uploaded["tags"] == ["x", "y"]
        assert uploaded["size_bytes"] == len(b"%PDF-1.4 demo")

        # 分类
        resp = await client.patch(f"/api/documents/{doc_id}", json={"collection": "manuals"})
        assert resp.status == 200
        moved = next(
            d for d in await (await client.get("/api/documents")).json() if d["doc_id"] == doc_id
        )
        assert moved["collection"] == "manuals"

        # 删除
        assert (await client.delete(f"/api/documents/{doc_id}")).status == 200
        assert (await client.delete(f"/api/documents/{doc_id}")).status == 404
    finally:
        await client.close()


async def test_upload_empty_file_rejected(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        form = FormData()
        form.add_field("file", b"", filename="empty.pdf")
        resp = await client.post("/api/documents", data=form)
        assert resp.status == 400
    finally:
        await client.close()


# ── KB 检索 / 配额 ─────────────────────────────────────────────


async def test_kb_search(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        assert await (await client.get("/api/kb/collections")).json() == ["papers"]
        hits = await (await client.get("/api/kb/search?collection=papers&q=alpha&top_k=5")).json()
        assert [h["chunk_id"] for h in hits] == ["c0"]
    finally:
        await client.close()


async def test_quota_dashboard(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        quota = await (await client.get("/api/quota")).json()
        by_target = {q["target"]: q for q in quota}
        assert by_target["r2"]["ratio"] == pytest.approx(0.8)       # 8GB / 10GB
        assert by_target["notion"]["limit_bytes"] == 0             # 无字节上限
    finally:
        await client.close()


# ── 认证 ────────────────────────────────────────────────────────


async def test_auth_required_blocks_then_login(tmp_path: Path) -> None:
    client = await _client(tmp_path, auth_required=True)
    try:
        assert (await client.get("/api/collections")).status == 401

        bad = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert bad.status == 401

        ok = await client.post("/api/login", json={"username": "admin", "password": "pw"})
        assert ok.status == 200
        assert SESSION_COOKIE in client.session.cookie_jar.filter_cookies("http://127.0.0.1")

        # 登录后放行
        assert (await client.get("/api/collections")).status == 200
    finally:
        await client.close()


async def test_auth_probe_endpoint_is_public(tmp_path: Path) -> None:
    client = await _client(tmp_path, auth_required=True)
    try:
        resp = await client.get("/api/auth")
        assert resp.status == 200
        body = await resp.json()
        assert body["auth_required"] is True and body["logged_in"] is False
    finally:
        await client.close()


# ── 预留端口（reserved → 501 + available_in）────────────────────


@pytest.mark.parametrize(
    "method,path,version",
    [
        ("post", "/api/sync/r2", "v0.3.0 / v0.4.0"),
        ("post", "/api/sync/all", "v0.3.0 / v0.4.0"),
        ("post", "/api/backup", "v0.3.0"),
        ("post", "/api/restore", "v0.3.0"),
        ("post", "/api/graph/build", "v0.6.0"),
        ("get", "/api/graph/query?q=x", "v0.6.0"),
        ("get", "/api/graph?collection=papers", "v0.7.0"),
    ],
)
async def test_reserved_endpoints_return_501(
    tmp_path: Path, method: str, path: str, version: str
) -> None:
    client = await _client(tmp_path)
    try:
        kwargs = {"json": {}} if method == "post" else {}
        resp = await getattr(client, method)(path, **kwargs)
        assert resp.status == 501
        body = await resp.json()
        assert body["status"] == "reserved"
        assert body["available_in"] == version
    finally:
        await client.close()


async def test_sync_status_endpoint_returns_200(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/sync/status")
        assert resp.status == 200
        body = await resp.json()
        assert isinstance(body, list)
    finally:
        await client.close()
