/**
 * lib/api.ts — 唯一网络出口
 * 所有组件禁止裸 fetch，必须经此模块。
 * ?mock 参数启用内置离线模拟数据。
 */

// ─── 类型定义 ──────────────────────────────────────────────────

export interface Collection {
  name: string;
  description?: string;
  is_system?: boolean;
  origin?: "local" | "zotero";
  read_only?: boolean;
  zotero_collection_key?: string;
}

export interface ZoteroMeta {
  item_type?: string;
  creators?: string[];
  year?: string;
  venue?: string;
  doi?: string;
  url?: string;
  abstract?: string;
}

export interface KrDocument {
  doc_id: string;
  title?: string;
  filename?: string;
  collection: string;
  tags: string[];
  size?: number;
  chunks?: number;
  updated?: string;
  ext?: string;
  needs_reindex?: boolean;
  lightrag_index_status?: { status: string; collection: string; last_error?: string } | null;
  // 制品包 / 来源 / 三指示元数据（v0.22.0）
  origin?: "local" | "zotero";
  read_only?: boolean;
  lifecycle_state?: "active" | "detached";
  library_id?: string;
  zotero_item_key?: string;
  attachment_key?: string;
  last_synced_at?: string | null;
  milvus_covered?: boolean;
  zotero_meta?: ZoteroMeta;
}

export interface KbChunkContext {
  chunk_id: string;
  doc_id: string;
  ordinal: number;
  text: string;
}

export interface KbChunk {
  chunk_id: string;
  doc_id: string;
  ordinal: number;
  text: string;
  context_before?: KbChunkContext[];
  context_after?: KbChunkContext[];
}

export interface ChunkContextResult {
  context_before: KbChunkContext[];
  context_after: KbChunkContext[];
  matched_chunk_id: string;
}

export interface QuotaItem {
  target: string;
  used_bytes: number;
  limit_bytes: number;
  ratio: number;
  detail?: string;
}

export interface EffectiveConfig {
  source_store?: Record<string, unknown>;
  r2_sync?: Record<string, unknown>;
  notion_sync?: Record<string, unknown>;
  web_console?: Record<string, unknown>;
  graph?: Record<string, unknown>;
  ask?: Record<string, unknown>;
  vector_db?: Record<string, unknown>;
  embedding?: Record<string, unknown>;
  zotero_sync?: Record<string, unknown>;
  diagnostics?: string[];
}

export interface ZoteroConfig {
  enabled: boolean;
  access_mode: "local" | "server";
  zotero_data_dir: string;
  resolved_data_dir?: string;
  api_port: number;
  storage_mode: "managed_copy" | "linked";
  linked_root: string;
  sync_mode: "strict_mirror" | "conservative" | "archive";
  auto_sync_enabled: boolean;
  auto_sync_interval_sec: number;
  server_key_present?: boolean;
  server_key_masked?: string;
  server_user_id?: string;
  server_username?: string;
  server_access?: Record<string, unknown>;
  connection?: { connected: boolean; port: number; detail: string };
  availability?: {
    available: boolean;
    reason?: string;
    data_dir?: string;
    access_mode?: "local" | "server";
    server_user_id?: string;
    server_username?: string;
    server_access?: Record<string, unknown>;
  };
  linked_probe?: { valid: boolean; reason: string; resolved: string };
}

export interface ZoteroSyncResult {
  sync_mode?: string;
  storage_mode?: string;
  started_at?: string;
  finished_at?: string | null;
  items_mirrored?: number;
  collections_mirrored?: number;
  new?: string[];
  changed?: string[];
  removed?: string[];
  detached?: string[];
  reattached?: string[];
  skipped_unchanged?: number;
  needs_milvus_rebuild?: boolean;
  errors?: string[];
  status?: string;
  message?: string;
}

export interface ZoteroProbeResult {
  connection: { connected: boolean; port?: number; detail?: string };
  read: {
    available: boolean;
    reason?: string;
    data_dir?: string;
    item_count?: number;
    collection_count?: number;
    attachment_count?: number;
    pdf_attachment_count?: number;
  };
}

export interface GraphNode {
  id: string;
  name: string;
  type?: string;
  degree?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  description?: string;
  weight?: number;
  source_chunk_ids?: string[];
  source_previews?: string[];
}

export interface GraphData {
  status?: string;
  engine?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNotReady {
  status: "not_ready";
  ready: false;
  collection?: string;
  engine?: string;
  reason?: string;
  message?: string;
  build_available: boolean;
}

export type GraphResponse = GraphData | GraphNotReady;

export interface GraphQueryResult {
  status: string;
  query: string;
  collection?: string;
  engine?: string;
  answer?: string;
  context?: string;
  chunks?: KbChunk[];
  entities?: GraphNode[];
  relations?: GraphEdge[];
  debug?: Record<string, unknown>;
}

export interface GraphBuildEstimate {
  collection: string;
  docs_count: number;
  chunks_count: number;
  chars_count: number;
  estimated_lrag_chunks?: number;
  estimated_llm_calls_min: number;
  estimated_llm_calls_max: number;
  estimated_embedding_batches: number;
  estimated_duration_seconds_min: number;
  estimated_duration_seconds_max: number;
  seconds_per_chunk?: number;
  runtime_profile?: "local" | "remote" | string;
  estimate_notice: string;
}

export interface GraphBuildJob {
  job_id: string;
  collection: string;
  engine: "lightrag_core";
  status: string;
  stage?: string;
  paused?: boolean;
  pause_requested?: boolean;
  pause_message?: string;
  processed_docs?: number;
  failed_docs?: number;
  total_docs?: number;
  processed_chunks?: number;
  failed_chunks?: number;
  total_chunks?: number;
  current_doc_id?: string;
  current_chunk_index?: number;
  progress_basis?: "lrag_chunks" | "estimated_lrag_chunks" | string;
  progress_current?: number;
  progress_total?: number;
  progress_percent?: number;
  progress_label?: string;
  elapsed_seconds?: number;
  average_seconds_per_chunk?: number | null;
  estimated_remaining_seconds?: number | null;
  paused_seconds?: number;
  paused_at?: string | null;
  started_at?: string;
  finished_at?: string | null;
  recent_error?: string;
}

export interface AskSource {
  n: number;
  doc_id: string;
  title: string;
  chunk_id: string;
  ordinal: number;
  text: string;
  rrf_score?: number;
}

export interface AskResult {
  conversation_id: string;
  answer: string;
  sources: AskSource[];
  requested_retrieval_mode: "default" | "high_precision" | "graph_only" | "fulltext";
  actual_retrieval_mode: string;
  retrieval_engines: string[];
  fallback_reason?: string | null;
}

export interface ReservedResult {
  reserved: true;
  available_in: string;
}

export type MaybeReserved<T> = T | ReservedResult;

export interface SyncRecord {
  doc_id: string;
  target: string;
  remote_ref?: string | null;
  status: string;
  synced_at?: string | null;
  message?: string;
}

// ─── mock 检测 ─────────────────────────────────────────────────

function isMock(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("mock");
}

// ─── 错误类 ────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ─── 核心 fetch 封装 ───────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    credentials: "include",
  });
  if (!res.ok) {
    let msg = res.statusText;
    let parsedBody: Record<string, unknown> | undefined;
    try {
      const body = await res.json() as Record<string, unknown>;
      parsedBody = body;
      if (res.status === 501 && body.status === "reserved") {
        return {
          ...body,
          reserved: true,
        } as T;
      }
      msg = String(body.error || body.message || body.detail || msg);
    } catch {
      /* ignore parse error */
    }
    throw new ApiError(res.status, msg, parsedBody);
  }
  return res.json() as Promise<T>;
}

