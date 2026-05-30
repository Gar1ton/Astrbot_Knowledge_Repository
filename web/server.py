"""HTTP 路由与 WebUI 服务（见 web/README.md 与 ../ARCHITECTURE.md §7）。

只做 HTTP↔业务的翻译：解析请求 → 调 `core/api` → 序列化响应。零业务逻辑。
认证经中间件统一处理；静态前端由 `static_dir` 托管（生产指向 pages/，调试指向 web/frontend/）。

依赖经 build_app 注入（api 门面 + 配置），自身不构造依赖。
"""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from core.api import KnowledgeRepositoryApi

# ── 常量 ────────────────────────────────────────────────────────

SESSION_COOKIE = "kr_session"
_API_PREFIX = "/api/"
_PUBLIC_PATHS = frozenset({"/api/login", "/api/auth"})


# ── 中间件：认证 ────────────────────────────────────────────────


@web.middleware
async def _auth_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    """保护 /api/*（登录/鉴权探测除外）；auth_required=False 时直接放行。"""
    app = request.app
    if not app["auth_required"]:
        return await handler(request)
    path = request.path
    if path.startswith(_API_PREFIX) and path not in _PUBLIC_PATHS:
        token = request.cookies.get(SESSION_COOKIE)
        if token not in app["sessions"]:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


# ── 路由处理 ────────────────────────────────────────────────────


def _api(request: web.Request) -> KnowledgeRepositoryApi:
    return request.app["api"]


async def handle_auth(request: web.Request) -> web.Response:
    """前端探测是否需要登录 / 当前是否已登录。"""
    app = request.app
    logged_in = (
        not app["auth_required"]
        or request.cookies.get(SESSION_COOKIE) in app["sessions"]
    )
    return web.json_response({"auth_required": app["auth_required"], "logged_in": logged_in})


async def handle_login(request: web.Request) -> web.Response:
    app = request.app
    body = await request.json()
    if body.get("username") == app["username"] and body.get("password") == app["password"]:
        token = secrets.token_urlsafe(24)
        app["sessions"].add(token)
        resp = web.json_response({"ok": True})
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax")
        return resp
    return web.json_response({"error": "invalid credentials"}, status=401)


async def handle_list_collections(request: web.Request) -> web.Response:
    cols = await _api(request).list_collections()
    return web.json_response([_collection_dict(c) for c in cols])


async def handle_create_collection(request: web.Request) -> web.Response:
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    await _api(request).create_collection(name, body.get("description", ""))
    return web.json_response({"ok": True})


async def handle_delete_collection(request: web.Request) -> web.Response:
    ok = await _api(request).delete_collection(request.match_info["name"])
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def handle_list_documents(request: web.Request) -> web.Response:
    collection = request.query.get("collection") or None
    tag = request.query.get("tag") or None
    docs = await _api(request).list_documents(collection=collection, tag=tag)
    return web.json_response([_document_dict(d) for d in docs])


