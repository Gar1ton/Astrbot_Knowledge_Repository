"""运行时配置覆盖文件。

用于保存插件运行后产生的非敏感配置，例如 Notion 自动建库得到的 database_id。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import merge_config_dicts

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("RuntimeConfigStore")

_ALLOWED_RUNTIME_KEYS = {
    "notion_sync": frozenset({"database_id", "parent_page_id", "database_title"}),
    "vector_db": frozenset({
        "backend",
        "embedding_provider",
        "embedding_model",
        "base_url",
        "db_filename",
        "auto_index_enabled",
    }),
    "graph": frozenset({
        "enabled",
        "query_mode",
        "embedding_dim",
        "max_token_size",
        "llm_max_async",
        "embedding_max_async",
    }),
    "ask": frozenset({"conversation_enhancement_mode", "persona_enabled"}),
}


class RuntimeConfigStore:
    """data_dir 内的轻量 JSON 配置覆盖存储。"""

    def __init__(
        self,
        path: Path,
        framework_persist_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._path = path
        self._framework_persist_cb = framework_persist_cb

    def load(self) -> dict[str, Any]:
        """从 JSON 文件中加载运行时配置字典。边界清晰，容错度高。"""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to read runtime config from {self._path}: {e}")
            return {}
        return _sanitize_override(data) if isinstance(data, dict) else {}

    def save(self, override: dict[str, Any]) -> None:
        """保存运行时配置字典到本地 JSON，并尝试触发框架原生适配写回接口。"""
        sanitized = _sanitize_override(override)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                sanitized,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            self._path.write_text(payload + "\n", encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to write runtime config to {self._path}: {e}")
            raise e

        # 触发原生配置写回适配接口
        if self._framework_persist_cb is not None:
            try:
                self._framework_persist_cb(sanitized)
            except Exception as e:
                logger.warning(f"Framework config persist callback failed: {e}")

    def set_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """更新单个小节与键的值并保存。"""
        if key not in _ALLOWED_RUNTIME_KEYS.get(section, frozenset()):
            raise ValueError(f"runtime config key is not allowed: {section}.{key}")
        data = self.load()
        current = data.setdefault(section, {})
        if not isinstance(current, dict):
            current = {}
            data[section] = current
        current[key] = value
        self.save(data)
        return data

    def merged_with(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        """将加载的配置与外部提供的原始配置合并。"""
        return merge_config_dicts(raw_config, self.load())


def _sanitize_override(data: dict[str, Any]) -> dict[str, Any]:
    """只保留插件运行时允许生成的非敏感配置键。"""
    sanitized: dict[str, Any] = {}
    for section, allowed_keys in _ALLOWED_RUNTIME_KEYS.items():
        values = data.get(section)
        if not isinstance(values, dict):
            continue
        sanitized_values = {key: values[key] for key in allowed_keys if key in values}
        if sanitized_values:
            sanitized[section] = sanitized_values
    return sanitized


__all__ = ["RuntimeConfigStore"]
