"""真实开发环境的配置翻译与 MemEcho 装配 helper；导入时不读取密钥、不访问网络。"""

from __future__ import annotations

import os
import sys
from typing import Any


def _str_cfg(cfg, name: str, default: str = "") -> str:
    value = getattr(cfg, name, default)
    return value.strip() if isinstance(value, str) else str(value).strip()


def _str_cfg_or_env(cfg, name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    return _str_cfg(cfg, name, default)


def _first_cfg(cfg, *names: str, default: str = "") -> str:
    for name in names:
        value = _str_cfg(cfg, name)
        if value:
            return value
    return default


def _normalize_provider(value: str, allowed: set[str], default: str) -> str:
    provider = (value or default).strip().lower()
    if provider not in allowed:
        print(f"[Error] Unsupported LLM provider {provider!r}; choose one of {sorted(allowed)}")
        sys.exit(1)
    return provider


def _resolve_main_llm_settings(cfg) -> dict[str, str]:
    provider = _normalize_provider(_str_cfg(cfg, "LLM_PROVIDER", "api"), {"api", "local"}, "api")
    if provider == "local":
        base_url = _first_cfg(
            cfg,
            "LOCAL_LLM_API_URL",
            "LLM_LOCAL_API_URL",
            default="http://host.docker.internal:1234/v1",
        )
        model = _first_cfg(cfg, "LOCAL_LLM_MODEL", "LLM_LOCAL_MODEL")
        api_key = _first_cfg(cfg, "LOCAL_LLM_API_KEY", "LLM_LOCAL_API_KEY")
    else:
        base_url = _first_cfg(cfg, "API_LLM_API_URL", "LLM_API_URL")
        model = _first_cfg(cfg, "API_LLM_MODEL", "LLM_MODEL")
        api_key = _first_cfg(cfg, "API_LLM_API_KEY", "LLM_API_KEY", "DEEPSEEK_API_KEY")

    if not base_url or not model:
        print(f"[Error] 主 LLM provider={provider} 需要配置 base_url 与 model")
        sys.exit(1)
    if provider == "api" and not api_key:
        print(
            "[Warning] 主 LLM provider=api 但未配置 API key；若 endpoint 要求鉴权，连通性探针会失败"
        )
    return {"provider": provider, "base_url": base_url, "model": model, "api_key": api_key}


def _resolve_lightrag_llm_settings(cfg) -> dict[str, str]:
    legacy_base_url = _first_cfg(cfg, "LIGHTRAG_LLM_BASE_URL")
    legacy_model = _first_cfg(cfg, "LIGHTRAG_LLM_MODEL")
    raw_provider = _str_cfg(cfg, "LIGHTRAG_LLM_PROVIDER")
    default_provider = "local" if legacy_base_url and legacy_model else "main"
    provider = _normalize_provider(raw_provider, {"main", "api", "local"}, default_provider)
    if provider == "main":
        return {"provider": "main", "base_url": "", "model": "", "api_key": ""}

    base_url = _first_cfg(cfg, "LIGHTRAG_LLM_BASE_URL", "LIGHTRAG_LLM_API_URL")
    model = _first_cfg(cfg, "LIGHTRAG_LLM_MODEL")
    api_key = _first_cfg(cfg, "LIGHTRAG_LLM_API_KEY")
    if not base_url or not model:
        print(
            f"[Error] LIGHTRAG_LLM_PROVIDER={provider!r} 需要配置 "
            "LIGHTRAG_LLM_BASE_URL 与 LIGHTRAG_LLM_MODEL"
        )
        sys.exit(1)
    if provider == "api" and not api_key:
        print(
            "[Warning] LightRAG provider=api 但未配置 LIGHTRAG_LLM_API_KEY；"
            "若 endpoint 要求鉴权，构建会失败"
        )
    return {"provider": provider, "base_url": base_url, "model": model, "api_key": api_key}


def _memecho_raw_config(cfg: Any) -> dict[str, object]:
    """把本地开发配置模块翻译为正式 MemEcho 配置段，绝不读取或返回 API Key。"""
    return {
        "enabled": bool(getattr(cfg, "MEMECHO_ENABLED", False)),
        "base_url": _str_cfg(cfg, "MEMECHO_BASE_URL", "https://api.artific.social"),
        "default_vault_id": _str_cfg(cfg, "MEMECHO_DEFAULT_VAULT_ID"),
        "query_readonly": bool(getattr(cfg, "MEMECHO_QUERY_READONLY", True)),
        "write_back_enabled": bool(getattr(cfg, "MEMECHO_WRITE_BACK_ENABLED", False)),
        "timeout_seconds": int(getattr(cfg, "MEMECHO_TIMEOUT_SECONDS", 30)),
        "import_timeout_seconds": int(
            getattr(cfg, "MEMECHO_IMPORT_TIMEOUT_SECONDS", 300)
        ),
        "import_preset": _str_cfg(cfg, "MEMECHO_IMPORT_PRESET", "default"),
    }


def _attach_memecho(api: Any, config: Any) -> str:
    """按配置与运行时密钥装配 MemEcho；返回可直接打印的诊断，不发起网络请求。"""
    from kacore.adapters.memecho.client import MemEchoClient
    from kacore.pipelines.memecho_recall import MemEchoRecall

    memecho_cfg = config.get_memecho_config()
    memecho_key = api._memecho_api_key()
    config.runtime_memecho_key_present = bool(memecho_key)
    if memecho_cfg.enabled and memecho_key:
        client = MemEchoClient(
            memecho_cfg.base_url,
            api._memecho_api_key,
            timeout_seconds=memecho_cfg.timeout_seconds,
            import_timeout_seconds=memecho_cfg.import_timeout_seconds,
        )
        api._memecho_recall = MemEchoRecall(client)
        return (
            "[Init] MemEcho 已装配："
            f"{memecho_cfg.base_url}  vault={memecho_cfg.default_vault_id or '<未配置>'}"
        )
    if memecho_cfg.enabled:
        return "[Init] MemEcho 已启用但未找到 API Key；可在 Flow 面板保存后以 --keep 重启"
    return "[Init] MemEcho 未启用（config.py: MEMECHO_ENABLED=False）"
