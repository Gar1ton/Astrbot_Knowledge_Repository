"""web/server.py 路由 smoke 测试（aiohttp TestServer + 内存 api）。

验证 HTTP↔core/api 的翻译与认证中间件，不连真实后端。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from core.api import KnowledgeRepositoryApi
from core.config import Config
from core.domain.models import (
    Collection,
    DocumentChunk,
    GraphEntity,
    GraphRelation,
    SourceDocument,
    SyncTargetKind,
)
from core.repository.graph_store.memory import InMemoryGraphStore
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
    return KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        sync_targets=targets,
        config=Config({"notion_sync": {"database_id": "db1", "parent_page_id": "parent1"}}),
    )


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
        assert await resp.json() == {"name": "manuals", "description": "m"}
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
        docs = await resp.json()
        assert [d["doc_id"] for d in docs] == ["d1"]
        assert docs[0]["size"] == docs[0]["size_bytes"] == 100
        assert docs[0]["filename"] == "d1.pdf"
        assert docs[0]["ext"] == "pdf"
        assert docs[0]["chunks"] == 0
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
        uploaded_resource = await resp.json()
        doc_id = uploaded_resource["doc_id"]
        assert uploaded_resource["title"] == "new.pdf"
        assert uploaded_resource["size"] == len(b"%PDF-1.4 demo")

        # 上传后列表 +1，且标签生效
        docs = await (await client.get("/api/documents")).json()
        uploaded = next(d for d in docs if d["doc_id"] == doc_id)
        assert uploaded["tags"] == ["x", "y"]
        assert uploaded["size_bytes"] == len(b"%PDF-1.4 demo")

        # 分类
        resp = await client.patch(f"/api/documents/{doc_id}", json={"collection": "manuals"})
        assert resp.status == 200
        assert (await resp.json())["collection"] == "manuals"
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


async def test_effective_config_endpoint_returns_masked_config(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/config/effective")
        assert resp.status == 200
        body = await resp.json()
        assert body["notion_sync"]["database_id"] == "db1"
        assert "r2_sync" in body
        assert "graph" in body
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
        assert body["reserved"] is True
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


async def test_graph_endpoints_return_200(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock
    # Create an API with mocked pipelines
    store = InMemorySourceDocumentStore()
    kb = InMemoryKnowledgeBaseReader({})

    mock_build = AsyncMock()
    mock_build.build_graph.return_value = {
        "status": "success",
        "message": "Extracted 2, skipped 1.",
        "total_chunks": 3,
        "extracted_chunks": 2,
        "skipped_chunks": 1,
        "deleted_stale_chunks": 0,
    }

    mock_search = AsyncMock()
    mock_search.search.return_value = {
        "status": "success",
        "query": "Transformer",
        "chunks": [],
        "entities": [GraphEntity("transformer", "Transformer", "Method", "desc", ["c2"])],
        "relations": [
            GraphRelation("r1", "transformer", "attention", "uses", "desc", 1.0, ["c2"])
        ],
        "context": "Context text",
        "debug": {
            "vector_chunk_ids": ["c2"],
            "keyword_chunk_ids": [],
            "graph_chunk_ids": [],
            "rrf_scores": {"c2": 0.1},
        },
    }

    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        graph_build_pipeline=mock_build,
        graph_search_pipeline=mock_search,
    )

    app = build_app(
        api=api,
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # Test post build graph
        resp1 = await client.post("/api/graph/build", json={"collection": "papers"})
        assert resp1.status == 200
        body1 = await resp1.json()
        assert body1["status"] == "success"
        assert body1["extracted_chunks"] == 2

        # Test get query graph
        resp2 = await client.get("/api/graph/query?q=Transformer&top_k=3&debug=true")
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["status"] == "success"
        assert body2["context"] == "Context text"
        assert body2["debug"]["vector_chunk_ids"] == ["c2"]
        assert body2["entities"][0]["id"] == "transformer"
        assert body2["entities"][0]["type"] == "Method"
        assert body2["relations"][0]["id"] == "r1"
        assert body2["relations"][0]["source"] == "transformer"
        assert body2["relations"][0]["target"] == "attention"
    finally:
        await client.close()


async def test_graph_data_endpoint_returns_200(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="papers", description="d"))
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/p/d1.pdf", "application/pdf", 100, "h1", "papers", ["t"])
    )
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "source text", "ch1")])
    graph = InMemoryGraphStore()
    await graph.upsert_entities([
        GraphEntity("transformer", "Transformer", "Method", "desc", ["c1"]),
        GraphEntity("attention", "Attention", "Method", "desc", ["c1"]),
    ])
    await graph.upsert_relations([
        GraphRelation("r1", "transformer", "attention", "uses", "desc", 2.0, ["c1"])
    ])
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        graph_store=graph,
    )
    app = build_app(
        api=api,
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/api/graph?collection=papers")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "success"
        assert {n["id"] for n in body["nodes"]} == {"transformer", "attention"}
        assert body["edges"][0]["id"] == "r1"
        assert body["nodes"][0]["source_previews"][0]["text"] == "source text"
    finally:
        await client.close()


async def test_notion_init_and_pull_routes_return_200(tmp_path: Path) -> None:
    class StubApi:
        async def initialize_notion_database(
            self,
            parent_page_id: str | None = None,
            database_title: str | None = None,
        ) -> dict:
            return {
                "status": "success",
                "database_id": "db-created",
                "parent_page_id": parent_page_id,
                "database_title": database_title,
                "created": True,
            }

        async def pull_notion_metadata(self) -> dict:
            return {"status": "success", "updated_count": 1, "skipped_count": 0}

    app = build_app(
        api=StubApi(),  # type: ignore[arg-type]
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        init = await client.post(
            "/api/notion/init",
            json={"parent_page_id": "parent", "database_title": "KR"},
        )
        assert init.status == 200
        assert (await init.json())["database_id"] == "db-created"

        pull = await client.post("/api/sync/notion/pull")
        assert pull.status == 200
        assert (await pull.json())["updated_count"] == 1
    finally:
        await client.close()


# ── /api/ask ──────────────────────────────────────────────────────


async def test_ask_route_returns_answer_and_sources(tmp_path: Path) -> None:
    """POST /api/ask 应委派 api.ask() 并返回 answer + sources JSON。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post(
            "/api/ask",
            json={"question": "alpha beta", "collection": "papers", "top_k": 5},
        )
        assert resp.status == 200
        body = await resp.json()
        assert "answer" in body and body["answer"]
        assert "sources" in body and isinstance(body["sources"], list)
        assert "conversation_id" in body and body["conversation_id"]
    finally:
        await client.close()


