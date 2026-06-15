import type { I18nKey, Lang } from "@/lib/i18n";
import type { PipelineStage } from "@/lib/api";

export type FlowStageStatus = PipelineStage["status"];

export type FlowStageId =
  | "zotero"
  | "ingest"
  | "embedding"
  | "vector_store"
  | "retrieval"
  | "graph"
  | "ask"
  | "sync";

export type FlowEdge = {
  from: FlowStageId;
  to: FlowStageId;
  labelKey?: I18nKey;
  dashed?: boolean;
  vertical?: boolean;
};

export type FlowStageMeta = {
  idx: number;
  titleKey: I18nKey;
  descKey: I18nKey;
  roleKey: I18nKey;
  icon: "doc" | "spark" | "db" | "layers" | "graph" | "chat" | "cloud" | "book";
  kind: "pipe" | "dest" | "source";
  link?: { labelKey: I18nKey; href: string; primary?: boolean };
};

export const STAGE_META: Record<FlowStageId, FlowStageMeta> = {
  zotero: {
    idx: 0,
    titleKey: "flow_stage_zotero",
    descKey: "flow_stage_zotero_desc",
    roleKey: "flow_role_optional_source",
    icon: "book",
    kind: "source",
    link: { labelKey: "flow_open_sync", href: "/settings" },
  },
  ingest: {
    idx: 1,
    titleKey: "flow_stage_ingest",
    descKey: "flow_stage_ingest_desc",
    roleKey: "flow_role_readonly",
    icon: "doc",
    kind: "pipe",
  },
  embedding: {
    idx: 2,
    titleKey: "flow_stage_embedding",
    descKey: "flow_stage_embedding_desc",
    roleKey: "flow_role_switchable",
    icon: "spark",
    kind: "pipe",
  },
  vector_store: {
    idx: 3,
    titleKey: "flow_stage_vector_store",
    descKey: "flow_stage_vector_store_desc",
    roleKey: "flow_role_switchable",
    icon: "db",
    kind: "pipe",
  },
  retrieval: {
    idx: 4,
    titleKey: "flow_stage_retrieval",
    descKey: "flow_stage_retrieval_desc",
    roleKey: "flow_role_default",
    icon: "layers",
    kind: "pipe",
  },
  graph: {
    idx: 5,
    titleKey: "flow_stage_graph",
    descKey: "flow_stage_graph_desc",
    roleKey: "flow_role_parallel",
    icon: "graph",
    kind: "pipe",
    link: { labelKey: "flow_open_graph", href: "/graph" },
  },
  ask: {
    idx: 6,
    titleKey: "flow_stage_ask",
    descKey: "flow_stage_ask_desc",
    roleKey: "flow_role_interface_switchable",
    icon: "chat",
    kind: "dest",
    link: { labelKey: "flow_open_ask", href: "/ask", primary: true },
  },
  sync: {
    idx: 7,
    titleKey: "flow_stage_sync",
    descKey: "flow_stage_sync_desc",
    roleKey: "flow_role_interface_bypass",
    icon: "cloud",
    kind: "dest",
    link: { labelKey: "flow_open_sync", href: "/settings", primary: true },
  },
};

export const FIELD_LABEL_KEYS: Partial<Record<FlowStageId, I18nKey>> = {
  ingest: "flow_field_store",
  embedding: "flow_field_provider",
  vector_store: "flow_field_backend",
  retrieval: "flow_field_strategy",
  graph: "flow_field_enabled",
  ask: "flow_field_mode",
  sync: "flow_field_enabled",
};

export const SWITCH_MAP: Partial<Record<FlowStageId, { section: string; key: string; toBool?: boolean }>> = {
  zotero: { section: "zotero_sync", key: "enabled", toBool: true },
  embedding: { section: "embedding", key: "provider" },
  vector_store: { section: "vector_db", key: "backend" },
  ask: { section: "ask", key: "conversation_enhancement_mode" },
  graph: { section: "graph", key: "enabled", toBool: true },
};

// 整体右移一列，最左列(col 1)留给 Zotero 可选来源；与 ingest 同行(row 2)。
export const GRID: Record<FlowStageId, { col: number; row: number }> = {
  zotero: { col: 1, row: 2 },
  sync: { col: 2, row: 1 },
  ingest: { col: 2, row: 2 },
  embedding: { col: 3, row: 2 },
  vector_store: { col: 4, row: 2 },
  retrieval: { col: 5, row: 1 },
  graph: { col: 5, row: 3 },
  ask: { col: 6, row: 2 },
};

