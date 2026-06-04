"""类型化配置（见 config.README.md 与 ../ARCHITECTURE.md §5）。

唯一解析原始配置（AstrBot 注入的 dict）的地方：原始 dict → Config → get_xxx_config() → XxxConfig。
键名、默认值、类型集中于此，与 `_conf_schema.json` 同源（改配置项须两处同步）。

机密约定：密钥/密码优先从环境变量读取，原始 dict 仅作回退，且密钥不应提交进仓库。
    - R2 Secret Access Key：env `KR_R2_SECRET_ACCESS_KEY`
    - Web 控制台密码：env `KR_WEB_PASSWORD`
    Notion 不在此持有 token——同步经 AstrBot 已配置的 notion MCP server，token 由 MCP 侧管理。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# ── 环境变量名（机密来源）────────────────────────────────────────

ENV_R2_SECRET_ACCESS_KEY = "KR_R2_SECRET_ACCESS_KEY"
ENV_WEB_PASSWORD = "KR_WEB_PASSWORD"


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    """取一组子配置；缺失或类型不符时返回空 dict（让 dataclass 用默认值）。"""
    value = raw.get(name)
    return value if isinstance(value, dict) else {}


def _secret(raw_value: Any, env_name: str) -> str:
    """机密取值：环境变量优先，原始配置回退，最终回退空串。"""
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    return raw_value if isinstance(raw_value, str) else ""


# ── 各子系统专属 typed config ────────────────────────────────────


@dataclass
class SourceStoreConfig:
    """源文档库配置。ocr_enabled 默认关，开启会引入额外 OCR/LLM 成本。"""

    db_filename: str = "knowledge_repository.db"
    default_collection: str = "default"
    ocr_enabled: bool = False


@dataclass
class R2SyncConfig:
    """Cloudflare R2 备份配置。

    secret_access_key 仅经环境变量注入（见模块 docstring）。endpoint 由 account_id 推导，
    无需用户单独配置。free_tier_gb 固定为 R2 免费额度（10 GB），不暴露给用户配置。
    """

    enabled: bool = False
    account_id: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    bucket: str = ""
    cdn_domain: str = ""
    free_tier_gb: int = 10
    warn_threshold: float = 0.8
    backup_interval_sec: int = 86400

    @property
    def endpoint(self) -> str:
        """R2 的 S3 兼容端点；account_id 为空时返回空串。"""
        if not self.account_id:
            return ""
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @property
    def free_tier_bytes(self) -> int:
        """免费额度的字节数。"""
        return self.free_tier_gb * 1024 * 1024 * 1024


@dataclass
class NotionSyncConfig:
    """Notion 单向镜像配置。经 mcp_server_name 指向的 MCP server 调用，本侧不持 token。

    max_upload_mib 固定为 Notion API 限制（5 MiB），不暴露给用户配置。
    """

    enabled: bool = False
    mcp_server_name: str = "notion"
    database_id: str = ""
    parent_page_id: str = ""
    database_title: str = "Knowledge Repository"
    max_upload_mib: int = 5
    rate_limit_rps: int = 3

    @property
    def max_upload_bytes(self) -> int:
        """单文件上传上限的字节数。"""
        return self.max_upload_mib * 1024 * 1024


@dataclass
class WebConsoleConfig:
    """独立 Web 控制台配置。password 仅经环境变量注入；为空时控制台应拒绝启动。"""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 6520
    username: str = "admin"
    password: str = ""


@dataclass
class GraphConfig:
    """LightRAG Core 图谱配置。每个 collection 使用独立 workspace。"""

    enabled: bool = False
    query_mode: str = "mix"
    embedding_dim: int = 1024
    max_token_size: int = 8192
    llm_max_async: int = 4
    embedding_max_async: int = 8
    working_dir: str = "lightrag_workspaces"


@dataclass
class VectorDbConfig:
    """向量数据库与检索后端配置。"""

    backend: str = "astr"
    embedding_provider: str = "local"
    db_filename: str = "vector_store.db"
    auto_index_enabled: bool = True


@dataclass
class AskAgentConfig:
    """Ask Agent 的会话增强和回答配置。"""

    conversation_enhancement_mode: str = "inject"


# ── 解析门面 ────────────────────────────────────────────────────


@dataclass
class Config:
    """原始配置的唯一解析入口。持有 raw dict，按需产出各子系统的 typed config。"""

    raw: dict[str, Any] = field(default_factory=dict)

    def apply_override(self, override: dict[str, Any]) -> None:
        """合并运行时覆盖配置。用于自动建库后回填 database_id。"""
        self.raw = merge_config_dicts(self.raw, override)

    def set_value(self, section: str, key: str, value: Any) -> None:
        """更新内存中的单个配置值。"""
        current = self.raw.setdefault(section, {})
        if not isinstance(current, dict):
            current = {}
            self.raw[section] = current
        current[key] = value

    def to_public_dict(self) -> dict[str, Any]:
        """返回前端可展示的有效配置；敏感字段脱敏。"""
        source = self.get_source_store_config()
        r2 = self.get_r2_sync_config()
        notion = self.get_notion_sync_config()
        web = self.get_web_console_config()
        graph = self.get_graph_config()
        vector_db = self.get_vector_db_config()
        ask = self.get_ask_agent_config()
        return {
            "source_store": {
                "db_filename": source.db_filename,
                "default_collection": source.default_collection,
                "ocr_enabled": source.ocr_enabled,
            },
            "r2_sync": {
                "enabled": r2.enabled,
                "account_id": r2.account_id,
                "access_key_id": _mask(r2.access_key_id),
                "secret_access_key": _mask(r2.secret_access_key),
                "bucket": r2.bucket,
                "warn_threshold": r2.warn_threshold,
                "backup_interval_sec": r2.backup_interval_sec,
                "endpoint": r2.endpoint,
            },
            "notion_sync": {
                "enabled": notion.enabled,
                "mcp_server_name": notion.mcp_server_name,
                "database_id": notion.database_id,
                "parent_page_id": notion.parent_page_id,
                "database_title": notion.database_title,
                "rate_limit_rps": notion.rate_limit_rps,
            },
            "web_console": {
                "enabled": web.enabled,
                "host": web.host,
                "port": web.port,
                "username": web.username,
                "password": _mask(web.password),
            },
            "graph": {
                "enabled": graph.enabled,
                "query_mode": graph.query_mode,
                "embedding_dim": graph.embedding_dim,
                "max_token_size": graph.max_token_size,
                "llm_max_async": graph.llm_max_async,
                "embedding_max_async": graph.embedding_max_async,
                "working_dir": graph.working_dir,
            },
            "vector_db": {
                "backend": vector_db.backend,
                "embedding_provider": vector_db.embedding_provider,
                "db_filename": vector_db.db_filename,
                "auto_index_enabled": vector_db.auto_index_enabled,
            },
            "ask": {
                "conversation_enhancement_mode": ask.conversation_enhancement_mode,
            },
            "diagnostics": self.get_diagnostics(),
        }

    def get_diagnostics(self) -> list[str]:
        """返回已启用子系统的缺失配置提示，不阻断保存半成品配置。"""
        diagnostics = []
        r2 = self.get_r2_sync_config()
        if r2.enabled:
            required = {
                "account_id": r2.account_id,
                "access_key_id": r2.access_key_id,
                "secret_access_key": r2.secret_access_key,
                "bucket": r2.bucket,
            }
            diagnostics.extend(
                f"r2_sync.{key} is required when r2_sync.enabled=true"
                for key, value in required.items()
                if not value
            )

        notion = self.get_notion_sync_config()
        if notion.enabled:
            if not notion.mcp_server_name:
                diagnostics.append(
                    "notion_sync.mcp_server_name is required when notion_sync.enabled=true"
                )
            if not notion.database_id and not notion.parent_page_id:
                diagnostics.append(
                    "notion_sync.database_id or notion_sync.parent_page_id is required "
                    "when notion_sync.enabled=true"
                )
        return diagnostics

    def get_source_store_config(self) -> SourceStoreConfig:
        s = _section(self.raw, "source_store")
        return SourceStoreConfig(
            db_filename=s.get("db_filename", SourceStoreConfig.db_filename),
            default_collection=s.get("default_collection", SourceStoreConfig.default_collection),
            ocr_enabled=bool(s.get("ocr_enabled", SourceStoreConfig.ocr_enabled)),
        )

    def get_r2_sync_config(self) -> R2SyncConfig:
        s = _section(self.raw, "r2_sync")
        return R2SyncConfig(
            enabled=bool(s.get("enabled", R2SyncConfig.enabled)),
            account_id=s.get("account_id", R2SyncConfig.account_id),
            access_key_id=s.get("access_key_id", R2SyncConfig.access_key_id),
            secret_access_key=_secret(s.get("secret_access_key"), ENV_R2_SECRET_ACCESS_KEY),
            bucket=s.get("bucket", R2SyncConfig.bucket),
            cdn_domain=s.get("cdn_domain", R2SyncConfig.cdn_domain),
            warn_threshold=float(s.get("warn_threshold", R2SyncConfig.warn_threshold)),
            backup_interval_sec=int(s.get("backup_interval_sec", R2SyncConfig.backup_interval_sec)),
        )

    def get_notion_sync_config(self) -> NotionSyncConfig:
        s = _section(self.raw, "notion_sync")
        return NotionSyncConfig(
            enabled=bool(s.get("enabled", NotionSyncConfig.enabled)),
            mcp_server_name=s.get("mcp_server_name", NotionSyncConfig.mcp_server_name),
            database_id=s.get("database_id", NotionSyncConfig.database_id),
            parent_page_id=s.get("parent_page_id", NotionSyncConfig.parent_page_id),
            database_title=s.get("database_title", NotionSyncConfig.database_title),
            rate_limit_rps=int(s.get("rate_limit_rps", NotionSyncConfig.rate_limit_rps)),
        )

    def get_web_console_config(self) -> WebConsoleConfig:
        s = _section(self.raw, "web_console")
        return WebConsoleConfig(
            enabled=bool(s.get("enabled", WebConsoleConfig.enabled)),
            host=s.get("host", WebConsoleConfig.host),
            port=int(s.get("port", WebConsoleConfig.port)),
            username=s.get("username", WebConsoleConfig.username),
            password=_secret(s.get("password"), ENV_WEB_PASSWORD),
        )

    def get_graph_config(self) -> GraphConfig:
        s = _section(self.raw, "graph")
        query_mode = str(s.get("query_mode", GraphConfig.query_mode))
        if query_mode not in {"local", "global", "hybrid", "naive", "mix", "bypass"}:
            query_mode = GraphConfig.query_mode
        return GraphConfig(
            enabled=bool(s.get("enabled", GraphConfig.enabled)),
            query_mode=query_mode,
            embedding_dim=int(s.get("embedding_dim", GraphConfig.embedding_dim)),
            max_token_size=int(s.get("max_token_size", GraphConfig.max_token_size)),
            llm_max_async=int(s.get("llm_max_async", GraphConfig.llm_max_async)),
            embedding_max_async=int(s.get("embedding_max_async", GraphConfig.embedding_max_async)),
            working_dir=str(s.get("working_dir", GraphConfig.working_dir)),
        )

    def get_vector_db_config(self) -> VectorDbConfig:
        s = _section(self.raw, "vector_db")
        raw_auto = s.get("auto_index_enabled", VectorDbConfig.auto_index_enabled)
        auto_index = bool(raw_auto) if not isinstance(raw_auto, bool) else raw_auto
        return VectorDbConfig(
            backend=s.get("backend", VectorDbConfig.backend),
            embedding_provider=s.get("embedding_provider", VectorDbConfig.embedding_provider),
            db_filename=s.get("db_filename", VectorDbConfig.db_filename),
            auto_index_enabled=auto_index,
        )

    def get_ask_agent_config(self) -> AskAgentConfig:
        s = _section(self.raw, "ask")
        return AskAgentConfig(
            conversation_enhancement_mode=s.get(
                "conversation_enhancement_mode", AskAgentConfig.conversation_enhancement_mode
            ),
        )


def merge_config_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置 dict，返回新对象。"""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_config_dicts(current, value)
        else:
            merged[key] = value
    return merged


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


__all__ = [
    "ENV_R2_SECRET_ACCESS_KEY",
    "ENV_WEB_PASSWORD",
    "merge_config_dicts",
    "SourceStoreConfig",
    "R2SyncConfig",
    "NotionSyncConfig",
    "WebConsoleConfig",
    "GraphConfig",
    "VectorDbConfig",
    "AskAgentConfig",
    "Config",
]
