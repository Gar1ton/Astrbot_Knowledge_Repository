"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Btn } from "@/components/ui/Btn";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  AskResult, AskSource, ApiError, EffectiveConfig, GraphBuildEstimate, GraphBuildJob,
  ask, buildGraph, estimateGraphBuild, getEffectiveConfig, getGraphBuildJob, listCollections,
  listKbCollections,
} from "@/lib/api";
import { RetrievalProgress } from "@/components/fx/RetrievalProgress";

type RetrievalMode = "default" | "high_precision";

function retrievalModeLabel(mode?: string): string {
  if (mode === "milvus_lightrag") return "高精度 · Milvus + LightRAG";
  if (mode === "astrbot_lightrag") return "高精度 · AstrBot + LightRAG";
  if (mode === "lexical_lightrag") return "高精度 · 词汇召回 + LightRAG";
  if (mode === "lightrag") return "高精度 · 仅 LightRAG";
  if (mode === "astrbot_fallback") return "已回退 · AstrBot";
  if (mode === "astrbot") return "AstrBot";
  if (mode === "sqlite_lexical") return "SQLite 词汇召回";
  if (mode === "none") return "未完成召回";
  return "Milvus";
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
      <div
        className="fx-glass"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 2,
          height: "var(--topbar-h)",
          boxSizing: "border-box",
          padding: "0 10px 0 16px",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <div style={{ flex: 1, fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", lineHeight: 1 }}>
          {t("ask_sources")}
        </div>
        <button
          onClick={onClose}
          title="收起来源面板"
          style={{
            width: 24, height: 24, borderRadius: 6, border: "none",
            background: "transparent", color: "var(--fg-subtle)",
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", flexShrink: 0, transition: "all .15s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; e.currentTarget.style.color = "var(--fg)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--fg-subtle)"; }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 10px" }}>
        {sources.length === 0 ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 12, padding: 8 }}>暂无引用来源</div>
        ) : (
          sources.map((src) => {
            const isActive = activeN === src.n;
            return (
              <div
                key={src.n}
                style={{
                  background: isActive ? "var(--accent-soft)" : "var(--bg-inset)",
                  border: `1px solid ${isActive ? "var(--accent-border)" : "var(--border)"}`,
                  borderRadius: 10, padding: "10px 12px", marginBottom: 8,
                  transition: "all .15s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                  <span
                    style={{
                      background: "var(--accent)", color: "#fff",
                      borderRadius: 999, fontSize: 10, fontWeight: 700,
                      width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {src.n}
                  </span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--heading)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {src.title}
                  </span>
                </div>
                <p style={{ margin: "0 0 6px", fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {src.text}
                </p>
                {src.rrf_score !== undefined && (
                  <div style={{ fontSize: 10, color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)", marginBottom: 5 }}>
                    RRF: {src.rrf_score.toFixed(4)}
                  </div>
                )}
                <Link
                  href={`/documents?doc_id=${src.doc_id}`}
                  style={{ fontSize: 11, color: "var(--accent)", fontWeight: 500 }}
                >
                  {t("ask_open_doc")} →
                </Link>
              </div>
            );
          })
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

function MessageBubble({ msg, activeN, setActiveN }: { msg: Message; activeN: number | null; setActiveN: (n: number | null) => void }) {
  const isUser = msg.role === "user";
  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 14,
      }}
    >
      <div
        style={{
          maxWidth: "80%",
          background: isUser ? "var(--accent)" : "var(--surface)",
          color: isUser ? "var(--accent-fg)" : "var(--fg)",
          border: isUser ? "none" : "1px solid var(--border)",
          borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
          padding: "10px 14px",
          fontSize: 13,
          lineHeight: 1.65,
          boxShadow: "var(--shadow)",
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

// ─── Ask Agent 主页 ───────────────────────────────────────────

export default function AskPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);

  const [localCollections, setLocalCollections] = useState<string[]>([]);
  const [defaultCollections, setDefaultCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sources, setSources] = useState<AskSource[]>([]);
  const [activeN, setActiveN] = useState<number | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrievalActive, setRetrievalActive] = useState(false);
  const [modeInfo, setModeInfo] = useState<string>("embedding + RRF");
  const [defaultRetrievalLabel, setDefaultRetrievalLabel] = useState("Milvus");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("default");
  const [personaEnabled, setPersonaEnabled] = useState(false);
  const [showCollectionPicker, setShowCollectionPicker] = useState(false);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [showSources, setShowSources] = useState(true);
  const [precisionDialog, setPrecisionDialog] = useState<PrecisionDialogState | null>(null);
  const highPrecisionCollectionReady = Boolean(
    collection && localCollections.includes(collection)
  );

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
  }, []);

  useEffect(() => {
    if (!showCollectionPicker && !showSettingsMenu) return;
    function onMouseDown() { setShowCollectionPicker(false); setShowSettingsMenu(false); }
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
    if (mode === "high_precision" && !highPrecisionCollectionReady) {
      setShowCollectionPicker(true);
      toast("高精度召回需要先选择一个集合。", "info");
      return;
    }
    if (appendUser) {
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: question }]);
    }
    setLoading(true);
    setRetrievalActive(true);
    setActiveN(null);

    try {
      const result: AskResult = await ask({
        question,
        collection: collection || null,
        top_k: 5,
        conversation_id: conversationId,
        persona_enabled: personaEnabled,
        retrieval_mode: mode,
      });

      setConversationId(result.conversation_id);
      setSources(result.sources);
      if (result.sources.length > 0) setShowSources(true);
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
        mode === "high_precision"
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
      setRetrievalActive(false);
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
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--heading)", flex: 1, display: "flex", alignItems: "center", gap: 8, lineHeight: 1 }}>
            {t("nav_ask")}
            <span style={{ color: "var(--accent)", fontSize: 11, lineHeight: 1 }}>●</span>
            <span style={{ color: "var(--fg-subtle)", fontSize: 11, fontWeight: 500, lineHeight: 1 }}>{modeInfo}</span>
            <Tag label={retrievalMode === "high_precision" ? "高精度召回" : `${defaultRetrievalLabel} 默认召回`} accent={retrievalMode === "high_precision"} />
          </h1>
          {messages.length > 0 && (
            <Btn
              variant="ghost"
              size="sm"
              onClick={() => {
                setMessages([]);
                setSources([]);
                setConversationId(null);
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
              <MessageBubble key={i} msg={msg} activeN={activeN} setActiveN={setActiveN} />
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
        {/* 辉光召回进度条（紧贴消息区底部内边缘） */}
        <RetrievalProgress
          conversationId={conversationId}
          active={retrievalActive}
          onDone={() => setRetrievalActive(false)}
        />
        </div>{/* end position:relative wrapper */}

        {/* 输入框 */}
        <div style={{ padding: "10px 16px 14px", width: "100%", maxWidth: 900, margin: "0 auto" }}>
          <form onSubmit={handleSend}>
            <div className="ask-card">
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
              {/* 底部操作行 */}
              <div style={{ display: "flex", alignItems: "center", padding: "6px 10px 10px", gap: 6 }}>
                {/* 集合选择图标按钮 */}
                <div style={{ position: "relative" }} onMouseDown={(e) => e.stopPropagation()}>
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
                    {collection && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, lineHeight: 1,
                        maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {collection}
                      </span>
                    )}
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
                      {(retrievalMode === "high_precision" ? localCollections : [null, ...defaultCollections]).map((c) => (
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

                {/* 设置图标按钮 */}
                <div style={{ position: "relative" }} onMouseDown={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    title="查询设置"
                    onClick={() => { setShowSettingsMenu((v) => !v); setShowCollectionPicker(false); }}
                    style={{
                      width: 30, height: 30, borderRadius: 8,
                      background: personaEnabled || retrievalMode === "high_precision" || showSettingsMenu ? "var(--accent-soft)" : "var(--bg-inset)",
                      color: personaEnabled || retrievalMode === "high_precision" || showSettingsMenu ? "var(--accent)" : "var(--fg-subtle)",
                      border: "1px solid var(--border)", cursor: "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      transition: "all .15s", flexShrink: 0,
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="4" y1="6" x2="20" y2="6"/>
                      <line x1="8" y1="12" x2="20" y2="12"/>
                      <line x1="12" y1="18" x2="20" y2="18"/>
                      <circle cx="4" cy="6" r="2" fill="currentColor" stroke="none"/>
                      <circle cx="8" cy="12" r="2" fill="currentColor" stroke="none"/>
                      <circle cx="12" cy="18" r="2" fill="currentColor" stroke="none"/>
                    </svg>
                  </button>
                  {showSettingsMenu && (
                    <div
                      style={{
                        position: "absolute", bottom: "calc(100% + 8px)", left: 0,
                        background: "var(--surface)", border: "1px solid var(--border)",
                        borderRadius: 12, padding: "8px 6px", boxShadow: "var(--shadow-pop)",
                        minWidth: 180, zIndex: 500,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", padding: "2px 8px 6px" }}>
                        查询设置
                      </div>
                      <label
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "6px 8px", borderRadius: 8, cursor: "pointer",
                          fontSize: 12, color: "var(--fg)", userSelect: "none",
                          transition: "background .1s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-inset)")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <span>{t("ask_persona_toggle")}</span>
                        <input
                          type="checkbox"
                          checked={personaEnabled}
                          onChange={(e) => setPersonaEnabled(e.target.checked)}
                          style={{ accentColor: "var(--accent)", cursor: "pointer", width: 14, height: 14 }}
                        />
                      </label>
                      <label
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "7px 8px", borderRadius: 8, cursor: "pointer",
                          fontSize: 12, color: "var(--fg)", userSelect: "none",
                          borderTop: "1px solid var(--border)",
                        }}
                      >
                        <span>
                          高精度召回
                          <span style={{ display: "block", fontSize: 9, color: "var(--fg-subtle)", marginTop: 2 }}>
                            Milvus + LightRAG · 需指定集合
                          </span>
                        </span>
                        <input
                          type="checkbox"
                          checked={retrievalMode === "high_precision"}
                          onChange={(e) => {
                            const next = e.target.checked ? "high_precision" : "default";
                            setRetrievalMode(next);
                            if (
                              next === "high_precision"
                              && (!collection || !localCollections.includes(collection))
                            ) {
                              setCollection(null);
                              setShowSettingsMenu(false);
                              setShowCollectionPicker(true);
                            }
                          }}
                          style={{ accentColor: "var(--accent)", cursor: "pointer", width: 14, height: 14 }}
                        />
                      </label>
                      <div style={{ fontSize: 10, color: "var(--fg-subtle)", padding: "2px 8px 4px", marginTop: 2, borderTop: "1px solid var(--border)" }}>
                        {retrievalMode === "high_precision" ? "Milvus + LightRAG 上下文" : `${defaultRetrievalLabel} + RRF 默认召回`}
                      </div>
                    </div>
                  )}
                </div>

                <span style={{ flex: 1 }} />
                {/* 圆形发送按钮 */}
                <button
                  type="submit"
                  disabled={!input.trim() || loading || (retrievalMode === "high_precision" && !highPrecisionCollectionReady)}
                  style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: input.trim() && !loading && (retrievalMode === "default" || highPrecisionCollectionReady) ? "var(--accent)" : "var(--bg-inset)",
                    border: "none", cursor: input.trim() && !loading && (retrievalMode === "default" || highPrecisionCollectionReady) ? "pointer" : "default",
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
        <SourcesPanel sources={sources} activeN={activeN} onClose={() => setShowSources(false)} />
      )}
    </div>
  );
}
