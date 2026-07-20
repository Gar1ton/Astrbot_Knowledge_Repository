#!/usr/bin/env python3
"""Token-efficient, standard-library client for the local Knowledge Arch WebUI API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

DEFAULT_URL = "http://127.0.0.1:26618"
DEFAULT_USERNAME = "admin"
DEFAULT_TIMEOUT_SECONDS = 30
RRF_K = 60
MAX_QUERIES = 4
MAX_FINAL_HITS = 20
MAX_HIT_CHARS = 4000
MAX_READ_CHARS = 40000
ASK_EVIDENCE_MODES = ("default", "enhanced", "deep_thinking")
READ_INTENTS = ("anchored", "full-text")

# Keep this compact distribution-side snapshot synchronized with kacore.config.CONFIG_KEY_POLICY.
CONFIG_POLICIES: dict[str, dict[str, str]] = {
    "vector_db": {"backend": "restart", "auto_index_enabled": "restart"},
    "embedding": {"provider": "rebuild", "model": "rebuild", "base_url": "rebuild"},
    "ask": {"answer_language": "none"},
    "graph": {
        "enabled": "restart",
        "query_mode": "restart",
        "llm_max_async": "restart",
        "embedding_max_async": "restart",
        "max_doc_chars": "rebuild",
        "lightrag_llm_provider": "restart",
        "lightrag_llm_base_url": "restart",
        "lightrag_llm_model": "restart",
        "lightrag_llm_timeout_seconds": "restart",
    },
    "notion_sync": {
        "enabled": "restart",
        "auto_sync_interval_sec": "none",
        "sync_mode": "none",
    },
    "r2_sync": {"enabled": "restart"},
    "source_store": {"default_collection": "restart", "ocr_enabled": "restart"},
    "zotero_sync": {
        "enabled": "restart",
        "access_mode": "restart",
        "zotero_data_dir": "restart",
        "api_port": "restart",
        "storage_mode": "rebuild",
        "linked_root": "rebuild",
        "zotmoov_root": "rebuild",
        "sync_mode": "rebuild",
        "auto_sync_enabled": "restart",
        "auto_sync_interval_sec": "restart",
    },
    "deep_thinking": {
        "max_rounds": "none",
        "max_sub_queries": "none",
        "wide_top_k": "none",
        "rerank_weight": "none",
        "verify_enabled": "none",
        "max_verify_rounds": "none",
        "llm_base_url": "restart",
        "llm_model": "restart",
    },
    "rerank": {"provider": "none", "model": "none"},
    "enhanced_recall": {
        "max_sub_queries": "none",
        "wide_top_k": "none",
        "max_final_evidence": "none",
        "rerank_weight": "none",
        "corrective_enabled": "none",
    },
}

_SECRET_MARKERS = ("password", "secret", "api_key", "access_key", "token")


class ClientError(RuntimeError):
    """Expected, user-actionable client failure."""

    code = "client_error"
    exit_code = 2


class AuthenticationError(ClientError):
    code = "authentication_error"
    exit_code = 3


class ConnectionFailure(ClientError):
    code = "connection_error"
    exit_code = 4


class ApiError(ClientError):
    code = "api_error"
    exit_code = 5


class UsageError(ClientError):
    code = "usage_error"
    exit_code = 2


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(marker in normalized for marker in _SECRET_MARKERS)


def redact_secrets(value: Any) -> Any:
    """Recursively replace secret-shaped values without echoing masked API payloads."""
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _is_secret_key(key) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_value(raw: str) -> Any:
    """Parse JSON literals while keeping ordinary unquoted strings ergonomic."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _bounded(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


