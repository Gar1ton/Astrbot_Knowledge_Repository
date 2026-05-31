/**
 * lib/api.ts — 唯一网络出口
 * 所有组件禁止裸 fetch，必须经此模块。
 * ?mock 参数启用内置离线模拟数据。
 */

// ─── 类型定义 ──────────────────────────────────────────────────

export interface Collection {
  name: string;
  description?: string;
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
}

export interface KbChunk {
  chunk_id: string;
  ordinal: number;
  text: string;
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
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphQueryResult {
  status: string;
  query: string;
  collection?: string;
  chunks: KbChunk[];
  entities: GraphNode[];
  relations: GraphEdge[];
  context?: string;
  debug?: {
    vector_chunk_ids: string[];
    keyword_chunk_ids: string[];
    graph_chunk_ids: string[];
    rrf_scores: Record<string, number>;
  };
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
}

export interface ReservedResult {
  reserved: true;
  available_in: string;
}

export type MaybeReserved<T> = T | ReservedResult;

// ─── mock 检测 ─────────────────────────────────────────────────

function isMock(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("mock");
}

// ─── 错误类 ────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
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
    try {
      const body = await res.json();
      msg = body.error || body.detail || msg;
    } catch {
      /* ignore parse error */
    }
    throw new ApiError(res.status, msg);
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
  { chunk_id: "k1", ordinal: 0, text: "Transformer 架构通过自注意力机制（Self-Attention）实现对序列中任意位置的直接依赖建模，彻底摆脱了 RNN 的顺序计算限制。" },
  { chunk_id: "k2", ordinal: 1, text: "LightRAG 将知识图谱与向量检索融合，采用双层检索策略：局部级（实体邻域）与全局级（跨文档主题）协同工作以提升召回质量。" },
  { chunk_id: "k3", ordinal: 2, text: "RRF（Reciprocal Rank Fusion）是一种无参数排名融合算法，通过 1/(k+rank_i) 公式合并多路召回结果，天然规避了分数量纲不统一的问题。" },
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
  graph: { enabled: true, llm_extraction: true, rrf_k: 60, query_top_k: 5 },
  ask: { top_k: 5, cite_sources: true },
};

const MOCK_ASK: AskResult = {
  conversation_id: "conv-demo-1",
  answer: "Transformer 架构的核心是**自注意力机制**（Self-Attention），它允许模型在处理序列时直接建模任意位置之间的依赖关系 [1]。与 RNN 不同，Transformer 可以并行计算，显著提升训练效率。\n\nLightRAG 则将图结构检索与向量检索融合，通过 RRF 算法 [3] 对多路召回结果进行排名融合，提供更准确的上下文 [2]。",
  sources: [
    { n: 1, doc_id: "seed-1", title: "Attention Is All You Need", chunk_id: "k1", ordinal: 0, text: "Transformer 架构通过自注意力机制（Self-Attention）实现对序列中任意位置的直接依赖建模。", rrf_score: 0.0327 },
    { n: 2, doc_id: "seed-2", title: "LightRAG 论文", chunk_id: "k2", ordinal: 1, text: "LightRAG 将知识图谱与向量检索融合，采用双层检索策略。", rrf_score: 0.0289 },
    { n: 3, doc_id: "seed-1", title: "Attention Is All You Need", chunk_id: "k3", ordinal: 2, text: "RRF 是一种无参数排名融合算法，通过 1/(k+rank_i) 公式合并多路召回结果。", rrf_score: 0.0214 },
  ],
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
  // 后端暂无 /api/logout，前端清除 cookie 降级（见 TODO）
  if (typeof document !== "undefined") {
    document.cookie = "kr_session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
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
  const params = new URLSearchParams({ collection, q, k: String(k) });
  return apiFetch<KbChunk[]>(`/api/kb/search?${params}`);
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

// ─────────────────────────────────────────────────────────────
// 知识图谱 Graph
// ─────────────────────────────────────────────────────────────

export async function getGraph(
  collection?: string
): Promise<MaybeReserved<GraphData>> {
  if (isMock()) return { ...MOCK_GRAPH };
  const qs = collection ? `?collection=${encodeURIComponent(collection)}` : "";
  return apiFetch<MaybeReserved<GraphData>>(`/api/graph${qs}`);
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

export async function buildGraph(
  collection?: string
): Promise<MaybeReserved<{ status: string; message?: string }>> {
  if (isMock()) {
    return { reserved: true, available_in: "v0.6.0" };
  }
  return apiFetch<MaybeReserved<{ status: string }>>("/api/graph/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collection ? { collection } : {}),
  });
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

export async function getSyncStatus(): Promise<MaybeReserved<unknown>> {
  if (isMock()) return { reserved: true, available_in: "v0.4.0" };
  return apiFetch("/api/sync/status");
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
  top_k?: number;
  conversation_id?: string | null;
}): Promise<AskResult> {
  if (isMock()) {
    await new Promise((r) => setTimeout(r, 800));
    return { ...MOCK_ASK, conversation_id: `conv-${Date.now()}` };
  }
  return apiFetch<AskResult>("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: opts.question,
      collection: opts.collection ?? null,
      top_k: opts.top_k ?? 5,
      conversation_id: opts.conversation_id ?? null,
    }),
  });
}
