"""MemEcho 召回编排（pipelines 层，分支 Experiment-with-MemEcho-API 新增）。

消费注入的 ``MemEchoClient``，把 MemoryEcho 的语义召回结果 shape 成 ask 下游可直接消费的
形状（合成上下文字符串 + sources 列表 + degraded 标记），并封装「问答写回」与「文件导入」编排。

定位：新检索方法 memecho，二选一独立——**不与本地 LightRAG/Milvus 结果融合**。
外部端点/密钥全部由注入的 client 持有，本管线不硬编码（遵循 pipelines/README 约定）。
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from kacore.adapters.memecho.client import MemEchoClient, MemEchoError, to_data_url

logger = logging.getLogger("MemEchoRecall")


@dataclass
class MemEchoRecallResult:
    """召回产物：合成上下文 + ask 下游 sources 形状 + 降级标记。"""

    context: str
    sources: list[dict[str, Any]]
    degraded: bool = False
    raw_results: list[Any] = field(default_factory=list)


class MemEchoRecall:
    """MemEcho 召回 / 写回 / 导入的编排门面。"""

    def __init__(self, client: MemEchoClient) -> None:
        self._client = client

    async def recall(
        self, question: str, vault_id: str, *, readonly: bool = True
    ) -> MemEchoRecallResult:
        """对 vault 做一次语义召回。readonly=True 走 /query-readonly（不留痕）。"""
        if not vault_id:
            raise ValueError(
                "memecho recall requires a vault_id (set memecho.default_vault_id)"
            )
        data = await (
            self._client.query_readonly(vault_id, question)
            if readonly
            else self._client.query(vault_id, question)
        )
        results = data.get("results") or []
        degraded = bool(data.get("degraded"))
        # query-readonly 降级：results 为空但带 messages 兜底（拿最近消息拼上下文）。
        if degraded and not results:
            messages = data.get("messages") or []
            sources = _sources_from_messages(messages)
            return MemEchoRecallResult(
                context=_context_from_sources(sources),
                sources=sources,
                degraded=True,
                raw_results=list(messages),
            )
        sources = _sources_from_results(results)
        return MemEchoRecallResult(
            context=_context_from_sources(sources),
            sources=sources,
            degraded=degraded,
            raw_results=list(results),
        )

    async def write_back(self, vault_id: str, question: str, answer: str) -> bool:
        """把本轮问答 append 回 vault 形成长期记忆。失败仅告警不抛（保非破坏）。"""
        if not vault_id:
            return False
        try:
            if question:
                await self._client.append_user_message(vault_id, question)
            if answer:
                await self._client.append_assistant_message(vault_id, answer)
            return True
        except MemEchoError as exc:
            logger.warning("memecho write_back failed (non-fatal): %s", exc)
            return False

    async def import_documents(
        self,
        vault_id: str,
        docs: Iterable[dict[str, Any]],
        *,
        preset: str = "default",
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """把一组文档逐个 import_file 到 vault；返回 {imported, failed, total}。

        docs 每项形如 {"doc_id", "title"?, "file_name"?, "content"|"text"}。
        单个失败（含超时/连接失败）记入 failed 不中断整体；progress_cb 每篇回报一次进度事件。
        """
        doc_list = list(docs)
        total = len(doc_list)
        imported = 0
        failed: list[dict[str, Any]] = []
        for idx, doc in enumerate(doc_list, start=1):
            doc_id = str(doc.get("doc_id") or "")
            file_name = _import_file_name(doc)
            content = str(doc.get("content") or doc.get("text") or "")
            try:
                events = await self._client.import_file(
                    vault_id, file_name, to_data_url(content), preset=preset
                )
                imported += 1
                _emit(
                    progress_cb,
                    {
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "status": "ok",
                        "index": idx,
                        "total": total,
                        "events": len(events),
                    },
                )
            except Exception as exc:
                # 兜底到 Exception 而非 MemEchoError：单篇失败绝不能打断整批。client 已把
                # 超时/连接错翻译成 MemEchoError，此处再兜一层防的是「将来某个新异常又逃逸」。
                message = str(exc) or type(exc).__name__
                failed.append(
                    {
                        "doc_id": doc_id,
                        "error": message,
                        "status": getattr(exc, "status", None),
                    }
                )
                logger.warning("memecho import failed for %s: %s", doc_id, message)
                _emit(
                    progress_cb,
                    {
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "status": "error",
                        "index": idx,
                        "total": total,
                        "error": message,
                    },
                )
        return {"imported": imported, "failed": failed, "total": total}


# ── 结果 shaping helper ───────────────────────────────────────────


def _sources_from_results(results: Iterable[Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for i, r in enumerate(results, start=1):
        if not isinstance(r, dict):
            sources.append(_source(i, "", str(r), "", None, {}))
            continue
        text = str(r.get("content") or r.get("text") or r.get("memory") or "")
        mem_id = str(r.get("id") or r.get("memory_id") or "")
        role = str(r.get("role") or "")
        score = r.get("score", r.get("similarity"))
        metadata = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        sources.append(_source(i, mem_id, text, role, score, metadata))
    return sources


def _sources_from_messages(messages: Iterable[Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for i, m in enumerate(messages, start=1):
        if not isinstance(m, dict):
            continue
        text = str(m.get("content") or "")
        metadata = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
        role = str(m.get("role") or "")
        sources.append(_source(i, str(m.get("id") or ""), text, role, None, metadata))
    return sources


def _source(
    n: int,
    mem_id: str,
    text: str,
    role: str,
    score: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    label = f"MemEcho:{mem_id[:8]}" if mem_id else f"MemEcho#{n}"
    return {
        "n": n,
        "doc_id": mem_id or label,
        "document_id": mem_id or label,
        "title": label,
        "chunk_id": mem_id or f"memecho-{n}",
        "ordinal": n,
        "text": text,
        "metadata": metadata,
        "origin": "memecho",
        "role": role,
        "score": score,
    }


def _context_from_sources(sources: Iterable[dict[str, Any]]) -> str:
    parts = [f"[{s['n']}] {s['text']}" for s in sources if s.get("text")]
    return "\n\n".join(parts)


def _import_file_name(doc: dict[str, Any]) -> str:
    name = str(doc.get("file_name") or doc.get("title") or doc.get("doc_id") or "document")
    if not name.lower().endswith((".md", ".txt")):
        name = f"{name}.md"
    return name


def _emit(cb: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if cb is None:
        return
    try:
        cb(event)
    except Exception as exc:  # noqa: BLE001 - 进度回调失败不得影响导入主流程
        logger.debug("memecho import progress_cb failed: %s", exc)


__all__ = ["MemEchoRecall", "MemEchoRecallResult"]
