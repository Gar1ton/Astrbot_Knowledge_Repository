"""HTTP 路由与 WebUI 服务（见 web/README.md 与 ../ARCHITECTURE.md §7）。

只做 HTTP↔业务的翻译：解析请求 → 调 `core/api` → 序列化响应。零业务逻辑。
认证经中间件统一处理；静态前端由 `static_dir` 托管（生产指向 pages/，调试指向 web/frontend/）。

依赖经 build_app 注入（api 门面 + 配置），自身不构造依赖。
"""

from __future__ import annotations

import hashlib
import logging as _logging
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from core.api import KnowledgeRepositoryApi
    from core.log_capture import MemoryLogHandler

# ── 常量 ────────────────────────────────────────────────────────

SESSION_COOKIE = "kr_session"
_API_PREFIX = "/api/"
_PUBLIC_PATHS = frozenset({"/api/login", "/api/auth"})


# ── 中间件 ──────────────────────────────────────────────────────

_mw_logger = _logging.getLogger("KRWebServer")


@web.middleware
async def _error_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    """将所有未捕获异常转为 JSON 500，确保 API 始终返回结构化响应。"""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        _mw_logger.error(
            "Unhandled error [%s %s]: %s",
            request.method,
            request.path,
            exc,
            exc_info=True,
        )
        return web.json_response({"error": str(exc)}, status=500)


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
    logged_in = not app["auth_required"] or request.cookies.get(SESSION_COOKIE) in app["sessions"]
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


async def handle_logout(request: web.Request) -> web.Response:
    app = request.app
    token = request.cookies.get(SESSION_COOKIE)
    if token in app["sessions"]:
        app["sessions"].remove(token)
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESSION_COOKIE)
    return resp


async def handle_list_collections(request: web.Request) -> web.Response:
    cols = await _api(request).list_collections()
    return web.json_response([_collection_dict(c) for c in cols])


async def handle_create_collection(request: web.Request) -> web.Response:
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "name required"}, status=400)
    description = body.get("description", "")
    await _api(request).create_collection(name, description)
    return web.json_response({"name": name, "description": description})


async def handle_delete_collection(request: web.Request) -> web.Response:
    try:
        ok = await _api(request).delete_collection(request.match_info["name"])
    except ValueError as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=400)
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def handle_list_documents(request: web.Request) -> web.Response:
    collection = request.query.get("collection") or None
    tag = request.query.get("tag") or None
    docs = await _api(request).list_documents(collection=collection, tag=tag)
    return web.json_response([await _document_dict(_api(request), d) for d in docs])


async def handle_upload_document(request: web.Request) -> web.Response:
    """multipart 上传：暂存 → 计算 sha256/大小 → 摄入插件托管原件库。"""
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

    _mw_logger.info("Upload: file=%r size=%d collection=%r", filename, len(payload), collection)
    upload_dir: Path = request.app["upload_dir"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(payload).hexdigest()
    dest = upload_dir / f"{content_hash[:16]}_{filename}"
    dest.write_bytes(payload)

    try:
        doc_id = await _api(request).register_document(
            title=filename,
            file_path=str(dest),
            content_type=content_type,
            size_bytes=len(payload),
            content_hash=content_hash,
            collection=collection,
            tags=tags,
        )
    except Exception as exc:
        dest.unlink(missing_ok=True)
        _mw_logger.error("Upload failed for %r: %s", filename, exc, exc_info=True)
        return web.json_response({"error": str(exc)}, status=500)
    doc = await _api(request).get_document(doc_id)
    if doc is None:
        dest.unlink(missing_ok=True)
        return web.json_response({"error": "document registration failed"}, status=500)
    try:
        if Path(doc.file_path).resolve() != dest.resolve():
            dest.unlink(missing_ok=True)
    except OSError as exc:
        _mw_logger.warning("Failed to remove upload staging file %s: %s", dest, exc)
    return web.json_response(await _document_dict(_api(request), doc))


async def handle_classify_document(request: web.Request) -> web.Response:
    body = await request.json()
    tags = body.get("tags")
    ok = await _api(request).classify_document(
        request.match_info["doc_id"],
        collection=body.get("collection"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else None,
    )
    if not ok:
        return web.json_response({"error": "document not found"}, status=404)
    doc = await _api(request).get_document(request.match_info["doc_id"])
    if doc is None:
        return web.json_response({"error": "document not found"}, status=404)
    return web.json_response(await _document_dict(_api(request), doc))


async def handle_delete_document(request: web.Request) -> web.Response:
    doc_id = request.match_info["doc_id"]
    _mw_logger.info("Delete document: doc_id=%s", doc_id)
    ok = await _api(request).delete_document(doc_id)
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def handle_download_document(request: web.Request) -> web.StreamResponse:
    doc_id = request.match_info["doc_id"]
    doc = await _api(request).get_document(doc_id)
    if doc is None:
        return web.json_response({"error": "document not found"}, status=404)
    file_path = Path(doc.file_path)
    if not file_path.is_file():
        return web.json_response({"error": "file not found on disk"}, status=404)
    return web.FileResponse(
        file_path,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.title}"',
        },
    )


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
            {
                "status": "reserved",
                "reserved": True,
                "available_in": available_in,
                "detail": str(exc),
            },
            status=501,
        )
    return web.json_response(result)


