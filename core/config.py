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
    无需用户单独配置。free_tier_gb / warn_threshold 驱动配额预警（见 quota_manager）。
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
    """Notion 单向镜像配置。经 mcp_server_name 指向的 MCP server 调用，本侧不持 token。"""

    enabled: bool = False
    mcp_server_name: str = "notion"
    database_id: str = ""
    max_upload_mib: int = 5
    link_large_to_r2: bool = True
    rate_limit_rps: int = 3

    @property
    def max_upload_bytes(self) -> int:
        """单文件上传上限的字节数（超过则改走 R2 链接）。"""
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
    """LightRAG 知识图谱配置。incremental 决定是否按 content_hash 跳过未变 chunk。"""

    enabled: bool = False
    llm_extraction: bool = True
    incremental: bool = True
    reuse_kb_embedding: bool = True
    merge_similarity_threshold: float = 0.9
    rrf_k: int = 60
    query_top_k: int = 5


# ── 解析门面 ────────────────────────────────────────────────────


@dataclass
class Config:
    """原始配置的唯一解析入口。持有 raw dict，按需产出各子系统的 typed config。"""

    raw: dict[str, Any] = field(default_factory=dict)

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
            free_tier_gb=int(s.get("free_tier_gb", R2SyncConfig.free_tier_gb)),
            warn_threshold=float(s.get("warn_threshold", R2SyncConfig.warn_threshold)),
            backup_interval_sec=int(s.get("backup_interval_sec", R2SyncConfig.backup_interval_sec)),
        )

    def get_notion_sync_config(self) -> NotionSyncConfig:
        s = _section(self.raw, "notion_sync")
        return NotionSyncConfig(
            enabled=bool(s.get("enabled", NotionSyncConfig.enabled)),
            mcp_server_name=s.get("mcp_server_name", NotionSyncConfig.mcp_server_name),
            database_id=s.get("database_id", NotionSyncConfig.database_id),
            max_upload_mib=int(s.get("max_upload_mib", NotionSyncConfig.max_upload_mib)),
            link_large_to_r2=bool(s.get("link_large_to_r2", NotionSyncConfig.link_large_to_r2)),
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
        return GraphConfig(
            enabled=bool(s.get("enabled", GraphConfig.enabled)),
            llm_extraction=bool(s.get("llm_extraction", GraphConfig.llm_extraction)),
            incremental=bool(s.get("incremental", GraphConfig.incremental)),
            reuse_kb_embedding=bool(s.get("reuse_kb_embedding", GraphConfig.reuse_kb_embedding)),
            merge_similarity_threshold=float(
                s.get("merge_similarity_threshold", GraphConfig.merge_similarity_threshold)
            ),
            rrf_k=int(s.get("rrf_k", GraphConfig.rrf_k)),
            query_top_k=int(s.get("query_top_k", GraphConfig.query_top_k)),
        )


__all__ = [
    "ENV_R2_SECRET_ACCESS_KEY",
    "ENV_WEB_PASSWORD",
    "SourceStoreConfig",
    "R2SyncConfig",
    "NotionSyncConfig",
    "WebConsoleConfig",
    "GraphConfig",
    "Config",
]