async def test_ask_route_requires_question(tmp_path: Path) -> None:
    """question 为空时应返回 400。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post("/api/ask", json={"question": "  "})
        assert resp.status == 400
        body = await resp.json()
        assert "error" in body
    finally:
        await client.close()


async def test_ask_route_accepts_conversation_id(tmp_path: Path) -> None:
    """conversation_id 由调用方提供时应原样返回。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post(
            "/api/ask",
            json={"question": "alpha", "conversation_id": "test-conv-123"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["conversation_id"] == "test-conv-123"
    finally:
        await client.close()


async def test_ask_route_clamps_top_k(tmp_path: Path) -> None:
    """top_k 超出边界应被截断而不是报错。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post("/api/ask", json={"question": "alpha", "top_k": 999})
        assert resp.status == 200
    finally:
        await client.close()


async def test_spa_static_fallback_serves_index(tmp_path: Path) -> None:
    """非 /api 路径应由 SPA catch-all 回退到 index.html（存在时）。"""
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html>root</html>")
    docs_dir = static / "documents"
    docs_dir.mkdir()
    (docs_dir / "index.html").write_text("<html>docs</html>")

    app = build_app(
        api=await _make_api(),
        static_dir=static,
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # 子路由返回子 index.html
        resp = await client.get("/documents")
        assert resp.status == 200
        assert (await resp.text()) == "<html>docs</html>"

        # 未知路由回退到根 index.html
        resp2 = await client.get("/unknown-path")
        assert resp2.status == 200
        assert (await resp2.text()) == "<html>root</html>"
    finally:
        await client.close()


async def test_logout_route(tmp_path: Path) -> None:
    """显式登出端点应从 app sessions 中移除会话 Token 并清除 Cookie。"""
    client = await _client(tmp_path, auth_required=True)
    try:
        # 1. 登录以创建 Token
        resp = await client.post("/api/login", json={"username": "admin", "password": "pw"})
        assert resp.status == 200
        cookies = client.session.cookie_jar.filter_cookies(client.make_url("/"))
        assert SESSION_COOKIE in cookies

        # 2. 登出
        resp_logout = await client.post("/api/logout")
        assert resp_logout.status == 200
        body = await resp_logout.json()
        assert body["ok"] is True

        # 3. 再次获取 api 资源应返回 401
        resp_api = await client.get("/api/collections")
        assert resp_api.status == 401
    finally:
        await client.close()


async def test_download_document_route(tmp_path: Path) -> None:
    """文档下载端点应正确下载物理原件，不存在的 doc_id 或物理文件应返回 404。"""
    api = await _make_api()
    
    # 模拟真实物理原件写入
    file_path = tmp_path / "test_doc.pdf"
    file_path.write_bytes(b"pdf data here")
    
    # 在内存 store 中更新文档物理路径
    doc = await api._source_store.get_document("d1")
    assert doc is not None
    doc.file_path = str(file_path)
    await api._source_store.update_document(doc)

    app = build_app(
        api=api,
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # 1. 下载存在的文档
        resp = await client.get("/api/documents/d1/raw")
        assert resp.status == 200
        assert (await resp.read()) == b"pdf data here"
        assert resp.headers["Content-Disposition"] == 'attachment; filename="Doc 1"'

        # 2. 下载不存在的文档
        resp_missing = await client.get("/api/documents/missing-id/raw")
        assert resp_missing.status == 404
        
        # 3. 物理文件缺失的文档
        doc.file_path = "/missing/path.pdf"
        await api._source_store.update_document(doc)
        resp_file_missing = await client.get("/api/documents/d1/raw")
        assert resp_file_missing.status == 404
    finally:
        await client.close()