async def handle_sync(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    target = request.match_info.get("target", "all")
    doc_ids = body.get("doc_ids") if isinstance(body, dict) else None
    _mw_logger.info("Sync requested: target=%s", target)
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


async def handle_update_config(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    if not isinstance(body, dict):
        return web.json_response({"status": "error", "message": "Invalid JSON body"}, status=400)
    section = body.get("section")
    key = body.get("key")
    value = body.get("value")
    if not section or not key:
        return web.json_response(
            {"status": "error", "message": "Missing section or key"}, status=400
        )

    _mw_logger.info("Config update: section=%s key=%s", section, key)

    async def _update():
        return await _api(request).update_config_value(section, key, value)

    try:
        resp = await _reserved(_update(), "v0.10.0")
        _mw_logger.info("Config update success: %s.%s", section, key)
        return resp
    except ValueError as exc:
        _mw_logger.warning("Config update rejected [%s.%s]: %s", section, key, exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=400)


async def handle_rebuild_index_pending(request: web.Request) -> web.Response:
    _mw_logger.info("Index rebuild requested")
    try:
        result = await _api(request).rebuild_index_pending()
        _mw_logger.info("Index rebuild completed: %s", result)
        return web.json_response({"status": "ok", **result})
    except RuntimeError as exc:
        _mw_logger.error("Index rebuild failed: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=503)


async def handle_pending_reindex_count(request: web.Request) -> web.Response:
    count = await _api(request).get_pending_reindex_count()
    return web.json_response({"count": count})


async def handle_test_embedding(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    base_url = body.get("base_url", "https://api.openai.com/v1")
    model_name = body.get("model_name", "")
    result = await _api(request).test_embedding_connection(base_url, model_name)
    return web.json_response(result)


async def handle_sync_status(request: web.Request) -> web.Response:
    return await _reserved(_api(request).get_sync_status(), "v0.3.0")


async def handle_backup(request: web.Request) -> web.Response:
    return await _reserved(_api(request).backup_now(), "v0.3.0")


async def handle_restore(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    snapshot = body.get("snapshot") if isinstance(body, dict) else None
    return await _reserved(_api(request).restore_from_backup(snapshot), "v0.3.0")


async def handle_graph_build_estimate(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    collection = body.get("collection") if isinstance(body, dict) else None
    try:
        result = await _api(request).estimate_graph_build(collection)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def handle_graph_build(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    collection = body.get("collection") if isinstance(body, dict) else None
    confirmed = bool(body.get("confirmed")) if isinstance(body, dict) else False
    _mw_logger.info("Graph build requested: collection=%r confirmed=%s", collection, confirmed)
    try:
        result = await _api(request).build_graph(collection, confirmed=confirmed)
        return web.json_response(result)
    except ValueError as exc:
        _mw_logger.warning("Graph build rejected: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=400)
    except NotImplementedError as exc:
        return web.json_response(
            {
                "status": "reserved",
                "reserved": True,
                "available_in": "v0.16.0+ LightRAG Core",
                "detail": str(exc),
            },
            status=501,
        )
    except Exception as exc:
        _mw_logger.error("Graph build failed: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def handle_graph_build_job(request: web.Request) -> web.Response:
    result = await _api(request).get_graph_build_job(request.match_info["job_id"])
    if result is None:
        return web.json_response({"status": "error", "message": "job not found"}, status=404)
    return web.json_response(result)


async def handle_graph_probe(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else {}
    if not isinstance(body, dict) or body.get("confirmed") is not True:
        return web.json_response(
            {"status": "error", "message": "LightRAG probe requires confirmed=true"}, status=400
        )
    collection = body.get("collection") or "default"
    text = (
        (body.get("text") or "LightRAG probe document for Knowledge Repository.")
        if isinstance(body, dict)
        else "LightRAG probe document for Knowledge Repository."
    )
    doc_id = (
        (body.get("doc_id") or "kr-lightrag-probe-doc")
        if isinstance(body, dict)
        else "kr-lightrag-probe-doc"
    )
    query = (
        (body.get("query") or "What is this probe document about?")
        if isinstance(body, dict)
        else "What is this probe document about?"
    )
    try:
        result = await _api(request).probe_lightrag_core(collection, text, doc_id, query)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def handle_graph_query(request: web.Request) -> web.Response:
    query = request.query.get("q", "")
    top_k = int(request.query.get("top_k", "5"))
    collection = request.query.get("collection") or None
    debug = request.query.get("debug", "").lower() in {"1", "true", "yes", "on"}
    response = await _reserved(
        _api(request).query_graph(query, top_k, collection=collection, debug=debug),
        "v0.6.0",
    )
    if response.status == 200:
        response = web.json_response(_graph_query_dict(response.body))
    return response


async def handle_graph_data(request: web.Request) -> web.Response:
    collection = request.query.get("collection") or None
    try:
        result = await _api(request).get_graph(collection)
        return web.json_response(result)
    except NotImplementedError as exc:
        return web.json_response(
            {
                "status": "reserved",
                "reserved": True,
                "available_in": "v0.16.0+ LightRAG Core",
                "detail": str(exc),
            },
            status=501,
        )
    except Exception as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def handle_graph_stats(request: web.Request) -> web.Response:
    """GET /api/graph/stats — 图谱摘要统计（实体数、关系数、涉及集合数）。"""
    try:
        result = await _api(request).get_graph_stats()
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def handle_metrics(request: web.Request) -> web.Response:
    """GET /api/metrics — 近期操作延迟聚合（供性能监控面板使用）。"""
    summary = _api(request).get_metrics_summary()
    return web.json_response(summary)


async def handle_ask_progress(request: web.Request) -> web.Response:
    """GET /api/ask/progress/{cid} — 轮询指定对话的召回进度。"""
    cid = request.match_info.get("cid", "")
    progress = _api(request).get_ask_progress(cid)
    if progress is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(progress)


async def handle_system_info(request: web.Request) -> web.Response:
    """GET /api/system/info — 返回后端运行环境信息（调试面板用）。"""
    try:
        return web.json_response(_api(request).get_system_info())
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_files_list(request: web.Request) -> web.Response:
    """GET /api/files/list?dir=<subdir> — 列出 data_dir 内文件（路径穿越防护）。"""
    subdir = request.query.get("dir", "")
    try:
        return web.json_response(_api(request).list_data_files(subdir))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_list_local_models(request: web.Request) -> web.Response:
    """GET /api/models/local — 列出 HuggingFace 缓存中的本地模型。"""
    try:
        return web.json_response(_api(request).list_local_embedding_models())
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_delete_local_model(request: web.Request) -> web.Response:
    """DELETE /api/models/local/{name} — 删除本地缓存模型（name 经 URL 编码）。"""
    from urllib.parse import unquote

    raw = request.match_info.get("name", "")
    model_name = unquote(raw)
    try:
        result = _api(request).delete_local_embedding_model(model_name)
        return web.json_response(result)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_logs(request: web.Request) -> web.Response:
    """GET /api/logs?after=<float>&limit=<int> — 返回内存日志缓冲区中的最新日志行。"""
    handler: MemoryLogHandler | None = request.app.get("log_handler")
    if handler is None:
        return web.json_response({"lines": [], "server_ts": time.time()})
    try:
        after_ts = float(request.query.get("after", "0"))
        limit = min(int(request.query.get("limit", "200")), 500)
    except ValueError:
        return web.json_response({"error": "invalid params"}, status=400)
    lines = handler.get_lines(after_ts=after_ts, limit=limit)
    return web.json_response({"lines": lines, "server_ts": time.time()})


async def handle_ask(request: web.Request) -> web.Response:
    """POST /api/ask — Ask Agent：检索 + LLM 答案生成。"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    question = (body.get("question") or "").strip()
    if not question:
        return web.json_response({"error": "question required"}, status=400)
    collection = body.get("collection") or None
    top_k = int(body.get("top_k") or 5)
    conversation_id = body.get("conversation_id") or None
    persona_enabled = bool(body.get("persona_enabled") or False)
    retrieval_mode = body.get("retrieval_mode") or "default"
    from core.api import HighPrecisionQueryError, LightRAGNotReadyError

    try:
        result = await _api(request).ask(
            question=question,
            collection=collection,
            top_k=max(1, min(top_k, 20)),
            conversation_id=conversation_id,
            persona_enabled=persona_enabled,
            retrieval_mode=retrieval_mode,
        )
    except LightRAGNotReadyError as exc:
        return web.json_response(
            {
                "status": "lightrag_not_ready",
                "message": exc.reason,
                "collection": exc.collection,
                "build_available": exc.build_available,
            },
            status=409,
        )
    except HighPrecisionQueryError as exc:
        return web.json_response(
            {
                "status": "high_precision_failed",
                "message": exc.reason,
                "collection": exc.collection,
            },
            status=502,
        )
    except ValueError as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=400)
    return web.json_response(result)


# ── 序列化 helper（domain → JSON-safe dict）─────────────────────


def _collection_dict(c: object) -> dict:
    from core.api import SYSTEM_COLLECTION_UNCATEGORIZED

    return {
        "name": c.name,  # type: ignore[attr-defined]
        "description": c.description,  # type: ignore[attr-defined]
        "is_system": c.name == SYSTEM_COLLECTION_UNCATEGORIZED,  # type: ignore[attr-defined]
    }


async def _document_dict(api: KnowledgeRepositoryApi, d: object) -> dict:
    chunks = await api.list_document_chunks(d.doc_id)  # type: ignore[attr-defined]
    lightrag_status = await api.get_lightrag_index_status(d.doc_id)  # type: ignore[attr-defined]
    updated_at = d.updated_at.isoformat() if d.updated_at else None  # type: ignore[attr-defined]
    filename = Path(d.file_path).name  # type: ignore[attr-defined]
    ext = Path(filename).suffix.lstrip(".").lower()
    return {
        "doc_id": d.doc_id,  # type: ignore[attr-defined]
        "title": d.title,  # type: ignore[attr-defined]
        "filename": filename,
        "content_type": d.content_type,  # type: ignore[attr-defined]
        "size_bytes": d.size_bytes,  # type: ignore[attr-defined]
        "size": d.size_bytes,  # type: ignore[attr-defined]
        "collection": d.collection,  # type: ignore[attr-defined]
        "tags": d.tags,  # type: ignore[attr-defined]
        "content_hash": d.content_hash,  # type: ignore[attr-defined]
        "chunks": len(chunks),
        "updated_at": updated_at,
        "updated": updated_at,
        "ext": ext,
        "needs_reindex": getattr(d, "needs_reindex", False),
        "lightrag_index_status": lightrag_status,
    }


def _chunk_dict(c: object) -> dict:
    return {
        "chunk_id": c.chunk_id,  # type: ignore[attr-defined]
        "doc_id": c.doc_id,  # type: ignore[attr-defined]
        "ordinal": c.ordinal,  # type: ignore[attr-defined]
        "text": c.text,  # type: ignore[attr-defined]
        "metadata": getattr(c, "metadata", {}),
    }


def _quota_dict(u: object) -> dict:
    return {
        "target": u.target.value,  # type: ignore[attr-defined]
        "used_bytes": u.used_bytes,  # type: ignore[attr-defined]
        "limit_bytes": u.limit_bytes,  # type: ignore[attr-defined]
        "ratio": round(u.ratio, 4),  # type: ignore[attr-defined]
        "detail": u.detail,  # type: ignore[attr-defined]
    }


def _graph_query_dict(payload: bytes) -> dict:
    """把业务门面的图谱查询字段翻译为 WebUI 稳定模型。"""
    import json

    body = json.loads(payload)
    body["entities"] = [
        {
            "id": ent["entity_id"],
            "name": ent["name"],
            "type": ent.get("entity_type", ""),
            "description": ent.get("description", ""),
            "degree": ent.get("degree", 0),
            "source_chunk_ids": ent.get("source_chunk_ids", []),
        }
        for ent in body.get("entities", [])
    ]
    body["relations"] = [
        {
            "id": rel["relation_id"],
            "source": rel["src_entity_id"],
            "target": rel["dst_entity_id"],
            "relation": rel["relation"],
            "description": rel.get("description", ""),
            "weight": rel.get("weight", 1.0),
            "source_chunk_ids": rel.get("source_chunk_ids", []),
        }
        for rel in body.get("relations", [])
    ]
    return body


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

    app = web.Application(middlewares=[_error_middleware, _auth_middleware])
    app["api"] = api
    app["upload_dir"] = upload_dir
    app["auth_required"] = auth_required
    app["username"] = username
    app["password"] = password
    app["sessions"] = set()

    app.router.add_get("/api/auth", handle_auth)
    app.router.add_post("/api/login", handle_login)
    app.router.add_post("/api/logout", handle_logout)
    app.router.add_get("/api/collections", handle_list_collections)
    app.router.add_post("/api/collections", handle_create_collection)
    app.router.add_delete("/api/collections/{name}", handle_delete_collection)
    app.router.add_get("/api/documents", handle_list_documents)
    app.router.add_post("/api/documents", handle_upload_document)
    app.router.add_patch("/api/documents/{doc_id}", handle_classify_document)
    app.router.add_delete("/api/documents/{doc_id}", handle_delete_document)
    app.router.add_get("/api/documents/{doc_id}/raw", handle_download_document)
    app.router.add_get("/api/kb/collections", handle_kb_collections)
    app.router.add_get("/api/kb/search", handle_kb_search)
    app.router.add_get("/api/quota", handle_quota)
    app.router.add_get("/api/config/effective", handle_effective_config)
    app.router.add_post("/api/config/update", handle_update_config)
    app.router.add_post("/api/config/test-embedding", handle_test_embedding)
    app.router.add_post("/api/documents/rebuild-index", handle_rebuild_index_pending)
    app.router.add_get("/api/documents/pending-reindex-count", handle_pending_reindex_count)
    # 预留端口（reserved，未实现回 501 + available_in）
    app.router.add_post("/api/sync/{target}", handle_sync)
    app.router.add_post("/api/notion/init", handle_notion_init)
    app.router.add_post("/api/sync/notion/pull", handle_notion_pull)
    app.router.add_get("/api/sync/status", handle_sync_status)
    app.router.add_post("/api/backup", handle_backup)
    app.router.add_post("/api/restore", handle_restore)
    app.router.add_post("/api/graph/build/estimate", handle_graph_build_estimate)
    app.router.add_post("/api/graph/build", handle_graph_build)
    app.router.add_get("/api/graph/build/{job_id}", handle_graph_build_job)
    app.router.add_post("/api/graph/probe", handle_graph_probe)
    app.router.add_get("/api/graph/query", handle_graph_query)
    app.router.add_get("/api/graph/stats", handle_graph_stats)
    app.router.add_get("/api/graph", handle_graph_data)
    app.router.add_get("/api/metrics", handle_metrics)
    app.router.add_get("/api/ask/progress/{cid}", handle_ask_progress)
    app.router.add_get("/api/system/info", handle_system_info)
    app.router.add_get("/api/files/list", handle_files_list)
    app.router.add_get("/api/models/local", handle_list_local_models)
    app.router.add_delete("/api/models/local/{name}", handle_delete_local_model)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_post("/api/ask", handle_ask)

    # 安装内存日志 handler（幂等，重复调用安全）
    from core.log_capture import install as _install_log_handler

    app["log_handler"] = _install_log_handler(maxlen=500)

    # 静态文件服务：兼容 Next.js export 产物（pages/ 下存在子目录 index.html）
    # 和旧的单文件 HTML 产物。
    if static_dir.exists():
        # Next.js 资源包（_next/static/…）直接映射，避免走 SPA 回退逻辑
        next_dir = static_dir / "_next"
        if next_dir.is_dir():
            app.router.add_static("/_next/", next_dir)

        _static_root = static_dir.resolve()

        async def handle_spa(request: web.Request) -> web.StreamResponse:
            """SPA 路径回退：按 Next.js export 目录结构查找 index.html，否则回退根页面。"""
            rel = request.match_info.get("path", "").strip("/")
            try:
                if rel:
                    # 安全检查：防止路径穿越
                    direct = (static_dir / rel).resolve()
                    direct.relative_to(_static_root)
                    if direct.is_file():
                        return web.FileResponse(direct)
                    subindex = direct / "index.html"
                    if subindex.is_file():
                        return web.FileResponse(subindex)
                    html = static_dir / f"{rel}.html"
                    if html.is_file():
                        return web.FileResponse(html)
            except (ValueError, OSError):
                pass
            root_index = static_dir / "index.html"
            if root_index.is_file():
                return web.FileResponse(root_index)
            return web.Response(status=404, text="Not Found")

        app.router.add_get("/", handle_spa)
        app.router.add_get("/{path:.*}", handle_spa)
    return app


__all__ = ["build_app", "SESSION_COOKIE"]
