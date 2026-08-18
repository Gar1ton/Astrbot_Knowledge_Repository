#!/usr/bin/env python3
"""Token-efficient, standard-library client for the local Knowledge Arch WebUI API."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

CONNECTION_CONFIG_VERSION = 1
CONNECTION_KEYRING_SERVICE = "knowledge-arch.codex.connection.v1"


DEFAULT_TIMEOUT_SECONDS = 30
# index-rebuild --wait 的轮询节奏与上限。重建是后台 job，服务端 POST 立即返回；
# 上限到点只是停止观察，**不会**取消仍在跑的重建（用 index-status 继续查）。
INDEX_REBUILD_POLL_SECONDS = 3.0
INDEX_REBUILD_WAIT_MAX_SECONDS = 1800
# 终态集合，与 kacore/milvus_build.py 的 MILVUS_BUILD_TERMINAL_STATUSES 对齐。
INDEX_REBUILD_TERMINAL_STATUSES = ("success", "partial_failure", "error")
RRF_K = 60
MAX_QUERIES = 4
MAX_FINAL_HITS = 20
MAX_HIT_CHARS = 4000
MAX_NOTION_QA_ITEMS = 20
MAX_NOTION_QA_QUESTION_CHARS = 2000
MAX_NOTION_QA_ANSWER_CHARS = 100000
ASK_EVIDENCE_MODES = ("default", "enhanced", "deep_thinking")
READ_INTENTS = ("anchored", "full-text")

# Keep this compact distribution-side snapshot synchronized with kacore.config.CONFIG_KEY_POLICY.
CONFIG_POLICIES: dict[str, dict[str, str]] = {
    "vector_db": {
        "backend": "restart",
        "auto_index_enabled": "restart",
        "auto_rebuild_enabled": "none",
        "auto_rebuild_delay_seconds": "none",
    },
    "embedding": {
        "provider": "rebuild",
        "model": "rebuild",
        "base_url": "rebuild",
        "load_timeout_seconds": "restart",
        "device": "restart",
    },
    "ask": {
        "answer_language": "none",
        "llm_timeout_seconds": "restart",
        "task_timeout_seconds": "none",
    },
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
    "memecho": {
        "enabled": "restart",
        "base_url": "restart",
        "default_vault_id": "none",
        "query_readonly": "none",
        "write_back_enabled": "none",
        "timeout_seconds": "none",
        "import_preset": "none",
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


class StructuredApiError(ApiError):
    """An API error whose JSON body carries a machine-readable ``status`` discriminator.

    Subclasses ApiError on purpose: every existing ``except ApiError`` site and the
    ``exit_code`` contract keep working untouched. Callers that care about a specific
    gate (e.g. the full-text confirmation gate) can inspect ``http_status``/``payload``.
    """

    def __init__(self, message: str, http_status: int, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.payload = payload


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


class ConnectionNotConfigured(ClientError):
    code = "connection_not_configured"
    exit_code = 6


class CredentialStoreUnavailable(ClientError):
    code = "credential_store_unavailable"
    exit_code = 7


class CredentialStore(Protocol):
    """最小系统凭据库契约，便于隔离测试且不提供明文回退。"""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class KeyringCredentialStore:
    """通过 keyring 使用操作系统凭据库；依赖缺失时明确失败。"""

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise CredentialStoreUnavailable(
                "System credential storage requires keyring. Install it into this Python "
                "environment with: python -m pip install -r requirements-codex-skill.txt"
            ) from exc
        try:
            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise RuntimeError("no usable keyring backend")
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "System credential storage is unavailable. Configure an operating-system "
                "credential backend and rerun connection-setup."
            ) from exc
        self._keyring = keyring

    def get_password(self, service: str, username: str) -> str | None:
        try:
            return self._keyring.get_password(service, username)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "System credential storage could not read the registered password."
            ) from exc

    def set_password(self, service: str, username: str, password: str) -> None:
        try:
            self._keyring.set_password(service, username, password)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "System credential storage could not save the password."
            ) from exc

    def delete_password(self, service: str, username: str) -> None:
        try:
            self._keyring.delete_password(service, username)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                "System credential storage could not remove a replaced password."
            ) from exc


@dataclass(frozen=True)
class ConnectionProfile:
    """单一日常实例的非秘密连接资料。"""

    base_url: str
    username: str
    credential_id: str | None


def _normalize_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UsageError("WebUI URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise UsageError("Do not embed credentials in the WebUI URL")
    return base_url.strip().rstrip("/")


def _credential_id(base_url: str, username: str) -> str:
    identity = f"{base_url}\0{username}".encode()
    return hashlib.sha256(identity).hexdigest()


def connection_config_path() -> Path:
    """返回用户级连接配置路径；该文件不含密码。"""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "Codex" / "knowledge-arch" / "connection.json"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Codex"
            / "knowledge-arch"
            / "connection.json"
        )
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "codex" / "knowledge-arch" / "connection.json"


def load_connection_profile(path: Path | None = None) -> ConnectionProfile | None:
    """加载非秘密单实例配置；损坏配置要求用户重新登记。"""
    target = path or connection_config_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != CONNECTION_CONFIG_VERSION:
            raise ValueError("unsupported connection profile")
        base_url = _normalize_base_url(str(raw["base_url"]))
        username = str(raw["username"]).strip()
        credential_id = raw.get("credential_id")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConnectionNotConfigured(
            "Registered connection details are invalid. Run connection-setup again."
        ) from exc
    if not username or (credential_id is not None and not isinstance(credential_id, str)):
        raise ConnectionNotConfigured(
            "Registered connection details are invalid. Run connection-setup again."
        )
    return ConnectionProfile(
        base_url=base_url,
        username=username,
        credential_id=credential_id or None,
    )


def _write_connection_profile(profile: ConnectionProfile, path: Path | None = None) -> None:
    """原子写入无密码配置，并在 POSIX 上限制为当前用户可读写。"""
    target = path or connection_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CONNECTION_CONFIG_VERSION,
        "base_url": profile.base_url,
        "username": profile.username,
        "credential_id": profile.credential_id,
    }
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False, prefix=".connection-"
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    try:
        os.replace(temp_path, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _default_credential_store() -> CredentialStore:
    return KeyringCredentialStore()


def connection_status(path: Path | None = None) -> dict[str, str]:
    """仅报告连接来源状态，不输出地址、用户名、密码或凭据标识。"""
    env_url = os.environ.get("KNOWLEDGE_ARCH_URL")
    env_username = os.environ.get("KNOWLEDGE_ARCH_USERNAME")
    if env_url or env_username:
        if env_url and env_username:
            return {"status": "environment_override"}
        return {"status": "unconfigured", "reason": "temporary_connection_incomplete"}
    return {"status": "configured" if load_connection_profile(path) else "unconfigured"}


def resolve_connection_client(
    *,
    path: Path | None = None,
    credential_store: CredentialStore | None = None,
) -> tuple[KnowledgeArchClient, str]:
    """解析临时覆盖或已登记实例，绝不将已登记密码发送给临时目标。"""
    env_url = os.environ.get("KNOWLEDGE_ARCH_URL")
    env_username = os.environ.get("KNOWLEDGE_ARCH_USERNAME")
    env_password = os.environ.get("KR_WEB_PASSWORD")
    if env_url or env_username:
        if not env_url or not env_username:
            raise UsageError(
                "Temporary connection requires both KNOWLEDGE_ARCH_URL and "
                "KNOWLEDGE_ARCH_USERNAME."
            )
        return KnowledgeArchClient(env_url, env_username, env_password), "environment_override"

    profile = load_connection_profile(path)
    if profile is None:
        raise ConnectionNotConfigured(
            "No Knowledge Arch instance is registered. Run connection-setup first."
        )
    if env_password is not None:
        return KnowledgeArchClient(profile.base_url, profile.username, env_password), "configured"
    password = None
    if profile.credential_id:
        store = credential_store or _default_credential_store()
        password = store.get_password(CONNECTION_KEYRING_SERVICE, profile.credential_id)
    return KnowledgeArchClient(profile.base_url, profile.username, password), "configured"


def connection_setup(
    *,
    path: Path | None = None,
    credential_store: CredentialStore | None = None,
    input_func: Callable[[str], str] = input,
    password_func: Callable[[str], str] = getpass.getpass,
) -> dict[str, object]:
    """交互验证后持久化单一实例；失败时不留下新配置或新密码。"""
    target = path or connection_config_path()
    previous = load_connection_profile(target)
    if previous is not None:
        replace = input_func(
            "A connection is already registered. Replace it? [y/N]: "
        ).strip().lower()
        if replace not in {"y", "yes"}:
            raise UsageError("Connection setup cancelled; existing registration was kept.")
    base_url = _normalize_base_url(input_func("Knowledge Arch WebUI URL: "))
    username = input_func("Knowledge Arch username: ").strip()
    if not username:
        raise UsageError("Knowledge Arch username must not be empty")
    password = password_func(
        "Knowledge Arch password (leave blank only when authentication is disabled): "
    )
    client = KnowledgeArchClient(base_url, username, password or None)
    verification = doctor(client)

    credential_id = _credential_id(base_url, username) if password else None
    store = credential_store
    stored_new_credential = False
    try:
        if credential_id:
            store = store or _default_credential_store()
            store.set_password(CONNECTION_KEYRING_SERVICE, credential_id, password)
            stored_new_credential = True
        _write_connection_profile(
            ConnectionProfile(base_url=base_url, username=username, credential_id=credential_id),
            target,
        )
    except Exception:
        if stored_new_credential and store is not None and credential_id:
            try:
                store.delete_password(CONNECTION_KEYRING_SERVICE, credential_id)
            except CredentialStoreUnavailable:
                pass
        raise

    if previous and previous.credential_id and previous.credential_id != credential_id:
        store = store or _default_credential_store()
        store.delete_password(CONNECTION_KEYRING_SERVICE, previous.credential_id)
    return {
        "status": "configured",
        "auth_required": bool(verification["auth_required"]),
        "credential_stored": bool(credential_id),
    }


class KnowledgeArchClient:
    """Cookie-aware synchronous client; one short-lived instance per CLI invocation."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.username = username
        self._password = password
        self.timeout = timeout
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._auth_state: dict[str, Any] | None = None

    @classmethod
    def from_env(cls) -> KnowledgeArchClient:
        """兼容入口：解析临时覆盖或用户已登记的单一实例。"""
        client, _source = resolve_connection_client()
        return client

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
            structured: dict[str, Any] | None = None
            try:
                parsed = json.loads(payload)
                detail = parsed.get("message") or parsed.get("error") or payload
                if isinstance(parsed, dict):
                    structured = parsed
            except (json.JSONDecodeError, AttributeError):
                detail = payload or exc.reason
            message = self._protect_message(str(detail))
            if exc.code == 401:
                raise AuthenticationError(
                    f"Knowledge Arch authentication failed: {message}"
                ) from None
            summary = f"Knowledge Arch API returned HTTP {exc.code}: {message}"
            if structured is not None:
                raise StructuredApiError(summary, exc.code, structured) from None
            raise ApiError(summary) from None
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
    confirm_large_read: bool = False,
) -> dict[str, Any]:
    """Read document Markdown. ``max_chars=0`` reads to the end of the document.

    There is no client-side character cap. Reads whose returned size exceeds the
    server's confirmation threshold come back as a preview carrying **no document
    text**; surface ``total_chars`` to the user, obtain explicit consent, and only
    then retry with ``confirm_large_read=True``.
    """
    if intent not in READ_INTENTS:
        raise UsageError("read requires --intent anchored or --intent full-text")
    if start < 0:
        raise UsageError("--start must be zero or greater")
    if max_chars < 0:
        raise UsageError("--max-chars must be zero or greater (0 reads to the end)")
    query: dict[str, Any] = {"start": start, "max_chars": max_chars}
    if confirm_large_read:
        query["confirmed"] = 1
    try:
        payload = client.request_json(
            f"/api/documents/{quote(doc_id, safe='')}/content/page",
            query_params=query,
        )
    except StructuredApiError as exc:
        if (
            exc.http_status == 409
            and exc.payload.get("status") == "fulltext_confirmation_required"
        ):
            gate = redact_secrets(exc.payload)
            return {
                "status": "preview",
                "doc_id": doc_id,
                "start": start,
                "total_chars": gate.get("total_chars"),
                "requested_chars": gate.get("requested_chars"),
                "confirm_threshold_chars": gate.get("threshold_chars"),
                "estimated_tokens": gate.get("estimated_tokens"),
                "title": gate.get("title"),
                "message": gate.get("message"),
                "requires_explicit_confirmation": True,
                # Deliberately not `mutation_performed`: this is a read gate, not a
                # write gate. What the caller needs to know is that no text came back.
                "content_returned": False,
                "full_text_used": False,
                "read_intent": intent,
            }
        raise
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
            "rebuild": (
                "saved; a separately confirmed restart plus an index rebuild are required "
                "(see the index-rebuild command)"
            ),
        },
        "writable": CONFIG_POLICIES,
        # v1.1.2 起可用：`index-rebuild --apply` 等价于 WebUI 的「重建索引」按钮。
        # 仍是变更操作，须先 preview 并取得用户明确确认。
        "rebuild_command_available": True,
        "rebuild_command": "index-rebuild",
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