// reserved 响应识别
export function isReserved(x: unknown): x is ReservedResult {
  return (
    typeof x === "object" &&
    x !== null &&
    "reserved" in x &&
    (x as ReservedResult).reserved === true
  );
}

export function isGraphNotReady(x: unknown): x is GraphNotReady {
  return (
    typeof x === "object" &&
    x !== null &&
    (x as { status?: unknown }).status === "not_ready" &&
    (x as { ready?: unknown }).ready === false
  );
}

// ─────────────────────────────────────────────────────────────
// MOCK 数据（从 legacy index.html 移植）
// ─────────────────────────────────────────────────────────────

const MOCK_COLLECTIONS: Collection[] = [
  { name: "papers", description: "学术论文集合" },
  { name: "manuals", description: "产品手册与文档" },
  { name: "default", description: "默认集合" },
];

const MOCK_DOCS: KrDocument[] = [
  {
    doc_id: "seed-1",
    title: "Attention Is All You Need.pdf",
    filename: "Attention Is All You Need.pdf",
    collection: "papers",
    tags: ["transformer", "attention", "nlp"],
    size: 2_456_789,
    chunks: 42,
    updated: "2024-03-15T10:30:00Z",
    ext: "pdf",
  },
  {
    doc_id: "seed-2",
    title: "LightRAG: Simple and Fast Retrieval-Augmented Generation.pdf",
    filename: "LightRAG.pdf",
    collection: "papers",
    tags: ["rag", "lightrag", "retrieval"],
    size: 1_234_567,
    chunks: 28,
    updated: "2024-04-20T14:20:00Z",
    ext: "pdf",
  },
  {
    doc_id: "seed-3",
    title: "AstrBot 使用手册.md",
    filename: "AstrBot 使用手册.md",
    collection: "manuals",
    tags: ["astrbot", "manual"],
    size: 98_432,
    chunks: 15,
    updated: "2024-05-01T09:00:00Z",
    ext: "md",
  },
  {
    doc_id: "seed-4",
    title: "GraphRAG 技术报告.pdf",
    filename: "GraphRAG.pdf",
    collection: "papers",
    tags: ["graphrag", "knowledge-graph"],
    size: 3_120_000,
    chunks: 56,
    updated: "2024-04-10T16:00:00Z",
    ext: "pdf",
  },
  {
    doc_id: "seed-5",
    title: "系统配置说明.txt",
    filename: "system-config.txt",
    collection: "default",
    tags: [],
    size: 12_800,
    chunks: 3,
    updated: "2024-05-10T08:30:00Z",
    ext: "txt",
  },
];

const MOCK_KB_CHUNKS: KbChunk[] = [
  { chunk_id: "k1", doc_id: "seed-1", ordinal: 0, text: "Transformer 架构通过自注意力机制（Self-Attention）实现对序列中任意位置的直接依赖建模，彻底摆脱了 RNN 的顺序计算限制。", context_before: [], context_after: [] },
  { chunk_id: "k2", doc_id: "seed-2", ordinal: 1, text: "LightRAG 将知识图谱与向量检索融合，采用双层检索策略：局部级（实体邻域）与全局级（跨文档主题）协同工作以提升召回质量。", context_before: [], context_after: [] },
  { chunk_id: "k3", doc_id: "seed-1", ordinal: 2, text: "RRF（Reciprocal Rank Fusion）是一种无参数排名融合算法，通过 1/(k+rank_i) 公式合并多路召回结果，天然规避了分数量纲不统一的问题。", context_before: [], context_after: [] },
];

const MOCK_GRAPH: GraphData = {
  nodes: [
    { id: "n1", name: "Transformer", type: "Method/Algorithm", degree: 4 },
    { id: "n2", name: "Attention", type: "Method/Algorithm", degree: 3 },
    { id: "n3", name: "LightRAG", type: "Method/Algorithm", degree: 2 },
    { id: "n4", name: "FAISS", type: "Method/Algorithm", degree: 2 },
    { id: "n5", name: "RRF", type: "Method/Algorithm", degree: 3 },
    { id: "n6", name: "Knowledge Graph", type: "Dataset", degree: 2 },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2", relation: "uses", weight: 1.0 },
    { id: "e2", source: "n3", target: "n4", relation: "integrates", weight: 0.8 },
    { id: "e3", source: "n3", target: "n5", relation: "uses", weight: 0.9 },
    { id: "e4", source: "n3", target: "n6", relation: "builds", weight: 1.0 },
    { id: "e5", source: "n5", target: "n2", relation: "leverages", weight: 0.7 },
  ],
};

const MOCK_QUOTA: QuotaItem[] = [
  {
    target: "r2",
    used_bytes: 3_200_000_000,
    limit_bytes: 10_737_418_240,
    ratio: 0.298,
    detail: "3.2 GB / 10 GB",
  },
  {
    target: "notion",
    used_bytes: 52_428_800,
    limit_bytes: 1_073_741_824,
    ratio: 0.049,
    detail: "50 MB / 1 GB",
  },
];