async def handle_upload_document(request: web.Request) -> web.Response:
    """multipart 上传：保存原件 → 计算 sha256/大小 → 登记。预览级，真实抽取在 v0.3.0。"""
    reader = await request.multipart()
    collection = "default"
    tags: list[str] = []
    filename = "upload.bin"
    content_type = "application/octet-stream"
    payload = b""
    async for part in reader:
        if part.name == "file":
            filename = part.filename or filename
            content_type = part.headers.get("Content-Type", content_type)
            payload = await part.read(decode=False)
        elif part.name == "collection":
            collection = (await part.text()).strip() or "default"
        elif part.name == "tags":
            tags = [t.strip() for t in (await part.text()).split(",") if t.strip()]
    if not payload:
        return web.json_response({"error": "empty file"}, status=400)

    upload_dir: Path = request.app["upload_dir"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(payload).hexdigest()
    dest = upload_dir / f"{content_hash[:16]}_{filename}"
    dest.write_bytes(payload)

    doc_id = await _api(request).register_document(
        title=filename,
        file_path=str(dest),
        content_type=content_type,
        size_bytes=len(payload),
        content_hash=content_hash,
        collection=collection,
        tags=tags,
    )
    return web.json_response({"ok": True, "doc_id": doc_id})


async def handle_classify_document(request: web.Request) -> web.Response:
    body = await request.json()
    tags = body.get("tags")
    ok = await _api(request).classify_document(
        request.match_info["doc_id"],
        collection=body.get("collection"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else None,
    )
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def handle_delete_document(request: web.Request) -> web.Response:
    ok = await _api(request).delete_document(request.match_info["doc_id"])
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def handle_kb_collections(request: web.Request) -> web.Response:
    return web.json_response(await _api(request).list_kb_collections())


async def handle_kb_search(request: web.Request) -> web.Response:
    collection = request.query.get("collection", "")
    query = request.query.get("q", "")
    top_k = int(request.query.get("top_k", "5"))
    chunks = await _api(request).search_kb(collection, query, top_k)
    return web.json_response([_chunk_dict(c) for c in chunks])


async def handle_quota(request: web.Request) -> web.Response:
    usages = await _api(request).list_quota()
    return web.json_response([_quota_dict(u) for u in usages])


# ── 预留端口路由（Reserved）──────────────────────────────────────
#
# 这些路由对应 core/api 的预留方法。现在就在 URL 层把「插座」装好，前端据此预留入口。
# 统一用 _reserved() 包裹：方法已实现则正常返回，未实现（NotImplementedError）则回 501 +
# available_in，使前端可显示「将在 vX.Y.0 接入」而无需改动布局。


async def _reserved(coro, available_in: str) -> web.Response:
    """执行预留方法；NotImplementedError → 501 + 结构化提示，其它异常照常上抛。"""
    try:
        result = await coro
    except NotImplementedError as exc:
        return web.json_response(
            {"status": "reserved", "available_in": available_in, "detail": str(exc)},
            status=501,
        )
    return web.json_response(result)


async def handle_sync(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    target = request.match_info.get("target", "all")
    doc_ids = body.get("doc_ids") if isinstance(body, dict) else None
    return await _reserved(_api(request).sync_documents(target, doc_ids), "v0.3.0 / v0.4.0")


async def handle_notion_init(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    parent_page_id = body.get("parent_page_id") if isinstance(body, dict) else None
    database_title = body.get("database_title") if isinstance(body, dict) else None
    return await _reserved(
        _api(request).initialize_notion_database(parent_page_id, database_title),
        "v0.8.0",
    )


async def handle_notion_pull(request: web.Request) -> web.Response:
    return await _reserved(_api(request).pull_notion_metadata(), "v0.8.0")


async def handle_effective_config(request: web.Request) -> web.Response:
    return await _reserved(_api(request).get_effective_config(), "v0.8.0")


async def handle_sync_status(request: web.Request) -> web.Response:
    return await _reserved(_api(request).get_sync_status(), "v0.3.0")


async def handle_backup(request: web.Request) -> web.Response:
    return await _reserved(_api(request).backup_now(), "v0.3.0")


async def handle_restore(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    snapshot = body.get("snapshot") if isinstance(body, dict) else None
    return await _reserved(_api(request).restore_from_backup(snapshot), "v0.3.0")


async def handle_graph_build(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    collection = body.get("collection") if isinstance(body, dict) else None
    return await _reserved(_api(request).build_graph(collection), "v0.6.0")


async def handle_graph_query(request: web.Request) -> web.Response:
    query = request.query.get("q", "")
    top_k = int(request.query.get("top_k", "5"))
    collection = request.query.get("collection") or None
    debug = request.query.get("debug", "").lower() in {"1", "true", "yes", "on"}
    return await _reserved(
        _api(request).query_graph(query, top_k, collection=collection, debug=debug),
        "v0.6.0",
    )


async def handle_graph_data(request: web.Request) -> web.Response:
    collection = request.query.get("collection") or None
    return await _reserved(_api(request).get_graph(collection), "v0.7.0")


# ── 序列化 helper（domain → JSON-safe dict）─────────────────────


def _collection_dict(c: object) -> dict:
    return {"name": c.name, "description": c.description}  # type: ignore[attr-defined]


def _document_dict(d: object) -> dict:
    return {
        "doc_id": d.doc_id,                  # type: ignore[attr-defined]
        "title": d.title,                    # type: ignore[attr-defined]
        "content_type": d.content_type,      # type: ignore[attr-defined]
        "size_bytes": d.size_bytes,          # type: ignore[attr-defined]
        "collection": d.collection,          # type: ignore[attr-defined]
        "tags": d.tags,                      # type: ignore[attr-defined]
        "content_hash": d.content_hash,      # type: ignore[attr-defined]
    }


def _chunk_dict(c: object) -> dict:
    return {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "ordinal": c.ordinal, "text": c.text}  # type: ignore[attr-defined]


def _quota_dict(u: object) -> dict:
    return {
        "target": u.target.value,            # type: ignore[attr-defined]
        "used_bytes": u.used_bytes,          # type: ignore[attr-defined]
        "limit_bytes": u.limit_bytes,        # type: ignore[attr-defined]
        "ratio": round(u.ratio, 4),          # type: ignore[attr-defined]
        "detail": u.detail,                  # type: ignore[attr-defined]
    }


# ── 应用装配 ────────────────────────────────────────────────────


def build_app(
    *,
    api: KnowledgeRepositoryApi,
    static_dir: Path,
    upload_dir: Path,
    auth_required: bool = True,
    username: str = "admin",
    password: str = "",
) -> web.Application:
    """构造 aiohttp 应用：注入 api、配置认证与静态目录。

    auth_required=True 且 password 为空时拒绝构造（避免无密码暴露）。
    """
    if auth_required and not password:
        raise ValueError(
            "web console password is empty; set a password or pass auth_required=False"
        )

    app = web.Application(middlewares=[_auth_middleware])
    app["api"] = api
    app["upload_dir"] = upload_dir
    app["auth_required"] = auth_required
    app["username"] = username
    app["password"] = password
    app["sessions"] = set()

    app.router.add_get("/api/auth", handle_auth)
    app.router.add_post("/api/login", handle_login)
    app.router.add_get("/api/collections", handle_list_collections)
    app.router.add_post("/api/collections", handle_create_collection)
    app.router.add_delete("/api/collections/{name}", handle_delete_collection)
    app.router.add_get("/api/documents", handle_list_documents)
    app.router.add_post("/api/documents", handle_upload_document)
    app.router.add_patch("/api/documents/{doc_id}", handle_classify_document)
    app.router.add_delete("/api/documents/{doc_id}", handle_delete_document)
    app.router.add_get("/api/kb/collections", handle_kb_collections)
    app.router.add_get("/api/kb/search", handle_kb_search)
    app.router.add_get("/api/quota", handle_quota)
    app.router.add_get("/api/config/effective", handle_effective_config)
    # 预留端口（reserved，未实现回 501 + available_in）
    app.router.add_post("/api/sync/{target}", handle_sync)
    app.router.add_post("/api/notion/init", handle_notion_init)
    app.router.add_post("/api/sync/notion/pull", handle_notion_pull)
    app.router.add_get("/api/sync/status", handle_sync_status)
    app.router.add_post("/api/backup", handle_backup)
    app.router.add_post("/api/restore", handle_restore)
    app.router.add_post("/api/graph/build", handle_graph_build)
    app.router.add_get("/api/graph/query", handle_graph_query)
    app.router.add_get("/api/graph", handle_graph_data)

    async def index(_: web.Request) -> web.StreamResponse:
        return web.FileResponse(static_dir / "index.html")

    app.router.add_get("/", index)
    if static_dir.exists():
        app.router.add_static("/static/", static_dir)
    return app


__all__ = ["build_app", "SESSION_COOKIE"]
