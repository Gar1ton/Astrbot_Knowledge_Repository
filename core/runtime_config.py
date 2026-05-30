"""运行时配置覆盖文件。

用于保存插件运行后产生的非敏感配置，例如 Notion 自动建库得到的 database_id。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import merge_config_dicts


class RuntimeConfigStore:
    """data_dir 内的轻量 JSON 配置覆盖存储。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, override: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(override, ensure_ascii=False, indent=2, sort_keys=True)
        self._path.write_text(payload + "\n", encoding="utf-8")

    def set_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        data = self.load()
        current = data.setdefault(section, {})
        if not isinstance(current, dict):
            current = {}
            data[section] = current
        current[key] = value
        self.save(data)
        return data

    def merged_with(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        return merge_config_dicts(raw_config, self.load())


__all__ = ["RuntimeConfigStore"]
