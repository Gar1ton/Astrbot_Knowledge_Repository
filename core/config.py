"""类型化配置（见 config.README.md 与 ../ARCHITECTURE.md §5）。

唯一解析原始配置（AstrBot 注入的 dict）的地方：原始 dict → Config → get_xxx_config() → XxxConfig。
键名、默认值、类型集中于此，与 `_conf_schema.json` 同源（改配置项须两处同步）。

机密约定：密钥/密码优先从环境变量读取，原始 dict 仅作回退，且密钥不应提交进仓库。
    - R2 Secret Access Key：env `KR_R2_SECRET_ACCESS_KEY`
    - Web 控制台密码：env `KR_WEB_PASSWORD`
    - Embedding API Key：env `KR_EMBEDDING_API_KEY`
    Notion 不在此持有 token——同步经 AstrBot 已配置的 notion MCP server，token 由 MCP 侧管理。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# 依赖探测收口至能力注册表；保留模块内 _module_available 名以兼容既有测试的 monkeypatch。
from core.capabilities import module_available as _module_available

# ── 环境变量名（机密来源）────────────────────────────────────────

ENV_R2_SECRET_ACCESS_KEY = "KR_R2_SECRET_ACCESS_KEY"
ENV_WEB_PASSWORD = "KR_WEB_PASSWORD"
ENV_EMBEDDING_API_KEY = "KR_EMBEDDING_API_KEY"
ENV_LIGHTRAG_LLM_API_KEY = "KR_LIGHTRAG_LLM_API_KEY"


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
    llm_max_async: int = 4
    embedding_max_async: int = 8
    working_dir: str = "lightrag_workspaces"
    # 每篇文档传入 LightRAG 进行实体提取的最大字符数。
    # LightRAG 以内部 ~2000 chars/chunk 分块并为每块调用 LLM，限制此值可直接控制 LLM 调用次数。
    # 默认 30000 chars ≈ 15 次 LLM 调用/文档；设为 0 表示不限制。
    max_doc_chars: int = 30000
    # 图谱构建专用 LLM（可选）。设置后 LightRAG 的实体/关系抽取将调用此 endpoint，
    # 与答案生成所用的主 LLM（AstrBot context）完全独立。
    # 支持任意 OpenAI-compatible endpoint，例如 LM Studio: http://localhost:1234/v1
    lightrag_llm_base_url: str = ""
    lightrag_llm_model: str = ""


@dataclass
class VectorDbConfig:
    """向量数据库与检索后端配置。"""

    backend: str = "milvus"
    db_filename: str = "vector_store.db"
    auto_index_enabled: bool = True


@dataclass
class EmbeddingConfig:
    """Shared embedding configuration for Milvus and LightRAG."""

    provider: str = "local"
    model: str = "intfloat/multilingual-e5-small"
    base_url: str = "https://api.openai.com/v1"
    max_token_size: int = 512


@dataclass
class AskAgentConfig:
    """Ask Agent 的会话增强和回答配置。"""

    conversation_enhancement_mode: str = "inject"


# ── 解析门面 ────────────────────────────────────────────────────


@dataclass
class Config:
    """原始配置的唯一解析入口。持有 raw dict，按需产出各子系统的 typed config。"""

    raw: dict[str, Any] = field(default_factory=dict)
    runtime_diagnostics: list[str] = field(default_factory=list)
    runtime_embedding_dimension: int | None = None

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

    def add_diagnostic(self, message: str) -> None:
        if message not in self.runtime_diagnostics:
            self.runtime_diagnostics.append(message)

    def set_embedding_dimension(self, dimension: int) -> None:
        self.runtime_embedding_dimension = dimension

    def to_public_dict(self) -> dict[str, Any]:
        """返回前端可展示的有效配置；敏感字段脱敏。"""
        source = self.get_source_store_config()
        r2 = self.get_r2_sync_config()
        notion = self.get_notion_sync_config()
        web = self.get_web_console_config()
        graph = self.get_graph_config()
        vector_db = self.get_vector_db_config()
        embedding = self.get_embedding_config()
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
                "llm_max_async": graph.llm_max_async,
                "embedding_max_async": graph.embedding_max_async,
                "working_dir": graph.working_dir,
                "lightrag_llm_base_url": graph.lightrag_llm_base_url,
                "lightrag_llm_model": graph.lightrag_llm_model,
            },
            "vector_db": {
                "backend": vector_db.backend,
                "db_filename": vector_db.db_filename,
                "auto_index_enabled": vector_db.auto_index_enabled,
            },
            "embedding": {
                "provider": embedding.provider,
                "model": embedding.model,
                "base_url": embedding.base_url,
                "max_token_size": embedding.max_token_size,
                "actual_dimension": self.runtime_embedding_dimension,
                "api_key": _mask(_secret("", ENV_EMBEDDING_API_KEY)),
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
            if not _module_available("boto3"):
                diagnostics.append(
                    "R2 sync requires optional dependencies from requirements-additional.txt."
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
        embedding_raw = _section(self.raw, "embedding")
        vector_raw = _section(self.raw, "vector_db")
        graph_raw = _section(self.raw, "graph")
        legacy_keys = {"embedding_provider", "embedding_model", "base_url"}
        uses_legacy_embedding = any(
            key not in embedding_raw and key in vector_raw
            for key in legacy_keys
        ) or ("max_token_size" not in embedding_raw and "max_token_size" in graph_raw)
        if uses_legacy_embedding:
            diagnostics.append(
                "Legacy embedding settings are active; migrate them to the top-level "
                "embedding section."
            )
        embedding = self.get_embedding_config()
        if embedding.provider == "astr":
            diagnostics.append(
                "embedding.provider=astr is not implemented; choose local or external."
            )
        elif embedding.provider == "local" and not _module_available("sentence_transformers"):
            diagnostics.append(
                "Local embedding requires optional dependencies from "
                "requirements-additional.txt."
            )
        elif embedding.provider == "external" and not _secret("", ENV_EMBEDDING_API_KEY):
            diagnostics.append(
                "KR_EMBEDDING_API_KEY is required when embedding.provider=external."
            )
        if self.get_vector_db_config().backend == "milvus" and not _module_available("pymilvus"):
            diagnostics.append(
                "Milvus Lite requires optional dependencies from requirements-additional.txt; "
                "SQLite/AstrBot fallback remains available."
            )
        if self.get_graph_config().enabled and not _module_available("lightrag"):
            diagnostics.append(
                "LightRAG requires optional dependencies from requirements-additional.txt."
            )
        return diagnostics + list(self.runtime_diagnostics)

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
            llm_max_async=int(s.get("llm_max_async", GraphConfig.llm_max_async)),
            embedding_max_async=int(s.get("embedding_max_async", GraphConfig.embedding_max_async)),
            working_dir=str(s.get("working_dir", GraphConfig.working_dir)),
            max_doc_chars=max(0, int(s.get("max_doc_chars", GraphConfig.max_doc_chars))),
            lightrag_llm_base_url=str(s.get("lightrag_llm_base_url", GraphConfig.lightrag_llm_base_url)),
            lightrag_llm_model=str(s.get("lightrag_llm_model", GraphConfig.lightrag_llm_model)),
        )

    def get_vector_db_config(self) -> VectorDbConfig:
        s = _section(self.raw, "vector_db")
        raw_auto = s.get("auto_index_enabled", VectorDbConfig.auto_index_enabled)
        auto_index = bool(raw_auto) if not isinstance(raw_auto, bool) else raw_auto
        return VectorDbConfig(
            backend=s.get("backend", VectorDbConfig.backend),
            db_filename=s.get("db_filename", VectorDbConfig.db_filename),
            auto_index_enabled=auto_index,
        )

    def get_embedding_config(self) -> EmbeddingConfig:
        current = _section(self.raw, "embedding")
        legacy_vector = _section(self.raw, "vector_db")
        legacy_graph = _section(self.raw, "graph")
        return EmbeddingConfig(
            provider=str(
                current.get(
                    "provider",
                    legacy_vector.get("embedding_provider", EmbeddingConfig.provider),
                )
            ),
            model=str(
                current.get(
                    "model",
                    legacy_vector.get("embedding_model", EmbeddingConfig.model),
                )
            ),
            base_url=str(
                current.get(
                    "base_url",
                    legacy_vector.get("base_url", EmbeddingConfig.base_url),
                )
            ),
            max_token_size=int(
                current.get(
                    "max_token_size",
                    legacy_graph.get("max_token_size", EmbeddingConfig.max_token_size),
                )
            ),
        )

    def get_ask_agent_config(self) -> AskAgentConfig:
        s = _section(self.raw, "ask")
        return AskAgentConfig(
            conversation_enhancement_mode=s.get(
                "conversation_enhancement_mode", AskAgentConfig.conversation_enhancement_mode
            ),
        )


# ── 可写配置键登记（API 写入 / 运行时持久化的唯一真相源）────────────
#
# 此前「允许写入的键」散落三处：api 的 _CONFIG_UPDATE_KEYS、_STRUCTURAL_KEYS 与
# runtime_config 的 _ALLOWED_RUNTIME_KEYS。在此收口为单一登记表，两个消费者各自派生其
# 子集（见 api.py / runtime_config.py）。新增项须与 _conf_schema.json 同步（CLAUDE.md §6）。

# 切换某键后的后果标识：none 即时生效 / restart 需重启插件 / rebuild 需重建索引（且隐含重启）。
CONSEQUENCE_NONE = "none"
CONSEQUENCE_RESTART = "restart"
CONSEQUENCE_REBUILD = "rebuild"


@dataclass(frozen=True)
class ConfigKeyPolicy:
    """单个配置键的写入策略。

    api_writable        可经 /api/config/update 写入（机密与结构键不可）。
    runtime_persistable 可写入 data_dir/runtime_config.json 持久化。
    structural          结构性参数：禁止运行时 API 写，改后须重建/重启（防静默破坏数据）。
    consequence         改动后果，用于计算 restart_required / rebuild_required 与前端提示。
    """

    api_writable: bool = False
    runtime_persistable: bool = False
    structural: bool = False
    consequence: str = CONSEQUENCE_NONE


# 注：r2_sync.enabled / notion_sync.enabled / source_store.ocr_enabled 为新纳入的非机密开关，
# 让数据流向导可「按需切换」更多环节；机密（secret_access_key/password/api_key）始终不可写。
CONFIG_KEY_POLICY: dict[str, dict[str, ConfigKeyPolicy]] = {
    "vector_db": {
        "backend": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "auto_index_enabled": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "db_filename": ConfigKeyPolicy(
            False, True, structural=True, consequence=CONSEQUENCE_RESTART
        ),
    },
    "embedding": {
        "provider": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_REBUILD),
        "model": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_REBUILD),
        "base_url": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_REBUILD),
        "max_token_size": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
    },
    "ask": {
        "conversation_enhancement_mode": ConfigKeyPolicy(True, True),
        "persona_enabled": ConfigKeyPolicy(False, True),
    },
    "graph": {
        "enabled": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "query_mode": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "llm_max_async": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "embedding_max_async": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "working_dir": ConfigKeyPolicy(
            False, False, structural=True, consequence=CONSEQUENCE_RESTART
        ),
        "lightrag_llm_base_url": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "lightrag_llm_model": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
    },
    "notion_sync": {
        "enabled": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
        "database_id": ConfigKeyPolicy(False, True),
        "parent_page_id": ConfigKeyPolicy(False, True),
        "database_title": ConfigKeyPolicy(False, True),
    },
    "r2_sync": {
        "enabled": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
    },
    "source_store": {
        "ocr_enabled": ConfigKeyPolicy(True, True, consequence=CONSEQUENCE_RESTART),
    },
}


def api_writable_keys() -> dict[str, frozenset[str]]:
    """可经 API 写入的键（排除机密与结构键）。供 api._CONFIG_UPDATE_KEYS 派生。"""
    return {
        section: frozenset(k for k, p in keys.items() if p.api_writable and not p.structural)
        for section, keys in CONFIG_KEY_POLICY.items()
        if any(p.api_writable and not p.structural for p in keys.values())
    }


def structural_keys() -> dict[str, frozenset[str]]:
    """结构性键：禁止运行时 API 写。供 api._STRUCTURAL_KEYS 派生。"""
    return {
        section: frozenset(k for k, p in keys.items() if p.structural)
        for section, keys in CONFIG_KEY_POLICY.items()
        if any(p.structural for p in keys.values())
    }


def runtime_persistable_keys() -> dict[str, frozenset[str]]:
    """可写入 runtime_config.json 的键。供 runtime_config._ALLOWED_RUNTIME_KEYS 派生。"""
    return {
        section: frozenset(k for k, p in keys.items() if p.runtime_persistable)
        for section, keys in CONFIG_KEY_POLICY.items()
        if any(p.runtime_persistable for p in keys.values())
    }


def change_consequence(section: str, key: str) -> str:
    """返回改动该键的后果标识（none/restart/rebuild）；未登记键按 none 处理。"""
    policy = CONFIG_KEY_POLICY.get(section, {}).get(key)
    return policy.consequence if policy else CONSEQUENCE_NONE


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
    "ENV_EMBEDDING_API_KEY",
    "ENV_LIGHTRAG_LLM_API_KEY",
    "CONSEQUENCE_NONE",
    "CONSEQUENCE_RESTART",
    "CONSEQUENCE_REBUILD",
    "ConfigKeyPolicy",
    "CONFIG_KEY_POLICY",
    "api_writable_keys",
    "structural_keys",
    "runtime_persistable_keys",
    "change_consequence",
    "merge_config_dicts",
    "SourceStoreConfig",
    "R2SyncConfig",
    "NotionSyncConfig",
    "WebConsoleConfig",
    "GraphConfig",
    "VectorDbConfig",
    "EmbeddingConfig",
    "AskAgentConfig",
    "Config",
]
