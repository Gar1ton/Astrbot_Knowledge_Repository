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
from dataclasses import replace
from typing import Any

from kacore.domain.llm_generation import (
    STATUS_CONTENT_FILTER,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_LENGTH,
    STATUS_OK,
    STATUS_REASONING_ONLY,
    STATUS_TIMEOUT,
    GenerationResult,
)

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
    """运行态 LLM 通用调用适配器（结构化抽取 + 问答生成）。

    timeout_seconds：单次主 LLM 调用的上限。AstrBot provider 自身不保证有超时，
    provider 挂死时整条 ask 会永远不返回——前端只能看到「请求超时」，后端却仍占着连接。
    <=0 表示不设限（保留旧行为）。
    """

    def __init__(self, context: Any = None, timeout_seconds: int = 300) -> None:
        self._context = context
        self._timeout_seconds = max(0, int(timeout_seconds))

    async def generate(
        self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True
    ) -> str:
        """通用文本生成（用于 Ask Agent 等问答场景）。

        优先使用 AstrBot context 中的 LLM Provider；无运行态时返回离线占位答案。
        薄委派 `generate_result()`——只取文本，不需要状态诊断的调用方用这个。
        """
        result = await self.generate_result(prompt, system_prompt, allow_mock=allow_mock)
        return result.text

    async def generate_result(
        self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True
    ) -> GenerationResult:
        """通用文本生成，返回结构化结果（finish_reason/token 用量/reasoning 状态等）。

        供需要按状态分流决策的调用方使用（如 answer_synthesis/llm_json），而不是只靠
        「文本是否为空」判断成败——reasoning_only/length/content_filter 时文本可能为空
        也可能非空，必须看 status。契约与 generate() 一致：allow_mock=False 时无真实
        响应直接抛异常，不做离线占位兜底。
        """
        result = await self._call_context_llm_result(prompt, system_prompt)

        if not result.text or not result.text.strip():
            if not allow_mock:
                # 具体原因（超时 / 异常 / 空响应 / reasoning-only）已由
                # _call_context_llm_result 记进日志；这里指路而不复述，避免多线并发时
                # 把别人的失败原因贴到本次异常上。
                raise RuntimeError(
                    "No real AstrBot LLM provider response (超时/异常/空响应，"
                    "详见终端日志中 LLMAdapter 的上一条 ERROR/WARNING)；"
                    "mock fallback is disabled"
                )
            # 降级到离线占位答案是「回答看起来正常、内容其实是假的」，必须是 WARNING 级：
            # 此前记 INFO，用户在终端页几乎不可能注意到主 LLM 根本没被调通。
            logger.warning(
                "AstrBot 主 LLM 未返回内容，本次回答使用离线占位文本（非真实回答）；"
                "请检查 AstrBot 的 LLM Provider 配置与上方错误日志。"
            )
            return replace(result, text=self._mock_generate(prompt).strip())

        return replace(result, text=result.text.strip())

    async def _call_context_llm(self, prompt: str, system_prompt: str = "") -> str:
        """按 AstrBot 新旧 SDK 顺序调用主 LLM，只取纯文本。

        薄委派 `_call_context_llm_result()`；保留纯文本签名给不需要状态诊断的调用方
        （如 extract_graph）与既有测试。
        """
        return (await self._call_context_llm_result(prompt, system_prompt)).text

    async def _call_context_llm_result(
        self, prompt: str, system_prompt: str = ""
    ) -> GenerationResult:
        """按 AstrBot 新旧 SDK 顺序调用主 LLM，返回结构化结果。

        契约：本方法不抛异常（status!=ok 即失败），但失败/空响应必须留下可诊断的日志——
        调用方拿到非 ok 状态后会据此分流（重试/降级/直接失败），日志是唯一线索。
        """
        if self._context is None:
            logger.warning("LLMAdapter 未拿到 AstrBot context，无法调用主 LLM。")
            return GenerationResult(text="", status=STATUS_EMPTY)

        started = time.monotonic()
        try:
            result, path = await self._await_provider(
                self._call_provider_paths(prompt, system_prompt)
            )
            if result.text:
                self._log_call_done(path, started, prompt, result.text)
                return result
        except TimeoutError:
            logger.error(
                "AstrBot 主 LLM 调用超时（%ss，prompt %d 字符）：本次回答放弃等待。"
                "请检查 LLM Provider 的可达性与并发限制，或调大 ask.llm_timeout_seconds。",
                self._timeout_seconds,
                len(prompt),
            )
            return GenerationResult(text="", status=STATUS_TIMEOUT)
        except Exception as e:
            logger.error(
                "AstrBot 主 LLM 调用失败（耗时 %.1fs）：%s: %s",
                time.monotonic() - started,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return GenerationResult(text="", status=STATUS_ERROR)

        if result.status == STATUS_REASONING_ONLY:
            logger.warning(
                "AstrBot 主 LLM 最终仍只有 reasoning_content、未给出最终答案"
                "（耗时 %.1fs，prompt %d 字符，finish_reason=%s）。",
                time.monotonic() - started,
                len(prompt),
                result.finish_reason or "unknown",
            )
        else:
            logger.warning(
                "AstrBot 主 LLM 返回空响应（耗时 %.1fs，prompt %d 字符）："
                "provider 可能未配置、被限流或输出被过滤。",
                time.monotonic() - started,
                len(prompt),
            )
        return result

    async def _await_provider(self, call: Any) -> tuple[GenerationResult, str]:
        """给一次 provider 调用套上超时闸；<=0 表示不限。"""
        if self._timeout_seconds <= 0:
            return await call
        return await asyncio.wait_for(call, timeout=self._timeout_seconds)

    async def _call_provider_paths(
        self, prompt: str, system_prompt: str
    ) -> tuple[GenerationResult, str]:
        """按 AstrBot 新旧 SDK 顺序尝试，返回 (结构化结果, 命中的调用路径)。"""
        result = await self._call_astrbot_llm_generate(prompt, system_prompt)
        if result.text:
            return result, "llm_generate"
        legacy_result = await self._call_legacy_context_llm(prompt, system_prompt)
        if legacy_result.text:
            return legacy_result, "legacy_provider"
        # 两条路径都没拿到文本：保留更有诊断价值的那个（reasoning_only 等信息状态
        # 优先于笼统的 empty），供上层日志/GenerationResult 使用。
        final = result if result.status != STATUS_EMPTY else legacy_result
        return final, "none"

    def _log_call_done(self, path: str, started: float, prompt: str, raw: str) -> None:
        """记一次成功调用的路径与耗时：慢在 LLM 还是慢在检索，日志里要能直接分辨。"""
        logger.info(
            "AstrBot 主 LLM 调用完成 path=%s 耗时 %.1fs prompt=%d 字符 response=%d 字符",
            path,
            time.monotonic() - started,
            len(prompt),
            len(raw),
        )

    # 开了 reasoning 的模型可能只返回 reasoning_content、不给 completion_text——AstrBot
    # 视其为有效响应。若不识别会被当空响应，进而对同一 provider 触发下面 text_chat 的
    # 盲目重复调用；reasoning 模型大概率对 text_chat 复现同样的现象，白耗一整轮超时。
    _REASONING_RETRY_SUFFIX = "\n\n请直接输出最终结论/答案本身，不要仅输出推理过程。"

    async def _call_astrbot_llm_generate(
        self, prompt: str, system_prompt: str
    ) -> GenerationResult:
        """适配 AstrBot 4.5.7+ 的 context.llm_generate()。"""
        llm_generate = getattr(self._context, "llm_generate", None)
        provider = await self._get_astrbot_chat_provider()
        provider_id = self._provider_id(provider)

        fallback_result = GenerationResult(text="", status=STATUS_EMPTY, provider_id=provider_id)
        if callable(llm_generate) and provider_id:
            response = await llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system_prompt or None,
            )
            result = self._build_result(response, provider_id)
            if result.text:
                return result
            if result.reasoning_present:
                # reasoning-only：对同一 provider 带「直接给答案」的追加指令重试一次，
                # 而不是立刻当作调用失败去滚 text_chat/legacy 兜底链。
                retry_system = (system_prompt or "") + self._REASONING_RETRY_SUFFIX
                response = await llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=retry_system,
                )
                result = self._build_result(response, provider_id)
                if result.text:
                    return result
                logger.warning(
                    "AstrBot 主 LLM 连续两次仅返回 reasoning_content、未给出最终答案"
                    "（provider=%s finish_reason=%s）；回退到 text_chat。",
                    provider_id,
                    result.finish_reason or "unknown",
                )
            fallback_result = result

        text_chat = getattr(provider, "text_chat", None) if provider is not None else None
        if callable(text_chat):
            response = await text_chat(
                prompt=prompt,
                system_prompt=system_prompt or None,
            )
            text_chat_result = self._build_result(response, provider_id)
            if text_chat_result.text or text_chat_result.status != STATUS_EMPTY:
                return text_chat_result
            # text_chat 也只给了个笼统的空响应：保留更有诊断价值的 fallback_result
            # （如 reasoning_only），不要用一个信息量更低的 empty 覆盖它。
            return fallback_result

        return fallback_result

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

    async def _call_legacy_context_llm(
        self, prompt: str, system_prompt: str
    ) -> GenerationResult:
        call_llm = getattr(self._context, "call_llm", None)
        if callable(call_llm):
            raw = await call_llm(prompt, system_prompt=system_prompt or None)
            if raw:
                return self._build_result(raw, "")

        provider = getattr(self._context, "llm_provider", None)
        result = await self._call_provider_chat(provider, prompt, system_prompt)
        if result.text:
            return result

        get_provider = getattr(self._context, "get_llm_provider", None)
        if callable(get_provider):
            provider = await get_provider()
            return await self._call_provider_chat(provider, prompt, system_prompt)

        return GenerationResult(text="", status=STATUS_EMPTY)

    async def _call_provider_chat(
        self, provider: Any, prompt: str, system_prompt: str
    ) -> GenerationResult:
        if provider is None:
            return GenerationResult(text="", status=STATUS_EMPTY)
        chat_fn = getattr(provider, "chat", None) or getattr(provider, "generate", None)
        if not callable(chat_fn):
            return GenerationResult(text="", status=STATUS_EMPTY)
        response = await chat_fn(prompt, system_prompt=system_prompt or None)
        return self._build_result(response, self._provider_id(provider))

    def _extract_text(self, response: Any) -> str:
        """从 AstrBot LLMResponse（或裸字符串）里取最终答案文本。

        只看 completion_text / result_chain 纯文本——reasoning_content 是否存在
        由 `_extract_reasoning` 单独判断，二者不合并，避免把推理过程当答案展示给用户。
        """
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

    def _extract_reasoning(self, response: Any) -> str:
        """取 AstrBot LLMResponse 的 reasoning_content（无该属性/非 LLMResponse 时为空）。

        AstrBot 允许「只有 reasoning_content、没有 completion_text」的响应，并把它视为
        有效模型输出；这里单独判断是否存在，供调用方区分「reasoning-only」与「真空响应」。
        """
        if response is None or isinstance(response, str):
            return ""
        reasoning = getattr(response, "reasoning_content", None)
        return str(reasoning).strip() if reasoning else ""

    def _extract_finish_reason(self, response: Any) -> str:
        """取 AstrBot LLMResponse 的 finish_reason（best-effort，仅用于诊断日志）。"""
        if response is None or isinstance(response, str):
            return ""
        finish_reason = getattr(response, "finish_reason", None)
        return str(finish_reason).strip() if finish_reason else ""

    def _extract_model(self, response: Any) -> str:
        """取 AstrBot LLMResponse 的 model（best-effort）。"""
        if response is None or isinstance(response, str):
            return ""
        model = getattr(response, "model", None)
        return str(model).strip() if model else ""

    def _extract_tokens(self, response: Any) -> tuple[int, int]:
        """取 (prompt_tokens, completion_tokens)，best-effort、取不到则为 0。

        AstrBot 不同 provider 实现下 usage 字段名尚不稳定：优先尝试
        `raw_completion`（多数 provider 透传底层 OpenAI-compatible completion 对象）
        上的 `usage.prompt_tokens/completion_tokens`，退化到响应对象自身同名属性
        （与 LMStudioLLMAdapter._log_success 的 OpenAI-compatible 解析口径一致）。
        """
        if response is None or isinstance(response, str):
            return 0, 0
        raw_completion = getattr(response, "raw_completion", None)
        usage: Any = getattr(raw_completion, "usage", None) if raw_completion is not None else None
        if usage is None and isinstance(raw_completion, dict):
            usage = raw_completion.get("usage")

        if isinstance(usage, dict):
            prompt_tokens = self._as_int(usage.get("prompt_tokens"))
            completion_tokens = self._as_int(usage.get("completion_tokens"))
        elif usage is not None:
            prompt_tokens = self._as_int(getattr(usage, "prompt_tokens", None))
            completion_tokens = self._as_int(getattr(usage, "completion_tokens", None))
        else:
            prompt_tokens = 0
            completion_tokens = 0

        if not prompt_tokens:
            prompt_tokens = self._as_int(getattr(response, "prompt_tokens", None))
        if not completion_tokens:
            completion_tokens = self._as_int(getattr(response, "completion_tokens", None))
        return prompt_tokens, completion_tokens

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

    def _build_result(
        self, response: Any, provider_id: str, *, status: str | None = None
    ) -> GenerationResult:
        """把一次 provider 响应统一转成 GenerationResult；status 不传时按内容自动判定。

        判定顺序：finish_reason 明确指向截断/内容过滤时优先于「有没有文本」；否则
        有文本即 ok；无文本但有 reasoning_content 即 reasoning_only；两者皆无才是 empty。
        """
        text = self._extract_text(response)
        reasoning_present = bool(self._extract_reasoning(response))
        finish_reason = self._extract_finish_reason(response)
        prompt_tokens, completion_tokens = self._extract_tokens(response)
        model = self._extract_model(response)

        if status is None:
            if finish_reason == "content_filter":
                status = STATUS_CONTENT_FILTER
            elif finish_reason == "length":
                status = STATUS_LENGTH
            elif text:
                status = STATUS_OK
            elif reasoning_present:
                status = STATUS_REASONING_ONLY
            else:
                status = STATUS_EMPTY

        return GenerationResult(
            text=text,
            status=status,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_present=reasoning_present,
            provider_id=provider_id,
            model=model,
        )

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
