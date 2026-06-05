"use client";

import React, { useEffect, useRef, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  AskResult, AskSource, ApiError, EffectiveConfig, GraphBuildEstimate, GraphBuildJob,
  ChatMessage, KbChunkContext,
  ask, buildGraph, estimateGraphBuild, getEffectiveConfig, getGraphBuildJob, listCollections,
  listKbCollections, getChatHistory, clearChatHistory, getChunkContext,
} from "@/lib/api";

type RetrievalMode = "default" | "high_precision" | "graph_only";

function retrievalModeLabel(mode?: string): string {
  if (mode === "lightrag_only") return "图谱检索 · LightRAG";
  if (mode === "milvus_lightrag") return "联合检索 · Milvus + 图谱";
  if (mode === "astrbot_lightrag") return "联合检索 · AstrBot + 图谱";
  if (mode === "lexical_lightrag") return "联合检索 · 词汇 + 图谱";
  if (mode === "lightrag") return "联合检索 · LightRAG";
  if (mode === "astrbot_fallback") return "已回退 · AstrBot";
  if (mode === "astrbot") return "语义检索 · AstrBot";
  if (mode === "sqlite_lexical") return "语义检索 · 词汇召回";
  if (mode === "none") return "未完成召回";
  return "语义检索 · Milvus";
}

// ─── Markdown 渲染（轻量：仅处理 **bold**、[n] 角标、换行） ──

function renderAnswer(text: string, sources: AskSource[], activeN: number | null, setActiveN: (n: number | null) => void): React.ReactNode {
  const lines = text.split("\n");
  return lines.map((line, li) => {
    const parts = line.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
    const rendered = parts.map((part, pi) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) {
        return <strong key={pi}>{part.slice(2, -2)}</strong>;
      }
      const m = part.match(/^\[(\d+)\]$/);
      if (m) {
        const n = parseInt(m[1]);
        return (
          <sup
            key={pi}
            onClick={() => setActiveN(activeN === n ? null : n)}
            style={{
              cursor: "pointer",
              color: "var(--accent)",
              background: activeN === n ? "var(--accent-soft)" : "transparent",
              borderRadius: 3,
              padding: "0 2px",
              fontWeight: 700,
              fontSize: "0.75em",
              transition: "background .15s",
            }}
          >
            [{n}]
          </sup>
        );
      }
      return part;
    });
    return (
      <React.Fragment key={li}>
        {rendered}
        {li < lines.length - 1 && <br />}
      </React.Fragment>
    );
  });
}

// ─── 来源卡片（可展开显示上下文） ────────────────────────────

