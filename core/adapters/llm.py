"""LLM 结构化抽取适配器（adapters 层）。

利用 AstrBot 运行态 context 中的 LLM Provider，执行学术实体与有向关系的结构化 JSON 抽取。
支持动态注入自定义 Entity Types 提示词约束，并提供高保真的离线测试 Stub 实现。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("LLMAdapter")


class LLMAdapter:
    """运行态 LLM 结构化调用适配器。"""

    def __init__(self, context: Any = None) -> None:
        self._context = context

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
            f"Please analyze the following academic text and extract the knowledge graph:\n\n"
            f"{text}"
        )

        raw_response = ""
        if self._context is not None:
            try:
                # 1) 尝试 context.call_llm
                call_llm = getattr(self._context, "call_llm", None)
                if callable(call_llm):
                    raw_response = await call_llm(user_prompt, system_prompt=system_prompt)

                # 2) 尝试 context.llm_provider
                if not raw_response:
                    provider = getattr(self._context, "llm_provider", None)
                    if provider is not None:
                        chat_fn = getattr(provider, "chat", None) or getattr(
                            provider, "generate", None
                        )
                        if callable(chat_fn):
                            raw_response = await chat_fn(user_prompt, system_prompt=system_prompt)

                # 3) 尝试 context.get_llm_provider
                if not raw_response:
                    get_provider = getattr(self._context, "get_llm_provider", None)
                    if callable(get_provider):
                        provider = await get_provider()
                        chat_fn = getattr(provider, "chat", None) or getattr(
                            provider, "generate", None
                        )
                        if callable(chat_fn):
                            raw_response = await chat_fn(user_prompt, system_prompt=system_prompt)
            except Exception as e:
                logger.error(f"LLM Adapter invocation failed: {e}")

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
            entities.append({
                "name": word,
                "type": default_type,
                "description": f"Extracted academic concept representing {word}."
            })

        # 构造链式有向关系
        for i in range(len(entities) - 1):
            relations.append({
                "src": entities[i]["name"],
                "dst": entities[i+1]["name"],
                "relation": "relates_to",
                "description": f"{entities[i]['name']} is connected to {entities[i+1]['name']}.",
                "weight": 1.0
            })

        result = {
            "entities": entities,
            "relations": relations
        }
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
