"""LLM 结构化抽取适配器（adapters 层）。

利用 AstrBot 运行态 context 中的 LLM Provider，执行学术实体与有向关系的结构化 JSON 抽取。
支持动态注入自定义 Entity Types 提示词约束，并提供高保真的离线测试 Stub 实现。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger("LLMAdapter")


class LMStudioLLMAdapter:
    """OpenAI-compatible HTTP adapter，供 LightRAG 图谱构建专用。

    调用任意 OpenAI-compatible endpoint（LM Studio / Ollama / vLLM 等）。
    与主 LLMAdapter（AstrBot context）完全独立，图谱构建 LLM 与答案生成 LLM 互不影响。
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        *,
        timeout_seconds: int = 900,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    async def generate(
        self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True
    ) -> str:
        try:
            import aiohttp
        except ImportError as exc:
            if not allow_mock:
                raise RuntimeError("aiohttp is required for LMStudioLLMAdapter") from exc
            logger.error("aiohttp not available; LMStudioLLMAdapter cannot call LM Studio")
            return ""

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {"model": self._model, "messages": messages, "temperature": 0.1}
        url = f"{self._base_url}/chat/completions"

        input_chars = sum(len(m["content"]) for m in messages)
        estimated_prompt_tokens = input_chars // 4
        attempts = self._max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            t0 = time.monotonic()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                elapsed = time.monotonic() - t0
                return self._log_success(
                    data,
                    elapsed=elapsed,
                    prompt_tokens_fallback=estimated_prompt_tokens,
                    attempt=attempt,
                )
            except Exception as exc:
                last_exc = exc
                elapsed = time.monotonic() - t0
                logger.warning(
                    "LMStudio call failed attempt=%d/%d elapsed=%.1fs timeout=%ss "
                    "model=%s error=%s",
                    attempt,
                    attempts,
                    elapsed,
                    self._timeout_seconds,
                    self._model,
                    exc,
                )
                if attempt < attempts:
                    await asyncio.sleep(self._retry_backoff_seconds * attempt)

        if not allow_mock:
            raise RuntimeError(f"LM Studio call to {url} failed: {last_exc}") from last_exc
        logger.error("LMStudioLLMAdapter.generate failed after retries: %s", last_exc)
        return ""

    def _log_success(
        self,
        data: dict[str, Any],
        *,
        elapsed: float,
        prompt_tokens_fallback: int,
        attempt: int,
    ) -> str:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = str(message.get("content") or "").strip()
        finish_reason = str(choice.get("finish_reason") or "")

        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens") or prompt_tokens_fallback
        completion_tokens = usage.get("completion_tokens") or max(1, len(content) // 4)
        tps = completion_tokens / elapsed if elapsed > 0 else 0

        logger.debug(
            "LMStudio | prompt=%d tok completion=%d tok elapsed=%.1fs "
            "gen_speed=%.1f t/s retry=%d finish=%s model=%s",
            prompt_tokens,
            completion_tokens,
            elapsed,
            tps,
            attempt - 1,
            finish_reason or "unknown",
            self._model,
        )

        if tps < 8 and completion_tokens > 10:
            logger.warning(
                "LMStudio 生成速度偏低 %.1f t/s（prompt=%d tok）"
                "——长 prompt 会显著降低推理速度，可减小 max_doc_chars 缩短输入",
                tps,
                prompt_tokens,
            )

        return content


class LLMAdapter:
    """运行态 LLM 通用调用适配器（结构化抽取 + 问答生成）。"""

    def __init__(self, context: Any = None) -> None:
        self._context = context

    async def generate(
        self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True
    ) -> str:
        """通用文本生成（用于 Ask Agent 等问答场景）。

        优先使用 AstrBot context 中的 LLM Provider；无运行态时返回离线占位答案。
        """
        raw = await self._call_context_llm(prompt, system_prompt)

        if not raw or not raw.strip():
            if not allow_mock:
                raise RuntimeError(
                    "No real AstrBot LLM provider response; mock fallback is disabled"
                )
            logger.info("[Offline Stub] generate: returning placeholder answer.")
            raw = self._mock_generate(prompt)

        return raw.strip()

    async def _call_context_llm(self, prompt: str, system_prompt: str = "") -> str:
        """按 AstrBot 新旧 SDK 顺序调用主 LLM，并统一抽取纯文本。"""
        if self._context is None:
            return ""

        try:
            raw = await self._call_astrbot_llm_generate(prompt, system_prompt)
            if raw:
                return raw

            raw = await self._call_legacy_context_llm(prompt, system_prompt)
            if raw:
                return raw
        except Exception as e:
            logger.error(f"LLMAdapter context invocation failed: {e}")

        return ""

    async def _call_astrbot_llm_generate(self, prompt: str, system_prompt: str) -> str:
        """适配 AstrBot 4.5.7+ 的 context.llm_generate()。"""
        llm_generate = getattr(self._context, "llm_generate", None)
        provider = await self._get_astrbot_chat_provider()
        provider_id = self._provider_id(provider)

        if callable(llm_generate) and provider_id:
            response = await llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system_prompt or None,
            )
            text = self._response_text(response)
            if text:
                return text

        text_chat = getattr(provider, "text_chat", None) if provider is not None else None
        if callable(text_chat):
            response = await text_chat(
                prompt=prompt,
                system_prompt=system_prompt or None,
            )
            return self._response_text(response)

        return ""

    async def _get_astrbot_chat_provider(self) -> Any:
        provider_manager = getattr(self._context, "provider_manager", None)
        if provider_manager is None:
            return None

        get_using_provider = getattr(provider_manager, "get_using_provider", None)
        if callable(get_using_provider):
            try:
                from astrbot.core.provider.entities import ProviderType

                provider = get_using_provider(ProviderType.CHAT_COMPLETION)
                if inspect.isawaitable(provider):
                    provider = await provider
                if provider is not None:
                    return provider
            except Exception as exc:
                logger.debug("AstrBot get_using_provider unavailable: %s", exc)

        return getattr(provider_manager, "curr_provider_inst", None)

    def _provider_id(self, provider: Any) -> str:
        if provider is None:
            return ""

        meta_attr = getattr(provider, "meta", None)
        meta = meta_attr() if callable(meta_attr) else meta_attr
        if isinstance(meta, dict):
            return str(meta.get("id") or "")
        provider_id = getattr(meta, "id", None)
        if provider_id:
            return str(provider_id)

        for attr in ("id", "provider_id"):
            value = getattr(provider, attr, None)
            if value:
                return str(value)
        return ""

    async def _call_legacy_context_llm(self, prompt: str, system_prompt: str) -> str:
        call_llm = getattr(self._context, "call_llm", None)
        if callable(call_llm):
            raw = await call_llm(prompt, system_prompt=system_prompt or None)
            if raw:
                return self._response_text(raw)

        provider = getattr(self._context, "llm_provider", None)
        raw = await self._call_provider_chat(provider, prompt, system_prompt)
        if raw:
            return raw

        get_provider = getattr(self._context, "get_llm_provider", None)
        if callable(get_provider):
            provider = await get_provider()
            return await self._call_provider_chat(provider, prompt, system_prompt)

        return ""

    async def _call_provider_chat(
        self, provider: Any, prompt: str, system_prompt: str
    ) -> str:
        if provider is None:
            return ""
        chat_fn = getattr(provider, "chat", None) or getattr(provider, "generate", None)
        if not callable(chat_fn):
            return ""
        response = await chat_fn(prompt, system_prompt=system_prompt or None)
        return self._response_text(response)

    def _response_text(self, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response.strip()

        completion_text = getattr(response, "completion_text", None)
        if completion_text:
            return str(completion_text).strip()

        result_chain = getattr(response, "result_chain", None)
        get_plain_text = getattr(result_chain, "get_plain_text", None)
        if callable(get_plain_text):
            text = get_plain_text()
            if text:
                return str(text).strip()

        return ""

    def _mock_generate(self, prompt: str) -> str:
        """离线占位：从 prompt 中提取关键词，构造简单示例答案。"""
        lines = [ln.strip() for ln in prompt.splitlines() if ln.strip()]
        question = next((ln for ln in lines if ln.startswith("问题")), lines[0] if lines else "")
        return (
            f"根据知识库中的相关资料，对于「{question[:60]}」的问答如下：\n\n"
            "这是一个离线测试占位答案。请配置 AstrBot LLM Provider 以获得真实回答。"
        )

    async def extract_graph(
        self, text: str, entity_types: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """从给定的文本中，根据指定的 entity_types 提取结构化的实体和关系。

        返回格式：
        {
            "entities": [{"name": "Transformer", "type": "Method/Algorithm",
                          "description": "..."}],
            "relations": [{"src": "Transformer", "dst": "Attention",
                           "relation": "uses", "description": "...",
                           "weight": 1.0}]
        }
        """
        types_str = ", ".join(entity_types)
        system_prompt = f"""You are a brilliant scientific researcher and knowledge graph builder.
Your task is to extract unique, high-quality entities and relationships
from the provided scientific text.

CRITICAL CONSTRAINTS:
1. Every extracted entity's `type` field MUST be exactly one of the
following categories: [{types_str}]. Do NOT use any other categories.
2. Output your response as a single, valid JSON object matching this schema:
{{
    "entities": [
        {{
            "name": "Entity Name",
            "type": "One of the configured categories",
            "description": "Clean, informative academic description"
        }}
    ],
    "relations": [
        {{
            "src": "Exact Name of Src Entity",
            "dst": "Exact Name of Dst Entity",
            "relation": "Relationship word (lower_case)",
            "description": "How they are related",
            "weight": 1.0
        }}
    ]
}}
3. Do NOT wrap the JSON in Markdown backticks (e.g. ```json) in your raw response.
Output ONLY the raw JSON string.
"""

        user_prompt = (
            f"Please analyze the following academic text and extract the knowledge graph:\n\n{text}"
        )

        raw_response = await self._call_context_llm(user_prompt, system_prompt)

        # 4) 离线测试桩回退
        if not raw_response or not raw_response.strip():
            logger.info("[Offline Stub] Using mock LLM extraction stub.")
            raw_response = self._mock_llm_extraction(text, entity_types)

        # 5) 清洗并解析 JSON
        return self._clean_and_parse_json(raw_response)

    def _mock_llm_extraction(self, text: str, entity_types: list[str]) -> str:
        """纯离线高保真测试桩，从文本中发现专有名词生成结构化学术图谱。"""
        # 简单使用正则表达式发现英文首字母大写的科学名词（模拟学术概念）
        words = re.findall(r"\b[A-Z][a-zA-Z0-9-]+\b", text)
        unique_words = sorted(list(set(words)))

        entities = []
        relations = []

        # 默认回退的第一个类别
        default_type = entity_types[0] if entity_types else "Method/Algorithm"

        # 如果发现专有名词，构造实体
        for i, word in enumerate(unique_words[:4]):  # 限制数量
            entities.append(
                {
                    "name": word,
                    "type": default_type,
                    "description": f"Extracted academic concept representing {word}.",
                }
            )

        # 构造链式有向关系
        for i in range(len(entities) - 1):
            relations.append(
                {
                    "src": entities[i]["name"],
                    "dst": entities[i + 1]["name"],
                    "relation": "relates_to",
                    "description": (
                        f"{entities[i]['name']} is connected to {entities[i + 1]['name']}."
                    ),
                    "weight": 1.0,
                }
            )

        result = {"entities": entities, "relations": relations}
        return json.dumps(result)

    def _clean_and_parse_json(self, raw_str: str) -> dict[str, list[dict[str, Any]]]:
        """清洗大模型可能包含的 Markdown ```json 包裹并安全解析为字典。"""
        cleaned = raw_str.strip()
        # 移除 markdown json 标记
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "entities" in parsed:
                return parsed
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON response: {e}. Raw: {raw_str}")

        return {"entities": [], "relations": []}
