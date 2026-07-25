#!/usr/bin/env python3
"""本地实时开发测试脚本：真实 SQLite + Milvus + LightRAG + LLM + MemEcho，端口 6521。

使用前提：
    1. pip install -r requirements-additional.txt  （含 pymilvus、lightrag 等）
    2. 复制 tests/mock_data/Config/config.example.py → tests/mock_data/Config/config.py
       并填入真实的 API Key 与模型名。
       可选：设置 LLM_PROVIDER = "local" 让答案生成走本地 LM Studio/Ollama；
             设置 LIGHTRAG_LLM_PROVIDER = "main" / "local" / "api" 切换图谱构建 LLM。
    3. 若测试 MemEcho：设置环境变量 KR_MEMECHO_API_KEY，或启动后在 Flow 面板保存 Key；
       同时在 config.py 设置 MEMECHO_ENABLED = True。Key 不写入本配置文件。
    4. python tests/mocks/run_dev_realtime.py

启动流程（全自动）：
    - 归档旧测试数据 → 种子 PDF → 生成 clean.md 制品 → 自动构建 Milvus 向量索引 → 启动 WebUI

启动模式（keep / restore / fresh）：
    默认启动时交互选择：
      - 若 .test_data/ 已有文档：回车 = 继续用当前数据（不归档/不种子/不重建）；
        输入归档编号 = 恢复该归档；输入 f = 全新开始。
      - 若 .test_data/ 为空：回车 / n = 全新；输入归档编号 = 恢复该归档。
    也可用 CLI 参数跳过交互：
      python tests/mocks/run_dev_realtime.py --keep      # 直接用当前 .test_data/ 继续
      python tests/mocks/run_dev_realtime.py --restore   # 直接恢复最近一次归档
      python tests/mocks/run_dev_realtime.py --fresh     # 强制全新跑
    说明：
      - keep：当前 .test_data/ 即活动数据，原样起服务，最快。
      - restore：选中的归档会被「移动」为 .test_data/（提升为活动数据，不占双倍磁盘）；
        全新/恢复前会先把当前 .test_data/ 安全归档（不丢数据）。
      - 若数据缺向量库或 embedding 配置已变更，会自动重建索引（仍跳过最耗时的 md 清洗）。

停止：Ctrl+C

注意：本脚本及 tests/mock_data/Config/config.py 均已被 .gitignore，不会入库。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── 将仓库根加入 import 路径 ──────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── 路径常量 ──────────────────────────────────────────────────────
_MOCKS_DIR = Path(__file__).resolve().parent
if str(_MOCKS_DIR) not in sys.path:
    sys.path.insert(0, str(_MOCKS_DIR))

from realtime_config import (  # noqa: E402
    _attach_memecho,
    _memecho_raw_config,
    _resolve_lightrag_llm_settings,
    _resolve_main_llm_settings,
    _str_cfg_or_env,
)
from realtime_data import (  # noqa: E402
    _PDF_DIR,
    _TEST_DATA,
    _archive_step,
    _choose_startup_mode,
    _live_doc_count,
    _seed_pdfs,
)

_CONFIG_PATH = _MOCKS_DIR.parent / "mock_data" / "Config" / "config.py"
_PORT = 6521
_DEFAULT_PASSWORD = "admin123"


# ── 阶段 1：加载本地配置 ──────────────────────────────────────────


def _load_config():
    if not _CONFIG_PATH.exists():
        print(
            f"[Error] 未找到配置文件：{_CONFIG_PATH}\n"
            f"  请先复制 config.example.py → config.py 并填入真实值。"
        )
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("_dev_config", _CONFIG_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── 主启动函数 ────────────────────────────────────────────────────

# 仅出现在「已重建、含 rerank 数据流 UI」的前端产物中的标记串。
_RERANK_UI_MARKER = "flow_quick_rerank"


def _warn_if_frontend_stale(static_dir: Path) -> None:
    """前端新鲜度护栏：所服务产物若不含 rerank 数据流 UI，醒目提示先重建前端。

    realtime 只服务 web/frontend/out（缺则回退 pages/），二者均靠 `npm run build` +
    tools/sync_frontend.py 更新。只改后端、不重建前端时，数据流「问答 Ask」模块不会出现
    rerank 字段——本护栏把「字段没出现」从玄学变成一行明确提示，避免反复踩坑。
    """
    chunks_dir = static_dir / "_next" / "static" / "chunks"
    has_marker = False
    if chunks_dir.exists():
        for js in chunks_dir.rglob("*.js"):
            try:
                if _RERANK_UI_MARKER in js.read_text(encoding="utf-8", errors="ignore"):
                    has_marker = True
                    break
            except OSError:
                continue
    if not has_marker:
        print("=" * 65)
        print("  [警告] 当前前端产物不含 rerank 数据流 UI，数据流『问答 Ask』")
        print(f"         模块将看不到 Rerank 开关/模型/状态字段。产物目录：{static_dir}")
        print("         请先重建前端再启动：")
        print("           cd web/frontend && npm run build")
        print("           python tools/sync_frontend.py")
        print("         并在浏览器硬刷新（Ctrl+Shift+R）清掉旧 chunk 缓存。")
        print("=" * 65)


async def _make_app(cfg, restore: bool = False) -> object:
    import aiosqlite

    from kacore.adapters.llm import LMStudioLLMAdapter as _OpenAICompatibleAdapter
    from kacore.ask_progress import ProgressStore
    from kacore.config import DEFAULT_RERANK_MODEL, Config
    from kacore.domain.models import Collection
    from kacore.log_capture import install as _install_log
    from kacore.metrics import PerformanceTracker
    from kacore.migration_runner import run_migrations
    from kacore.repository.source_store.sqlite import SQLiteSourceDocumentStore
    from kacore.repository.vector_store.milvus_lite import MilvusLiteVectorStore
    from web.server import build_app

    # 0) 最优先安装日志 handler
    _install_log()

    # 阶段 3：创建目录结构
    _TEST_DATA.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DATA / "source.db"

    # 制品包根目录（clean.md 等制品存放于此，供内容端点读取）
    managed_docs_dir = _TEST_DATA / "managed_docs"
    managed_docs_dir.mkdir(parents=True, exist_ok=True)

    # 阶段 4：SQLite source store + 种子文档
    db = await aiosqlite.connect(str(db_path))
    await db.execute("PRAGMA foreign_keys = ON")
    await run_migrations(db)
    store = SQLiteSourceDocumentStore(db)

    # 确保 default collection 存在
    now = datetime.now(timezone.utc)
    await store.upsert_collection(
        Collection(name="default", description="Test_Library 测试集合", created_at=now)
    )

    if restore:
        print("[Restore] 复用归档数据，跳过 PDF 种子与 md 清洗")
    else:
        total_chunks = await _seed_pdfs(store, managed_docs_dir)
        print(f"[Seed] 共导入 {total_chunks} 个 chunks")

    # 阶段 5：Embedding provider（本地 or 云端，由 config.EMBEDDING_PROVIDER 决定）
    embedding_mode = getattr(cfg, "EMBEDDING_PROVIDER", "local")
    if embedding_mode == "external":
        from kacore.repository.embedding.external import ExternalEmbeddingProvider

        os.environ["KR_EMBEDDING_API_KEY"] = cfg.EMBEDDING_API_KEY
        embedding_provider = ExternalEmbeddingProvider(
            base_url=cfg.EMBEDDING_API_URL,
            model_name=cfg.EMBEDDING_MODEL,
        )
        print(f"[Init] Embedding 模式：external（{cfg.EMBEDDING_MODEL}）")
    else:
        from kacore.repository.embedding.local import LocalEmbeddingProvider

        local_model = getattr(cfg, "EMBEDDING_LOCAL_MODEL", "intfloat/multilingual-e5-small")
        embedding_provider = LocalEmbeddingProvider(model_name=local_model)
        print(f"[Init] Embedding 模式：local（{local_model}，首次使用将自动下载）")

    # 探针：获取真实向量维度
    print("[Init] 探测 Embedding 维度...")
    probe = await embedding_provider.embed_query("dimension probe")
    if not probe:
        print("[Error] Embedding 探针返回空向量，请检查 API key 与模型配置")
        sys.exit(1)
    embedding_dim = len(probe)
    print(f"[Init] Embedding 维度：{embedding_dim}")

    # 阶段 6：真实 MilvusLiteVectorStore
    milvus_path = _TEST_DATA / "milvus.db"
    vector_store = MilvusLiteVectorStore(
        db_path=str(milvus_path),
        dim=embedding_dim,
    )
    vector_store.validate_schema()
    print(f"[Init] Milvus Lite 已初始化：{milvus_path}")

    # 阶段 7：主 LLM 适配器（答案生成）
    main_llm = _resolve_main_llm_settings(cfg)
    llm_adapter = _OpenAICompatibleAdapter(
        base_url=main_llm["base_url"],
        model=main_llm["model"],
        api_key=main_llm["api_key"],
        timeout_seconds=getattr(
            cfg,
            "LLM_TIMEOUT_SECONDS",
            getattr(cfg, "LIGHTRAG_LLM_TIMEOUT_SECONDS", 900),
        ),
        max_retries=getattr(cfg, "LLM_MAX_RETRIES", getattr(cfg, "LIGHTRAG_LLM_MAX_RETRIES", 2)),
        retry_backoff_seconds=getattr(
            cfg,
            "LLM_RETRY_BACKOFF_SECONDS",
            getattr(cfg, "LIGHTRAG_LLM_RETRY_BACKOFF_SECONDS", 2.0),
        ),
    )
    print(
        "[Init] 主 LLM 模式："
        f"{main_llm['provider']}  {main_llm['base_url']}  model={main_llm['model']}"
    )

    # 阶段 7.1：LLM 连通性探针（1 次 API 调用，失败则立即退出）
    print("[Init] 验证主 LLM 连通性（1 次 API 调用）…")
    try:
        _llm_ping = await llm_adapter.generate("以'OK'二字回应", allow_mock=False)
        print(f"[Init] 主 LLM 连通性验证通过：{_llm_ping[:40]!r}")
    except Exception as _e:
        print(f"[Error] 主 LLM 连接失败：{_e}")
        print("        请检查 config.py 中的 LLM_PROVIDER 与对应 endpoint/model/key 配置")
        sys.exit(1)

    # 阶段 7.2：图谱构建专用 LLM（可选，独立于主 LLM）
    graph_llm = _resolve_lightrag_llm_settings(cfg)
    if graph_llm["provider"] != "main":
        lightrag_llm_adapter = _OpenAICompatibleAdapter(
            base_url=graph_llm["base_url"],
            model=graph_llm["model"],
            api_key=graph_llm["api_key"],
            timeout_seconds=getattr(cfg, "LIGHTRAG_LLM_TIMEOUT_SECONDS", 900),
            max_retries=getattr(cfg, "LIGHTRAG_LLM_MAX_RETRIES", 2),
            retry_backoff_seconds=getattr(cfg, "LIGHTRAG_LLM_RETRY_BACKOFF_SECONDS", 2.0),
        )
        print(
            "[Init] 图谱构建 LLM："
            f"{graph_llm['provider']}  {graph_llm['base_url']}  model={graph_llm['model']}"
        )
        print("[Init] 验证图谱 LLM 连通性…")
        try:
            _ping2 = await lightrag_llm_adapter.generate("以'OK'二字回应", allow_mock=False)
            print(f"[Init] 图谱 LLM 连通性验证通过：{_ping2[:40]!r}")
        except Exception as _e:
            print(f"[Warning] 图谱 LLM 连接失败：{_e}，回退使用主 LLM")
            lightrag_llm_adapter = llm_adapter
            graph_llm = {"provider": "main", "base_url": "", "model": "", "api_key": ""}
    else:
        lightrag_llm_adapter = llm_adapter
        print("[Init] 图谱构建 LLM：与主 LLM 共用（LIGHTRAG_LLM_PROVIDER=main）")

    # 阶段 8：Config 对象（provider 与实际 embedding_mode 保持一致）
    if embedding_mode == "external":
        embedding_model_name = cfg.EMBEDDING_MODEL
        embedding_base_url = cfg.EMBEDDING_API_URL
    else:
        embedding_model_name = getattr(
            cfg, "EMBEDDING_LOCAL_MODEL", "intfloat/multilingual-e5-small"
        )
        embedding_base_url = ""  # local 模式不需要

    rerank_provider = _str_cfg_or_env(cfg, "RERANK_PROVIDER")
    rerank_model = _str_cfg_or_env(cfg, "RERANK_MODEL", DEFAULT_RERANK_MODEL)
    deep_rerank_weight = _str_cfg_or_env(cfg, "DEEP_THINKING_RERANK_WEIGHT", "0.2")
    rerank_raw = {"model": rerank_model}
    if rerank_provider:
        rerank_raw["provider"] = rerank_provider

    config = Config(
        {
            "source_store": {"default_collection": "default"},
            "vector_db": {
                "backend": "milvus",
                "db_filename": "milvus.db",
                "auto_index_enabled": True,
            },
            "embedding": {
                "provider": embedding_mode,  # "local" or "external"，与实例一致
                "model": embedding_model_name,
                "base_url": embedding_base_url,
                "max_token_size": 512,
            },
            "graph": {
                "enabled": True,
                "working_dir": "lightrag_workspaces",
                "lightrag_llm_provider": graph_llm["provider"],
                "lightrag_llm_base_url": graph_llm["base_url"],
                "lightrag_llm_model": graph_llm["model"],
                "lightrag_llm_timeout_seconds": getattr(cfg, "LIGHTRAG_LLM_TIMEOUT_SECONDS", 900),
                "lightrag_llm_max_retries": getattr(cfg, "LIGHTRAG_LLM_MAX_RETRIES", 2),
                "lightrag_llm_retry_backoff_seconds": getattr(
                    cfg, "LIGHTRAG_LLM_RETRY_BACKOFF_SECONDS", 2.0
                ),
                "lightrag_seconds_per_chunk_local": getattr(
                    cfg, "LIGHTRAG_SECONDS_PER_CHUNK_LOCAL", 90.0
                ),
                "lightrag_seconds_per_chunk_remote": getattr(
                    cfg, "LIGHTRAG_SECONDS_PER_CHUNK_REMOTE", 20.0
                ),
            },
            "rerank": rerank_raw,
            "deep_thinking": {"rerank_weight": deep_rerank_weight},
            "web_console": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": _PORT,
                "username": "admin",
            },
            "memecho": _memecho_raw_config(cfg),
        }
    )
    config.set_embedding_dimension(embedding_dim)

    # 阶段 8.2：IndexCompatibilityStore + embedding fingerprint
    # 必须传入，否则 RetrievalOrchestrator 认为 milvus_compatible=False 直接跳过 Milvus
    from kacore.index_compatibility import IndexCompatibilityStore
    from kacore.index_compatibility import embedding_fingerprint as _make_fingerprint

    index_compat = IndexCompatibilityStore(_TEST_DATA / "index_compatibility.json")
    emb_fingerprint = _make_fingerprint(config.get_embedding_config(), embedding_dim)
    if not restore:
        # 新建的 Milvus 是空库，先标为不兼容；后面 rebuild 完成后再标为兼容
        index_compat.mark_milvus_incompatible("初始化中，正在构建向量索引")
    # restore 模式保留归档自带的兼容性记录，由阶段 9b 据此决定是否重建
    print("[Init] IndexCompatibilityStore 已创建")

    # 阶段 8.1：LightRAGCoreRegistry（真实图谱）
    lightrag_registry = None
    try:
        from kacore.lightrag_core import LightRAGCoreRegistry

        graph_cfg = config.get_graph_config()
        lightrag_registry = LightRAGCoreRegistry(
            config=graph_cfg,
            data_dir=_TEST_DATA,
            llm_adapter=lightrag_llm_adapter,  # type: ignore[arg-type]
            embedding_provider=embedding_provider,
            embedding_dim=embedding_dim,
            max_token_size=512,
            embedding_model=embedding_model_name,
        )
        print("[Init] LightRAGCoreRegistry 已创建")
    except ImportError:
        print("[Init] LightRAG 未安装，图谱功能不可用（向量检索仍正常）")

    # 阶段 9：组装 KnowledgeRepositoryApi
    from kacore.api import KnowledgeRepositoryApi
    from kacore.pipelines.deep_thinking_orchestrator import DeepThinkingOrchestrator
    from kacore.pipelines.retrieval_orchestrator import RetrievalOrchestrator
    from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from kacore.repository.reranker import build_reranker

    retrieval_orchestrator = RetrievalOrchestrator(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=config,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        lightrag_registry=lightrag_registry,
        index_compatibility=index_compat,
        embedding_fingerprint=emb_fingerprint,
    )

    rerank_cfg = config.get_rerank_config()
    dt_cfg = config.get_deep_thinking_config()
    print(
        "[Init] Rerank 配置："
        f"provider={rerank_cfg.provider} model={rerank_cfg.model} "
        f"weight={dt_cfg.rerank_weight}"
    )
    if rerank_cfg.provider == "cross_encoder":
        print("[Init] Rerank 模型将在首次 Deep Thinking 使用时下载/加载")
    else:
        print("[Init] Rerank 关闭：Deep Thinking 使用纯 RRF 排序")
    deep_thinking_orchestrator = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval_orchestrator,
        reranker=build_reranker(
            provider=rerank_cfg.provider,
            model=rerank_cfg.model,
            device=rerank_cfg.device,
            batch_size=rerank_cfg.batch_size,
            max_candidates=rerank_cfg.max_candidates,
        ),
        llm_adapter=llm_adapter,  # type: ignore[arg-type]
        dt_config=dt_cfg,
        rerank_config=rerank_cfg,
    )
    print("[Init] DeepThinkingOrchestrator 已创建（使用主 LLM）")

    # MemEcho 密钥只进入独立的加密 secret store；KR_MEMECHO_API_KEY 仍可作环境变量覆盖。
    from kacore.secret_store import EncryptedSecretStore

    secret_store = EncryptedSecretStore(_TEST_DATA / "secrets")

    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=config,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        retrieval_orchestrator=retrieval_orchestrator,
        deep_thinking_orchestrator=deep_thinking_orchestrator,
        lightrag_registry=lightrag_registry,
        llm_adapter=llm_adapter,  # type: ignore[arg-type]
        metrics=PerformanceTracker(),
        progress_store=ProgressStore(),
        secret_store=secret_store,
        index_compatibility=index_compat,
        embedding_fingerprint=emb_fingerprint,
        managed_documents_dir=managed_docs_dir,  # 供 /content 端点解析 clean.md
    )

    # 阶段 9a：按当前配置装配 MemEcho；此步骤只组装对象，不调用远端 API。
    print(_attach_memecho(api, config))

    # 阶段 9b：构建 Milvus 向量索引（自动，无需手动点击 UI）
    if restore and index_compat.is_milvus_compatible(emb_fingerprint):
        print("[Restore] 向量索引与当前 embedding 配置兼容，跳过重建")
    else:
        if restore:
            print("[Restore] 警告：归档缺向量库或 embedding 配置已变更，将重建索引")
            index_compat.mark_milvus_incompatible("restore: embedding 指纹变更或向量库缺失")
        print("[Init] 正在构建 Milvus 向量索引（embedding 所有 pending chunk）…")
        result = await api.rebuild_index_pending()
        index_compat.mark_milvus_compatible(emb_fingerprint)
        print(
            f"[Init] Milvus 索引构建完成：{result.get('rebuilt_docs', 0)} 文档，"
            f"{result.get('rebuilt_chunks', 0)} chunks"
        )

    # 阶段 10：启动 WebUI
    upload_dir = Path(tempfile.gettempdir()) / "kr_dev_uploads"
    static_dir = _ROOT / "web" / "frontend" / "out"
    if not static_dir.exists():
        static_dir = _ROOT / "pages"
    _warn_if_frontend_stale(static_dir)

    app = build_app(
        api=api,
        static_dir=static_dir,
        upload_dir=upload_dir,
        auth_required=True,
        username="admin",
        password=_DEFAULT_PASSWORD,
    )

    # 初始化全部完成，服务即将就绪
    print("=" * 65)
    print(f"  ✅ 构建完成，现在可以访问： http://127.0.0.1:{_PORT}")
    print(f"     登录： admin / {_DEFAULT_PASSWORD}      退出： Ctrl+C")
    print("=" * 65)
    return app


def main() -> None:
    from aiohttp import web

    print("=" * 65)
    print("  KR 本地开发测试环境（Milvus + LightRAG + Deepseek）")
    print(f"  地址:   http://127.0.0.1:{_PORT}")
    print(f"  登录:   admin / {_DEFAULT_PASSWORD}")
    print("  数据:   真实 Milvus + 真实 LightRAG + 真实 Embedding")
    print(f"  PDF:    {_PDF_DIR}")
    print("  退出:   Ctrl+C")
    print("-" * 65)
    print("  验证路径（向量检索与问答）：")
    print("    Ask 页    → 提问                   → 语义检索 + LLM 回答")
    print("    Search 页 → 输入关键词             → 向量检索结果 + 前后文上下文")
    print("-" * 65)
    print("  验证路径（PDF 浏览器）：")
    print("    Documents 页 → 点击任意文档        → 右侧面板打开")
    print("                 → 切换到「阅读」标签  → PDF 在浏览器内逐页渲染")
    print("                 → 验证页面数量与原 PDF 一致（pdfjs-dist 驱动）")
    print("-" * 65)
    print("  验证路径（文档内容 / Markdown）：")
    print("    Documents 页 → 点击文档            → 右侧面板")
    print("                 → 切换到「内容」标签  → 显示 PyMuPDF4LLM 提取的 clean.md")
    print("-" * 65)
    print("  验证路径（文档笔记）：")
    print("    Documents 页 → 点击文档            → 右侧面板")
    print("                 → 切换到「笔记」标签  → 新建笔记 → 刷新后仍可见")
    print("-" * 65)
    print("  验证路径（LightRAG 图谱）：")
    print("    Graph 页  → 「预估并构建图谱」→「确认」→ 终端出现 [KR LightRAG] insert 日志")
    print("    Graph 页  → 构建完成 → 右侧搜索实体 → 画布显示局部关系网络")
    print("    Ask  页   → 齿轮设置 → 检索方式选「图谱检索」或「联合检索」→ 提问")
    print("-" * 65)
    print("  验证路径（MemEcho API）：")
    print("    Flow 页 → MemEcho → 保存 Key / Probe / 新建或选择 vault")
    print("    Documents 页准备 default 集合 → Flow 页导入 → Ask 页选择 MemEcho 提问")
    print("    HTTP 端点：/api/memecho/probe、/vaults、/import 与 /api/ask")
    print("=" * 65)

    # 阶段 2：选择启动模式（keep 当前 / 恢复归档 / 全新）
    mode, archive = _choose_startup_mode()
    cfg = _load_config()

    if mode == "keep":
        # 直接用当前 .test_data/ 起服务：不归档、不种子、不重建
        print(f"[Keep] 继续使用当前 .test_data/（{_live_doc_count()} 文档，不归档不重建）")
        web.run_app(_make_app(cfg, restore=True), host="127.0.0.1", port=_PORT, print=None)
    elif mode == "restore" and archive is not None:
        # 恢复前先把当前 .test_data/（若有，多为上次崩溃残留）安全归档移走
        _archive_step()
        try:
            shutil.move(str(archive), str(_TEST_DATA))
        except Exception as e:
            print(f"[Restore] 错误：无法恢复归档 {archive.name}/（{e}）")
            sys.exit(1)
        print(f"[Restore] 已恢复归档 {archive.name}/ → .test_data/")
        web.run_app(_make_app(cfg, restore=True), host="127.0.0.1", port=_PORT, print=None)
    else:
        _archive_step()
        web.run_app(_make_app(cfg, restore=False), host="127.0.0.1", port=_PORT, print=None)


if __name__ == "__main__":
    main()
