"""web/server.py 路由 smoke 测试（aiohttp TestServer + 内存 api）。

验证 HTTP↔core/api 的翻译与认证中间件，不连真实后端。
"""
from __future__ import annotations

from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from core.api import KnowledgeRepositoryApi
from core.config import Config
from core.domain.models import (
    Collection,
    DocumentChunk,
    SourceDocument,
    SyncTargetKind,
)
from core.index_compatibility import IndexCompatibilityStore
from core.plugin_initializer import PluginInitializer
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
        {
            "papers": [
                DocumentChunk(
                    "c0",
                    "d1",
                    0,
                    "alpha beta",
                    "h0",
                    metadata={"page_number": 1, "locator": "page_1_p1", "paragraph": 1},
                )
            ]
        }
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


async def test_upload_moves_staging_file_into_managed_pdf_repository(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    initializer = PluginInitializer(object(), {"vector_db": {"backend": "astr"}}, data_dir)
    await initializer.initialize()
    assert initializer.api is not None

    app = build_app(
        api=initializer.api,
        static_dir=tmp_path / "frontend",
        upload_dir=data_dir / "uploads",
        auth_required=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        pdf_path = tmp_path / "managed.pdf"
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 750), "managed repository upload")
        pdf.save(pdf_path)
        pdf.close()

        form = FormData()
        form.add_field(
            "file",
            pdf_path.read_bytes(),
            filename=pdf_path.name,
            content_type="application/pdf",
        )
        response = await client.post("/api/documents", data=form)
        assert response.status == 200
        doc_id = (await response.json())["doc_id"]

        stored = await initializer.api.get_document(doc_id)
        assert stored is not None
        # 制品包模型：原件落在 library/<document_id>/original.pdf
        assert Path(stored.file_path) == data_dir / "library" / doc_id / "original.pdf"
        assert Path(stored.file_path).exists()
        assert (data_dir / "library" / doc_id / "clean.md").exists()
        assert list((data_dir / "uploads").iterdir()) == []
    finally:
        await client.close()
        await initializer.teardown()


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
        # /api/graph/build 与 /api/graph 已在 v0.15.1 移除 _reserved() 包裹，不再测 501
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
    class StubLightRAGRegistry:
        def has_workspace(self, collection: str) -> bool:
            return collection == "papers"

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks: list[str] | None = None,
            progress_callback=None,
        ) -> None:
            self.inserted = (collection, doc_id, text)

        async def query(self, collection: str, query: str) -> dict:
            return {
                "answer": "LightRAG answer",
                "context": "LightRAG context",
                "collection": collection,
                "engine": "lightrag_core",
                "debug": {"query_mode": "mix"},
            }

    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="papers", description="d"))
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/p/d1.pdf", "application/pdf", 100, "h1", "papers")
    )
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "source text", "ch1")])
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=StubLightRAGRegistry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
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
        estimate = await client.post("/api/graph/build/estimate", json={"collection": "papers"})
        assert estimate.status == 200
        estimate_body = await estimate.json()
        assert "LRAG chunk" in estimate_body["estimate_notice"]
        assert "estimated_lrag_chunks" in estimate_body

        resp1 = await client.post("/api/graph/build", json={"collection": "papers"})
        assert resp1.status == 400
        resp1 = await client.post(
            "/api/graph/build", json={"collection": "papers", "confirmed": True}
        )
        assert resp1.status == 200
        body1 = await resp1.json()
        assert body1["engine"] == "lightrag_core"
        assert body1["collection"] == "papers"
        assert body1["job_id"]

        job_resp = await client.get(f"/api/graph/build/{body1['job_id']}")
        assert job_resp.status == 200
        assert (await job_resp.json())["engine"] == "lightrag_core"

        resp2 = await client.get(
            "/api/graph/query?q=Transformer&top_k=3&debug=true&collection=papers"
        )
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["status"] == "success"
        assert body2["answer"] == "LightRAG answer"
        assert body2["context"] == "LightRAG context"
        assert body2["engine"] == "lightrag_core"
        assert body2["debug"]["query_mode"] == "mix"
    finally:
        await client.close()


async def test_graph_data_endpoint_returns_200(tmp_path: Path) -> None:
    class StubLightRAGRegistry:
        def has_workspace(self, collection: str) -> bool:
            return collection == "papers"

        async def export_graph(self, collection: str) -> dict:
            return {
                "status": "success",
                "collection": collection,
                "nodes": [{"id": "transformer"}, {"id": "attention"}],
                "edges": [{"id": "r1", "source": "transformer", "target": "attention"}],
            }

    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="papers", description="d"))
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/p/d1.pdf", "application/pdf", 100, "h1", "papers", ["t"])
    )
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "source text", "ch1")])
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=StubLightRAGRegistry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
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
        assert len(body["sources"]) > 0
        src = body["sources"][0]
        assert "chunk_id" in src and src["chunk_id"] == "c0"
        assert "doc_id" in src and src["doc_id"] == "d1"
        assert "metadata" in src and src["metadata"]
        assert "locator" in src["metadata"] and src["metadata"]["locator"] == "page_1_p1"
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