const MOCK_CONFIG: EffectiveConfig = {
  source_store: { db_filename: "knowledge_repository.db", default_collection: "default", ocr_enabled: false },
  r2_sync: { enabled: true, bucket: "kr-bucket", account_id: "ac****nt", access_key_id: "ak****id", secret_access_key: "****", free_tier_gb: 10, warn_threshold: 0.8 },
  notion_sync: { enabled: true, database_id: "db-****", max_upload_mib: 5 },
  web_console: { enabled: true, host: "0.0.0.0", port: 6520, username: "admin", password: "****" },
  graph: { enabled: false, query_mode: "mix", llm_max_async: 4, embedding_max_async: 8, working_dir: "lightrag_workspaces", max_doc_chars: 30000, lightrag_llm_provider: "main", lightrag_llm_base_url: "", lightrag_llm_model: "", lightrag_llm_timeout_seconds: 900 },
  ask: { conversation_enhancement_mode: "inject" },
  vector_db: { backend: "milvus", db_filename: "vector_store.db", auto_index_enabled: true },
  embedding: { provider: "local", model: "intfloat/multilingual-e5-small", base_url: "https://api.openai.com/v1", max_token_size: 512, actual_dimension: 384, api_key: "" },
  zotero_sync: { enabled: false, access_mode: "local", zotero_data_dir: "", resolved_data_dir: "", api_port: 23119, storage_mode: "managed_copy", linked_root: "", sync_mode: "conservative", auto_sync_enabled: false, auto_sync_interval_sec: 3600, server_key_present: false, server_key_masked: "" },
};

const MOCK_ASK: AskResult = {
  conversation_id: "conv-demo-1",
  answer: "Transformer 架构的核心是**自注意力机制**（Self-Attention），它允许模型在处理序列时直接建模任意位置之间的依赖关系 [1]。与 RNN 不同，Transformer 可以并行计算，显著提升训练效率。\n\nLightRAG 则将图结构检索与向量检索融合，通过 RRF 算法 [3] 对多路召回结果进行排名融合，提供更准确的上下文 [2]。",
  sources: [
    { n: 1, doc_id: "seed-1", title: "Attention Is All You Need", chunk_id: "k1", ordinal: 0, text: "Transformer 架构通过自注意力机制（Self-Attention）实现对序列中任意位置的直接依赖建模。", rrf_score: 0.0327 },
    { n: 2, doc_id: "seed-2", title: "LightRAG 论文", chunk_id: "k2", ordinal: 1, text: "LightRAG 将知识图谱与向量检索融合，采用双层检索策略。", rrf_score: 0.0289 },
    { n: 3, doc_id: "seed-1", title: "Attention Is All You Need", chunk_id: "k3", ordinal: 2, text: "RRF 是一种无参数排名融合算法，通过 1/(k+rank_i) 公式合并多路召回结果。", rrf_score: 0.0214 },
  ],
  requested_retrieval_mode: "default",
  actual_retrieval_mode: "milvus",
  retrieval_engines: ["milvus", "sqlite_lexical"],
  fallback_reason: null,
};

// ─────────────────────────────────────────────────────────────
// 认证 Auth
// ─────────────────────────────────────────────────────────────

export async function getAuth(): Promise<{ logged_in: boolean }> {
  if (isMock()) return { logged_in: true };
  return apiFetch<{ logged_in: boolean }>("/api/auth");
}

