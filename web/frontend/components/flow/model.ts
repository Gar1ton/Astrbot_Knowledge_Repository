import type { I18nKey, Lang } from "@/lib/i18n";
import type { PipelineStage } from "@/lib/api";

export type FlowStageStatus = PipelineStage["status"];

export type FlowStageId =
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
  icon: "doc" | "spark" | "db" | "layers" | "graph" | "chat" | "cloud";
  kind: "pipe" | "dest";
  link?: { labelKey: I18nKey; href: string; primary?: boolean };
};

export const STAGE_META: Record<FlowStageId, FlowStageMeta> = {
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
    link: { labelKey: "flow_open_sync", href: "/sync", primary: true },
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
  embedding: { section: "embedding", key: "provider" },
  vector_store: { section: "vector_db", key: "backend" },
  ask: { section: "ask", key: "conversation_enhancement_mode" },
  graph: { section: "graph", key: "enabled", toBool: true },
};

export const GRID: Record<FlowStageId, { col: number; row: number }> = {
  sync: { col: 1, row: 1 },
  ingest: { col: 1, row: 2 },
  embedding: { col: 2, row: 2 },
  vector_store: { col: 3, row: 2 },
  retrieval: { col: 4, row: 1 },
  graph: { col: 4, row: 3 },
  ask: { col: 5, row: 2 },
};

export const EDGES: FlowEdge[] = [
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
  external: "云端 API",
  milvus: "Milvus Lite",
  astr: "AstrBot KB",
  on: "开启",
  off: "关闭",
  inject: "原生注入",
  query_agent: "内部代理",
  rrf_fusion: "RRF",
  sqlite: "SQLite",
  sqlite_lexical: "SQLite",
  astrbot_kb: "AstrBot KB",
};

const BACKEND_LABEL_EN: Record<string, string> = {
  local: "Local",
  external: "Cloud API",
  milvus: "Milvus Lite",
  astr: "AstrBot KB",
  on: "On",
  off: "Off",
  inject: "Inject",
  query_agent: "Query Agent",
  rrf_fusion: "RRF",
  sqlite: "SQLite",
  sqlite_lexical: "SQLite",
  astrbot_kb: "AstrBot KB",
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

  if (typeof model === "string" && model) parts.push(model);
  if (typeof dim === "number" || typeof dim === "string") parts.push(`${dim}d`);
  if (stage.id === "retrieval" && Array.isArray(engines) && engines.length > 0) {
    parts.push(`${flowEnginesLabel} ${engines.map((e) => backendLabel(String(e), lang)).join(" + ")}`);
  }
  return parts;
}
