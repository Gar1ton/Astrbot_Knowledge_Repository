/* flow.data.js — 数据层（与代码仓 lib/api.ts 的 capabilities / SWITCH_MAP / i18n 同源）
   纯 JS，挂到 window.FLOW。前端只渲染，不反推状态。 */
(function () {
  "use strict";

  // ── 候选值标签（移植自 page.tsx backendLabel，zh）────────────
  const LABEL = {
    local: "本地离线", external: "云端 API",
    milvus: "Milvus Lite", astr: "AstrBot KB",
    on: "开启", off: "关闭",
    inject: "原生注入", query_agent: "内部代理",
    rrf_fusion: "RRF", sqlite: "SQLite",
    sqlite_lexical: "SQLite", astrbot_kb: "AstrBot KB",
  };
  const label = (v) => LABEL[v] || v;

  // ── SWITCH_MAP（移植自 page.tsx，决定写哪个 section.key）────────
  const SWITCH_MAP = {
    embedding:    { section: "embedding", key: "provider" },
    vector_store: { section: "vector_db", key: "backend" },
    ask:          { section: "ask",       key: "conversation_enhancement_mode" },
    graph:        { section: "graph",     key: "enabled", toBool: true },
    sync:         { section: "web_console", key: "sync_enabled", toBool: true },
  };

  // ── 阶段静态元数据（标题 / 角色标签 / 描述 / 图标键 / 跳转 / 终端面）──
  //   kind: "pipe"=管线环节, "dest"=用户可进入的真实界面（更显眼 + 跳转入口）
  const STAGE_META = {
    ingest:       { idx: 1, name: "上传 / 分块",      role: "只读",        icon: "doc",   kind: "pipe",
      desc: "上传的文档先留存原件，再切成文本片段存入 SQLite。基础安装即可用。" },
    embedding:    { idx: 2, name: "向量化",           role: "可切换",      icon: "spark", kind: "pipe",
      desc: "把文本片段转成向量。可用本地模型离线计算，或调用云端 API。" },
    vector_store: { idx: 3, name: "向量库",           role: "可切换",      icon: "db",    kind: "pipe",
      desc: "存放向量并做稠密检索。默认 Milvus Lite，可回退到 AstrBot 知识库。" },
    retrieval:    { idx: 4, name: "检索编排",         role: "只读 · 默认", icon: "layers", kind: "pipe",
      desc: "默认检索路径：向量与词汇多路召回，RRF 融合排序，自动完成。" },
    graph:        { idx: 5, name: "LightRAG 图谱",    role: "可选 · 并联", icon: "graph", kind: "pipe",
      link: { label: "打开图谱视图", href: "/graph" },
      desc: "与检索编排并联的高精度路径，基于知识图谱召回。可选启用，不影响默认检索。" },
    ask:          { idx: 6, name: "问答 Ask",         role: "界面 · 可切换", icon: "chat", kind: "dest",
      link: { label: "进入问答界面", href: "/ask" },
      desc: "知识库问答主界面。把检索到的上下文注入回答，或交由内部代理直接作答。" },
    sync:         { idx: 7, name: "同步 / 备份",      role: "界面 · 旁路", icon: "cloud", kind: "dest",
      link: { label: "进入同步设置", href: "/sync" },
      desc: "把知识库镜像备份到 Cloudflare R2 / Notion，与检索互不影响。密钥经环境变量配置。" },
  };

  // ── 节点连接拓扑（并联：vector_store 分叉到 retrieval / graph，二者汇入 ask；
  //    ingest 旁路分支到 sync 做备份）。edge.label 为线上小标签，dashed=旁路虚线。──
  const EDGES = [
    { from: "ingest",       to: "embedding" },
    { from: "embedding",    to: "vector_store" },
    { from: "vector_store", to: "retrieval", label: "默认" },
    { from: "vector_store", to: "graph",     label: "高精度" },
    { from: "retrieval",    to: "ask" },
    { from: "graph",        to: "ask" },
    { from: "ingest",       to: "sync", label: "备份旁路", dashed: true, vertical: true },
  ];

  // ── 状态文案 ───────────────────────────────────────────────
  const STATUS_TEXT = {
    ready: "就绪", degraded: "待处理", off: "可选 · 关闭", info: "信息",
  };

  // ── 依赖元数据（移植自 MOCK_DEPENDENCIES）────────────────────
  const DEP_META = {
    local_embedding: { name: "本地 Embedding",  pip: "sentence-transformers>=3,<6" },
    milvus:          { name: "Milvus 向量库",    pip: "pymilvus[milvus_lite]>=2.5,<3.0" },
    lightrag:        { name: "LightRAG 图谱",    pip: "lightrag-hku>=1.5.0rc1,<2.0.0" },
    r2:              { name: "Cloudflare R2",    pip: "boto3" },
  };

  // ── capabilities 初始快照（移植自 MOCK_CAPABILITIES）──────────
  function initialCaps() {
    return {
      pipeline: [
        { id: "ingest",       current: "sqlite",     candidates: ["sqlite"],            status: "ready", switchable: false, consequence: "none",    required_deps: [],                detail: {} },
        { id: "embedding",    current: "local",      candidates: ["local", "external"], status: "ready", switchable: true,  consequence: "rebuild", required_deps: ["local_embedding"], detail: { model: "intfloat/multilingual-e5-small", actual_dimension: 384 } },
        { id: "vector_store", current: "milvus",     candidates: ["milvus", "astr"],    status: "ready", switchable: true,  consequence: "restart", required_deps: ["milvus"],          detail: {} },
        { id: "retrieval",    current: "rrf_fusion", candidates: ["rrf_fusion"],        status: "ready", switchable: false, consequence: "none",    required_deps: [],                detail: { engines: ["milvus", "sqlite_lexical"] } },
        { id: "graph",        current: "off",        candidates: ["on", "off"],         status: "off",   switchable: true,  consequence: "rebuild", required_deps: ["lightrag"],        detail: { query_mode: "mix" } },
        { id: "ask",          current: "inject",     candidates: ["inject", "query_agent"], status: "ready", switchable: true, consequence: "none", required_deps: [],                detail: {} },
        { id: "sync",         current: "off",        candidates: ["on", "off"],         status: "off",   switchable: true,  consequence: "restart", required_deps: ["r2"],             detail: {} },
      ],
      dependencies: [
        { key: "local_embedding", installed: true,  version: "3.0.1", pip_spec: DEP_META.local_embedding.pip },
        { key: "milvus",          installed: true,  version: "2.5.0", pip_spec: DEP_META.milvus.pip },
        { key: "lightrag",        installed: false, version: null,    pip_spec: DEP_META.lightrag.pip },
        { key: "r2",              installed: false, version: null,    pip_spec: DEP_META.r2.pip },
      ],
    };
  }

  // ── detail → 摘要字符串（移植自 buildDetail）────────────────
  function buildDetail(stage) {
    const parts = [];
    if (stage.detail.model) parts.push(stage.detail.model);
    if (stage.detail.actual_dimension) parts.push(stage.detail.actual_dimension + "d");
    if (stage.id === "retrieval" && Array.isArray(stage.detail.engines))
      parts.push("生效引擎 " + stage.detail.engines.map(label).join(" + "));
    return parts;
  }

  window.FLOW = {
    label, SWITCH_MAP, STAGE_META, EDGES, STATUS_TEXT, DEP_META,
    initialCaps, buildDetail,
    i18n: {
      title: "数据流 / 配置向导",
      subtitle: "查看知识库各环节当前用哪个后端、是否就绪，并按需切换。",
      recheck: "重新检测", rechecking: "检测中…",
      saved: "已保存",
      consequence_restart: "切换后需重启插件",
      consequence_rebuild: "切换后需重启并重建索引",
      restart_banner: "配置已保存。部分改动需重启插件后生效。",
      rebuild_banner: "配置已保存。需重启插件并重建 Milvus / LightRAG 索引。",
      install_banner: "安装完成，需重启插件后生效。",
      missing_dep: "缺少依赖", install_now: "去安装", installing: "安装中…", installed: "已安装",
      legend: { ready: "就绪", degraded: "待处理", off: "未启用" },
    },
  };
})();