export async function login(username: string, password: string): Promise<void> {
  if (isMock()) {
    if (username === "admin") return;
    throw new ApiError(401, "用户名或密码错误");
  }
  await apiFetch<{ status: string }>("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  if (isMock()) return;
  try {
    await apiFetch<{ ok: boolean }>("/api/logout", { method: "POST" });
  } catch {
    // Fallback: clear session cookie locally if backend logout endpoint doesn't exist
    if (typeof document !== "undefined") {
      document.cookie = "kr_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;";
    }
  }
}

// ─────────────────────────────────────────────────────────────
// 集合 Collections
// ─────────────────────────────────────────────────────────────

export async function listCollections(): Promise<Collection[]> {
  if (isMock()) return [...MOCK_COLLECTIONS];
  return apiFetch<Collection[]>("/api/collections");
}

export async function createCollection(
  name: string,
  description?: string
): Promise<Collection> {
  if (isMock()) {
    const c: Collection = { name, description };
    MOCK_COLLECTIONS.push(c);
    return c;
  }
  return apiFetch<Collection>("/api/collections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
}

export async function deleteCollection(name: string): Promise<void> {
  if (isMock()) return;
  await apiFetch<{ status: string }>(`/api/collections/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

// ─────────────────────────────────────────────────────────────
// 文档 Documents
// ─────────────────────────────────────────────────────────────

export async function listDocuments(opts?: {
  collection?: string;
  tag?: string;
}): Promise<KrDocument[]> {
  if (isMock()) {
    let docs = [...MOCK_DOCS];
    if (opts?.collection) docs = docs.filter((d) => d.collection === opts.collection);
    if (opts?.tag) docs = docs.filter((d) => d.tags.includes(opts.tag!));
    return docs;
  }
  const params = new URLSearchParams();
  if (opts?.collection) params.set("collection", opts.collection);
  if (opts?.tag) params.set("tag", opts.tag);
  const qs = params.toString();
  return apiFetch<KrDocument[]>(`/api/documents${qs ? `?${qs}` : ""}`);
}

export async function uploadDocument(
  file: File,
  collection: string = "default",
  tags: string[] = []
): Promise<KrDocument> {
  if (isMock()) {
    const doc: KrDocument = {
      doc_id: `mock-${Date.now()}`,
      title: file.name,
      filename: file.name,
      collection,
      tags,
      size: file.size,
      chunks: 0,
      updated: new Date().toISOString(),
      ext: file.name.split(".").pop(),
    };
    MOCK_DOCS.unshift(doc);
    return doc;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("collection", collection);
  if (tags.length) form.append("tags", tags.join(","));
  return apiFetch<KrDocument>("/api/documents", { method: "POST", body: form });
}

export async function patchDocument(
  id: string,
  patch: { collection?: string; tags?: string[] }
): Promise<KrDocument> {
  if (isMock()) {
    const doc = MOCK_DOCS.find((d) => d.doc_id === id);
    if (!doc) throw new ApiError(404, "文档不存在");
    if (patch.collection !== undefined) doc.collection = patch.collection;
    if (patch.tags !== undefined) doc.tags = patch.tags;
    return { ...doc };
  }
  return apiFetch<KrDocument>(`/api/documents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function updateDocumentMeta(
  docId: string,
  meta: Partial<ZoteroMeta> & { title?: string },
): Promise<KrDocument> {
  return apiFetch<KrDocument>(`/api/documents/${encodeURIComponent(docId)}/meta`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(meta),
  });
}

export async function deleteDocument(id: string): Promise<void> {
  if (isMock()) {
    const idx = MOCK_DOCS.findIndex((d) => d.doc_id === id);
    if (idx !== -1) MOCK_DOCS.splice(idx, 1);
    return;
  }
  await apiFetch<{ status: string }>(`/api/documents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function downloadDocument(id: string): void {
  if (isMock() || typeof window === "undefined") return;
  window.location.assign(`/api/documents/${encodeURIComponent(id)}/raw`);
}

// ─────────────────────────────────────────────────────────────
// 知识库检索 KB
// ─────────────────────────────────────────────────────────────

export async function listKbCollections(): Promise<string[]> {
  if (isMock()) return MOCK_COLLECTIONS.map((c) => c.name);
  return apiFetch<string[]>("/api/kb/collections");
}

export async function searchKb(
  collection: string,
  q: string,
  k: number = 5
): Promise<KbChunk[]> {
  if (isMock()) return [...MOCK_KB_CHUNKS];
  const params = new URLSearchParams({ collection, q, top_k: String(k), window: "2" });
  return apiFetch<KbChunk[]>(`/api/kb/search?${params}`);
}

export async function getChunkContext(
  doc_id: string,
  chunk_id: string,
  window: number = 2,
): Promise<ChunkContextResult> {
  const params = new URLSearchParams({ doc_id, chunk_id, window: String(window) });
  return apiFetch<ChunkContextResult>(`/api/kb/chunk-context?${params}`);
}

// ─────────────────────────────────────────────────────────────
// 配额 / 配置 Quota / Config
// ─────────────────────────────────────────────────────────────

export async function getQuota(): Promise<QuotaItem[]> {
  if (isMock()) return [...MOCK_QUOTA];
  return apiFetch<QuotaItem[]>("/api/quota");
}

export async function getEffectiveConfig(): Promise<EffectiveConfig> {
  if (isMock()) return { ...MOCK_CONFIG };
  return apiFetch<EffectiveConfig>("/api/config/effective");
}

const MOCK_REBUILD_KEYS = new Set([
  "embedding.provider",
  "embedding.model",
  "embedding.base_url",
  "graph.max_doc_chars",
  "zotero_sync.storage_mode",
  "zotero_sync.linked_root",
  "zotero_sync.sync_mode",
]);

const MOCK_RESTART_KEYS = new Set([
  "vector_db.backend",
  "vector_db.auto_index_enabled",
  "graph.enabled",
  "graph.query_mode",
  "graph.llm_max_async",
  "graph.embedding_max_async",
  "graph.lightrag_llm_provider",
  "graph.lightrag_llm_base_url",
  "graph.lightrag_llm_model",
  "graph.lightrag_llm_timeout_seconds",
  "r2_sync.enabled",
  "notion_sync.enabled",
  "source_store.ocr_enabled",
  "zotero_sync.enabled",
  "zotero_sync.access_mode",
  "zotero_sync.zotero_data_dir",
  "zotero_sync.api_port",
  "zotero_sync.auto_sync_enabled",
  "zotero_sync.auto_sync_interval_sec",
]);

function applyMockConfigUpdate(section: string, key: string, value: unknown): void {
  const configSection = (MOCK_CONFIG as Record<string, Record<string, unknown>>)[section];
  if (configSection) configSection[key] = value;

  const stage = (id: string) => MOCK_CAPABILITIES.pipeline.find((item) => item.id === id);
  const embedding = stage("embedding");
  const vectorStore = stage("vector_store");
  const graph = stage("graph");
  const ask = stage("ask");
  const sync = stage("sync");
  const ingest = stage("ingest");
  const zotero = stage("zotero");

  if (section === "embedding" && embedding) {
    if (key === "provider") embedding.current = String(value);
    if (key === "model") embedding.detail.model = value;
    if (key === "max_token_size") embedding.detail.max_token_size = value;
  }

  if (section === "vector_db" && vectorStore) {
    if (key === "backend") vectorStore.current = String(value);
    if (key === "auto_index_enabled") vectorStore.detail.auto_index_enabled = Boolean(value);
  }

  if (section === "ask" && key === "conversation_enhancement_mode" && ask) {
    ask.current = String(value);
  }

  if (section === "graph" && graph) {
    if (key === "enabled") {
      const enabled = Boolean(value);
      graph.current = enabled ? "on" : "off";
      graph.status = enabled ? "degraded" : "off";
      graph.configured = enabled;
    } else {
      graph.detail[key] = value;
    }
  }

  if ((section === "r2_sync" || section === "notion_sync") && key === "enabled" && sync) {
    sync.detail[section === "r2_sync" ? "r2_enabled" : "notion_enabled"] = Boolean(value);
    const r2Enabled = Boolean(MOCK_CONFIG.r2_sync?.enabled);
    const notionEnabled = Boolean(MOCK_CONFIG.notion_sync?.enabled);
    sync.current = r2Enabled || notionEnabled ? "on" : "off";
    sync.status = r2Enabled || notionEnabled ? "ready" : "off";
    sync.configured = r2Enabled || notionEnabled;
  }

  if (section === "source_store" && key === "ocr_enabled" && ingest) {
    ingest.detail.ocr_enabled = Boolean(value);
  }

  if (section === "zotero_sync" && zotero) {
    if (key === "enabled") {
      const enabled = Boolean(value);
      zotero.current = enabled ? "on" : "off";
      zotero.status = enabled ? "ready" : "off";
      zotero.configured = enabled;
    } else {
      zotero.detail[key] = value;
    }
  }
}

function mockConfigResult(section: string, key: string): ConfigUpdateResult {
  const fullKey = `${section}.${key}`;
  return {
    status: "success",
    restart_required: MOCK_RESTART_KEYS.has(fullKey),
    rebuild_required: MOCK_REBUILD_KEYS.has(fullKey),
    message: "Configuration saved.",
  };
}

export async function updateConfigValue(
  section: string,
  key: string,
  value: unknown
): Promise<ConfigUpdateResult> {
  if (isMock()) {
    applyMockConfigUpdate(section, key, value);
    return mockConfigResult(section, key);
  }
  return apiFetch<ConfigUpdateResult>("/api/config/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ section, key, value }),
  });
}

export interface ConfigUpdateResult {
  status: string;
  restart_required: boolean;
  rebuild_required: boolean;
  message: string;
}

export interface RebuildIndexResult {
  status?: string;
  rebuilt_docs: number;
  rebuilt_chunks: number;
  failed_docs?: number;
  errors?: Array<{ doc_id: string; error: string }>;
  message?: string;
}

export async function rebuildIndexPending(): Promise<RebuildIndexResult> {
  if (isMock()) return { status: "ok", rebuilt_docs: 0, rebuilt_chunks: 0, failed_docs: 0, errors: [] };
  return apiFetch("/api/documents/rebuild-index", { method: "POST" });
}

export async function getPendingReindexCount(): Promise<{ count: number }> {
  if (isMock()) return { count: 0 };
  return apiFetch("/api/documents/pending-reindex-count");
}

export interface ChatMessage {
  id?: number;
  role: "user" | "assistant";
  content: string;
  sources: AskSource[];
  retrieval_mode: string;
  created_at: string;
  locked?: boolean;
  locked_at?: string | null;
  updated_at?: string | null;
}

export async function getChatHistory(conversationId: string): Promise<ChatMessage[]> {
  if (isMock()) return [];
  const res = await apiFetch<{ messages: ChatMessage[] }>(
    `/api/chat/history?conversation_id=${encodeURIComponent(conversationId)}`
  );
  return res.messages;
}

export async function clearChatHistory(
  conversationId: string,
  preserveLocked = false,
): Promise<void> {
  if (isMock()) return;
  const qs = new URLSearchParams({ conversation_id: conversationId });
  if (preserveLocked) qs.set("preserve_locked", "true");
  await apiFetch<{ status: string }>(
    `/api/chat/history?${qs}`,
    { method: "DELETE" }
  );
}

export interface EmbeddingTestResult {
  status: "ok" | "error";
  dimension?: number;
  model?: string;
  message?: string;
}

export async function testEmbeddingConnection(
  baseUrl: string,
  modelName: string
): Promise<EmbeddingTestResult> {
  if (isMock()) return { status: "ok", dimension: 1024, model: modelName };
  return apiFetch<EmbeddingTestResult>("/api/config/test-embedding", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: baseUrl, model_name: modelName }),
  });
}

// ─────────────────────────────────────────────────────────────
// 知识图谱 Graph
// ─────────────────────────────────────────────────────────────

export async function getGraph(
  collection?: string
): Promise<MaybeReserved<GraphResponse>> {
  if (isMock()) return { ...MOCK_GRAPH };
  const qs = collection ? `?collection=${encodeURIComponent(collection)}` : "";
  return apiFetch<MaybeReserved<GraphResponse>>(`/api/graph${qs}`);
}

export async function queryGraph(
  q: string,
  collection?: string
): Promise<MaybeReserved<GraphQueryResult>> {
  if (isMock()) {
    return {
      status: "ok",
      query: q,
      collection,
      chunks: MOCK_KB_CHUNKS,
      entities: MOCK_GRAPH.nodes.slice(0, 2),
      relations: MOCK_GRAPH.edges.slice(0, 1),
      context: "模拟图谱查询结果",
      debug: { vector_chunk_ids: ["k1"], keyword_chunk_ids: ["k2"], graph_chunk_ids: ["k3"], rrf_scores: { k1: 0.033, k2: 0.028, k3: 0.021 } },
    };
  }
  const params = new URLSearchParams({ q });
  if (collection) params.set("collection", collection);
  return apiFetch<MaybeReserved<GraphQueryResult>>(`/api/graph/query?${params}`);
}

export async function estimateGraphBuild(collection?: string): Promise<GraphBuildEstimate> {
  if (isMock()) return {
    collection: collection || "papers", docs_count: 5, chunks_count: 144, chars_count: 42000,
    estimated_lrag_chunks: 12,
    estimated_llm_calls_min: 12, estimated_llm_calls_max: 18, estimated_embedding_batches: 2,
    estimated_duration_seconds_min: 648, estimated_duration_seconds_max: 2592,
    seconds_per_chunk: 90, runtime_profile: "local",
    estimate_notice: "这是估算，不是承诺；实际 LLM 调用次数和耗时可能更高。",
  };
  return apiFetch<GraphBuildEstimate>("/api/graph/build/estimate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collection ? { collection } : {}),
  });
}

export async function buildGraph(collection?: string): Promise<GraphBuildJob> {
  if (isMock()) return { job_id: `mock-${Date.now()}`, status: "queued", engine: "lightrag_core", collection: collection || "papers" };
  return apiFetch<GraphBuildJob>("/api/graph/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection, confirmed: true }),
  });
}

export async function getGraphBuildJob(jobId: string): Promise<GraphBuildJob> {
  if (isMock()) return {
    job_id: jobId, status: "success", stage: "done", engine: "lightrag_core", collection: "papers",
    processed_docs: 5, failed_docs: 0, total_docs: 5,
    processed_chunks: 12, failed_chunks: 0, total_chunks: 12, progress_basis: "lrag_chunks",
    elapsed_seconds: 840, average_seconds_per_chunk: 70, estimated_remaining_seconds: 0,
  };
  return apiFetch<GraphBuildJob>(`/api/graph/build/${encodeURIComponent(jobId)}`);
}

export async function getActiveBuildJob(): Promise<GraphBuildJob | null> {
  if (isMock()) return null;
  const res = await apiFetch<{ job: GraphBuildJob | null }>("/api/graph/build/active");
  return res.job;
}

export interface BuildJobRecord {
  job_id: string;
  collection: string;
  status: string;
  stage: string;
  processed_docs: number;
  failed_docs: number;
  total_docs: number;
  processed_chunks: number;
  failed_chunks?: number;
  total_chunks: number;
  recent_error: string;
  started_at: string;
  finished_at: string | null;
  created_at: string;
  pause_requested?: boolean;
  paused_at?: string | null;
  paused_seconds?: number;
  progress_current?: number;
  progress_total?: number;
}

export async function getBuildJobHistory(collection?: string): Promise<BuildJobRecord[]> {
  if (isMock()) return [];
  const qs = collection ? `?collection=${encodeURIComponent(collection)}` : "";
  const res = await apiFetch<{ jobs: BuildJobRecord[] }>(`/api/graph/build/history${qs}`);
  return res.jobs;
}

export async function pauseBuildJob(jobId: string): Promise<void> {
  if (isMock()) return;
  await apiFetch(`/api/graph/build/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
}

export async function resumeBuildJob(jobId: string): Promise<void> {
  if (isMock()) return;
  await apiFetch(`/api/graph/build/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
}

// ─────────────────────────────────────────────────────────────
// 同步 / 备份 / Notion
// ─────────────────────────────────────────────────────────────

export async function notionInit(
  parentPageId: string,
  databaseTitle: string
): Promise<MaybeReserved<{ status: string; database_id?: string }>> {
  if (isMock()) return { reserved: true, available_in: "v0.8.0" };
  return apiFetch("/api/notion/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent_page_id: parentPageId, database_title: databaseTitle }),
  });
}

export async function syncNotionPull(): Promise<
  MaybeReserved<{ status: string; updated_count?: number; warnings?: string[] }>
> {
  if (isMock()) return { reserved: true, available_in: "v0.8.0" };
  return apiFetch("/api/sync/notion/pull", { method: "POST" });
}

export async function getSyncStatus(): Promise<MaybeReserved<SyncRecord[]>> {
  if (isMock()) return { reserved: true, available_in: "v0.4.0" };
  return apiFetch<MaybeReserved<SyncRecord[]>>("/api/sync/status");
}

export async function syncDocuments(
  target: "r2" | "notion" | "all",
  docIds?: string[]
): Promise<MaybeReserved<{ status: string; synced_count?: number; failed_count?: number }>> {
  if (isMock()) return { reserved: true, available_in: "v0.4.0" };
  return apiFetch(`/api/sync/${target}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(docIds ? { doc_ids: docIds } : {}),
  });
}

// ─────────────────────────────────────────────────────────────
// Zotero 单向 Pull 同步
// ─────────────────────────────────────────────────────────────

export async function getZoteroConfig(): Promise<ZoteroConfig> {
  if (isMock()) {
    const z = (MOCK_CONFIG.zotero_sync ?? {}) as Record<string, unknown>;
    return {
      enabled: Boolean(z.enabled),
      access_mode: z.access_mode === "server" ? "server" : "local",
      zotero_data_dir: String(z.zotero_data_dir ?? ""),
      resolved_data_dir: String(z.resolved_data_dir ?? ""),
      api_port: Number(z.api_port ?? 23119),
      storage_mode: z.storage_mode === "linked" ? "linked" : "managed_copy",
      linked_root: String(z.linked_root ?? ""),
      sync_mode: z.sync_mode === "strict_mirror" || z.sync_mode === "archive" ? z.sync_mode : "conservative",
      auto_sync_enabled: Boolean(z.auto_sync_enabled),
      auto_sync_interval_sec: Number(z.auto_sync_interval_sec ?? 3600),
      server_key_present: Boolean(z.server_key_present),
      server_key_masked: String(z.server_key_masked ?? ""),
      server_user_id: "",
      server_username: "",
      server_access: {},
      connection: { connected: false, port: 23119, detail: "mock" },
      availability: { available: false, reason: "mock" },
    };
  }
  return apiFetch<ZoteroConfig>("/api/zotero/config");
}

export async function saveZoteroServerKey(apiKey: string): Promise<ZoteroConfig> {
  if (isMock()) {
    const z = (MOCK_CONFIG.zotero_sync ?? {}) as Record<string, unknown>;
    z.server_key_present = true;
    z.server_key_masked = apiKey ? "mo****ck" : "";
    return getZoteroConfig();
  }
  return apiFetch<ZoteroConfig>("/api/zotero/server-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function deleteZoteroServerKey(): Promise<ZoteroConfig> {
  if (isMock()) {
    const z = (MOCK_CONFIG.zotero_sync ?? {}) as Record<string, unknown>;
    z.server_key_present = false;
    z.server_key_masked = "";
    return getZoteroConfig();
  }
  return apiFetch<ZoteroConfig>("/api/zotero/server-key", { method: "DELETE" });
}

export async function syncZoteroPull(incremental = true): Promise<ZoteroSyncResult> {
  if (isMock()) return { status: "success", new: [], changed: [], skipped_unchanged: 0 };
  return apiFetch<ZoteroSyncResult>("/api/sync/zotero/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ incremental }),
  });
}

export async function getZoteroSyncStatus(): Promise<ZoteroSyncResult> {
  if (isMock()) return {};
  return apiFetch<ZoteroSyncResult>("/api/sync/zotero/status");
}

// 本地离线探针：连接测试 + zotero.sqlite 干读计数（不写库、不同步）。
export async function probeZoteroLocal(): Promise<ZoteroProbeResult> {
  if (isMock()) {
    return {
      connection: { connected: false, port: 23119, detail: "mock" },
      read: { available: false, reason: "mock" },
    };
  }
  return apiFetch<ZoteroProbeResult>("/api/zotero/probe");
}

export async function backupNow(): Promise<MaybeReserved<unknown>> {
  if (isMock()) return { reserved: true, available_in: "v0.3.0" };
  return apiFetch("/api/backup", { method: "POST" });
}

export async function restoreBackup(): Promise<MaybeReserved<unknown>> {
  if (isMock()) return { reserved: true, available_in: "v0.3.0" };
  return apiFetch("/api/restore", { method: "POST" });
}

// ─────────────────────────────────────────────────────────────
// Ask Agent
// ─────────────────────────────────────────────────────────────

export async function ask(opts: {
  question: string;
  collection?: string | null;
  doc_id?: string | null;
  top_k?: number;
  conversation_id?: string | null;
  persona_enabled?: boolean;
  retrieval_mode?: "default" | "high_precision" | "graph_only" | "fulltext";
  use_english_retrieval?: boolean;
  answer_language?: "auto" | "zh" | "en";
}): Promise<AskResult> {
  if (isMock()) {
    await new Promise((r) => setTimeout(r, 800));
    const requested = opts.retrieval_mode ?? "default";
    return {
      ...MOCK_ASK,
      conversation_id: `conv-${Date.now()}`,
      requested_retrieval_mode: requested,
      actual_retrieval_mode: requested === "high_precision" ? "milvus_lightrag" : requested === "graph_only" ? "lightrag_only" : requested === "fulltext" ? "sqlite_lexical" : "milvus",
      retrieval_engines: requested === "high_precision" ? ["milvus", "sqlite_lexical", "lightrag"] : requested === "graph_only" ? ["lightrag"] : requested === "fulltext" ? ["sqlite_lexical"] : ["milvus", "sqlite_lexical"],
    };
  }
  return apiFetch<AskResult>("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: opts.question,
      collection: opts.collection ?? null,
      doc_id: opts.doc_id ?? null,
      top_k: opts.top_k ?? 5,
      conversation_id: opts.conversation_id ?? null,
      persona_enabled: opts.persona_enabled ?? false,
      retrieval_mode: opts.retrieval_mode ?? "default",
      use_english_retrieval: opts.use_english_retrieval ?? false,
      answer_language: opts.answer_language ?? "auto",
    }),
  });
}

