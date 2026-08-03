"""Codex 项目级 Knowledge Arch Skill 客户端契约测试。"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from kacore.config import CONFIG_KEY_POLICY

ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "operate-knowledge-arch"
    / "scripts"
    / "knowledge_arch_client.py"
)


def _load_client_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("knowledge_arch_skill_client", CLIENT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client_module()
SKILL_PATH = ROOT / ".agents" / "skills" / "operate-knowledge-arch" / "SKILL.md"


class _MemoryCredentialStore:
    """测试用系统凭据库桩：密码永不写入连接配置文件。"""

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []
        self.fail_on_set = False

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.fail_on_set:
            raise CLIENT.CredentialStoreUnavailable("credential backend unavailable")
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.deleted.append((service, username))
        self.passwords.pop((service, username), None)


class _State:
    def __init__(self, *, auth_required: bool = False) -> None:
        self.auth_required = auth_required
        self.login_bodies: list[dict[str, Any]] = []
        self.config_updates: list[dict[str, Any]] = []
        self.restart_count = 0
        self.search_queries: list[dict[str, list[str]]] = []
        self.ask_bodies: list[dict[str, Any]] = []
        self.notion_push_bodies: list[dict[str, Any]] = []
        self.graph_build_bodies: list[dict[str, Any]] = []
        self.graph_submissions: list[dict[str, Any]] = []
        # 全文读门禁：单个用例可调大文档长度/调小阈值来触发 409 预览。
        self.doc_chars = 100
        self.confirm_threshold = 60000


class _Handler(BaseHTTPRequestHandler):
    state: _State

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _json(self, status: int, value: Any, *, cookie: str | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        assert isinstance(payload, dict)
        return payload

    def _logged_in(self) -> bool:
        return "kr_session=test-session" in self.headers.get("Cookie", "")

    def _reject_if_unauthenticated(self) -> bool:
        if self.state.auth_required and not self._logged_in():
            self._json(401, {"error": "authentication required"})
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/api/auth":
            self._json(
                200,
                {
                    "auth_required": self.state.auth_required,
                    "logged_in": not self.state.auth_required or self._logged_in(),
                },
            )
            return
        if self._reject_if_unauthenticated():
            return
        if parsed.path == "/api/collections":
            self._json(
                200,
                [
                    {
                        "name": "papers",
                        "coll_key": "Lpapers",
                        "parent_key": "",
                    }
                ],
            )
        elif parsed.path == "/api/kb/collections":
            self._json(200, ["papers"])
        elif parsed.path == "/api/documents":
            self._json(
                200,
                [
                    {
                        "doc_id": "d1",
                        "title": "Alpha Paper",
                        "filename": "alpha.pdf",
                        "collection": "papers",
                        "tags": ["theory"],
                        "lifecycle_state": "active",
                        "zotero_meta": {
                            "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
                            "year": "2024",
                            "doi": "10.1000/alpha",
                        },
                    },
                    {
                        "doc_id": "d2",
                        "title": "Beta Notes",
                        "filename": "beta.pdf",
                        "collection": "papers",
                        "tags": ["method"],
                        "lifecycle_state": "active",
                        "zotero_meta": {"creators": ["Grace Hopper"], "year": "2023"},
                    },
                ],
            )
        elif parsed.path == "/api/kb/search":
            params = parse_qs(parsed.query, keep_blank_values=True)
            self.state.search_queries.append(params)
            query = params.get("q", [""])[0]
            long_text = "Alpha evidence " + ("x" * 700)
            alpha = {
                "chunk_id": "c1",
                "doc_id": "d1",
                "ordinal": 2,
                "text": long_text,
                "page": 7,
                "context_before": [{"text": "Alpha context"}],
                "context_after": [],
            }
            shared = {
                "chunk_id": "c2",
                "doc_id": "d2",
                "ordinal": 4,
                "text": "Shared mechanism evidence",
                "page": 9,
                "context_before": [],
                "context_after": [],
            }
            duplicate = {**alpha, "chunk_id": "different-id", "doc_id": "d2"}
            self._json(200, [alpha, shared] if "alpha" in query else [shared, duplicate])
        elif parsed.path == "/api/config/effective":
            self._json(
                200,
                {
                    "embedding": {"provider": "local", "api_key": "server-secret"},
                    "notion_sync": {
                        "enabled": True,
                        "qa_database_id": "qa-configured",
                        "sync_mode": "preserve",
                    },
                    "web_console": {"password": "server-password"},
                },
            )
        elif parsed.path == "/api/documents/d1/content/page":
            params = parse_qs(parsed.query)
            # doc_chars 让单个用例决定文档长度；默认 100 保持既有用例的期望值不变。
            content = "0123456789" * (self.state.doc_chars // 10)
            threshold = self.state.confirm_threshold
            start = int(params.get("start", ["0"])[0])
            max_chars = int(params.get("max_chars", ["12000"])[0])
            confirmed = params.get("confirmed", ["0"])[0] in {"1", "true", "yes"}
            end = len(content) if max_chars == 0 else min(len(content), start + max_chars)
            if not confirmed and end - start > threshold:
                self._json(
                    409,
                    {
                        "status": "fulltext_confirmation_required",
                        "message": "confirmation required",
                        "doc_id": "d1",
                        "title": "Long Paper",
                        "total_chars": len(content),
                        "requested_chars": end - start,
                        "threshold_chars": threshold,
                        "estimated_tokens": (end - start) // 4,
                    },
                )
                return
            self._json(
                200,
                {
                    "doc_id": "d1",
                    "start": start,
                    "end": end,
                    "total_chars": len(content),
                    "has_more": end < len(content),
                    "content": content[start:end],
                },
            )
        elif parsed.path == "/api/graph/codex-build/job-1/next":
            self._json(
                200,
                {
                    "job": {"job_id": "job-1", "status": "waiting_agent"},
                    "task": {"task_id": "task-1", "content": "Ada created Alpha."},
                    "complete": False,
                    "plugin_llm_used": False,
                },
            )
        elif parsed.path == "/api/graph/build/job-1":
            self._json(200, {"job_id": "job-1", "status": "success"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/api/login":
            body = self._body()
            self.state.login_bodies.append(body)
            if body == {"username": "admin", "password": "correct-password"}:
                self._json(200, {"ok": True}, cookie="kr_session=test-session; Path=/; HttpOnly")
            else:
                self._json(401, {"error": "invalid credentials"})
            return
        if self._reject_if_unauthenticated():
            return
        if parsed.path == "/api/ask/evidence":
            body = self._body()
            self.state.ask_bodies.append(body)
            self._json(
                200,
                {
                    "question": body["question"],
                    "collection": body.get("collection", ""),
                    "requested_retrieval_mode": body["retrieval_mode"],
                    "actual_retrieval_mode": f"agent_{body['retrieval_mode']}",
                    "round": body["round"],
                    "queries": body["queries"],
                    "limits": {"max_queries_per_round": 4, "max_rounds": 2},
                    "evidence": [
                        {
                            "n": 1,
                            "doc_id": "d1",
                            "title": "Alpha Paper",
                            "chunk_id": "c1",
                            "text": "Alpha evidence",
                        }
                    ],
                    "requires_agent_assessment": True,
                    "plugin_llm_used": False,
                    "full_text_used": False,
                },
            )
        elif parsed.path == "/api/notion/push-note":
            body = self._body()
            self.state.notion_push_bodies.append(body)
            if body.get("title") == "暂存问题":
                self._json(
                    200,
                    {
                        "status": "partial",
                        "outbox_id": "outbox-queued",
                        "message": "queued for retry",
                    },
                )
            else:
                self._json(
                    200,
                    {
                        "status": "success",
                        "page_id": f"qa-page-{len(self.state.notion_push_bodies)}",
                        "outbox_id": f"outbox-{len(self.state.notion_push_bodies)}",
                    },
                )
        elif parsed.path == "/api/graph/build/estimate":
            body = self._body()
            self._json(
                200,
                {
                    "collection": body["collection"],
                    "documents": 2,
                    "lrag_chunks": 3,
                },
            )
        elif parsed.path == "/api/graph/codex-build":
            body = self._body()
            self.state.graph_build_bodies.append(body)
            self._json(
                200,
                {
                    "job_id": "job-1",
                    "status": "waiting_agent",
                    "plugin_llm_used": False,
                },
            )
        elif parsed.path == "/api/graph/codex-build/job-1/submit":
            body = self._body()
            self.state.graph_submissions.append(body)
            self._json(200, {"accepted": True, "plugin_llm_used": False})
        elif parsed.path == "/api/graph/codex-build/job-1/retry":
            body = self._body()
            self._json(200, {"task_id": body["task_id"], "status": "pending"})
        elif parsed.path == "/api/config/update":
            body = self._body()
            self.state.config_updates.append(body)
            rebuild = body.get("section") == "embedding"
            self._json(
                200,
                {
                    "status": "success",
                    "restart_required": rebuild,
                    "rebuild_required": rebuild,
                },
            )
        elif parsed.path == "/api/plugin/restart":
            self._body()
            self.state.restart_count += 1
            self._json(200, {"status": "restarting"})
        else:
            self._json(404, {"error": "not found"})


@contextmanager
def _mock_api(*, auth_required: bool = False) -> Iterator[tuple[_State, str]]:
    state = _State(auth_required=auth_required)

    class Handler(_Handler):
        pass

    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield state, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_doctor_and_catalog_use_read_only_endpoints() -> None:
    with _mock_api() as (state, url):
        client = CLIENT.KnowledgeArchClient(url)
        result = CLIENT.doctor(client)
        catalog = CLIENT.catalog(client, "Ada Alpha", 20)
    assert result["status"] == "ok"
    assert result["plugin_llm_used"] is False
    assert catalog["documents"][0]["doc_id"] == "d1"
    assert catalog["documents"][0]["authors"] == ["Ada Lovelace"]
    assert state.config_updates == []


def test_authentication_uses_environment_only_password(monkeypatch: pytest.MonkeyPatch) -> None:
    with _mock_api(auth_required=True) as (state, url):
        monkeypatch.setenv("KNOWLEDGE_ARCH_URL", url)
        monkeypatch.setenv("KNOWLEDGE_ARCH_USERNAME", "admin")
        monkeypatch.setenv("KR_WEB_PASSWORD", "correct-password")
        result = CLIENT.doctor(CLIENT.KnowledgeArchClient.from_env())
    assert result["auth_required"] is True
    assert state.login_bodies == [{"username": "admin", "password": "correct-password"}]
    assert "password" not in CLIENT.build_parser().format_help().lower()
    assert "correct-password" not in json.dumps(result)


def test_missing_password_and_connection_failure_are_actionable() -> None:
    with _mock_api(auth_required=True) as (_state, url):
        with pytest.raises(CLIENT.AuthenticationError, match="KR_WEB_PASSWORD"):
            CLIENT.doctor(CLIENT.KnowledgeArchClient(url))

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(CLIENT.ConnectionFailure, match="Cannot reach Knowledge Arch"):
        CLIENT.doctor(CLIENT.KnowledgeArchClient(f"http://127.0.0.1:{port}"))


def test_connection_status_requires_explicit_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """首次使用不猜测本机端口或用户名，必须先登记。"""
    for variable in (
        "KNOWLEDGE_ARCH_URL",
        "KNOWLEDGE_ARCH_USERNAME",
        "KR_WEB_PASSWORD",
    ):
        monkeypatch.delenv(variable, raising=False)
    config_path = tmp_path / "connection.json"

    assert CLIENT.connection_status(config_path) == {"status": "unconfigured"}
    with pytest.raises(CLIENT.ConnectionNotConfigured, match="connection-setup"):
        CLIENT.resolve_connection_client(path=config_path)


def test_connection_setup_stores_only_non_secret_profile_and_resolves(
    tmp_path: Path,
) -> None:
    """成功登记先验证，密码只进入凭据库，后续可被安全解析。"""
    config_path = tmp_path / "connection.json"
    store = _MemoryCredentialStore()
    with _mock_api(auth_required=True) as (state, url):
        answers = iter([url, "admin"])
        result = CLIENT.connection_setup(
            path=config_path,
            credential_store=store,
            input_func=lambda _prompt: next(answers),
            password_func=lambda _prompt: "correct-password",
        )
        client, source = CLIENT.resolve_connection_client(
            path=config_path, credential_store=store
        )
        doctor = CLIENT.doctor(client)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    saved_text = json.dumps(saved)
    assert result == {
        "status": "configured",
        "auth_required": True,
        "credential_stored": True,
    }
    assert CLIENT.connection_status(config_path) == {"status": "configured"}
    assert source == "configured"
    assert doctor["status"] == "ok"
    assert "password" not in saved
    assert "correct-password" not in saved_text
    assert len(store.passwords) == 1
    assert state.login_bodies == [
        {"username": "admin", "password": "correct-password"},
        {"username": "admin", "password": "correct-password"},
    ]


def test_connection_setup_rolls_back_on_verification_or_profile_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """验证或原子配置写入失败时均不残留新配置或密码。"""
    config_path = tmp_path / "connection.json"
    store = _MemoryCredentialStore()
    with _mock_api(auth_required=True) as (_state, url):
        answers = iter([url, "admin"])
        with pytest.raises(CLIENT.AuthenticationError):
            CLIENT.connection_setup(
                path=config_path,
                credential_store=store,
                input_func=lambda _prompt: next(answers),
                password_func=lambda _prompt: "wrong-password",
            )
    assert not config_path.exists()
    assert store.passwords == {}

    with _mock_api(auth_required=True) as (_state, url):
        monkeypatch.setattr(
            CLIENT,
            "_write_connection_profile",
            lambda _profile, _path=None: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        answers = iter([url, "admin"])
        with pytest.raises(OSError, match="disk unavailable"):
            CLIENT.connection_setup(
                path=config_path,
                credential_store=store,
                input_func=lambda _prompt: next(answers),
                password_func=lambda _prompt: "correct-password",
            )
    assert not config_path.exists()
    assert store.passwords == {}
    assert store.deleted


def test_connection_setup_replaces_old_credential_only_after_new_registration(
    tmp_path: Path,
) -> None:
    """替换成功后才删除旧凭据，避免失败时丢失可用连接。"""
    config_path = tmp_path / "connection.json"
    store = _MemoryCredentialStore()
    old_id = CLIENT._credential_id("http://old-instance.invalid", "old-user")
    store.set_password(CLIENT.CONNECTION_KEYRING_SERVICE, old_id, "old-password")
    CLIENT._write_connection_profile(
        CLIENT.ConnectionProfile(
            base_url="http://old-instance.invalid",
            username="old-user",
            credential_id=old_id,
        ),
        config_path,
    )
    with _mock_api(auth_required=True) as (_state, url):
        answers = iter(["y", url, "admin"])
        CLIENT.connection_setup(
            path=config_path,
            credential_store=store,
            input_func=lambda _prompt: next(answers),
            password_func=lambda _prompt: "correct-password",
        )

    assert (CLIENT.CONNECTION_KEYRING_SERVICE, old_id) in store.deleted
    assert old_id not in {account for _service, account in store.passwords}
    assert CLIENT.load_connection_profile(config_path).username == "admin"


def test_temporary_connection_override_never_reuses_registered_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """开发者临时 URL/用户名覆盖不读取、发送或写回日常实例密码。"""
    config_path = tmp_path / "connection.json"
    store = _MemoryCredentialStore()
    credential_id = CLIENT._credential_id("http://registered.invalid", "registered")
    store.set_password(CLIENT.CONNECTION_KEYRING_SERVICE, credential_id, "stored-secret")
    CLIENT._write_connection_profile(
        CLIENT.ConnectionProfile(
            base_url="http://registered.invalid",
            username="registered",
            credential_id=credential_id,
        ),
        config_path,
    )
    monkeypatch.setenv("KNOWLEDGE_ARCH_URL", "http://temporary.invalid")
    monkeypatch.setenv("KNOWLEDGE_ARCH_USERNAME", "developer")
    monkeypatch.delenv("KR_WEB_PASSWORD", raising=False)

    client, source = CLIENT.resolve_connection_client(
        path=config_path, credential_store=store
    )

    assert CLIENT.connection_status(config_path) == {"status": "environment_override"}
    assert source == "environment_override"
    assert client.username == "developer"
    assert client._password is None
    assert CLIENT.load_connection_profile(config_path).username == "registered"


def test_credential_store_failure_is_actionable_and_never_writes_a_profile(
    tmp_path: Path,
) -> None:
    """无法使用系统凭据库时拒绝明文降级，并保留未登记状态。"""
    config_path = tmp_path / "connection.json"
    store = _MemoryCredentialStore()
    store.fail_on_set = True
    with _mock_api(auth_required=True) as (_state, url):
        answers = iter([url, "admin"])
        with pytest.raises(CLIENT.CredentialStoreUnavailable):
            CLIENT.connection_setup(
                path=config_path,
                credential_store=store,
                input_func=lambda _prompt: next(answers),
                password_func=lambda _prompt: "correct-password",
            )
    assert not config_path.exists()


def test_skill_requires_explicit_connection_and_external_authorization() -> None:
    """分发 Skill 不得包含机器端口，并锁定首次连接与联网授权边界。"""
    source = SKILL_PATH.read_text(encoding="utf-8")
    assert "9821" not in source
    assert "connection-status" in source
    assert "connection-setup" in source
    assert "unless the user explicitly grants permission" in source
    assert "windows sandbox: helper_unknown_error: apply deny-read ACLs" in source
    assert "Do not rerun `doctor`" in source
    assert "notion-save-qa" in source
    assert "qa_database_id" in source
    assert "Never create a loose Notion page" in source


def test_notion_save_qa_uses_configured_database_and_preserves_partial_results(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "conversation.json"
    payload_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "question": "问题一",
                        "answer": "回答一",
                        "tags": ["conversation"],
                        "citations": ["d1"],
                    },
                    {"question": "暂存问题", "answer": "回答二"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with _mock_api() as (state, url):
        result = CLIENT.notion_save_qa(CLIENT.KnowledgeArchClient(url), str(payload_path))

    assert result["status"] == "partial"
    assert result["target_database_id"] == "qa-configured"
    assert result["pushed_count"] == 1
    assert result["queued_count"] == 1
    assert result["failed_count"] == 0
    assert state.notion_push_bodies == [
        {
            "content": "回答一",
            "title": "问题一",
            "tags": ["conversation"],
            "citations": ["d1"],
            "source": "codex",
            "keep_local": False,
        },
        {
            "content": "回答二",
            "title": "暂存问题",
            "tags": [],
            "citations": [],
            "source": "codex",
            "keep_local": False,
        },
    ]


def test_notion_save_qa_requires_configured_qa_database(tmp_path: Path) -> None:
    payload_path = tmp_path / "conversation.json"
    payload_path.write_text(
        json.dumps({"items": [{"question": "Q", "answer": "A"}]}),
        encoding="utf-8",
    )

    class MissingQaDatabaseClient:
        def request_json(self, path: str, **_kwargs: Any) -> dict[str, Any]:
            assert path == "/api/config/effective"
            return {"notion_sync": {"enabled": True, "qa_database_id": ""}}

    with pytest.raises(CLIENT.UsageError, match="qa_database_id"):
        CLIENT.notion_save_qa(MissingQaDatabaseClient(), str(payload_path))


def test_search_fuses_queries_deduplicates_content_and_caps_text() -> None:
    with _mock_api() as (state, url):
        result = CLIENT.search(
            CLIENT.KnowledgeArchClient(url),
            ["alpha concept", "beta mechanism"],
            [""],
            top_k=8,
            window=1,
            limit=99,
            max_chars=250,
        )
    assert result["collections"] == ["all"]
    assert result["result_count"] == 2
    assert {hit["chunk_id"] for hit in result["hits"]} == {"c1", "c2"}
    assert all(len(hit["text"]) <= 250 for hit in result["hits"])
    alpha = next(hit for hit in result["hits"] if hit["chunk_id"] == "c1")
    assert alpha["title"] == "Alpha Paper"
    assert alpha["page"] == 7
    assert len(alpha["matched_queries"]) == 2
    assert all(params["collection"] == [""] for params in state.search_queries)


def test_search_rejects_unbounded_query_fanout() -> None:
    with _mock_api() as (_state, url):
        with pytest.raises(CLIENT.UsageError, match="At most 4 queries"):
            CLIENT.search(
                CLIENT.KnowledgeArchClient(url),
                ["1", "2", "3", "4", "5"],
                [""],
                top_k=8,
                window=1,
                limit=10,
                max_chars=1600,
            )


def test_ask_evidence_preserves_agent_reasoning_boundary() -> None:
    with _mock_api() as (state, url):
        result = CLIENT.ask_evidence(
            CLIENT.KnowledgeArchClient(url),
            "Compare Alpha and Beta",
            ["alpha mechanism", "beta mechanism"],
            "papers",
            mode="enhanced",
            round_number=1,
        )
    assert result["actual_retrieval_mode"] == "agent_enhanced"
    assert result["requires_agent_assessment"] is True
    assert result["plugin_llm_used"] is False
    assert result["full_text_used"] is False
    assert state.ask_bodies == [
        {
            "question": "Compare Alpha and Beta",
            "queries": ["alpha mechanism", "beta mechanism"],
            "collection": "papers",
            "retrieval_mode": "enhanced",
            "round": 1,
        }
    ]


def test_read_document_pages_without_dumping_full_text() -> None:
    with _mock_api() as (_state, url):
        result = CLIENT.read_document(
            CLIENT.KnowledgeArchClient(url), "d1", 10, 25, intent="anchored"
        )
    assert result == {
        "doc_id": "d1",
        "start": 10,
        "end": 35,
        "total_chars": 100,
        "has_more": True,
        "content": "0123456789012345678901234",
        "read_intent": "anchored",
        "full_text_used": True,
    }


def test_read_document_requires_explicit_intent() -> None:
    with _mock_api() as (_state, url):
        with pytest.raises(CLIENT.UsageError, match="read requires --intent"):
            CLIENT.read_document(
                CLIENT.KnowledgeArchClient(url), "d1", 0, 10, intent=""
            )


def test_distribution_policy_snapshot_matches_config_truth_source() -> None:
    expected = {
        section: {
            key: policy.consequence
            for key, policy in policies.items()
            if policy.api_writable and not policy.structural
        }
        for section, policies in CONFIG_KEY_POLICY.items()
        if any(policy.api_writable and not policy.structural for policy in policies.values())
    }
    assert CLIENT.CONFIG_POLICIES == expected


def test_config_preview_apply_whitelist_and_redaction() -> None:
    with _mock_api() as (state, url):
        client = CLIENT.KnowledgeArchClient(url)
        preview = CLIENT.config_set(client, "embedding", "provider", "external", apply=False)
        assert state.config_updates == []
        assert preview["consequence"] == "rebuild"
        assert preview["mutation_performed"] is False

        applied = CLIENT.config_set(client, "embedding", "provider", "external", apply=True)
        shown = CLIENT.config_show(client, None)
        with pytest.raises(CLIENT.UsageError, match="not runtime-writable"):
            CLIENT.config_set(client, "web_console", "password", "leak", apply=True)

    assert state.config_updates == [
        {"section": "embedding", "key": "provider", "value": "external"}
    ]
    assert applied["mutation_performed"] is True
    assert shown["embedding"]["api_key"] == "[redacted]"
    assert shown["web_console"]["password"] == "[redacted]"
    assert "server-secret" not in json.dumps(shown)
    assert "server-password" not in json.dumps(shown)


def test_restart_has_a_separate_apply_gate() -> None:
    with _mock_api() as (state, url):
        client = CLIENT.KnowledgeArchClient(url)
        preview = CLIENT.restart(client, apply=False)
        assert preview["requires_explicit_confirmation"] is True
        assert state.restart_count == 0
        applied = CLIENT.restart(client, apply=True)
    assert applied["mutation_performed"] is True
    assert state.restart_count == 1


def test_codex_graph_build_is_previewed_and_uses_task_protocol() -> None:
    with _mock_api() as (state, url):
        client = CLIENT.KnowledgeArchClient(url)
        preview = CLIENT.graph_codex_build(client, "papers", apply=False)
        assert preview["mutation_performed"] is False
        assert preview["embedding_provider_will_be_used"] is True
        assert state.graph_build_bodies == []

        started = CLIENT.graph_codex_build(client, "papers", apply=True)
        task = CLIENT.graph_next(client, "job-1")
        submitted = CLIENT.graph_submit(
            client,
            "job-1",
            "task-1",
            {
                "entities": [
                    {
                        "entity_name": "Ada",
                        "entity_type": "PERSON",
                        "description": "Researcher",
                    }
                ],
                "relationships": [],
            },
        )
        status = CLIENT.graph_status(client, "job-1")

    assert started["job_id"] == "job-1"
    assert task["task"]["task_id"] == "task-1"
    assert submitted["accepted"] is True
    assert status["status"] == "success"
    assert state.graph_build_bodies == [{"collection": "papers", "confirmed": True}]
    assert state.graph_submissions[0]["task_id"] == "task-1"


def test_client_exposes_only_agent_evidence_and_guarded_graph_builds() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert '"/api/ask/evidence"' in source
    assert '"/api/ask"' not in source
    assert '"/api/graph/codex-build"' in source
    assert '"/api/graph/build"' not in source
    assert '"/api/documents/rebuild-index"' not in source
    assert '/content/page"' in source


def test_fresh_process_cli_notion_save_qa(tmp_path: Path) -> None:
    payload_path = tmp_path / "conversation.json"
    payload_path.write_text(
        json.dumps({"items": [{"question": "CLI 问题", "answer": "CLI 回答"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    with _mock_api() as (state, url):
        env = os.environ.copy()
        env["KNOWLEDGE_ARCH_URL"] = url
        env["KNOWLEDGE_ARCH_USERNAME"] = "admin"
        env.pop("KR_WEB_PASSWORD", None)
        saved = subprocess.run(
            [
                sys.executable,
                str(CLIENT_PATH),
                "notion-save-qa",
                "--input-file",
                str(payload_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=10,
        )

    assert saved.returncode == 0, saved.stderr
    assert json.loads(saved.stdout)["status"] == "success"
    assert state.notion_push_bodies[0]["title"] == "CLI 问题"


def test_fresh_process_cli_research_and_config_preview() -> None:
    """用隔离 Python 进程模拟 Codex 只读研究与配置预览两条真实命令链。"""
    with _mock_api() as (state, url):
        env = os.environ.copy()
        env["KNOWLEDGE_ARCH_URL"] = url
        env["KNOWLEDGE_ARCH_USERNAME"] = "admin"
        env.pop("KR_WEB_PASSWORD", None)
        research = subprocess.run(
            [
                sys.executable,
                str(CLIENT_PATH),
                "ask-evidence",
                "--question",
                "What is Alpha?",
                "--query",
                "alpha concept",
                "--mode",
                "default",
                "--all",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=10,
        )
        preview = subprocess.run(
            [
                sys.executable,
                str(CLIENT_PATH),
                "config-set",
                "embedding",
                "provider",
                "external",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=10,
        )

    assert research.returncode == 0, research.stderr
    assert json.loads(research.stdout)["plugin_llm_used"] is False
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["status"] == "preview"
    assert state.config_updates == []


def test_read_document_small_document_needs_no_confirmation() -> None:
    """低于阈值零摩擦：整篇读（--whole → max_chars=0）也直接返回正文。"""
    with _mock_api() as (_state, url):
        result = CLIENT.read_document(
            CLIENT.KnowledgeArchClient(url), "d1", 0, 0, intent="full-text"
        )
    assert result["full_text_used"] is True
    assert len(result["content"]) == 100
    assert "requires_explicit_confirmation" not in result


def test_read_document_large_document_previews_before_returning_text() -> None:
    """超阈值单次读取只回预览，**绝不夹带正文**。"""
    with _mock_api() as (state, url):
        state.doc_chars = 200_000
        result = CLIENT.read_document(
            CLIENT.KnowledgeArchClient(url), "d1", 0, 0, intent="full-text"
        )
    assert result["status"] == "preview"
    assert result["requires_explicit_confirmation"] is True
    assert result["content_returned"] is False
    assert result["full_text_used"] is False
    assert result["total_chars"] == 200_000
    assert result["confirm_threshold_chars"] == 60000
    assert "content" not in result


def test_read_document_confirmed_returns_whole_document() -> None:
    """确认后拿到全文；长度 > 40000 证明旧的客户端硬上限已拆除。"""
    with _mock_api() as (state, url):
        state.doc_chars = 200_000
        result = CLIENT.read_document(
            CLIENT.KnowledgeArchClient(url),
            "d1",
            0,
            0,
            intent="full-text",
            confirm_large_read=True,
        )
    assert result["full_text_used"] is True
    assert len(result["content"]) == 200_000
    assert result["has_more"] is False


def test_read_document_paging_below_threshold_never_trips_the_gate() -> None:
    """门禁按单次返回量判定：长文档的小分页读不应被拦。"""
    with _mock_api() as (state, url):
        state.doc_chars = 200_000
        result = CLIENT.read_document(
            CLIENT.KnowledgeArchClient(url), "d1", 0, 12000, intent="anchored"
        )
    assert result["full_text_used"] is True
    assert len(result["content"]) == 12000


def test_read_document_rejects_negative_max_chars() -> None:
    with _mock_api() as (_state, url):
        with pytest.raises(CLIENT.UsageError, match="zero or greater"):
            CLIENT.read_document(
                CLIENT.KnowledgeArchClient(url), "d1", 0, -1, intent="anchored"
            )
