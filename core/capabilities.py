"""系统能力注册表（横切支撑层，见 ../ARCHITECTURE.md §5「类型化配置」与 §0 可视性）。

【唯一真相源】回答两个问题，供前端向导页、依赖管理面板与后端装配共同消费：
  1. 「某个可选依赖是否已安装、版本几何」——`dependency_statuses()`。
  2. 「数据流每个环节当前用哪个后端、是否就绪、切换有什么后果」——`detect_pipeline()`。

为什么存在：可选依赖检测此前在 `config.py` 与 `plugin_initializer.py` 各写一份
`_module_available`，且前端靠对诊断字符串做子串匹配反推后端状态（脆弱）。本模块把
检测实现收口为一份 `module_available()`，把环节状态收口为结构化快照，杜绝重复与猜测。

依赖方向：本模块仅依赖 stdlib；对 `Config` 的引用只用于类型注解（TYPE_CHECKING），
运行时不反向 import 业务层，符合「横切支撑自身不反向依赖业务」。
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config

# ── 依赖探测（唯一实现）─────────────────────────────────────────


def module_available(name: str) -> bool:
    """模块是否可被 import。

    唯一实现：`config.py` 与 `plugin_initializer.py` 均 `import ... as _module_available`
    委派至此，保证「是否安装」的判断只有一处逻辑。
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _installed_version(dist_name: str) -> str | None:
    """返回已安装发行包的版本号；未安装返回 None。"""
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


# ── 可选依赖清单（与 requirements-additional.txt 同源）──────────────


@dataclass(frozen=True)
class OptionalDependency:
    """一个可选功能依赖的元数据。

    key          稳定标识（前端按此做 i18n 与图标映射）。
    import_name  运行时探测用的顶层 import 名。
    dist_name    PyPI 发行包名（用于查版本，可能与 import 名不同）。
    pip_spec     安装规格，与 requirements-additional.txt 对齐；安装接口只允许清单内的规格。
    feature      所属功能标识（local_embedding / milvus / lightrag / r2）。
    stages       使用该依赖的数据流环节 id 列表。
    """

    key: str
    import_name: str
    dist_name: str
    pip_spec: str
    feature: str
    stages: tuple[str, ...]


# 仅收录「用户可见可选功能」的依赖；核心安装依赖（如 pymupdf4llm）不在手动安装面板内。
# numpy/pytest/ruff/mypy 等开发工具同样不在面板内。
OPTIONAL_DEPENDENCIES: tuple[OptionalDependency, ...] = (
    OptionalDependency(
        key="local_embedding",
        import_name="sentence_transformers",
        dist_name="sentence-transformers",
        pip_spec="sentence-transformers>=3,<6",
        feature="local_embedding",
        stages=("embedding",),
    ),
    OptionalDependency(
        key="milvus",
        import_name="pymilvus",
        dist_name="pymilvus",
        pip_spec="pymilvus[milvus_lite]>=2.5,<3.0",
        feature="milvus",
        stages=("vector_store", "retrieval"),
    ),
    OptionalDependency(
        key="lightrag",
        import_name="lightrag",
        dist_name="lightrag-hku",
        pip_spec="lightrag-hku>=1.5.0rc1,<2.0.0",
        feature="lightrag",
        stages=("graph",),
    ),
    OptionalDependency(
        key="r2",
        import_name="boto3",
        dist_name="boto3",
        pip_spec="boto3",
        feature="r2",
        stages=("sync",),
    ),
)

# 安装接口的白名单：仅允许安装清单内声明的规格，拒绝任意包名（防注入）。
ALLOWED_INSTALL_SPECS: frozenset[str] = frozenset(dep.pip_spec for dep in OPTIONAL_DEPENDENCIES)
_SPEC_BY_KEY: dict[str, str] = {dep.key: dep.pip_spec for dep in OPTIONAL_DEPENDENCIES}


def resolve_install_spec(package: str) -> str:
    """把前端传入的「依赖 key 或 pip 规格」解析为白名单内的安装规格。

    入参可为依赖 key（如 "milvus"）或完整 pip_spec；二者皆须命中白名单，否则抛 ValueError。
    """
    if package in _SPEC_BY_KEY:
        return _SPEC_BY_KEY[package]
    if package in ALLOWED_INSTALL_SPECS:
        return package
    raise ValueError(f"package is not in the optional-dependency allowlist: {package!r}")


def dependency_statuses() -> list[dict[str, Any]]:
    """返回每个可选依赖的安装状态，供依赖管理面板渲染。"""
    return [
        {
            "key": dep.key,
            "import_name": dep.import_name,
            "dist_name": dep.dist_name,
            "pip_spec": dep.pip_spec,
            "feature": dep.feature,
            "stages": list(dep.stages),
            "installed": module_available(dep.import_name),
            "version": _installed_version(dep.dist_name),
        }
        for dep in OPTIONAL_DEPENDENCIES
    ]