// ─────────────────────────────────────────────────────────────
// 图谱统计 & 性能指标
// ─────────────────────────────────────────────────────────────

export interface GraphStats {
  entities_count: number;
  relations_count: number;
  collections_covered: number;
}

export async function getGraphStats(): Promise<GraphStats> {
  if (isMock()) {
    return { entities_count: 12, relations_count: 18, collections_covered: 2 };
  }
  return apiFetch<GraphStats>("/api/graph/stats");
}

// ─────────────────────────────────────────────────────────────
// 系统信息 & 文件列表 & 本地模型管理
// ─────────────────────────────────────────────────────────────

export interface SystemInfo {
  cwd: string; data_dir: string; db_file: string; docs_dir: string;
  python_version: string; platform: string;
}
export interface FileEntry { name: string; type: "file" | "dir"; size_bytes: number | null; modified_at: string | null; }
export interface FileList  { path: string; entries: FileEntry[]; }
export interface LocalModel { name: string; dir_name: string; size_bytes: number; last_modified: string | null; }

export async function getSystemInfo(): Promise<SystemInfo> {
  if (isMock()) return { cwd: "/mock/cwd", data_dir: "/mock/data", db_file: "knowledge_repository.db", docs_dir: "/mock/data/documents", python_version: "3.12.0", platform: "linux" };
  return apiFetch<SystemInfo>("/api/system/info");
}