async def test_config_update_route(tmp_path: Path) -> None:
    """测试 POST /api/config/update 接口更新配置以及写白名单保护。"""
    api = await _make_api()
    app = build_app(
        api=api,
        static_dir=tmp_path / "frontend",
        upload_dir=tmp_path / "uploads",
        auth_required=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # 1. 成功更新允许的配置键
        resp = await client.post(
            "/api/config/update",
            json={"section": "embedding", "key": "provider", "value": "external"}
        )
        assert resp.status == 200
        assert await resp.json() == {
            "status": "success",
            "restart_required": True,
            "rebuild_required": True,
            "message": "Configuration saved. Restart and rebuild indexes.",
        }

        # 2. 拒绝尚未实现的 AstrBot Embedding 配置，避免保存后静默禁用召回。
        resp_invalid_provider = await client.post(
            "/api/config/update",
            json={"section": "embedding", "key": "provider", "value": "astr"},
        )
        assert resp_invalid_provider.status == 400
        assert "must be 'local' or 'external'" in (
            await resp_invalid_provider.json()
        )["message"]

        # 3a. 机密键即便其所在节（r2_sync）已开放 enabled 开关，也拒绝写入（命中键白名单）。
        resp_secret = await client.post(
            "/api/config/update",
            json={"section": "r2_sync", "key": "secret_access_key", "value": "hack"}
        )
        assert resp_secret.status == 400
        secret_data = await resp_secret.json()
        assert secret_data["status"] == "error"
        assert "not allowed" in secret_data["message"]

        # 3b. 完全只读的配置节仍整节拒绝（命中节白名单）。
        resp_blocked = await client.post(
            "/api/config/update",
            json={"section": "web_console", "key": "password", "value": "hack"}
        )
        assert resp_blocked.status == 400
        data = await resp_blocked.json()
        assert data["status"] == "error"
        assert "write-protected" in data["message"]
    finally:
        await client.close()


async def test_capabilities_route_returns_pipeline_and_dependencies(tmp_path: Path) -> None:
    """GET /api/capabilities 返回环节快照 + 依赖状态 + 诊断。"""
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/capabilities")
        assert resp.status == 200
        data = await resp.json()
        stage_ids = [s["id"] for s in data["pipeline"]]
        assert stage_ids == [
            "ingest", "embedding", "vector_store", "retrieval", "graph", "ask", "sync",
        ]
        assert {d["key"] for d in data["dependencies"]} == {
            "pdf_extract",
            "local_embedding",
            "milvus",
            "lightrag",
            "r2",
        }
        assert isinstance(data["diagnostics"], list)
    finally:
        await client.close()


async def test_zotero_routes_respond(tmp_path: Path) -> None:
    """Zotero 路由：未装配管线时 config 返回结构、pull 返回错误、status 为空。"""
    client = await _client(tmp_path)
    try:
        cfg = await (await client.get("/api/zotero/config")).json()
        assert cfg["enabled"] is False
        assert cfg["sync_mode"] == "conservative"
        assert cfg["storage_mode"] == "managed_copy"

        pull = await (await client.post("/api/sync/zotero/pull", json={})).json()
        assert pull["status"] == "error"  # 未启用/未装配

        status = await (await client.get("/api/sync/zotero/status")).json()
        assert status == {}
    finally:
        await client.close()


async def test_dependencies_route_lists_optional_packages(tmp_path: Path) -> None:
    """GET /api/dependencies 列出可选依赖与安装状态。"""
    client = await _client(tmp_path)
    try:
        resp = await client.get("/api/dependencies")
        assert resp.status == 200
        deps = (await resp.json())["dependencies"]
        milvus = next(d for d in deps if d["key"] == "milvus")
        assert milvus["pip_spec"] == "pymilvus[milvus_lite]>=2.5,<3.0"
        assert "installed" in milvus
    finally:
        await client.close()


async def test_dependency_install_rejects_unlisted_package(tmp_path: Path) -> None:
    """POST /api/dependencies/install 拒绝白名单外包名（防注入），不触发 pip。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post(
            "/api/dependencies/install", json={"package": "evil; rm -rf /"}
        )
        assert resp.status == 400
        assert (await resp.json())["status"] == "error"

        missing = await client.post("/api/dependencies/install", json={})
        assert missing.status == 400
    finally:
        await client.close()


async def test_dependency_recheck_returns_fresh_state(tmp_path: Path) -> None:
    """POST /api/dependencies/recheck 重新探测并返回最新状态。"""
    client = await _client(tmp_path)
    try:
        resp = await client.post("/api/dependencies/recheck")
        assert resp.status == 200
        data = await resp.json()
        assert "dependencies" in data
    finally:
        await client.close()


async def test_ask_route_sources_contain_locator_fields(tmp_path: Path) -> None:
    """POST /api/ask 返回的 sources 每条应包含 chunk_id/doc_id/metadata 字段。"""
    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="papers", description="d"))
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/p/d1.pdf", "application/pdf", 100, "h1", "papers", [])
    )
    locator_meta = {"page_number": 3, "locator": "page_3_p2", "paragraph": 2}
    kb = InMemoryKnowledgeBaseReader(
        {"papers": [DocumentChunk("c0", "d1", 0, "alpha beta", "h0", metadata=locator_meta)]}
    )
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        sync_targets={},
        config=Config({}),
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
        resp = await client.post(
            "/api/ask",
            json={"question": "alpha beta", "collection": "papers"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["sources"], "sources 不应为空"
        src = body["sources"][0]
        assert "chunk_id" in src, "sources[0] 缺少 chunk_id"
        assert "doc_id" in src, "sources[0] 缺少 doc_id"
        assert "metadata" in src, "sources[0] 缺少 metadata"
        assert src["chunk_id"] == "c0"
        assert src["doc_id"] == "d1"
        assert src["metadata"]["page_number"] == 3
        assert src["metadata"]["locator"] == "page_3_p2"
    finally:
        await client.close()


async def test_log_event_endpoint_records_frontend_toast(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        resp = await client.post(
            "/api/logs/events",
            json={"type": "ok", "message": "已保存", "route": "/settings"},
        )
        assert resp.status == 200

        logs = await (await client.get("/api/logs?after=0&limit=20")).json()
        toast = next(line for line in logs["lines"] if line.get("category") == "toast")
        assert toast["source"] == "frontend"
        assert toast["operation"] == "notify"
        assert toast["status"] == "ok"
        assert toast["metadata"]["route"] == "/settings"
    finally:
        await client.close()


async def test_high_precision_ask_returns_structured_not_ready(tmp_path: Path) -> None:
    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return False

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument("d1", "Doc 1", "/d1.pdf", "application/pdf", 1, "h", "papers")
    )
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
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
        resp = await client.post(
            "/api/ask",
            json={
                "question": "q",
                "collection": "papers",
                "retrieval_mode": "high_precision",
            },
        )
        assert resp.status == 409
        assert await resp.json() == {
            "status": "lightrag_not_ready",
            "message": "LightRAG workspace has not been built.",
            "collection": "papers",
            "build_available": True,
        }
    finally:
        await client.close()


async def test_metrics_route(tmp_path: Path) -> None:
    """GET /api/metrics 应返回 ops + total_records 结构。"""
    from core.ask_progress import ProgressStore
    from core.metrics import PerformanceTracker

    tracker = PerformanceTracker()
    tracker.record("embed_query", 100.0)
    tracker.record("ask_total", 1500.0)

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        metrics=tracker,
        progress_store=ProgressStore(),
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
        resp = await client.get("/api/metrics")
        assert resp.status == 200
        body = await resp.json()
        assert "ops" in body
        assert "total_records" in body
        assert body["total_records"] == 2
        assert "embed_query" in body["ops"]
        assert body["ops"]["embed_query"]["count"] == 1
    finally:
        await client.close()


async def test_ask_progress_route_not_found(tmp_path: Path) -> None:
    """GET /api/ask/progress/{cid} — 不存在的 cid 应返回 404。"""
    from core.ask_progress import ProgressStore
    from core.metrics import PerformanceTracker

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        metrics=PerformanceTracker(),
        progress_store=ProgressStore(),
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
        resp = await client.get("/api/ask/progress/nonexistent-cid")
        assert resp.status == 404
    finally:
        await client.close()


async def test_ask_progress_route_found(tmp_path: Path) -> None:
    """GET /api/ask/progress/{cid} — 已设置进度时应返回 stage + pct。"""
    from core.ask_progress import ProgressStore
    from core.metrics import PerformanceTracker

    progress_store = ProgressStore()
    progress_store.set("test-cid-123", "vector_search", 20)

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        metrics=PerformanceTracker(),
        progress_store=progress_store,
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
        resp = await client.get("/api/ask/progress/test-cid-123")
        assert resp.status == 200
        body = await resp.json()
        assert body["stage"] == "vector_search"
        assert body["pct"] == 20
    finally:
        await client.close()


async def test_graph_data_requires_lightrag(tmp_path: Path) -> None:
    """GET /api/graph 在未配置 LightRAG 时返回运行态未就绪状态。"""
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
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
        resp = await client.get("/api/graph")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "not_ready"
        assert body["ready"] is False
        assert body["build_available"] is False
        assert "LightRAG Core" in body["reason"]
    finally:
        await client.close()


async def test_graph_stats_route(tmp_path: Path) -> None:
    """GET /api/graph/stats 应返回 entities_count / relations_count / collections_covered。"""
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
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
        resp = await client.get("/api/graph/stats")
        assert resp.status == 200
        body = await resp.json()
        assert "entities_count" in body
        assert "relations_count" in body
        assert "collections_covered" in body
        assert isinstance(body["entities_count"], int)
    finally:
        await client.close()
