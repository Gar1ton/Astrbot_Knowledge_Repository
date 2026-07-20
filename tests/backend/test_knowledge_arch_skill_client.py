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
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client_module()


class _State:
    def __init__(self, *, auth_required: bool = False) -> None:
        self.auth_required = auth_required
        self.login_bodies: list[dict[str, Any]] = []
        self.config_updates: list[dict[str, Any]] = []
        self.restart_count = 0
        self.search_queries: list[dict[str, list[str]]] = []
        self.ask_bodies: list[dict[str, Any]] = []
        self.graph_build_bodies: list[dict[str, Any]] = []
        self.graph_submissions: list[dict[str, Any]] = []


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
                    "notion_sync": {"sync_mode": "preserve"},
                    "web_console": {"password": "server-password"},
                },
            )
        elif parsed.path == "/api/documents/d1/content/page":
            params = parse_qs(parsed.query)
            content = "0123456789" * 10
            start = int(params.get("start", ["0"])[0])
            max_chars = int(params.get("max_chars", ["12000"])[0])
            end = min(len(content), start + max_chars)
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


def test_fresh_process_cli_research_and_config_preview() -> None:
    """用隔离 Python 进程模拟 Codex 只读研究与配置预览两条真实命令链。"""
    with _mock_api() as (state, url):
        env = os.environ.copy()
        env["KNOWLEDGE_ARCH_URL"] = url
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