export async function listDataFiles(subdir?: string): Promise<FileList> {
  const qs = subdir ? `?dir=${encodeURIComponent(subdir)}` : "";
  if (isMock()) return { path: subdir ?? "", entries: [] };
  return apiFetch<FileList>(`/api/files/list${qs}`);
}

export interface FsBrowseResult {
  path: string;
  parent: string | null;
  dirs: string[];
}

export async function browseDir(path?: string): Promise<FsBrowseResult> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  if (isMock()) return { path: path ?? "~", parent: null, dirs: ["Documents", "Desktop", "Downloads"] };
  return apiFetch<FsBrowseResult>(`/api/fs/browse${qs}`);
}

export async function listLocalModels(): Promise<LocalModel[]> {
  if (isMock()) return [
    { name: "BAAI/bge-m3", dir_name: "models--BAAI--bge-m3", size_bytes: 2_100_000_000, last_modified: null },
  ];
  return apiFetch<LocalModel[]>("/api/models/local");
}

export async function deleteLocalModel(name: string): Promise<void> {
  if (isMock()) return;
  await apiFetch<{ deleted: string }>(`/api/models/local/${encodeURIComponent(name.replace("/", "--"))}`, { method: "DELETE" });
}

// ─────────────────────────────────────────────────────────────
// 日志流
// ─────────────────────────────────────────────────────────────