# ── 数据流环节快照 ────────────────────────────────────────────────

# 环节状态机：稳定字符串常量，前端按此着色与配徽章，杜绝魔法字面量。
STATUS_READY = "ready"  # 已就绪并生效
STATUS_DEGRADED = "degraded"  # 配置想用某后端，但依赖缺失/未配置，已受控回退
STATUS_OFF = "off"  # 可选功能，当前关闭
STATUS_INFO = "info"  # 信息性环节（无独立后端选择）

# 切换某环节配置后的后果标识。
CONSEQUENCE_NONE = "none"
CONSEQUENCE_RESTART = "restart"
CONSEQUENCE_REBUILD = "rebuild"

ENV_EMBEDDING_API_KEY = "KR_EMBEDDING_API_KEY"


def detect_pipeline(config: Config) -> list[dict[str, Any]]:
    """根据 typed config（含运行时探针维度/诊断）产出数据流各环节的结构化快照。

    这是前端 `/api/capabilities` 的唯一数据来源，取代旧的「前端字符串匹配诊断」做法。
    纯函数式读取 config，无副作用；单测可只构造 Config 即可断言各环节状态。
    """
    source_cfg = config.get_source_store_config()
    zotero_cfg = config.get_zotero_sync_config()
    embedding_cfg = config.get_embedding_config()
    vdb_cfg = config.get_vector_db_config()
    graph_cfg = config.get_graph_config()
    ask_cfg = config.get_ask_agent_config()
    r2_cfg = config.get_r2_sync_config()
    notion_cfg = config.get_notion_sync_config()

    has_local = module_available("sentence_transformers")
    has_milvus = module_available("pymilvus")
    has_lightrag = module_available("lightrag")
    has_boto3 = module_available("boto3")
    has_pdf = module_available("pymupdf4llm")
    has_api_key = bool(os.environ.get(ENV_EMBEDDING_API_KEY))
    dim = config.runtime_embedding_dimension
    embedding_runtime_ready = dim is not None and dim > 0

    # ⓪ Zotero 可选来源：数据流最左端。enabled 时需 pymupdf4llm 清洗就绪；未启用为可选关闭态。
    if not zotero_cfg.enabled:
        zotero_status = STATUS_OFF
    elif has_pdf:
        zotero_status = STATUS_READY
    else:
        zotero_status = STATUS_DEGRADED
    zotero = {
        "id": "zotero",
        "current": "on" if zotero_cfg.enabled else "off",
        "candidates": ["on", "off"],
        "status": zotero_status,
        "switchable": True,
        "consequence": CONSEQUENCE_RESTART,
        "required_deps": [],
        "configured": zotero_cfg.enabled,
        "detail": {
            "sync_mode": zotero_cfg.sync_mode,
            "storage_mode": zotero_cfg.storage_mode,
        },
    }

    # ① 上传 / 分块：txt/md 基础安装即用；PDF 清洗需根 requirements.txt 自动安装的 pymupdf4llm。
    ingest = {
        "id": "ingest",
        "current": "pymupdf4llm",
        "candidates": ["pymupdf4llm"],
        "status": STATUS_READY if has_pdf else STATUS_DEGRADED,
        "switchable": False,
        "consequence": CONSEQUENCE_NONE,
        "required_deps": [],
        "configured": has_pdf,
        "detail": {
            "ocr_enabled": source_cfg.ocr_enabled,
            "pdf_converter": "pymupdf4llm",
            "pdf_converter_ready": has_pdf,
            "dependency_source": "requirements.txt",
        },
    }

    # ② 向量化 Embedding：local 需 sentence-transformers；external 需 API Key。
    if embedding_cfg.provider == "local":
        embed_configured = has_local
        embed_deps = ["local_embedding"]
    elif embedding_cfg.provider == "external":
        embed_configured = has_api_key
        embed_deps = []
    else:  # "astr" 旧值：不支持，禁用 Milvus/LightRAG
        embed_configured = False
        embed_deps = []
    embed_ready = embed_configured and embedding_runtime_ready
    embed_status = STATUS_READY if embed_ready else STATUS_DEGRADED
    embedding = {
        "id": "embedding",
        "current": embedding_cfg.provider,
        "candidates": ["local", "external"],
        "status": embed_status,
        "switchable": True,
        "consequence": CONSEQUENCE_REBUILD,
        "required_deps": embed_deps,
        "configured": embed_configured,
        "detail": {
            "model": embedding_cfg.model,
            "base_url": embedding_cfg.base_url,
            "actual_dimension": dim,
            "api_key_present": has_api_key,
        },
    }

    # ③ 向量库：milvus 需 pymilvus + embedding 就绪，否则受控回退到 AstrBot/SQLite。
    if vdb_cfg.backend == "milvus":
        vector_ready = has_milvus and embedding_runtime_ready
        vector_status = STATUS_READY if vector_ready else STATUS_DEGRADED
        vector_deps = ["milvus"]
    else:  # astr
        vector_status = STATUS_READY
        vector_deps = []
    vector_store = {
        "id": "vector_store",
        "current": vdb_cfg.backend,
        "candidates": ["milvus", "astr"],
        "status": vector_status,
        "switchable": True,
        "consequence": CONSEQUENCE_RESTART,
        "required_deps": vector_deps,
        "configured": True,
        "detail": {"auto_index_enabled": vdb_cfg.auto_index_enabled},
    }

    # ④ 检索编排：自动 RRF 融合，展示当前生效引擎集合。
    engines = ["sqlite_lexical"]
    if vdb_cfg.backend == "milvus" and has_milvus and embedding_runtime_ready:
        engines.insert(0, "milvus")
    else:
        engines.insert(0, "astrbot_kb")
    retrieval = {
        "id": "retrieval",
        "current": "rrf_fusion",
        "candidates": ["rrf_fusion"],
        "status": STATUS_READY,
        "switchable": False,
        "consequence": CONSEQUENCE_NONE,
        "required_deps": [],
        "configured": True,
        "detail": {"engines": engines},
    }

    # ⑤ LightRAG 图谱：可选，enabled 时需 lightrag-hku + embedding 就绪。
    if not graph_cfg.enabled:
        graph_status = STATUS_OFF
    elif has_lightrag and embedding_runtime_ready:
        graph_status = STATUS_READY
    else:
        graph_status = STATUS_DEGRADED
    graph = {
        "id": "graph",
        "current": "on" if graph_cfg.enabled else "off",
        "candidates": ["on", "off"],
        "status": graph_status,
        "switchable": True,
        "consequence": CONSEQUENCE_REBUILD,
        "required_deps": ["lightrag"],
        "configured": graph_cfg.enabled,
        "detail": {
            "query_mode": graph_cfg.query_mode,
            "llm_provider": graph_cfg.lightrag_llm_provider,
        },
    }

    # ⑥ 问答模式：纯配置，无依赖，即时生效。
    ask = {
        "id": "ask",
        "current": ask_cfg.conversation_enhancement_mode,
        "candidates": ["inject", "query_agent"],
        "status": STATUS_READY,
        "switchable": True,
        "consequence": CONSEQUENCE_NONE,
        "required_deps": [],
        "configured": True,
        "detail": {},
    }

    # ⑦ 同步：R2 需 boto3 + 凭证（密钥走 env）；Notion 经 MCP。启用为非机密开关，需重启。
    if not (r2_cfg.enabled or notion_cfg.enabled):
        sync_status = STATUS_OFF
    elif (r2_cfg.enabled and not has_boto3) or (
        r2_cfg.enabled and not (r2_cfg.account_id and r2_cfg.secret_access_key and r2_cfg.bucket)
    ):
        sync_status = STATUS_DEGRADED
    else:
        sync_status = STATUS_READY
    sync = {
        "id": "sync",
        "current": "on" if (r2_cfg.enabled or notion_cfg.enabled) else "off",
        "candidates": ["on", "off"],
        "status": sync_status,
        "switchable": True,
        "consequence": CONSEQUENCE_RESTART,
        "required_deps": ["r2"] if r2_cfg.enabled else [],
        "configured": r2_cfg.enabled or notion_cfg.enabled,
        "detail": {
            "r2_enabled": r2_cfg.enabled,
            "notion_enabled": notion_cfg.enabled,
        },
    }

    return [zotero, ingest, embedding, vector_store, retrieval, graph, ask, sync]


def detect_capabilities(config: Config) -> dict[str, Any]:
    """聚合环节快照 + 依赖状态 + 诊断，作为 `/api/capabilities` 的完整响应体。"""
    return {
        "pipeline": detect_pipeline(config),
        "dependencies": dependency_statuses(),
        "diagnostics": config.get_diagnostics(),
    }


__all__ = [
    "module_available",
    "OptionalDependency",
    "OPTIONAL_DEPENDENCIES",
    "ALLOWED_INSTALL_SPECS",
    "resolve_install_spec",
    "dependency_statuses",
    "detect_pipeline",
    "detect_capabilities",
    "STATUS_READY",
    "STATUS_DEGRADED",
    "STATUS_OFF",
    "STATUS_INFO",
    "CONSEQUENCE_NONE",
    "CONSEQUENCE_RESTART",
    "CONSEQUENCE_REBUILD",
]