function SourceCard({ src, isActive }: { src: AskSource; isActive: boolean }) {
  const [expanded, setExpanded] = React.useState(false);
  const [loadingCtx, setLoadingCtx] = React.useState(false);
  const [ctxBefore, setCtxBefore] = React.useState<KbChunkContext[]>([]);
  const [ctxAfter, setCtxAfter] = React.useState<KbChunkContext[]>([]);

  async function handleExpand() {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (ctxBefore.length === 0 && ctxAfter.length === 0) {
      setLoadingCtx(true);
      try {
        const ctx = await getChunkContext(src.doc_id, src.chunk_id, 2);
        setCtxBefore(ctx.context_before);
        setCtxAfter(ctx.context_after);
      } catch { /* ignore */ } finally {
        setLoadingCtx(false);
      }
    }
  }

  return (
    <div
      style={{
        background: isActive ? "var(--accent-soft)" : "var(--bg-inset)",
        border: `1px solid ${isActive ? "var(--accent-border)" : "var(--border)"}`,
        borderRadius: 10, marginBottom: 8, overflow: "hidden",
        transition: "all .15s",
      }}
    >
      {/* 卡片头 */}
      <div
        onClick={handleExpand}
        style={{ padding: "10px 12px", cursor: "pointer", userSelect: "none" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: expanded ? 0 : 5 }}>
          <span style={{ background: "var(--accent)", color: "#fff", borderRadius: 999, fontSize: 10, fontWeight: 700, width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            {src.n}
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--heading)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
            {src.title}
          </span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--fg-muted)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, transform: expanded ? "rotate(180deg)" : "none", transition: "transform .15s" }}>
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
        {!expanded && (
          <p style={{ margin: 0, fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
            {src.text}
          </p>
        )}
        {src.rrf_score !== undefined && !expanded && (
          <div style={{ fontSize: 10, color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)", marginTop: 5 }}>
            RRF: {src.rrf_score.toFixed(4)}
          </div>
        )}
      </div>

      {/* 展开上下文 */}
      {expanded && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "10px 12px", fontSize: 11, lineHeight: 1.65 }}>
          {loadingCtx ? (
            <div style={{ color: "var(--fg-muted)", display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block", animation: "spin 0.6s linear infinite" }} />
              加载上下文…
            </div>
          ) : (
            <>
              {ctxBefore.map((c) => (
                <p key={c.chunk_id} style={{ margin: "0 0 8px", color: "var(--fg-muted)", paddingBottom: 8, borderBottom: "1px solid var(--border)" }}>{c.text}</p>
              ))}
              <p style={{ margin: "8px 0", color: "var(--fg)", fontWeight: 600 }}>{src.text}</p>
              {ctxAfter.map((c) => (
                <p key={c.chunk_id} style={{ margin: "8px 0 0", color: "var(--fg-muted)", paddingTop: 8, borderTop: "1px solid var(--border)" }}>{c.text}</p>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 来源面板 ─────────────────────────────────────────────────

function SourcesPanel({ sources, activeN, onClose }: { sources: AskSource[]; activeN: number | null; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div
      style={{
        width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}
      className="fx-glass-edge"
    >
      {/* 折叠 bar（替代 X 按钮） */}
      <div
        className="fx-glass"
        style={{
          position: "sticky", top: 0, zIndex: 2,
          height: "var(--topbar-h)", boxSizing: "border-box",
          padding: "0 16px",
          display: "flex", alignItems: "center", gap: 8,
          cursor: "pointer",
        }}
        onClick={onClose}
        title="收起来源面板"
      >
        <div style={{ flex: 1, fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", lineHeight: 1 }}>
          {t("ask_sources")}
        </div>
        {/* 中间折叠指示器 */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--fg-subtle)", opacity: 0.6 }}>
          <div style={{ width: 20, height: 1, background: "var(--border-strong)", borderRadius: 1 }} />
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          <div style={{ width: 20, height: 1, background: "var(--border-strong)", borderRadius: 1 }} />
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 10px" }}>
        {sources.length === 0 ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 12, padding: 8 }}>暂无引用来源</div>
        ) : (
          sources.map((src) => (
            <SourceCard key={src.n} src={src} isActive={activeN === src.n} />
          ))
        )}
      </div>
    </div>
  );
}

// ─── 消息气泡 ─────────────────────────────────────────────────

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: AskSource[];
  actualRetrievalMode?: string;
}

function MessageBubble({
  msg, activeN, setActiveN, isSelected, isGlowing, onSelect, onGlowEnd,
}: {
  msg: Message;
  activeN: number | null;
  setActiveN: (n: number | null) => void;
  isSelected: boolean;
  isGlowing: boolean;
  onSelect: () => void;
  onGlowEnd: () => void;
}) {
  const isUser = msg.role === "user";
  const canSelect = !isUser && (msg.sources?.length ?? 0) > 0;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 14,
      }}
    >
      <div
        className={isGlowing ? "msg-bubble--glow" : undefined}
        onClick={canSelect ? onSelect : undefined}
        onAnimationEnd={isGlowing ? onGlowEnd : undefined}
        style={{
          maxWidth: "80%",
          background: isUser ? "var(--accent)" : "var(--surface)",
          color: isUser ? "var(--accent-fg)" : "var(--fg)",
          border: isUser ? "none" : `1px solid ${isSelected ? "var(--accent-border)" : "var(--border)"}`,
          borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
          padding: "10px 14px",
          fontSize: 13,
          lineHeight: 1.65,
          boxShadow: isSelected ? "0 0 0 2px var(--ring), var(--shadow)" : "var(--shadow)",
          cursor: canSelect ? "pointer" : "default",
          position: "relative",
          transition: "border-color .15s, box-shadow .15s",
        }}
      >
        {isUser ? msg.content : (
          <>
            <div style={{ marginBottom: 7 }}>
              <Tag
                label={retrievalModeLabel(msg.actualRetrievalMode)}
                accent={Boolean(msg.actualRetrievalMode?.includes("lightrag"))}
              />
            </div>
            {renderAnswer(msg.content, msg.sources ?? [], activeN, setActiveN)}
          </>
        )}
      </div>
    </div>
  );
}

interface PrecisionDialogState {
  question: string;
  collection: string;
  reason: string;
  estimate?: GraphBuildEstimate;
  canBuild: boolean;
  building?: boolean;
  job?: GraphBuildJob;
}

function PrecisionDialog({
  state,
  onBuild,
  onFallback,
  onCancel,
}: {
  state: PrecisionDialogState;
  onBuild: () => void;
  onFallback: () => void;
  onCancel: () => void;
}) {
  const rows: [string, string][] = state.estimate ? [
    ["集合", state.estimate.collection],
    ["文档数", String(state.estimate.docs_count)],
    ["分块数", String(state.estimate.chunks_count)],
    ["估算 LLM 调用", `${state.estimate.estimated_llm_calls_min} – ${state.estimate.estimated_llm_calls_max}`],
    ["估算耗时（秒）", `${state.estimate.estimated_duration_seconds_min} – ${state.estimate.estimated_duration_seconds_max}`],
  ] : [["集合", state.collection]];

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 600,
      }}
      onClick={(e) => e.target === e.currentTarget && !state.building && onCancel()}
    >
      <div style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 14, padding: 24, width: 410, boxShadow: "var(--shadow-pop)",
        display: "flex", flexDirection: "column", gap: 16,
      }}>
        <div>
          <h3 style={{ margin: "0 0 5px", fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
            高精度召回尚未就绪
          </h3>
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.6, color: "var(--fg-muted)" }}>
            {state.reason}
          </p>
        </div>

        <div style={{ background: "var(--bg-inset)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
          {rows.map(([label, value], i) => (
            <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 14px", borderTop: i > 0 ? "1px solid var(--border)" : undefined }}>
              <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>{label}</span>
              <span style={{ fontSize: 12, fontFamily: "var(--font-geist-mono)", color: "var(--fg)", fontWeight: 600 }}>{value}</span>
            </div>
          ))}
        </div>

        {state.estimate && (
          <div style={{ fontSize: 11, lineHeight: 1.6, color: "var(--warn)", background: "color-mix(in srgb, var(--warn, #d97706) 10%, transparent)", border: "1px solid color-mix(in srgb, var(--warn, #d97706) 30%, transparent)", borderRadius: 8, padding: "8px 12px" }}>
            {state.estimate.estimate_notice}
          </div>
        )}

        {state.job && (
          <div style={{ fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.6 }}>
            LightRAG 索引：{state.job.status} · {state.job.processed_docs ?? 0}/{state.job.total_docs ?? 0} 文档
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <Btn variant="ghost" size="sm" disabled={state.building} onClick={onCancel}>取消</Btn>
          <Btn variant="outline" size="sm" disabled={state.building} onClick={onFallback}>本次使用 Milvus</Btn>
          {state.canBuild && state.estimate && (
            <Btn size="sm" loading={state.building} onClick={onBuild}>构建并自动继续</Btn>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Toggle 开关行 ────────────────────────────────────────────

function SettingRow({ label, checked, onToggle, borderTop }: {
  label: string; checked: boolean; onToggle: () => void; borderTop?: boolean;
}) {
  return (
    <div
      onClick={onToggle}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "7px 8px", borderRadius: 8, cursor: "pointer",
        fontSize: 12, color: "var(--fg)", userSelect: "none",
        borderTop: borderTop ? "1px solid var(--border)" : undefined,
        transition: "background .1s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-inset)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <span style={{ fontWeight: checked ? 600 : 400, color: checked ? "var(--fg)" : "var(--fg-muted)" }}>
        {label}
      </span>
      {/* 小 toggle 开关 */}
      <div
        style={{
          width: 28, height: 16, borderRadius: 8, flexShrink: 0,
          background: checked ? "var(--accent)" : "var(--border-strong)",
          position: "relative",
          transition: "background 0.2s",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 2,
            left: checked ? 12 : 2,
            width: 12, height: 12,
            borderRadius: "50%",
            background: "white",
            boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
            transition: "left 0.18s cubic-bezier(0.4,0,0.2,1)",
          }}
        />
      </div>
    </div>
  );
}

// ─── Ask Agent 主页 ───────────────────────────────────────────

export default function AskPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyLoadedRef = useRef<string | null>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const collectionRef = useRef<HTMLDivElement>(null);

  const _CONV_KEY = "kr_conversation_id";
  const _COLL_KEY = "kr_ask_collection";

  function _getOrCreateConvId(): string {
    if (typeof window === "undefined") return crypto.randomUUID();
    const stored = localStorage.getItem(_CONV_KEY);
    if (stored) return stored;
    const id = crypto.randomUUID();
    localStorage.setItem(_CONV_KEY, id);
    return id;
  }

  const [localCollections, setLocalCollections] = useState<string[]>([]);
  const [defaultCollections, setDefaultCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeN, setActiveN] = useState<number | null>(null);
  // 用户当前选中的消息下标；null 表示默认展示最新 assistant 消息的来源
  const [selectedMsgIndex, setSelectedMsgIndex] = useState<number | null>(null);
  // 当前辉光中的气泡下标（动画结束后自动清除）
  const [glowingMsgIndex, setGlowingMsgIndex] = useState<number | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [modeInfo, setModeInfo] = useState<string>("embedding + RRF");
  const [defaultRetrievalLabel, setDefaultRetrievalLabel] = useState("Milvus");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("default");
  const [personaEnabled, setPersonaEnabled] = useState(false);
  const [useEnglishRetrieval, setUseEnglishRetrieval] = useState(true);
  const [answerLanguage, setAnswerLanguage] = useState<"auto" | "zh" | "en">("auto");
  const [showCollectionPicker, setShowCollectionPicker] = useState(false);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [showSources, setShowSources] = useState(true);
  const [precisionDialog, setPrecisionDialog] = useState<PrecisionDialogState | null>(null);
  const graphModeCollectionReady = Boolean(
    collection && localCollections.includes(collection)
  );
  // keep alias for places that still reference the old name
  const highPrecisionCollectionReady = graphModeCollectionReady;

  useEffect(() => {
    Promise.all([
      listCollections().catch(() => []),
      listKbCollections().catch(() => []),
    ])
      .then(([localItems, kbItems]) => {
        const localNames = localItems.map((item) => item.name);
        setLocalCollections(localNames);
        setDefaultCollections([...new Set([...localNames, ...kbItems])]);
      });
    // 拉取一次配置，组合显示向量后端 + embedding + 增强模式
    getEffectiveConfig().then((cfg: EffectiveConfig) => {
      const vdb = cfg.vector_db as Record<string, string> | undefined;
      const embedding = cfg.embedding as Record<string, string> | undefined;
      const ask = cfg.ask as Record<string, string> | undefined;
      const backend = vdb?.backend ?? "milvus";
      const provider = embedding?.provider ?? "local";
      const mode = ask?.conversation_enhancement_mode ?? "inject";
      const backendLabel = backend === "milvus" ? "Milvus" : "AstrBot KB";
      const providerLabel = provider === "local" ? "本地 Embedding" : "API Embedding";
      const modeLabel = mode === "inject" ? "注入增强" : "代理增强";
      setModeInfo(`${backendLabel} · ${providerLabel} · ${modeLabel}`);
      setDefaultRetrievalLabel(backend === "milvus" ? "Milvus" : "AstrBot");
    }).catch(() => {});

    // 从 localStorage 恢复 conversationId（历史加载由独立 effect 处理）
    const cid = _getOrCreateConvId();
    setConversationId(cid);
    // 恢复上次选择的集合
    if (typeof window !== "undefined") {
      const savedCol = localStorage.getItem(_COLL_KEY);
      if (savedCol !== null) setCollection(savedCol || null);
    }
  }, []);

  // 集合选择持久化
  useEffect(() => {
    if (typeof window !== "undefined" && collection !== null) {
      localStorage.setItem(_COLL_KEY, collection);
    }
  }, [collection]);

  // conversationId 稳定后加载历史记录（每个会话只加载一次）
  useEffect(() => {
    if (!conversationId || historyLoadedRef.current === conversationId) return;
    historyLoadedRef.current = conversationId;
    getChatHistory(conversationId)
      .then((msgs: ChatMessage[]) => {
        if (msgs.length === 0) return;
        setMessages(msgs.map((m) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
          sources: m.sources,
          actualRetrievalMode: m.retrieval_mode || undefined,
        })));
        // selectedMsgIndex=null 表示展示最新 assistant 消息来源（默认行为）
        setSelectedMsgIndex(null);
      })
      .catch(console.error);
  }, [conversationId]);

  useEffect(() => {
    if (!showCollectionPicker && !showSettingsMenu) return;
    function onMouseDown(e: MouseEvent) {
      const t = e.target as Node;
      // 点击在下拉组件内部时不关闭
      if (settingsRef.current?.contains(t) || collectionRef.current?.contains(t)) return;
      setShowCollectionPicker(false);
      setShowSettingsMenu(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { setShowCollectionPicker(false); setShowSettingsMenu(false); }
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [showCollectionPicker, showSettingsMenu]);

  // 自动滚到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function submitQuestion(
    question: string,
    mode: RetrievalMode,
    appendUser: boolean,
  ) {
    if (loading) return;
    if ((mode === "high_precision" || mode === "graph_only") && !graphModeCollectionReady) {
      setShowCollectionPicker(true);
      toast("图谱检索需要指定集合，请从下方选择一个集合后再发送", "info");
      return;
    }
    if (appendUser) {
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: question }]);
    }
    setLoading(true);
    setActiveN(null);

    try {
      const result: AskResult = await ask({
        question,
        collection: collection || null,
        top_k: 5,
        conversation_id: conversationId,
        persona_enabled: personaEnabled,
        retrieval_mode: mode,
        use_english_retrieval: useEnglishRetrieval,
        answer_language: answerLanguage,
      });

      setConversationId(result.conversation_id);
      if (typeof window !== "undefined") {
        localStorage.setItem(_CONV_KEY, result.conversation_id);
      }
      if (result.sources.length > 0) setShowSources(true);
      // 新消息到达后重置选中，展示最新来源
      setSelectedMsgIndex(null);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.answer,
          sources: result.sources,
          actualRetrievalMode: result.actual_retrieval_mode,
        },
      ]);
    } catch (err) {
      if (
        (mode === "high_precision" || mode === "graph_only")
        && err instanceof ApiError
        && (err.body?.status === "lightrag_not_ready" || err.body?.status === "high_precision_failed")
        && collection
      ) {
        let estimate: GraphBuildEstimate | undefined;
        const canBuild = err.body.build_available === true;
        if (canBuild) {
          try {
            estimate = await estimateGraphBuild(collection);
          } catch {
            estimate = undefined;
          }
        }
        setPrecisionDialog({
          question,
          collection,
          reason: err.message,
          estimate,
          canBuild,
        });
      } else {
        toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;
    await submitQuestion(input.trim(), retrievalMode, true);
  }

  async function handlePrecisionFallback() {
    if (!precisionDialog) return;
    const pending = precisionDialog;
    setPrecisionDialog(null);
    await submitQuestion(pending.question, "default", false);
  }

  async function handlePrecisionBuild() {
    if (!precisionDialog?.estimate) return;
    const pending = precisionDialog;
    setPrecisionDialog({ ...pending, building: true });
    try {
      let job = await buildGraph(pending.collection);
      setPrecisionDialog((current) => current ? { ...current, job } : current);
      while (!["success", "partial_failure", "error"].includes(job.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
        job = await getGraphBuildJob(job.job_id);
        setPrecisionDialog((current) => current ? { ...current, job } : current);
      }
      if (job.status !== "success") {
        throw new Error(job.recent_error || `LightRAG build ended with ${job.status}`);
      }
      setPrecisionDialog(null);
      await submitQuestion(pending.question, "high_precision", false);
    } catch (err) {
      setPrecisionDialog((current) => current ? {
        ...current,
        building: false,
        reason: err instanceof Error ? err.message : t("error_generic"),
      } : current);
    }
  }

  // 当前展示的来源：选中消息 > 最后一条 assistant 消息
  const displayedSources: AskSource[] = (() => {
    if (selectedMsgIndex !== null && messages[selectedMsgIndex]?.sources?.length) {
      return messages[selectedMsgIndex].sources!;
    }
    const lastA = [...messages].reverse().find((m) => m.role === "assistant");
    return lastA?.sources ?? [];
  })();

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>
      {precisionDialog && (
        <PrecisionDialog
          state={precisionDialog}
          onBuild={handlePrecisionBuild}
          onFallback={handlePrecisionFallback}
          onCancel={() => setPrecisionDialog(null)}
        />
      )}

      {/* 对话区 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 1 }}>
        {/* 顶部工具条 */}
        <div
          className="fx-glass"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 3,
            height: "var(--topbar-h)",
            boxSizing: "border-box",
            padding: "0 22px",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, lineHeight: 1, minWidth: 0 }}>
            <span style={{ color: "var(--fg-subtle)", fontSize: 12, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{modeInfo}</span>
            <Tag
              label={retrievalMode === "graph_only" ? "图谱检索" : retrievalMode === "high_precision" ? "联合检索" : "语义检索"}
              accent={retrievalMode !== "default"}
            />
          </div>
          {messages.length > 0 && (
            <Btn
              variant="ghost"
              size="sm"
              onClick={() => {
                if (conversationId) {
                  clearChatHistory(conversationId).catch(() => {});
                }
                const newId = crypto.randomUUID();
                if (typeof window !== "undefined") {
                  localStorage.setItem(_CONV_KEY, newId);
                }
                setConversationId(newId);
                setMessages([]);
                setSelectedMsgIndex(null);
              }}
            >
              新对话
            </Btn>
          )}
          <button
            onClick={() => setShowSources(v => !v)}
            title={showSources ? "收起来源面板" : "展开来源面板"}
            style={{
              width: 28, height: 28, borderRadius: 7, border: "1px solid var(--border)",
              background: showSources ? "var(--accent-soft)" : "var(--bg-inset)",
              color: showSources ? "var(--accent)" : "var(--fg-subtle)",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", transition: "all .15s", flexShrink: 0,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="15" y1="3" x2="15" y2="21"/>
            </svg>
          </button>
        </div>

        {/* 消息列表（position:relative 供进度条绝对定位） */}
        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        <div ref={scrollRef} style={{ height: "100%", overflowY: "auto", padding: "16px 20px" }}>
          {messages.length === 0 ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                gap: 8,
                textAlign: "center",
                maxWidth: 400,
                margin: "0 auto",
              }}
            >
              <span
                style={{
                  width: 54,
                  height: 54,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 26,
                  color: "var(--accent-fg)",
                  background: "var(--accent)",
                  border: "8px solid color-mix(in srgb, var(--surface) 82%, transparent)",
                  marginBottom: 10,
                  boxShadow: "0 4px 16px var(--ring)",
                  animation: "sparkleFloat 3s ease-in-out infinite",
                }}
              >
                ✦
              </span>
              <h2
                style={{
                  margin: "0 0 4px",
                  fontSize: 16,
                  fontWeight: 700,
                  color: "var(--heading)",
                }}
              >
                {t("ask_empty_title")}
              </h2>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "var(--fg-muted)",
                  lineHeight: 1.6,
                }}
              >
                {t("ask_empty_sub")}
              </p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <MessageBubble
                key={i}
                msg={msg}
                activeN={activeN}
                setActiveN={setActiveN}
                isSelected={selectedMsgIndex === i}
                isGlowing={glowingMsgIndex === i}
                onSelect={() => {
                  setSelectedMsgIndex(i);
                  setGlowingMsgIndex(i);
                  setShowSources(true);
                }}
                onGlowEnd={() => setGlowingMsgIndex(null)}
              />
            ))
          )}
          {loading && (
            <div style={{ display: "flex", gap: 8, padding: "6px 0", color: "var(--fg-muted)", fontSize: 12, alignItems: "center" }}>
              <span
                style={{
                  width: 12, height: 12,
                  border: "2px solid var(--accent)",
                  borderTopColor: "transparent",
                  borderRadius: "50%",
                  animation: "spin 0.6s linear infinite",
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              {t("ask_thinking")}
            </div>
          )}
        </div>
        </div>{/* end position:relative wrapper */}

        {/* 输入框 */}
        <div style={{ padding: "10px 16px 14px", width: "100%", maxWidth: 900, margin: "0 auto" }}>
          <form onSubmit={handleSend}>
            <div className={`ask-card${loading ? " ask-card--loading" : ""}`}>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend(e as unknown as React.FormEvent);
                  }
                }}
                placeholder={t("ask_placeholder")}
                rows={2}
                style={{
                  width: "100%", resize: "none", border: "none", outline: "none",
                  background: "transparent", padding: "12px 14px 6px",
                  fontSize: 13, lineHeight: 1.6, fontFamily: "inherit",
                  color: "var(--fg)", boxShadow: "none",
                }}
              />
              {/* 底部操作行：设置（齿轮）→ 集合选择 → 发送 */}
              <div style={{ display: "flex", alignItems: "center", padding: "6px 10px 10px", gap: 6 }}>
                {/* ── 齿轮设置按钮（第 1 位）── */}
                <div ref={settingsRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    title="查询设置"
                    onClick={() => { setShowSettingsMenu((v) => !v); setShowCollectionPicker(false); }}
                    style={{
                      width: 30, height: 30, borderRadius: 8,
                      background: personaEnabled || retrievalMode !== "default" || useEnglishRetrieval || answerLanguage !== "auto" || showSettingsMenu ? "var(--accent-soft)" : "var(--bg-inset)",
                      color: personaEnabled || retrievalMode !== "default" || useEnglishRetrieval || answerLanguage !== "auto" || showSettingsMenu ? "var(--accent)" : "var(--fg-subtle)",
                      border: "1px solid var(--border)", cursor: "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      transition: "all .15s", flexShrink: 0,
                    }}
                  >
                    {/* 齿轮图标 */}
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="3"/>
                      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                    </svg>
                  </button>
                  {showSettingsMenu && (
                    <div
                      style={{
                        position: "absolute", bottom: "calc(100% + 8px)", left: 0,
                        background: "var(--surface)", border: "1px solid var(--border)",
                        borderRadius: 12, padding: "8px 6px", boxShadow: "var(--shadow-pop)",
                        minWidth: 220, zIndex: 500,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", padding: "2px 8px 6px" }}>
                        查询设置
                      </div>
                      <SettingRow label={t("ask_persona_toggle")} checked={personaEnabled} onToggle={() => setPersonaEnabled(v => !v)} />
                      {/* 检索方式三选 */}
                      <div style={{ padding: "8px 8px 4px", borderTop: "1px solid var(--border)" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 6 }}>检索方式</div>
                        <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
                          {([
                            { value: "default" as RetrievalMode, label: "语义检索", desc: "Milvus 向量相似度" },
                            { value: "graph_only" as RetrievalMode, label: "图谱检索", desc: "LightRAG 实体关系推理" },
                            { value: "high_precision" as RetrievalMode, label: "联合检索", desc: "向量 + 图谱 · 最全面" },
                          ] as const).map(({ value, label, desc }, idx) => {
                            const isSelected = retrievalMode === value;
                            const needsCollection = value === "graph_only" || value === "high_precision";
                            return (
                              <button
                                key={value}
                                type="button"
                                aria-pressed={isSelected}
                                onClick={() => {
                                  setRetrievalMode(value);
                                  if (needsCollection && (!collection || !localCollections.includes(collection))) {
                                    setCollection(null);
                                    setShowSettingsMenu(false);
                                    setShowCollectionPicker(true);
                                  }
                                }}
                                style={{
                                  display: "flex", alignItems: "center", gap: 10,
                                  width: "100%", padding: "8px 10px", cursor: "pointer",
                                  background: isSelected ? "var(--accent-soft)" : "transparent",
                                  borderTop: idx > 0 ? "1px solid var(--border)" : "none",
                                  border: "none", textAlign: "left", transition: "background .12s",
                                }}
                              >
                                <span style={{
                                  width: 14, height: 14, borderRadius: "50%", flexShrink: 0,
                                  border: `2px solid ${isSelected ? "var(--accent)" : "var(--fg-subtle)"}`,
                                  background: isSelected ? "var(--accent)" : "transparent",
                                  display: "flex", alignItems: "center", justifyContent: "center",
                                }}>
                                  {isSelected && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "white", display: "block" }} />}
                                </span>
                                <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                                  <span style={{ fontSize: 12, fontWeight: 600, color: isSelected ? "var(--accent)" : "var(--fg)", lineHeight: 1.2 }}>{label}</span>
                                  <span style={{ fontSize: 10, color: "var(--fg-muted)", lineHeight: 1.3 }}>{desc}</span>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                      {/* 使用英语召回 */}
                      <SettingRow label="使用英语召回" checked={useEnglishRetrieval} borderTop onToggle={() => setUseEnglishRetrieval(v => !v)} />
                      {/* 回答语言 */}
                      <div style={{ padding: "6px 8px 4px", borderTop: "1px solid var(--border)" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 5 }}>回答语言</div>
                        <div style={{ display: "flex", gap: 4 }}>
                          {(["auto", "zh", "en"] as const).map((lang) => (
                            <button
                              key={lang}
                              type="button"
                              onClick={() => setAnswerLanguage(lang)}
                              style={{
                                flex: 1, padding: "4px 0", fontSize: 11, borderRadius: 6, cursor: "pointer",
                                border: "1px solid var(--border)",
                                background: answerLanguage === lang ? "var(--accent-soft)" : "var(--bg-inset)",
                                color: answerLanguage === lang ? "var(--accent)" : "var(--fg-subtle)",
                                fontWeight: answerLanguage === lang ? 600 : 400,
                                transition: "all .12s",
                              }}
                            >
                              {{"auto": "自动", "zh": "中文", "en": "English"}[lang]}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* ── 集合选择按钮（第 2 位）── */}
                <div ref={collectionRef} style={{ position: "relative" }}>
                  <button
                    type="button"
                    title="选择知识库集合"
                    onClick={() => { setShowCollectionPicker((v) => !v); setShowSettingsMenu(false); }}
                    style={{
                      height: 30, borderRadius: 8,
                      paddingLeft: 8, paddingRight: collection ? 10 : 8,
                      background: collection || showCollectionPicker ? "var(--accent-soft)" : "var(--bg-inset)",
                      color: collection || showCollectionPicker ? "var(--accent)" : "var(--fg-subtle)",
                      border: "1px solid var(--border)", cursor: "pointer",
                      display: "flex", alignItems: "center", gap: 5,
                      transition: "all .15s", flexShrink: 0,
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                      <ellipse cx="12" cy="5" rx="9" ry="3"/>
                      <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/>
                      <path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>
                    </svg>
                    <span style={{
                      fontSize: 11, fontWeight: 600, lineHeight: 1,
                      maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {collection ?? t("ask_collection_all")}
                    </span>
                  </button>
                  {showCollectionPicker && (
                    <div
                      style={{
                        position: "absolute", bottom: "calc(100% + 8px)", left: 0,
                        background: "var(--surface)", border: "1px solid var(--border)",
                        borderRadius: 12, padding: "8px 6px", boxShadow: "var(--shadow-pop)",
                        minWidth: 160, zIndex: 500,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", padding: "2px 8px 6px" }}>
                        知识库集合
                      </div>
                      {((retrievalMode === "high_precision" || retrievalMode === "graph_only") ? localCollections : [null, ...defaultCollections]).map((c) => (
                        <button
                          key={c ?? "__all__"}
                          type="button"
                          onClick={() => { setCollection(c); setShowCollectionPicker(false); }}
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            width: "100%", padding: "6px 8px", borderRadius: 8,
                            background: collection === c ? "var(--accent-soft)" : "transparent",
                            color: collection === c ? "var(--accent)" : "var(--fg)",
                            border: "none", cursor: "pointer", fontSize: 12, fontFamily: "inherit",
                            textAlign: "left", transition: "background .1s",
                          }}
                        >
                          <span style={{
                            width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                            background: collection === c ? "var(--accent)" : "var(--border-strong)",
                          }} />
                          {c ?? t("ask_collection_all")}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <span style={{ flex: 1 }} />
                {/* 圆形发送按钮 */}
                <button
                  type="submit"
                  disabled={!input.trim() || loading}
                  style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: input.trim() && !loading ? "var(--accent)" : "var(--bg-inset)",
                    border: "none", cursor: input.trim() && !loading ? "pointer" : "default",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "background 0.15s, transform 0.1s",
                    flexShrink: 0,
                  }}
                  onMouseDown={(e) => { if (input.trim()) (e.currentTarget as HTMLElement).style.transform = "scale(0.92)"; }}
                  onMouseUp={(e) => { (e.currentTarget as HTMLElement).style.transform = ""; }}
                >
                  {loading ? (
                    <span style={{
                      width: 14, height: 14, borderRadius: "50%",
                      border: "2px solid var(--fg-subtle)", borderTopColor: "transparent",
                      display: "inline-block", animation: "spin 0.6s linear infinite",
                    }} />
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={input.trim() ? "#fff" : "var(--fg-subtle)"} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13" />
                      <polygon points="22 2 15 22 11 13 2 9 22 2" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* 来源面板（可折叠） */}
      {showSources && (
        <SourcesPanel sources={displayedSources} activeN={activeN} onClose={() => setShowSources(false)} />
      )}
    </div>
  );
}