export interface LogLine {
  ts: number; level: string; name: string; msg: string;
  source?: string; category?: string; operation?: string; status?: string;
  elapsed_ms?: number | null; metadata?: Record<string, unknown>;
}
export interface LogsResponse { lines: LogLine[]; server_ts: number; }

export async function postLogEvent(event: {
  type: "info" | "error" | "ok";
  message: string;
  route?: string;
}): Promise<void> {
  if (isMock()) return;
  await apiFetch<{ status: string }>("/api/logs/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  });
}

export async function getLogs(after = 0, limit = 200): Promise<LogsResponse> {
  if (isMock()) return { lines: [], server_ts: Date.now() / 1000 };
  return apiFetch<LogsResponse>(`/api/logs?after=${after}&limit=${limit}`);
}

// ─────────────────────────────────────────────────────────────
// 系统能力 / 数据流 / 可选依赖（向导页 + 依赖管理面板）
// 后端唯一真相源：core/capabilities.py。前端只渲染，不再反推状态。
// ─────────────────────────────────────────────────────────────

/** 数据流单个环节的结构化快照。status: ready|degraded|off|info。consequence: none|restart|rebuild。 */
export interface PipelineStage {
  id: string;
  current: string;
  candidates: string[];
  status: "ready" | "degraded" | "off" | "info";
  switchable: boolean;
  consequence: "none" | "restart" | "rebuild";
  required_deps: string[];
  configured: boolean;
  detail: Record<string, unknown>;
}

/** 单个可选依赖的安装状态。 */
export interface DependencyStatus {
  key: string;
  import_name: string;
  dist_name: string;
  pip_spec: string;
  feature: string;
  stages: string[];
  required?: boolean;
  installed: boolean;
  version: string | null;
}

export interface CapabilitiesData {
  pipeline: PipelineStage[];
  dependencies: DependencyStatus[];
  diagnostics: string[];
}

export interface InstallResult {
  status: "ok" | "error";
  package?: string;
  returncode?: number;
  restart_required?: boolean;
  message?: string;
}

const MOCK_DEPENDENCIES: DependencyStatus[] = [
  { key: "local_embedding", import_name: "sentence_transformers", dist_name: "sentence-transformers", pip_spec: "sentence-transformers>=3,<6", feature: "local_embedding", stages: ["embedding"], required: false, installed: true, version: "3.0.1" },
  { key: "milvus", import_name: "pymilvus", dist_name: "pymilvus", pip_spec: "pymilvus[milvus_lite]>=2.5,<3.0", feature: "milvus", stages: ["vector_store", "retrieval"], required: true, installed: true, version: "2.5.0" },
  { key: "lightrag", import_name: "lightrag", dist_name: "lightrag-hku", pip_spec: "lightrag-hku>=1.5.0rc1,<2.0.0", feature: "lightrag", stages: ["graph"], required: false, installed: false, version: null },
  { key: "r2", import_name: "boto3", dist_name: "boto3", pip_spec: "boto3", feature: "r2", stages: ["sync"], required: false, installed: false, version: null },
];

const MOCK_CAPABILITIES: CapabilitiesData = {
  pipeline: [
    { id: "zotero", current: "off", candidates: ["on", "off"], status: "off", switchable: true, consequence: "restart", required_deps: [], configured: false, detail: { access_mode: "local", api_port: 23119, sync_mode: "conservative", storage_mode: "managed_copy" } },
    { id: "ingest", current: "pymupdf4llm", candidates: ["pymupdf4llm"], status: "ready", switchable: false, consequence: "none", required_deps: [], configured: true, detail: { ocr_enabled: false, pdf_converter: "pymupdf4llm", pdf_converter_ready: true, dependency_source: "requirements.txt" } },
    { id: "embedding", current: "local", candidates: ["local", "external"], status: "ready", switchable: true, consequence: "rebuild", required_deps: ["local_embedding"], configured: true, detail: { model: "intfloat/multilingual-e5-small", actual_dimension: 384 } },
    { id: "vector_store", current: "milvus", candidates: ["milvus", "astr"], status: "ready", switchable: true, consequence: "restart", required_deps: ["milvus"], configured: true, detail: { auto_index_enabled: true, astrbot_locked: true, compatible: true, rebuild_required: false, pending_reindex_count: 0, document_count: 0, chunk_count: 0, reason: "" } },
    { id: "retrieval", current: "rrf_fusion", candidates: ["rrf_fusion"], status: "ready", switchable: false, consequence: "none", required_deps: [], configured: true, detail: { engines: ["milvus", "sqlite_lexical"] } },
    { id: "graph", current: "off", candidates: ["on", "off"], status: "off", switchable: true, consequence: "rebuild", required_deps: ["lightrag"], configured: false, detail: { query_mode: "mix", llm_provider: "main", llm_model: "", llm_label: "<main - AstrBot main LLM>" } },
    { id: "ask", current: "inject", candidates: ["inject", "query_agent"], status: "ready", switchable: true, consequence: "none", required_deps: [], configured: true, detail: {} },
    { id: "sync", current: "off", candidates: ["on", "off"], status: "off", switchable: true, consequence: "restart", required_deps: [], configured: false, detail: { r2_enabled: false, notion_enabled: false } },
  ],
  dependencies: MOCK_DEPENDENCIES,
  diagnostics: [],
};

export async function getCapabilities(): Promise<CapabilitiesData> {
  if (isMock()) return JSON.parse(JSON.stringify(MOCK_CAPABILITIES));
  return apiFetch<CapabilitiesData>("/api/capabilities");
}

export async function listDependencies(): Promise<DependencyStatus[]> {
  if (isMock()) return JSON.parse(JSON.stringify(MOCK_DEPENDENCIES));
  const res = await apiFetch<{ dependencies: DependencyStatus[] }>("/api/dependencies");
  return res.dependencies;
}

export async function installDependency(pkg: string): Promise<InstallResult> {
  if (isMock()) return { status: "ok", package: pkg, restart_required: true, message: "mock installed" };
  return apiFetch<InstallResult>("/api/dependencies/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package: pkg }),
  });
}

