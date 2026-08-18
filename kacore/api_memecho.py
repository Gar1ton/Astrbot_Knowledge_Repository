"""MemEcho（MemoryEcho）召回公开门面（api mixin，分支 Experiment-with-MemEcho-API 新增）。

把 MemoryEcho 托管记忆 API 的 key 管理 / 探针 / vault / 集合导入，以及 `ask()` 的
`memecho` 分支编排收拢在本 mixin；组合进 KnowledgeRepositoryApi 使用。真正的 HTTP
翻译在 `kacore/adapters/memecho/client.py`，召回/写回/导入编排在
`kacore/pipelines/memecho_recall.py`——本文件只做「面向调用方的门面」，与
`kacore/api_capabilities.py`（CapabilitiesApiMixin）同一拆分模式：把体量较大、边界
清晰的一整块公开方法迁出 `api.py` 主体，减小其代码量并方便未来单独同步这块代码。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kacore.adapters.memecho.client import MemEchoError
from kacore.config import ENV_MEMECHO_API_KEY
from kacore.retrieval_modes import MODE_MEMECHO

if TYPE_CHECKING:
    from kacore.adapters.llm import LLMAdapter
    from kacore.config import Config
    from kacore.pipelines.memecho_recall import MemEchoRecall
    from kacore.repository.source_store.base import SourceDocumentStore
    from kacore.secret_store import EncryptedSecretStore

logger = logging.getLogger("KnowledgeRepositoryApi")

MEMECHO_API_KEY_SECRET = "memecho.api_key"


class MemEchoApiMixin:
    """MemEcho 记忆库 key/探针/vault/导入门面；组合进 KnowledgeRepositoryApi 使用。

    真正的检索分支跳转仍留在 `api.py::ask()` 内（见 `_retrieve_and_generate()` 顶部），
    与 `MODE_FULLTEXT` 自己的派发一样，不能搬进本 mixin——那是中央调度点。
    """

    _config: Config | None
    _secret_store: EncryptedSecretStore | None
    _source_store: SourceDocumentStore
    _llm_adapter: LLMAdapter | None
    _memecho_recall: MemEchoRecall | None

    def _memecho_api_key(self) -> str:
        """解析 MemEcho API Key：加密 secret_store 优先，环境变量回退。"""
        if self._secret_store is not None:
            key = self._secret_store.get_secret(MEMECHO_API_KEY_SECRET)
            if key:
                return key
        import os

        return os.environ.get(ENV_MEMECHO_API_KEY, "") or ""

    def _build_memecho_client(self) -> Any | None:
        """按 config + 已配置 key 构造一个瞬时 MemEchoClient；无 key 返回 None。"""
        key = self._memecho_api_key()
        if not key:
            return None
        from kacore.adapters.memecho.client import DEFAULT_BASE_URL, MemEchoClient

        cfg = self._config.get_memecho_config() if self._config else None
        base_url = cfg.base_url if cfg else DEFAULT_BASE_URL
        timeout = cfg.timeout_seconds if cfg else 30
        import_timeout = cfg.import_timeout_seconds if cfg else None
        return MemEchoClient(
            base_url,
            key,
            timeout_seconds=timeout,
            import_timeout_seconds=import_timeout,
        )

    def _build_memecho_recall(self) -> Any | None:
        """优先用组合根注入的召回门面；否则按需构造瞬时门面（供探针/建库/导入复用）。"""
        if self._memecho_recall is not None:
            return self._memecho_recall
        client = self._build_memecho_client()
        if client is None:
            return None
        from kacore.pipelines.memecho_recall import MemEchoRecall

        return MemEchoRecall(client)

    async def get_memecho_config(self) -> dict[str, Any]:
        """返回 MemEcho 配置 + 密钥存在态（供设置页与 flow 面板）。"""
        from kacore.api import _mask_secret

        if self._config is None:
            return {"enabled": False, "api_key_present": False}
        cfg = self._config.get_memecho_config()
        key = self._memecho_api_key()
        return {
            "enabled": cfg.enabled,
            "base_url": cfg.base_url,
            "default_vault_id": cfg.default_vault_id,
            "query_readonly": cfg.query_readonly,
            "write_back_enabled": cfg.write_back_enabled,
            "timeout_seconds": cfg.timeout_seconds,
            "import_timeout_seconds": cfg.import_timeout_seconds,
            "import_preset": cfg.import_preset,
            "api_key_present": bool(key),
            "api_key_masked": _mask_secret(key),
        }

    async def save_memecho_api_key(self, api_key: str) -> dict[str, Any]:
        """保存 MemEcho API Key 到加密 secret_store，并刷新 runtime 存在态。"""
        cleaned = (api_key or "").strip()
        if not cleaned:
            raise ValueError("MemEcho API key is required")
        if self._secret_store is None:
            raise RuntimeError("Secret store is unavailable")
        self._secret_store.set_secret(MEMECHO_API_KEY_SECRET, cleaned)
        if self._config is not None:
            self._config.runtime_memecho_key_present = bool(self._memecho_api_key())
        return await self.get_memecho_config()

    async def delete_memecho_api_key(self) -> dict[str, Any]:
        """删除已存的 MemEcho API Key（env 注入的回退仍可能存在）。"""
        if self._secret_store is not None:
            self._secret_store.delete_secret(MEMECHO_API_KEY_SECRET)
        if self._config is not None:
            self._config.runtime_memecho_key_present = bool(self._memecho_api_key())
        return await self.get_memecho_config()

    async def probe_memecho(self) -> dict[str, Any]:
        """MemEcho 连通性探针：列出 vault + 用量（只读，不改动云端）。"""
        client = self._build_memecho_client()
        if client is None:
            return {"ok": False, "error": "MemEcho API Key 未配置"}
        return await client.probe()

    async def list_memecho_vaults(self) -> list[dict[str, Any]]:
        client = self._build_memecho_client()
        if client is None:
            raise ValueError("MemEcho API Key 未配置")
        return await client.list_vaults()

    async def create_memecho_vault(
        self, name: str, description: str = ""
    ) -> dict[str, Any]:
        client = self._build_memecho_client()
        if client is None:
            raise ValueError("MemEcho API Key 未配置")
        return await client.create_vault(name or "knowledge-arch", description)

    async def import_collection_to_memecho(
        self,
        collection: str,
        *,
        vault_id: str = "",
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """把某集合的文档逐篇导入到指定 vault（未指定则用 default_vault_id）。"""
        recall = self._build_memecho_recall()
        if recall is None:
            raise ValueError("MemEcho API Key 未配置")
        cfg = self._config.get_memecho_config() if self._config else None
        target_vault = vault_id or (cfg.default_vault_id if cfg else "")
        if not target_vault:
            raise ValueError("未指定 vault_id 且 memecho.default_vault_id 为空")
        preset = cfg.import_preset if cfg else "default"
        docs: list[dict[str, Any]] = []
        for doc in await self._source_store.list_documents():
            if collection and doc.collection != collection:
                continue
            chunks = await self._source_store.list_chunks(doc.doc_id)
            content = "\n\n".join(
                c.text for c in sorted(chunks, key=lambda x: x.ordinal) if c.text
            )
            if not content:
                continue
            docs.append(
                {"doc_id": doc.doc_id, "title": doc.title or doc.doc_id, "content": content}
            )
        return await recall.import_documents(
            target_vault, docs, preset=preset, progress_cb=progress_cb
        )

    async def _ask_memecho(
        self,
        *,
        question: str,
        cid: str,
        answer_language: str,
        ask_start: float,
        progress: Callable[..., None],
        record: Callable[..., None],
    ) -> dict:
        """memecho 模式：查 MemoryEcho 记忆库 → 合成作答 →（可选）写回 → 持久化 → 返回。"""
        if self._memecho_recall is None:
            raise RuntimeError(
                "MemEcho 召回未装配：请开启 memecho.enabled 并配置 API Key 后重启插件。"
            )
        memecho_cfg = self._config.get_memecho_config() if self._config else None
        if memecho_cfg is None or not memecho_cfg.enabled:
            raise ValueError("memecho.enabled=false：请先在设置中启用 MemEcho 召回。")
        vault_id = memecho_cfg.default_vault_id
        if not vault_id:
            raise ValueError(
                "memecho.default_vault_id 为空：请先在 MemEcho 面板选择或新建记忆库。"
            )

        progress("memecho_recall", 30)
        t_recall = time.monotonic()
        try:
            recall = await self._memecho_recall.recall(
                question, vault_id, readonly=memecho_cfg.query_readonly
            )
        except MemEchoError as exc:
            raise RuntimeError(f"MemEcho 召回失败：{exc}") from exc
        record(
            "memecho_recall", t_recall, sources=len(recall.sources), degraded=recall.degraded
        )

        progress("llm_generate", 80)
        t_llm = time.monotonic()
        if self._llm_adapter is not None and recall.context:
            if answer_language == "zh":
                lang_instr = "Answer in Chinese (中文)."
            elif answer_language == "en":
                lang_instr = "Answer in English."
            else:
                lang_instr = "Answer in the same language as the question."
            system_prompt = (
                "You are a helpful assistant answering from the user's long-term memory. "
                "Answer the question based solely on the provided recalled memories. "
                "If the memories are insufficient, state the limitation clearly and only "
                "answer what they support. Do not fill gaps with outside knowledge. "
                f"{lang_instr}"
            )
            user_prompt = (
                f"Recalled memories:\n\n{recall.context}\n\nQuestion: {question}"
            )
            answer = await self._llm_adapter.generate(user_prompt, system_prompt=system_prompt)
        else:
            answer = recall.context or "未在 MemEcho 记忆库中找到与该问题相关的记忆。"
        record("llm_generate", t_llm)

        if memecho_cfg.write_back_enabled:
            await self._memecho_recall.write_back(vault_id, question, answer)

        record("ask_total", ask_start, sources=len(recall.sources))
        progress("done", 100)
        try:
            await self._source_store.add_chat_message(cid, "user", question)
            await self._source_store.add_chat_message(
                cid, "assistant", answer, sources=recall.sources, retrieval_mode="memecho"
            )
        except Exception as exc:
            logger.warning("Failed to persist chat history: %s", exc)
        return {
            "conversation_id": cid,
            "answer": answer,
            "sources": recall.sources,
            "requested_retrieval_mode": MODE_MEMECHO,
            "actual_retrieval_mode": "memecho",
            "retrieval_engines": ["memecho"],
            "fallback_reason": None,
            "degraded": recall.degraded,
        }