export const EDGES: FlowEdge[] = [
  { from: "zotero", to: "ingest", labelKey: "flow_edge_zotero", dashed: true },
  { from: "ingest", to: "embedding" },
  { from: "embedding", to: "vector_store" },
  { from: "vector_store", to: "retrieval", labelKey: "flow_edge_default" },
  { from: "vector_store", to: "graph", labelKey: "flow_edge_precision" },
  { from: "retrieval", to: "ask" },
  { from: "graph", to: "ask" },
  { from: "ingest", to: "sync", labelKey: "flow_edge_backup", dashed: true, vertical: true },
];

const BACKEND_LABEL_ZH: Record<string, string> = {
  local: "本地离线",
  server: "服务器 API",
  external: "云端 API",
  milvus: "Milvus Lite",
  astr: "AstrBot KB",
  on: "开启",
  off: "关闭",
  inject: "原生注入",
  query_agent: "内部代理",
  cross_encoder: "本地 Rerank",
  noop: "关闭 Rerank",
  idle: "待首次使用",
  loading: "加载中",
  ready: "已就绪",
  failed: "加载失败",
  rrf_fusion: "RRF",
  sqlite: "SQLite",
  sqlite_lexical: "SQLite",
  astrbot_kb: "AstrBot KB",
  strict_mirror: "严格镜像",
  conservative: "保守同步",
  archive: "归档堆栈",
  managed_copy: "副本托管",
  linked: "链接 Zotero",
};

const BACKEND_LABEL_EN: Record<string, string> = {
  local: "Local",
  server: "Server API",
  external: "Cloud API",
  milvus: "Milvus Lite",
  astr: "AstrBot KB",
  on: "On",
  off: "Off",
  inject: "Inject",
  query_agent: "Query Agent",
  cross_encoder: "Local Rerank",
  noop: "Rerank Off",
  idle: "Idle",
  loading: "Loading",
  ready: "Ready",
  failed: "Failed",
  rrf_fusion: "RRF",
  sqlite: "SQLite",
  sqlite_lexical: "SQLite",
  astrbot_kb: "AstrBot KB",
  strict_mirror: "Strict mirror",
  conservative: "Conservative",
  archive: "Archive",
  managed_copy: "Managed copy",
  linked: "Linked",
};

export function isFlowStageId(id: string): id is FlowStageId {
  return id in STAGE_META;
}

export function backendLabel(value: string, lang: Lang): string {
  return (lang === "zh" ? BACKEND_LABEL_ZH : BACKEND_LABEL_EN)[value] ?? value;
}

export function buildDetailParts(stage: PipelineStage, lang: Lang, flowEnginesLabel: string): string[] {
  const parts: string[] = [];
  const model = stage.detail.model;
  const dim = stage.detail.actual_dimension;
  const engines = stage.detail.engines;
  const pending = stage.detail.pending_reindex_count;
  const docs = stage.detail.document_count;
  const chunks = stage.detail.chunk_count;
  const rerankModel = stage.detail.rerank_model;
  const rerankStatus = stage.detail.rerank_status;

  if (typeof model === "string" && model) parts.push(model);
  if (typeof dim === "number" || typeof dim === "string") parts.push(`${dim}d`);
  if (stage.id === "retrieval" && Array.isArray(engines) && engines.length > 0) {
    parts.push(`${flowEnginesLabel} ${engines.map((e) => backendLabel(String(e), lang)).join(" + ")}`);
  }
  if (stage.id === "ask") {
    if (typeof rerankStatus === "string" && rerankStatus) {
      parts.push(lang === "zh" ? `Rerank ${backendLabel(rerankStatus, lang)}` : `Rerank ${backendLabel(rerankStatus, lang)}`);
    }
    if (typeof rerankModel === "string" && rerankModel) parts.push(rerankModel);
  }
  if (stage.id === "vector_store") {
    if (typeof docs === "number") parts.push(lang === "zh" ? `${docs} 文档` : `${docs} docs`);
    if (typeof chunks === "number") parts.push(lang === "zh" ? `${chunks} chunks` : `${chunks} chunks`);
    if (typeof pending === "number" && pending > 0) {
      parts.push(lang === "zh" ? `${pending} 待重建` : `${pending} pending`);
    }
  }
  return parts;
}