export async function recheckDependencies(): Promise<CapabilitiesData> {
  if (isMock()) return JSON.parse(JSON.stringify(MOCK_CAPABILITIES));
  return apiFetch<CapabilitiesData>("/api/dependencies/recheck", { method: "POST" });
}

// ─────────────────────────────────────────────────────────────
// v0.23.0 新 UI 后端能力桩（部分端口尚未实现，501 降级）
// ─────────────────────────────────────────────────────────────

export interface DocumentNote {
  id: string;
  scope_type?: "document" | "collection";
  scope_key?: string;
  doc_id?: string;
  collection_name?: string;
  content: string;
  body?: string;
  note_html?: string;
  linked?: boolean;
  source?: string;
  library_id?: string;
  parent_item_key?: string;
  parent_attachment_key?: string;
  zotero_note_key?: string;
  zotero_version?: number;
  tags?: string[];
  collections?: string[];
  raw_zotero_json?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConsoleScopeState {
  scope_type: string;
  scope_key: string;
  selected_collection: string;
  selected_doc_id: string;
  note_doc_id: string;
  right_panel?: string;
  reading_mode?: string;
  payload?: Record<string, unknown>;
  updated_at?: string | null;
}

export interface ZoteroAnnotation {
  id: string;
  doc_id: string;
  text: string;
  comment?: string;
  color?: string;
  page?: number;
  page_label?: string;
  type?: string;
  position?: { pageIndex?: number; rects?: number[][] };
  created_at?: string;
  updated_at?: string;
}

export interface DocumentChunk {
  chunk_id: string;
  doc_id?: string;
  ordinal: number;
  page?: number;
  text: string;
  metadata?: Record<string, unknown>;
}

export async function getDocumentContent(
  docId: string,
  format: "md" | "pdf" = "md",
): Promise<string> {
  if (isMock()) return "";
  const res = await fetch(
    `/api/documents/${encodeURIComponent(docId)}/content?format=${format}`,
    { credentials: "include" },
  );
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText);
  }
  return res.text();
}

export async function getDocumentNotes(docId: string): Promise<DocumentNote[]> {
  return apiFetch<DocumentNote[]>(`/api/documents/${encodeURIComponent(docId)}/notes`);
}

export async function createDocumentNote(
  docId: string,
  content: string,
  options?: { linked?: boolean; source?: string; chat_conversation_id?: string; chat_message_id?: number },
): Promise<DocumentNote> {
  return apiFetch<DocumentNote>(`/api/documents/${encodeURIComponent(docId)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, ...(options ?? {}) }),
  });
}

export async function updateDocumentNote(
  docId: string,
  noteId: string,
  content: string,
): Promise<DocumentNote> {
  return apiFetch<DocumentNote>(
    `/api/documents/${encodeURIComponent(docId)}/notes/${encodeURIComponent(noteId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
}

export async function getCollectionNotes(collectionName: string): Promise<DocumentNote[]> {
  return apiFetch<DocumentNote[]>(`/api/collections/${encodeURIComponent(collectionName)}/notes`);
}

export async function createCollectionNote(
  collectionName: string,
  content: string,
  options?: { linked?: boolean; source?: string; chat_conversation_id?: string; chat_message_id?: number },
): Promise<DocumentNote> {
  return apiFetch<DocumentNote>(`/api/collections/${encodeURIComponent(collectionName)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, ...(options ?? {}) }),
  });
}

export async function updateCollectionNote(
  collectionName: string,
  noteId: string,
  content: string,
): Promise<DocumentNote> {
  return apiFetch<DocumentNote>(
    `/api/collections/${encodeURIComponent(collectionName)}/notes/${encodeURIComponent(noteId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
}

export async function getDocumentAnnotations(docId: string): Promise<ZoteroAnnotation[]> {
  if (isMock()) return [];
  return apiFetch<ZoteroAnnotation[]>(
    `/api/documents/${encodeURIComponent(docId)}/annotations`,
  );
}

export async function lockChatAnswer(
  convId: string,
  msgIdx: number,
  locked = true,
): Promise<ChatMessage> {
  return apiFetch<ChatMessage>(`/api/chat/history/${encodeURIComponent(convId)}/messages/${msgIdx}/lock`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ locked }),
  });
}

export async function getConsoleScopeState(
  scopeType: string,
  scopeKey: string,
): Promise<ConsoleScopeState | null> {
  if (isMock()) return null;
  const qs = new URLSearchParams({ scope_type: scopeType, scope_key: scopeKey });
  try {
    return await apiFetch<ConsoleScopeState>(`/api/console/scope-state?${qs}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function upsertConsoleScopeState(
  state: Omit<ConsoleScopeState, "updated_at">,
): Promise<ConsoleScopeState> {
  return apiFetch<ConsoleScopeState>("/api/console/scope-state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
}

export async function listDocumentChunks(docId: string): Promise<DocumentChunk[]> {
  if (isMock()) {
    return MOCK_KB_CHUNKS
      .filter((chunk) => chunk.doc_id === docId)
      .map((chunk) => ({
        chunk_id: chunk.chunk_id,
        doc_id: chunk.doc_id,
        ordinal: chunk.ordinal,
        text: chunk.text,
      }));
  }
  return apiFetch<DocumentChunk[]>(
    `/api/documents/${encodeURIComponent(docId)}/chunks`,
  );
}