class KnowledgeArchClient:
    """Cookie-aware synchronous client; one short-lived instance per CLI invocation."""

    def __init__(
        self,
        base_url: str,
        username: str = DEFAULT_USERNAME,
        password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise UsageError("KNOWLEDGE_ARCH_URL must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise UsageError("Do not embed credentials in KNOWLEDGE_ARCH_URL")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self._password = password
        self.timeout = timeout
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._auth_state: dict[str, Any] | None = None

    @classmethod
    def from_env(cls) -> KnowledgeArchClient:
        return cls(
            os.environ.get("KNOWLEDGE_ARCH_URL", DEFAULT_URL),
            username=os.environ.get("KNOWLEDGE_ARCH_USERNAME", DEFAULT_USERNAME),
            password=os.environ.get("KR_WEB_PASSWORD"),
        )

    def _protect_message(self, message: str) -> str:
        if self._password:
            return message.replace(self._password, "[redacted]")
        return message

    def _request_bytes(
        self,
        path: str,
        *,
        method: str = "GET",
        query_params: dict[str, object] | None = None,
        body: Any = None,
        authenticate: bool = True,
    ) -> bytes:
        if authenticate:
            self.authenticate()
        url = f"{self.base_url}{path}"
        if query_params:
            url = f"{url}?{urlencode(query_params)}"
        data = None if body is None else _json_bytes(body)
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(payload)
                detail = parsed.get("message") or parsed.get("error") or payload
            except (json.JSONDecodeError, AttributeError):
                detail = payload or exc.reason
            message = self._protect_message(str(detail))
            if exc.code == 401:
                raise AuthenticationError(
                    f"Knowledge Arch authentication failed: {message}"
                ) from None
            raise ApiError(f"Knowledge Arch API returned HTTP {exc.code}: {message}") from None
        except (URLError, TimeoutError, OSError) as exc:
            reason = self._protect_message(str(getattr(exc, "reason", exc)))
            raise ConnectionFailure(
                f"Cannot reach Knowledge Arch at {self.base_url}: {reason}"
            ) from None

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        query_params: dict[str, object] | None = None,
        body: Any = None,
        authenticate: bool = True,
    ) -> Any:
        raw = self._request_bytes(
            path,
            method=method,
            query_params=query_params,
            body=body,
            authenticate=authenticate,
        )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"Knowledge Arch returned invalid JSON for {path}") from exc

    def request_text(self, path: str, *, query_params: dict[str, object]) -> str:
        raw = self._request_bytes(path, query_params=query_params)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApiError(f"Knowledge Arch returned non-UTF-8 text for {path}") from exc

    def authenticate(self) -> dict[str, Any]:
        if self._auth_state is not None:
            return self._auth_state
        probe = self.request_json("/api/auth", authenticate=False)
        if not isinstance(probe, dict):
            raise ApiError("Knowledge Arch auth probe returned an unexpected payload")
        if not probe.get("auth_required") or probe.get("logged_in"):
            self._auth_state = probe
            return probe
        if not self._password:
            raise AuthenticationError(
                "WebUI authentication is enabled; set KR_WEB_PASSWORD in the environment"
            )
        result = self.request_json(
            "/api/login",
            method="POST",
            body={"username": self.username, "password": self._password},
            authenticate=False,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            raise AuthenticationError("Knowledge Arch login did not establish a session")
        self._auth_state = {"auth_required": True, "logged_in": True}
        return self._auth_state


def _expect_list(value: Any, endpoint: str) -> list[Any]:
    if not isinstance(value, list):
        raise ApiError(f"Knowledge Arch returned an unexpected payload for {endpoint}")
    return value


def _expect_dict(value: Any, endpoint: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError(f"Knowledge Arch returned an unexpected payload for {endpoint}")
    return value


def doctor(client: KnowledgeArchClient) -> dict[str, Any]:
    auth = client.authenticate()
    collections = _expect_list(client.request_json("/api/collections"), "/api/collections")
    kb_collections = _expect_list(
        client.request_json("/api/kb/collections"), "/api/kb/collections"
    )
    config = _expect_dict(
        client.request_json("/api/config/effective"), "/api/config/effective"
    )
    return {
        "status": "ok",
        "url": client.base_url,
        "auth_required": bool(auth.get("auth_required")),
        "local_collection_count": len(collections),
        "kb_collection_count": len(kb_collections),
        "config_sections": sorted(config),
        "plugin_llm_used": False,
    }


def _creator_names(metadata: dict[str, Any]) -> list[str]:
    creators = metadata.get("creators") or []
    result: list[str] = []
    if not isinstance(creators, list):
        return result
    for creator in creators:
        if isinstance(creator, str):
            name = creator.strip()
        elif isinstance(creator, dict):
            name = str(creator.get("name") or "").strip()
            if not name:
                name = " ".join(
                    str(creator.get(key) or "").strip()
                    for key in ("firstName", "lastName")
                ).strip()
        else:
            name = ""
        if name and name not in result:
            result.append(name)
    return result


def _document_summary(doc: dict[str, Any]) -> dict[str, Any]:
    metadata = doc.get("zotero_meta") if isinstance(doc.get("zotero_meta"), dict) else {}
    return {
        "doc_id": str(doc.get("doc_id") or ""),
        "title": str(doc.get("title") or doc.get("filename") or ""),
        "authors": _creator_names(metadata),
        "year": str(metadata.get("year") or metadata.get("date") or ""),
        "doi": str(metadata.get("doi") or ""),
        "collection": str(doc.get("collection") or ""),
        "tags": [str(tag) for tag in doc.get("tags", []) if str(tag).strip()],
        "lifecycle_state": str(doc.get("lifecycle_state") or "active"),
    }


def catalog(client: KnowledgeArchClient, query: str, limit: int) -> dict[str, Any]:
    collections = _expect_list(client.request_json("/api/collections"), "/api/collections")
    documents = _expect_list(client.request_json("/api/documents"), "/api/documents")
    terms = [term for term in re.findall(r"[\w.-]+", query.lower()) if term]
    summaries = [_document_summary(doc) for doc in documents if isinstance(doc, dict)]

    def score(summary: dict[str, Any]) -> tuple[int, str, str]:
        title = str(summary["title"]).lower()
        authors = " ".join(summary["authors"]).lower()
        fields = " ".join(
            [title, authors, str(summary["year"]), str(summary["doi"]),
             str(summary["collection"]), " ".join(summary["tags"])]
        ).lower()
        points = 0
        if query and query.lower() in title:
            points += 12
        for term in terms:
            if term in title:
                points += 5
            if term in authors:
                points += 3
            if term in fields:
                points += 1
        return (-points, title, str(summary["doc_id"]))

    summaries.sort(key=score)
    if terms:
        summaries = [item for item in summaries if score(item)[0] < 0]
    final_limit = _bounded(limit, 1, 100)
    collection_rows = [item for item in collections if isinstance(item, dict)]
    return {
        "query": query,
        "collections": [
            {
                "name": str(item.get("name") or ""),
                "coll_key": str(item.get("coll_key") or ""),
                "parent_key": str(item.get("parent_key") or ""),
            }
            for item in collection_rows
        ],
        "document_count": len(documents),
        "documents": summaries[:final_limit],
    }


def _joined_context(hit: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in hit.get("context_before", []):
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            parts.append(str(item["text"]).strip())
    if str(hit.get("text") or "").strip():
        parts.append(str(hit["text"]).strip())
    for item in hit.get("context_after", []):
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            parts.append(str(item["text"]).strip())
    unique: list[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return "\n\n".join(unique)


def _fingerprint(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def search(
    client: KnowledgeArchClient,
    queries: list[str],
    collections: list[str],
    *,
    top_k: int,
    window: int,
    limit: int,
    max_chars: int,
) -> dict[str, Any]:
    clean_queries = [query.strip() for query in queries if query.strip()]
    if not clean_queries:
        raise UsageError("At least one non-empty --query is required")
    if len(clean_queries) > MAX_QUERIES:
        raise UsageError(f"At most {MAX_QUERIES} queries are allowed per retrieval round")
    clean_collections = list(dict.fromkeys(collections)) or [""]
    top_k = _bounded(top_k, 1, 50)
    window = _bounded(window, 0, 10)
    limit = _bounded(limit, 1, MAX_FINAL_HITS)
    max_chars = _bounded(max_chars, 200, MAX_HIT_CHARS)

    documents = _expect_list(client.request_json("/api/documents"), "/api/documents")
    document_map = {
        str(doc.get("doc_id")): doc for doc in documents if isinstance(doc, dict)
    }
    aggregates: dict[str, dict[str, Any]] = {}
    content_keys: dict[str, str] = {}

    for query in clean_queries:
        for collection_name in clean_collections:
            payload = client.request_json(
                "/api/kb/search",
                query_params={
                    "q": query,
                    "collection": collection_name,
                    "top_k": top_k,
                    "window": window,
                },
            )
            hits = _expect_list(payload, "/api/kb/search")
            for rank, raw_hit in enumerate(hits, start=1):
                if not isinstance(raw_hit, dict):
                    continue
                text = _joined_context(raw_hit)
                if not text:
                    continue
                chunk_id = str(raw_hit.get("chunk_id") or "")
                doc_id = str(raw_hit.get("doc_id") or "")
                candidate_key = f"chunk:{chunk_id}" if chunk_id else f"text:{_fingerprint(text)}"
                fingerprint = _fingerprint(text)
                aggregate_key = content_keys.get(fingerprint, candidate_key)
                if aggregate_key not in aggregates:
                    aggregates[aggregate_key] = {
                        "score": 0.0,
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "page": raw_hit.get("page"),
                        "text": text,
                        "matched_queries": [],
                        "searched_collections": [],
                    }
                content_keys[fingerprint] = aggregate_key
                item = aggregates[aggregate_key]
                item["score"] += 1.0 / (RRF_K + rank)
                if query not in item["matched_queries"]:
                    item["matched_queries"].append(query)
                label = collection_name or "all"
                if label not in item["searched_collections"]:
                    item["searched_collections"].append(label)
                if len(text) > len(str(item["text"])):
                    item["text"] = text

    ordered = sorted(
        aggregates.values(),
        key=lambda item: (-float(item["score"]), str(item["doc_id"]), str(item["chunk_id"])),
    )[:limit]
    output_hits: list[dict[str, Any]] = []
    for rank, item in enumerate(ordered, start=1):
        doc = document_map.get(str(item["doc_id"]), {})
        summary = _document_summary(doc)
        output_hits.append(
            {
                "rank": rank,
                "rrf_score": round(float(item["score"]), 6),
                "chunk_id": item["chunk_id"],
                "doc_id": item["doc_id"],
                "title": summary["title"],
                "authors": summary["authors"],
                "year": summary["year"],
                "doi": summary["doi"],
                "source_collection": summary["collection"],
                "page": item["page"],
                "matched_queries": item["matched_queries"],
                "searched_collections": item["searched_collections"],
                "text": str(item["text"])[:max_chars],
            }
        )
    return {
        "queries": clean_queries,
        "collections": [name or "all" for name in clean_collections],
        "top_k_per_query": top_k,
        "context_window": window,
        "result_count": len(output_hits),
        "hits": output_hits,
        "plugin_llm_used": False,
    }


def ask_evidence(
    client: KnowledgeArchClient,
    question: str,
    queries: list[str],
    collection: str | None,
    *,
    mode: str,
    round_number: int,
) -> dict[str, Any]:
    """Call the no-generative-LLM Ask evidence endpoint."""
    clean_question = question.strip()
    clean_queries = [query.strip() for query in queries if query.strip()]
    if not clean_question:
        raise UsageError("--question must not be empty")
    if mode not in ASK_EVIDENCE_MODES:
        raise UsageError(f"Unsupported evidence mode: {mode}")
    if round_number < 1:
        raise UsageError("--round must be one or greater")
    if mode == "deep_thinking" and not collection:
        raise UsageError("deep_thinking requires --collection")
    payload = client.request_json(
        "/api/ask/evidence",
        method="POST",
        body={
            "question": clean_question,
            "queries": clean_queries or [clean_question],
            "collection": collection or "",
            "retrieval_mode": mode,
            "round": round_number,
        },
    )
    result = _expect_dict(payload, "/api/ask/evidence")
    if result.get("plugin_llm_used") is not False:
        raise ApiError("Evidence endpoint did not affirm plugin_llm_used=false")
    if result.get("full_text_used") is not False:
        raise ApiError("Evidence endpoint unexpectedly returned full document text")
    return result


def read_document(
    client: KnowledgeArchClient,
    doc_id: str,
    start: int,
    max_chars: int,
    *,
    intent: str,
) -> dict[str, Any]:
    if intent not in READ_INTENTS:
        raise UsageError("read requires --intent anchored or --intent full-text")
    if start < 0:
        raise UsageError("--start must be zero or greater")
    max_chars = _bounded(max_chars, 1, MAX_READ_CHARS)
    payload = client.request_json(
        f"/api/documents/{quote(doc_id, safe='')}/content/page",
        query_params={"start": start, "max_chars": max_chars},
    )
    result = _expect_dict(payload, "document content page")
    result["read_intent"] = intent
    result["full_text_used"] = True
    return result


def graph_estimate(client: KnowledgeArchClient, collection: str) -> dict[str, Any]:
    payload = client.request_json(
        "/api/graph/build/estimate",
        method="POST",
        body={"collection": collection},
    )
    return _expect_dict(payload, "/api/graph/build/estimate")


def graph_codex_build(
    client: KnowledgeArchClient, collection: str, *, apply: bool
) -> dict[str, Any]:
    estimate = graph_estimate(client, collection)
    if not apply:
        return {
            "status": "preview",
            "collection": collection,
            "estimate": estimate,
            "plugin_llm_used": False,
            "embedding_provider_will_be_used": True,
            "mutation_performed": False,
            "requires_explicit_confirmation": True,
        }
    result = _expect_dict(
        client.request_json(
            "/api/graph/codex-build",
            method="POST",
            body={"collection": collection, "confirmed": True},
        ),
        "/api/graph/codex-build",
    )
    result["mutation_performed"] = True
    return result


def graph_next(client: KnowledgeArchClient, job_id: str) -> dict[str, Any]:
    return _expect_dict(
        client.request_json(f"/api/graph/codex-build/{quote(job_id, safe='')}/next"),
        "Codex graph next task",
    )


def graph_submit(
    client: KnowledgeArchClient, job_id: str, task_id: str, result: Any
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise UsageError("--result-json must decode to an object")
    return _expect_dict(
        client.request_json(
            f"/api/graph/codex-build/{quote(job_id, safe='')}/submit",
            method="POST",
            body={"task_id": task_id, "result": result},
        ),
        "Codex graph task submission",
    )


def graph_retry(
    client: KnowledgeArchClient, job_id: str, task_id: str
) -> dict[str, Any]:
    return _expect_dict(
        client.request_json(
            f"/api/graph/codex-build/{quote(job_id, safe='')}/retry",
            method="POST",
            body={"task_id": task_id},
        ),
        "Codex graph task retry",
    )


def graph_status(client: KnowledgeArchClient, job_id: str) -> dict[str, Any]:
    return _expect_dict(
        client.request_json(f"/api/graph/build/{quote(job_id, safe='')}"),
        "graph build status",
    )


def config_options() -> dict[str, Any]:
    return {
        "consequences": {
            "none": "saved without restart or rebuild",
            "restart": "saved; separately confirmed plugin restart required",
            "rebuild": "saved; restart and user-operated index rebuild required",
        },
        "writable": CONFIG_POLICIES,
        "rebuild_command_available": False,
    }


def config_show(client: KnowledgeArchClient, section: str | None) -> dict[str, Any]:
    config = _expect_dict(
        client.request_json("/api/config/effective"), "/api/config/effective"
    )
    if section:
        if section not in config:
            raise UsageError(f"Unknown effective config section: {section}")
        return {section: redact_secrets(config[section])}
    return redact_secrets(config)


def config_set(
    client: KnowledgeArchClient,
    section: str,
    key: str,
    value: Any,
    *,
    apply: bool,
) -> dict[str, Any]:
    consequence = CONFIG_POLICIES.get(section, {}).get(key)
    if consequence is None:
        raise UsageError(
            f"{section}.{key} is not runtime-writable; inspect config-options "
            "instead of bypassing it"
        )
    config = _expect_dict(
        client.request_json("/api/config/effective"), "/api/config/effective"
    )
    section_values = config.get(section)
    if not isinstance(section_values, dict):
        raise ApiError(f"Effective config is missing section {section}")
    preview: dict[str, Any] = {
        "status": "preview",
        "section": section,
        "key": key,
        "current": redact_secrets(section_values.get(key)),
        "proposed": redact_secrets(value),
        "consequence": consequence,
        "restart_required": consequence in {"restart", "rebuild"},
        "rebuild_required": consequence == "rebuild",
        "mutation_performed": False,
        "requires_explicit_confirmation": True,
    }
    if not apply:
        return preview
    result = client.request_json(
        "/api/config/update",
        method="POST",
        body={"section": section, "key": key, "value": value},
    )
    preview.update(
        {
            "status": "applied",
            "mutation_performed": True,
            "requires_explicit_confirmation": False,
            "api_result": redact_secrets(result),
        }
    )
    return preview


def restart(client: KnowledgeArchClient, *, apply: bool) -> dict[str, Any]:
    if not apply:
        return {
            "status": "preview",
            "mutation_performed": False,
            "requires_explicit_confirmation": True,
            "effect": "WebUI connection will briefly drop while the plugin runtime restarts",
        }
    result = client.request_json("/api/plugin/restart", method="POST", body={})
    return {
        "status": "applied",
        "mutation_performed": True,
        "requires_explicit_confirmation": False,
        "api_result": redact_secrets(result),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Probe authentication and core read endpoints")

    catalog_parser = subparsers.add_parser(
        "catalog", help="Find collections and documents by metadata"
    )
    catalog_parser.add_argument("--query", default="")
    catalog_parser.add_argument("--limit", type=int, default=20)

    search_parser = subparsers.add_parser("search", help="Retrieve and fuse compact evidence")
    search_parser.add_argument("--query", action="append", required=True)
    scope = search_parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--collection", action="append")
    scope.add_argument("--all", dest="all_collections", action="store_true")
    search_parser.add_argument("--top-k", type=int, default=8)
    search_parser.add_argument("--window", type=int, default=1)
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--max-chars", type=int, default=1600)

    ask_parser = subparsers.add_parser(
        "ask-evidence", help="Retrieve mode-aware evidence without plugin LLM synthesis"
    )
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--query", action="append", default=[])
    ask_parser.add_argument("--mode", choices=ASK_EVIDENCE_MODES, default="default")
    ask_parser.add_argument("--round", type=int, default=1)
    ask_scope = ask_parser.add_mutually_exclusive_group(required=True)
    ask_scope.add_argument("--collection")
    ask_scope.add_argument("--all", dest="all_collections", action="store_true")

    read_parser = subparsers.add_parser("read", help="Read one bounded page of document Markdown")
    read_parser.add_argument("--doc-id", required=True)
    read_parser.add_argument("--start", type=int, default=0)
    read_parser.add_argument("--max-chars", type=int, default=12000)
    read_parser.add_argument("--intent", choices=READ_INTENTS, required=True)

    graph_estimate_parser = subparsers.add_parser(
        "graph-estimate", help="Estimate a LightRAG build without mutating state"
    )
    graph_estimate_parser.add_argument("--collection", required=True)
    graph_build_parser = subparsers.add_parser(
        "graph-build", help="Preview or start a Codex-driven LightRAG build"
    )
    graph_build_parser.add_argument("--collection", required=True)
    graph_build_parser.add_argument("--apply", action="store_true")
    graph_next_parser = subparsers.add_parser("graph-next", help="Get the next Codex KG task")
    graph_next_parser.add_argument("--job-id", required=True)
    graph_submit_parser = subparsers.add_parser(
        "graph-submit", help="Submit one Codex entity/relation result"
    )
    graph_submit_parser.add_argument("--job-id", required=True)
    graph_submit_parser.add_argument("--task-id", required=True)
    graph_submit_parser.add_argument("--result-json", required=True)
    graph_retry_parser = subparsers.add_parser("graph-retry", help="Retry one failed KG task")
    graph_retry_parser.add_argument("--job-id", required=True)
    graph_retry_parser.add_argument("--task-id", required=True)
    graph_status_parser = subparsers.add_parser("graph-status", help="Show graph build status")
    graph_status_parser.add_argument("--job-id", required=True)

    show_parser = subparsers.add_parser("config-show", help="Show redacted effective configuration")
    show_parser.add_argument("--section")
    subparsers.add_parser("config-options", help="List runtime-writable settings and consequences")

    set_parser = subparsers.add_parser(
        "config-set", help="Preview or apply one safe setting change"
    )
    set_parser.add_argument("section")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--apply", action="store_true")

    restart_parser = subparsers.add_parser("restart", help="Preview or apply a plugin restart")
    restart_parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "config-options":
            result = config_options()
        else:
            client = KnowledgeArchClient.from_env()
            if args.command == "doctor":
                result = doctor(client)
            elif args.command == "catalog":
                result = catalog(client, args.query, args.limit)
            elif args.command == "search":
                collections = [""] if args.all_collections else list(args.collection or [])
                result = search(
                    client,
                    list(args.query),
                    collections,
                    top_k=args.top_k,
                    window=args.window,
                    limit=args.limit,
                    max_chars=args.max_chars,
                )
            elif args.command == "ask-evidence":
                result = ask_evidence(
                    client,
                    args.question,
                    list(args.query),
                    None if args.all_collections else args.collection,
                    mode=args.mode,
                    round_number=args.round,
                )
            elif args.command == "read":
                result = read_document(
                    client,
                    args.doc_id,
                    args.start,
                    args.max_chars,
                    intent=args.intent,
                )
            elif args.command == "graph-estimate":
                result = graph_estimate(client, args.collection)
            elif args.command == "graph-build":
                result = graph_codex_build(client, args.collection, apply=args.apply)
            elif args.command == "graph-next":
                result = graph_next(client, args.job_id)
            elif args.command == "graph-submit":
                try:
                    graph_result = json.loads(args.result_json)
                except json.JSONDecodeError as exc:
                    raise UsageError("--result-json must be valid JSON") from exc
                result = graph_submit(client, args.job_id, args.task_id, graph_result)
            elif args.command == "graph-retry":
                result = graph_retry(client, args.job_id, args.task_id)
            elif args.command == "graph-status":
                result = graph_status(client, args.job_id)
            elif args.command == "config-show":
                result = config_show(client, args.section)
            elif args.command == "config-set":
                result = config_set(
                    client,
                    args.section,
                    args.key,
                    parse_value(args.value),
                    apply=args.apply,
                )
            elif args.command == "restart":
                result = restart(client, apply=args.apply)
            else:  # pragma: no cover - argparse guarantees a known command
                raise UsageError(f"Unknown command: {args.command}")
        print(_compact_json(result))
        return 0
    except ClientError as exc:
        print(
            _compact_json({"status": "error", "error": exc.code, "message": str(exc)}),
            file=sys.stderr,
        )
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