def _notion_qa_string_list(value: Any, field: str) -> list[str]:
    """校验并去重 QA 标签或引用；禁止把任意对象隐式写进同步载荷。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise UsageError(f"{field} must be an array of strings")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise UsageError(f"{field} must contain only strings")
        text = raw.strip()
        if not text:
            continue
        if len(text) > 1000:
            raise UsageError(f"{field} entries must not exceed 1000 characters")
        if text not in result:
            result.append(text)
    return result


def load_notion_qa_items(input_file: str) -> list[dict[str, Any]]:
    """读取 Codex 临时生成的 UTF-8 问答列表，供逐条写入已配置 QA 库。"""
    path = Path(input_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"Cannot read --input-file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError("--input-file must contain valid UTF-8 JSON") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise UsageError("--input-file must be an object with an items array")
    raw_items = payload["items"]
    if not raw_items:
        raise UsageError("--input-file items must not be empty")
    if len(raw_items) > MAX_NOTION_QA_ITEMS:
        raise UsageError(f"At most {MAX_NOTION_QA_ITEMS} QA items may be saved at once")

    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise UsageError(f"items[{index}] must be an object")
        raw_question = raw_item.get("question")
        raw_answer = raw_item.get("answer")
        if not isinstance(raw_question, str) or not raw_question.strip():
            raise UsageError(f"items[{index}].question must be a non-empty string")
        if not isinstance(raw_answer, str) or not raw_answer.strip():
            raise UsageError(f"items[{index}].answer must be a non-empty string")
        question = raw_question.strip()
        answer = raw_answer.strip()
        if len(question) > MAX_NOTION_QA_QUESTION_CHARS:
            raise UsageError(
                f"items[{index}].question exceeds {MAX_NOTION_QA_QUESTION_CHARS} characters"
            )
        if len(answer) > MAX_NOTION_QA_ANSWER_CHARS:
            raise UsageError(
                f"items[{index}].answer exceeds {MAX_NOTION_QA_ANSWER_CHARS} characters"
            )
        items.append(
            {
                "question": question,
                "answer": answer,
                "tags": _notion_qa_string_list(raw_item.get("tags"), f"items[{index}].tags"),
                "citations": _notion_qa_string_list(
                    raw_item.get("citations"), f"items[{index}].citations"
                ),
            }
        )
    return items


def notion_save_qa(client: KnowledgeArchClient, input_file: str) -> dict[str, Any]:
    """把多个原问题/回答逐条推送到已配置的 Notion QA 库。

    目标只能是 `notion_sync.qa_database_id`；文章镜像库 `database_id` 不可作为
    会话问答写入目标。每条请求由服务端先暂存 outbox，再立即尝试远端写入。
    """
    items = load_notion_qa_items(input_file)
    config = config_show(client, "notion_sync")
    notion = config.get("notion_sync")
    if not isinstance(notion, dict):
        raise ApiError("Effective config is missing notion_sync")
    if not bool(notion.get("enabled")):
        raise UsageError("Notion sync is disabled; enable it and restart the plugin first")
    target_database_id = str(notion.get("qa_database_id", "")).strip()
    if not target_database_id:
        raise UsageError(
            "Notion QA database is not configured (notion_sync.qa_database_id); "
            "initialize the QA database before saving conversation answers"
        )

    outcomes: list[dict[str, Any]] = []
    pushed_count = 0
    queued_count = 0
    failed_count = 0
    for index, item in enumerate(items, start=1):
        response = _expect_dict(
            client.request_json(
                "/api/notion/push-note",
                method="POST",
                body={
                    "content": item["answer"],
                    "title": item["question"],
                    "tags": item["tags"],
                    "citations": item["citations"],
                    "source": "codex",
                    "keep_local": False,
                },
            ),
            "/api/notion/push-note",
        )
        status = str(response.get("status", "error"))
        outcome = {
            "index": index,
            "question": item["question"],
            "status": status,
            "page_id": str(response.get("page_id", "")),
            "outbox_id": str(response.get("outbox_id", "")),
            "message": str(response.get("message", "")),
        }
        outcomes.append(outcome)
        if status == "success":
            pushed_count += 1
        elif status == "partial":
            queued_count += 1
        else:
            failed_count += 1

    status = "success" if not queued_count and not failed_count else "partial"
    if failed_count == len(outcomes):
        status = "error"
    return {
        "status": status,
        "target_database_id": target_database_id,
        "pushed_count": pushed_count,
        "queued_count": queued_count,
        "failed_count": failed_count,
        "items": outcomes,
    }


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


def _vector_store_stage(client: KnowledgeArchClient) -> dict[str, Any]:
    """从能力快照里取 vector_store 阶段；拿不到时返回空 dict 而不是抛错。

    索引状态本身不该因为能力端点的形状变化而整个失败——待重建数量才是主信号。
    """
    try:
        capabilities = client.request_json("/api/capabilities")
    except ApiError:
        return {}
    if not isinstance(capabilities, dict):
        return {}
    pipeline = capabilities.get("pipeline")
    if not isinstance(pipeline, list):
        return {}
    for stage in pipeline:
        if isinstance(stage, dict) and stage.get("id") == "vector_store":
            return stage
    return {}


def index_status(client: KnowledgeArchClient) -> dict[str, Any]:
    """只读：待重建文档数、当前重建任务、以及自动重建是否已经在管这件事。"""
    count_payload = _expect_dict(
        client.request_json("/api/documents/pending-reindex-count"),
        "/api/documents/pending-reindex-count",
    )
    active_payload = _expect_dict(
        client.request_json("/api/documents/rebuild-index/active"),
        "/api/documents/rebuild-index/active",
    )
    job = active_payload.get("job")
    stage = _vector_store_stage(client)
    detail = stage.get("detail") if isinstance(stage.get("detail"), dict) else {}
    return {
        "status": "ok",
        "pending_reindex_count": int(count_payload.get("count") or 0),
        "active_job": job if isinstance(job, dict) else None,
        "backend": stage.get("current", ""),
        "vector_store_status": stage.get("status", ""),
        "compatible": detail.get("compatible"),
        "rebuild_required": detail.get("rebuild_required"),
        # 自动重建已开时，队列通常会自己排空；先看这两个字段再决定是否手动催一次。
        "auto_rebuild_enabled": detail.get("auto_rebuild_enabled"),
        "auto_rebuild_delay_seconds": detail.get("auto_rebuild_delay_seconds"),
        "reason": detail.get("reason", ""),
        "mutation_performed": False,
    }


def _wait_for_index_rebuild(
    client: KnowledgeArchClient,
    *,
    max_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """轮询到重建进入终态或等待上限；返回观察结果（不代表重建被取消）。

    `/api/documents/rebuild-index/active` 在 success 时返回 `job: null`（前端据此隐藏进度条），
    因此「job 消失」与「job 到达终态」都算跑完，前者按 success 汇报。
    """
    deadline = monotonic() + max_seconds
    last_job: dict[str, Any] | None = None
    while True:
        payload = _expect_dict(
            client.request_json("/api/documents/rebuild-index/active"),
            "/api/documents/rebuild-index/active",
        )
        job = payload.get("job")
        if not isinstance(job, dict):
            # 任务已消失 = 成功收尾（失败/部分失败会一直留着供重试）。
            return {"observed": "finished", "job": last_job, "final_status": "success"}
        last_job = job
        status = str(job.get("status") or "")
        if status in INDEX_REBUILD_TERMINAL_STATUSES:
            return {"observed": "finished", "job": job, "final_status": status}
        if monotonic() >= deadline:
            return {"observed": "timeout", "job": job, "final_status": status}
        sleep(INDEX_REBUILD_POLL_SECONDS)


def index_rebuild(
    client: KnowledgeArchClient,
    *,
    apply: bool,
    wait: bool = False,
    max_wait_seconds: int = INDEX_REBUILD_WAIT_MAX_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """预览或启动一次 Milvus 索引重建（等价于 WebUI 的「重建索引」按钮）。

    预览里带上 `pending_reindex_count` 与 `auto_rebuild_enabled`：多数情况下自动重建已经在
    排空队列，用户该知道这一次手动触发是不是多余的。

    服务端是全局单飞——已有重建在跑时会返回同一个 job 而非并发起第二次。
    """
    status = index_status(client)
    if not apply:
        return {
            "status": "preview",
            "pending_reindex_count": status["pending_reindex_count"],
            "active_job": status["active_job"],
            "auto_rebuild_enabled": status["auto_rebuild_enabled"],
            "compatible": status["compatible"],
            "effect": (
                "Re-embeds every pending document; a full rebuild clears the vector "
                "collection first and retrieval stays degraded until it finishes"
            ),
            "embedding_provider_will_be_used": True,
            "plugin_llm_used": False,
            "mutation_performed": False,
            "requires_explicit_confirmation": True,
        }
    started = _expect_dict(
        client.request_json("/api/documents/rebuild-index", method="POST", body={}),
        "/api/documents/rebuild-index",
    )
    result: dict[str, Any] = {
        "status": "started",
        "mutation_performed": True,
        "requires_explicit_confirmation": False,
        "pending_reindex_count_before": status["pending_reindex_count"],
        "api_result": redact_secrets(started),
    }
    if not wait:
        return result
    observation = _wait_for_index_rebuild(
        client, max_seconds=max_wait_seconds, sleep=sleep, monotonic=monotonic
    )
    result["status"] = "completed" if observation["observed"] == "finished" else "timeout"
    result["final_status"] = observation["final_status"]
    result["final_job"] = observation["job"]
    if observation["observed"] == "timeout":
        # 说清楚「不再等」不等于「已停止」，否则模型会误报重建被取消。
        result["note"] = (
            "Stopped observing after the wait limit; the rebuild is still running. "
            "Poll index-status instead of starting another rebuild."
        )
    else:
        result["pending_reindex_count_after"] = index_status(client)["pending_reindex_count"]
    return result


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
    subparsers.add_parser(
        "connection-status", help="Show whether a safe local connection is available"
    )
    subparsers.add_parser(
        "connection-setup", help="Interactively register one Knowledge Arch instance"
    )
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

    read_parser = subparsers.add_parser("read", help="Read one page of document Markdown")
    read_parser.add_argument("--doc-id", required=True)
    read_parser.add_argument("--start", type=int, default=0)
    read_size_group = read_parser.add_mutually_exclusive_group()
    read_size_group.add_argument("--max-chars", type=int, default=12000)
    read_size_group.add_argument(
        "--whole",
        action="store_true",
        help="Read from --start to the end of the document (no character cap)",
    )
    read_parser.add_argument("--intent", choices=READ_INTENTS, required=True)
    read_parser.add_argument(
        "--confirm-large-read",
        action="store_true",
        help=(
            "Proceed with a read whose size exceeds the server's confirmation threshold. "
            "Only pass this after telling the user the document's total_chars and getting "
            "explicit consent. This is a read gate; --apply remains the mutation gate."
        ),
    )

    notion_save_parser = subparsers.add_parser(
        "notion-save-qa", help="Save conversation QA records to the configured Notion QA database"
    )
    notion_save_parser.add_argument(
        "--input-file",
        required=True,
        help="UTF-8 JSON object: {items:[{question,answer,tags?,citations?}]}",
    )

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

    subparsers.add_parser(
        "index-status", help="Show pending reindex count and any running index rebuild"
    )
    index_rebuild_parser = subparsers.add_parser(
        "index-rebuild", help="Preview or start the Milvus index rebuild (the WebUI button)"
    )
    index_rebuild_parser.add_argument("--apply", action="store_true")
    index_rebuild_parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll until the rebuild reaches a terminal status instead of returning immediately",
    )
    index_rebuild_parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=INDEX_REBUILD_WAIT_MAX_SECONDS,
        help="Stop observing after this many seconds; the rebuild itself keeps running",
    )

    restart_parser = subparsers.add_parser("restart", help="Preview or apply a plugin restart")
    restart_parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "connection-status":
            result = connection_status()
        elif args.command == "connection-setup":
            result = connection_setup()
        elif args.command == "config-options":
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
                    0 if args.whole else args.max_chars,
                    intent=args.intent,
                    confirm_large_read=args.confirm_large_read,
                )
            elif args.command == "notion-save-qa":
                result = notion_save_qa(client, args.input_file)
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
            elif args.command == "index-status":
                result = index_status(client)
            elif args.command == "index-rebuild":
                result = index_rebuild(
                    client,
                    apply=args.apply,
                    wait=args.wait,
                    max_wait_seconds=args.max_wait_seconds,
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
