"use client";
import React, { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ds/Badge";
import { Icon } from "@/components/ds/Icon";
import { IconButton } from "@/components/ds/IconButton";
import { Button } from "@/components/ds/Button";
import { Tooltip } from "@/components/ds/Tooltip";
import { useConsole } from "@/lib/ConsoleContext";
import { useToast } from "@/components/ui/Toast";
import { useI18n, type I18nKey } from "@/lib/i18n";
import {
  AskResult, AskSource, ApiError, GraphBuildEstimate, GraphBuildJob,
  ChatMessage, ask, buildGraph, estimateGraphBuild, getGraphBuildJob,
  listCollections, getChatHistory, clearChatHistory, lockChatAnswer,
  createDocumentNote, createCollectionNote,
} from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────

type RetrievalMode = "default" | "high_precision" | "graph_only";

interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  sources?: AskSource[];
  actualRetrievalMode?: string;
  pinned?: boolean;
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

// ─── Helpers ──────────────────────────────────────────────────

function retrievalModeLabel(
  mode: string | undefined,
  t: (key: I18nKey, vars?: Record<string, string | number>) => string,
): string {
  if (mode === "lightrag_only") return t("chat_retrieval_lightrag");
  if (mode === "milvus_lightrag") return t("chat_retrieval_milvus_lightrag");
  if (mode?.includes("lightrag")) return t("chat_retrieval_lightrag_mixed");
  if (mode === "astrbot") return t("chat_retrieval_astrbot");
  if (mode === "sqlite_lexical") return t("chat_retrieval_lexical");
  if (mode === "none") return t("chat_retrieval_none");
  return t("chat_retrieval_milvus");
}

function formatDuration(seconds?: number | null): string {
  const total = Math.max(0, Math.round(seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ─── renderAnswer: **bold** + [n] citation sups ───────────────

function renderAnswer(
  text: string,
  onCite: (n: number) => void,
): React.ReactNode {
  return text.split("\n").map((line, li, lines) => {
    const parts = line.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
    return (
      <React.Fragment key={li}>
        {parts.map((p, pi) => {
          if (/^\*\*[^*]+\*\*$/.test(p))
            return <strong key={pi} style={{ fontWeight: 700, color: "var(--heading)" }}>{p.slice(2, -2)}</strong>;
          const m = p.match(/^\[(\d+)\]$/);
          if (m) {
            const n = parseInt(m[1]);
            return (
              <sup
                key={pi}
                onClick={() => onCite(n)}
                style={{
                  cursor: "pointer",
                  color: "var(--accent)",
                  background: "var(--accent-soft)",
                  borderRadius: 3,
                  padding: "0 3px",
                  fontWeight: 700,
                  fontSize: ".72em",
                  margin: "0 1px",
                }}
              >
                [{n}]
              </sup>
            );
          }
          return p;
        })}
        {li < lines.length - 1 && <br />}
      </React.Fragment>
    );
  });
}

// ─── SourceMini card ──────────────────────────────────────────

function SourceMini({ s, onClick }: { s: AskSource; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        gap: 7,
        padding: "7px 9px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border)",
        background: "var(--surface)",
        cursor: "pointer",
        marginTop: 6,
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          flexShrink: 0,
          borderRadius: "50%",
          background: "var(--accent)",
          color: "#fff",
          fontSize: 9.5,
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {s.n}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--heading)" }}>{s.title}</span>
          <span style={{ fontSize: 9.5, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>
            {s.chunk_id}
          </span>
          <span style={{ flex: 1 }} />
          {s.rrf_score != null && (
            <span style={{ fontSize: 9.5, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
              RRF {s.rrf_score.toFixed(4)}
            </span>
          )}
        </div>
        <p
          style={{
            margin: "3px 0 0",
            fontSize: 10.5,
            lineHeight: 1.5,
            color: "var(--fg-muted)",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {s.text}
        </p>
      </div>
    </div>
  );
}

// ─── MessageBubble ────────────────────────────────────────────

const ACTION_BTN: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontSize: 11,
  fontWeight: 500,
  color: "var(--fg-muted)",
  background: "transparent",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-pill)",
  padding: "3px 9px",
  cursor: "pointer",
  fontFamily: "var(--font-sans)",
};

function MessageBubble({
  msg,
  onCite,
  onPin,
  onSaveNote,
}: {
  msg: Message;
  onCite: (n: number) => void;
  onPin: () => void;
  onSaveNote: () => void;
}) {
  const [hover, setHover] = useState(false);
  const { t } = useI18n();
  const isUser = msg.role === "user";

  if (isUser) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
        <div
          style={{
            maxWidth: "86%",
            background: "var(--accent)",
            color: "var(--accent-fg)",
            borderRadius: "10px 10px 3px 10px",
            padding: "9px 12px",
            fontSize: 12.5,
            lineHeight: 1.6,
          }}
        >
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div
      style={{ marginBottom: 16 }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div
        style={{
          maxWidth: "94%",
          background: "var(--surface)",
          border: `1px solid ${msg.pinned ? "var(--accent-border)" : "var(--border)"}`,
          borderRadius: "10px 10px 10px 3px",
          padding: "10px 13px",
          boxShadow: msg.pinned ? "0 0 0 3px var(--ring)" : "var(--shadow-card)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
          <Badge tone="accent">{retrievalModeLabel(msg.actualRetrievalMode, t)}</Badge>
          {msg.pinned && (
            <Badge tone="warn">
              <Icon name="pin" size={9} /> {t("chat_locked")}
            </Badge>
          )}
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--fg)" }}>
          {renderAnswer(msg.content, onCite)}
        </div>
        {msg.sources && msg.sources.length > 0 && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
            <div
              style={{
                fontSize: 9.5,
                fontWeight: 700,
                letterSpacing: ".06em",
                textTransform: "uppercase",
                color: "var(--fg-subtle)",
                marginBottom: 2,
              }}
            >
              {t("chat_sources_open")}
            </div>
            {msg.sources.map((s) => (
              <SourceMini key={s.n} s={s} onClick={() => onCite(s.n)} />
            ))}
          </div>
        )}
      </div>
      <div
        style={{
          display: "flex",
          gap: 4,
          marginTop: 6,
          opacity: hover || msg.pinned ? 1 : 0.4,
          transition: "opacity .15s",
        }}
      >
        <Tooltip label={t("chat_add_linked_note_tip")} side="top">
          <button onClick={onSaveNote} style={ACTION_BTN}>
            <Icon name="link" size={12} /> {t("chat_add_linked_note")}
          </button>
        </Tooltip>
        <Tooltip label={msg.pinned ? t("chat_unlock_answer") : t("chat_lock_answer")} side="top">
          <button
            onClick={onPin}
            style={{ ...ACTION_BTN, color: msg.pinned ? "var(--accent)" : "var(--fg-muted)" }}
          >
            <Icon name="pin" size={12} /> {msg.pinned ? t("chat_answer_locked") : t("chat_lock_answer_short")}
          </button>
        </Tooltip>
      </div>
    </div>
  );
}

// ─── PrecisionDialog ──────────────────────────────────────────

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
  const { t } = useI18n();
  const rows: [string, string][] = state.estimate
    ? [
        [t("chat_est_collection"), state.estimate.collection],
        [t("chat_est_docs"), String(state.estimate.docs_count)],
        [t("chat_est_chunks"), String(state.estimate.chunks_count)],
        [t("chat_est_llm_calls"), `${state.estimate.estimated_llm_calls_min} – ${state.estimate.estimated_llm_calls_max}`],
        [
          t("chat_est_duration"),
          `${formatDuration(state.estimate.estimated_duration_seconds_min)} – ${formatDuration(state.estimate.estimated_duration_seconds_max)}`,
        ],
      ]
    : [[t("chat_est_collection"), state.collection]];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 600,
      }}
      onClick={(e) => e.target === e.currentTarget && !state.building && onCancel()}
    >
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 14,
          padding: 24,
          width: 410,
          boxShadow: "var(--shadow-pop)",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div>
          <h3 style={{ margin: "0 0 5px", fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
            {t("chat_precision_title")}
          </h3>
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.6, color: "var(--fg-muted)" }}>
            {state.reason}
          </p>
        </div>
        <div
          style={{
            background: "var(--bg-inset)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          {rows.map(([label, value], i) => (
            <div
              key={label}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                padding: "8px 14px",
                borderTop: i > 0 ? "1px solid var(--border)" : undefined,
              }}
            >
              <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>{label}</span>
              <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg)", fontWeight: 600 }}>
                {value}
              </span>
            </div>
          ))}
        </div>
        {state.estimate?.estimate_notice && (
          <div
            style={{
              fontSize: 11,
              lineHeight: 1.6,
              color: "var(--warn)",
              background: "color-mix(in srgb, var(--warn) 10%, transparent)",
              border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
              borderRadius: 8,
              padding: "8px 12px",
            }}
          >
            {state.estimate.estimate_notice}
          </div>
        )}
        {state.job && (
          <div style={{ fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.6 }}>
            {t("chat_building_status", {
              status: state.job.status,
              done: state.job.processed_chunks ?? 0,
              total: state.job.total_chunks ?? "?",
            })}
            {state.job.elapsed_seconds != null && ` · ${t("chat_elapsed")} ${formatDuration(state.job.elapsed_seconds)}`}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <Button variant="ghost" size="sm" disabled={state.building} onClick={onCancel}>
            {t("btn_cancel")}
          </Button>
          <Button variant="outline" size="sm" disabled={state.building} onClick={onFallback}>
            {t("chat_use_milvus_once")}
          </Button>
          {state.canBuild && state.estimate && (
            <Button size="sm" loading={state.building} onClick={onBuild}>
              {t("chat_build_and_continue")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── ChatPanel ────────────────────────────────────────────────

const CONV_KEY = "kr_conversation_id";

function getOrCreateConvId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const stored = localStorage.getItem(CONV_KEY);
  if (stored) return stored;
  const id = crypto.randomUUID();
  localStorage.setItem(CONV_KEY, id);
  return id;
}

export function ChatPanel() {
  const { selectedCollection, selectedDocId, setSelectedDocId, setHighlightedChunk } = useConsole();
  const { t } = useI18n();
  const { toast } = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyLoadedRef = useRef<string | null>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  // Collection name (strip prefix)
  const collectionName = selectedCollection
    ? selectedCollection.replace(/^(z:|l:|lr:)/, "")
    : null;

  const [localCollections, setLocalCollections] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("default");
  const [personaEnabled, setPersonaEnabled] = useState(false);
  const [useEnglishRetrieval, setUseEnglishRetrieval] = useState(true);
  const [answerLanguage, setAnswerLanguage] = useState<"auto" | "zh" | "en">("auto");
  const [showSettings, setShowSettings] = useState(false);
  const [precisionDialog, setPrecisionDialog] = useState<PrecisionDialogState | null>(null);

  const graphModeReady = Boolean(collectionName && localCollections.includes(collectionName));

  useEffect(() => {
    listCollections()
      .then((cols) => setLocalCollections(cols.map((c) => c.name)))
      .catch(() => {});
    const cid = getOrCreateConvId();
    setConversationId(cid);
  }, []);

  useEffect(() => {
    if (!conversationId || historyLoadedRef.current === conversationId) return;
    historyLoadedRef.current = conversationId;
    getChatHistory(conversationId)
      .then((msgs: ChatMessage[]) => {
        if (msgs.length === 0) return;
        setMessages(
          msgs.map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            sources: m.sources,
            actualRetrievalMode: m.retrieval_mode || undefined,
            id: m.id,
            pinned: Boolean(m.locked),
          })),
        );
      })
      .catch(() => {});
  }, [conversationId]);

  useEffect(() => {
    if (!showSettings) return;
    const onDown = (e: MouseEvent) => {
      if (!settingsRef.current?.contains(e.target as Node)) setShowSettings(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowSettings(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [showSettings]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function handleCite(msg: Message, n: number) {
    const src = msg.sources?.find((s) => s.n === n);
    if (!src) return;
    setHighlightedChunk({ docId: src.doc_id, chunkId: src.chunk_id });
    if (src.doc_id !== selectedDocId) setSelectedDocId(src.doc_id);
  }

  async function handlePin(index: number) {
    const current = messages[index];
    const nextPinned = !current?.pinned;
    setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, pinned: nextPinned } : m)));
    if (!conversationId) return;
    try {
      const updated = await lockChatAnswer(conversationId, index, nextPinned);
      setMessages((prev) =>
        prev.map((m, i) => (i === index ? { ...m, id: updated.id, pinned: Boolean(updated.locked) } : m)),
      );
    } catch (err) {
      setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, pinned: !nextPinned } : m)));
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleSaveNote(msg: Message) {
    const body = msg.content.replace(/\*\*/g, "").replace(/\[\d+\]/g, "").slice(0, 200);
    const options = {
      linked: true,
      source: "chat",
      chat_conversation_id: conversationId ?? undefined,
      chat_message_id: msg.id,
    };
    try {
      if (selectedDocId) {
        await createDocumentNote(selectedDocId, body, options);
      } else if (collectionName) {
        await createCollectionNote(collectionName, body, options);
      } else {
        throw new Error("no active note scope");
      }
      toast(t("chat_note_saved"), "ok");
      return;
    } catch {
      /* local fallback below */
    }
    const key = `kr_notes_${collectionName ?? "global"}`;
    const existing = JSON.parse(localStorage.getItem(key) ?? "[]") as string[];
    localStorage.setItem(key, JSON.stringify([...existing, body]));
    toast(t("chat_note_saved"), "ok");
  }

  function clearChat() {
    if (conversationId) clearChatHistory(conversationId, true).catch(() => {});
    setMessages((prev) => prev.filter((m) => m.pinned));
  }

  async function submitQuestion(question: string, mode: RetrievalMode, appendUser: boolean) {
    if (loading) return;
    if ((mode === "high_precision" || mode === "graph_only") && !graphModeReady) {
      toast(t("chat_graph_requires_collection"), "info");
      return;
    }
    if (appendUser) {
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: question }]);
    }
    setLoading(true);
    try {
      const result: AskResult = await ask({
        question,
        collection: collectionName ?? null,
        top_k: 5,
        conversation_id: conversationId,
        persona_enabled: personaEnabled,
        retrieval_mode: mode,
        use_english_retrieval: useEnglishRetrieval,
        answer_language: answerLanguage,
      });
      setConversationId(result.conversation_id);
      if (typeof window !== "undefined") localStorage.setItem(CONV_KEY, result.conversation_id);
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
        (mode === "high_precision" || mode === "graph_only") &&
        err instanceof ApiError &&
        (err.body?.status === "lightrag_not_ready" || err.body?.status === "high_precision_failed") &&
        collectionName
      ) {
        let estimate: GraphBuildEstimate | undefined;
        const canBuild = err.body.build_available === true;
        if (canBuild) {
          try { estimate = await estimateGraphBuild(collectionName); } catch { /* ignore */ }
        }
        setPrecisionDialog({ question, collection: collectionName, reason: err.message, estimate, canBuild });
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
      setPrecisionDialog((cur) => cur ? { ...cur, job } : cur);
      while (!["success", "partial_failure", "error"].includes(job.status)) {
        await new Promise((res) => setTimeout(res, 1200));
        job = await getGraphBuildJob(job.job_id);
        setPrecisionDialog((cur) => cur ? { ...cur, job } : cur);
      }
      if (job.status !== "success") throw new Error(job.recent_error ?? `build ended with ${job.status}`);
      setPrecisionDialog(null);
      await submitQuestion(pending.question, "high_precision", false);
    } catch (err) {
      setPrecisionDialog((cur) =>
        cur ? { ...cur, building: false, reason: err instanceof Error ? err.message : t("error_generic") } : cur,
      );
    }
  }

  // Context badge info
  const isLightRAG = selectedCollection?.startsWith("lr:");
  const isDoc = !!selectedDocId;
  const contextTone = isLightRAG ? "violet" : isDoc ? "info" : "accent";
  const contextIcon = isDoc ? "file" : isLightRAG ? "graph" : "folder";
  const contextLabel = isDoc
    ? (selectedDocId ?? "").slice(0, 24)
    : collectionName ?? t("panel_all_collections");

  return (
    <section
      style={{
        width: "var(--chat-w)",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-card)",
        overflow: "hidden",
      }}
    >
      {precisionDialog && (
        <PrecisionDialog
          state={precisionDialog}
          onBuild={handlePrecisionBuild}
          onFallback={handlePrecisionFallback}
          onCancel={() => setPrecisionDialog(null)}
        />
      )}

      {/* Header */}
      <header
        style={{
          height: 38,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "0 8px 0 13px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <Icon name="sparkle" size={15} style={{ color: "var(--accent)" }} />
        <span style={{ flex: 1, fontSize: 12.5, fontWeight: 650, color: "var(--heading)" }}>
          {t("panel_chat")}
        </span>
        <IconButton name="trash" label={t("chat_clear_history")} onClick={clearChat} />
      </header>

      {/* Messages */}
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "14px 12px" }}>
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
              color: "var(--fg-subtle)",
              fontSize: 12,
              padding: "40px 20px",
            }}
          >
            <Icon name="sparkle" size={28} style={{ color: "var(--accent)", opacity: 0.6 }} />
            <span>{t("ask_empty_title")}</span>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble
              key={i}
              msg={msg}
              onCite={(n) => handleCite(msg, n)}
              onPin={() => handlePin(i)}
              onSaveNote={() => handleSaveNote(msg)}
            />
          ))
        )}
        {loading && (
          <div
            style={{
              display: "flex",
              gap: 8,
              padding: "6px 0",
              color: "var(--fg-muted)",
              fontSize: 12,
              alignItems: "center",
            }}
          >
            <span
              style={{
                width: 12,
                height: 12,
                border: "2px solid var(--accent)",
                borderTopColor: "transparent",
                borderRadius: "50%",
                animation: "spin 0.6s linear infinite",
                flexShrink: 0,
              }}
            />
            {t("ask_thinking")}
          </div>
        )}
      </div>

      {/* Composer */}
      <div
        style={{
          flexShrink: 0,
          padding: "8px 12px 12px",
          borderTop: "1px solid var(--border)",
        }}
      >
        {/* Context chip */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
          <span style={{ fontSize: 10.5, color: "var(--fg-subtle)" }}>{t("panel_scope")}</span>
          <Badge tone={contextTone}>
            <Icon name={contextIcon} size={10} /> {contextLabel}
          </Badge>
        </div>

        <form onSubmit={handleSend}>
          <div
            style={{
              border: "1px solid var(--border-strong)",
              borderRadius: "var(--radius-lg)",
              background: "var(--surface)",
              padding: 8,
              boxShadow: "var(--shadow-card)",
            }}
          >
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
                width: "100%",
                resize: "none",
                border: "none",
                outline: "none",
                background: "transparent",
                fontSize: 12.5,
                lineHeight: 1.55,
                fontFamily: "var(--font-sans)",
                color: "var(--fg)",
                padding: "2px 4px",
                boxShadow: "none",
              }}
            />
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
              {/* Settings popover */}
              <div ref={settingsRef} style={{ position: "relative" }}>
                <IconButton
                  name="settings"
                  label={t("chat_settings_label")}
                  active={personaEnabled || retrievalMode !== "default" || showSettings}
                  onClick={() => setShowSettings((v) => !v)}
                />
                {showSettings && (
                  <div
                    style={{
                      position: "absolute",
                      bottom: "calc(100% + 8px)",
                      left: 0,
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: 12,
                      padding: "8px 6px",
                      boxShadow: "var(--shadow-pop)",
                      minWidth: 220,
                      zIndex: 500,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: ".06em",
                        textTransform: "uppercase",
                        color: "var(--fg-subtle)",
                        padding: "2px 8px 6px",
                      }}
                    >
                      {t("chat_settings_title")}
                    </div>
                    {/* Retrieval mode */}
                    <div style={{ padding: "4px 8px 6px" }}>
                      {(
                        [
                          { value: "default" as const, label: t("chat_retrieval_semantic"), desc: t("chat_retrieval_semantic_desc") },
                          { value: "graph_only" as const, label: t("chat_retrieval_graph"), desc: t("chat_retrieval_graph_desc") },
                          { value: "high_precision" as const, label: t("chat_retrieval_hybrid"), desc: t("chat_retrieval_hybrid_desc") },
                        ] as const
                      ).map(({ value, label, desc }) => {
                        const selected = retrievalMode === value;
                        return (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setRetrievalMode(value)}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 10,
                              width: "100%",
                              padding: "7px 8px",
                              borderRadius: 7,
                              background: selected ? "var(--accent-soft)" : "transparent",
                              border: "none",
                              cursor: "pointer",
                              textAlign: "left",
                            }}
                          >
                            <span
                              style={{
                                width: 12,
                                height: 12,
                                borderRadius: "50%",
                                flexShrink: 0,
                                border: `2px solid ${selected ? "var(--accent)" : "var(--fg-subtle)"}`,
                                background: selected ? "var(--accent)" : "transparent",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                              }}
                            >
                              {selected && (
                                <span
                                  style={{
                                    width: 4,
                                    height: 4,
                                    borderRadius: "50%",
                                    background: "white",
                                    display: "block",
                                  }}
                                />
                              )}
                            </span>
                            <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                              <span
                                style={{
                                  fontSize: 12,
                                  fontWeight: 600,
                                  color: selected ? "var(--accent)" : "var(--fg)",
                                  lineHeight: 1.2,
                                }}
                              >
                                {label}
                              </span>
                              <span style={{ fontSize: 10, color: "var(--fg-muted)", lineHeight: 1.3 }}>
                                {desc}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    {/* English retrieval toggle */}
                    <div
                      onClick={() => setUseEnglishRetrieval((v) => !v)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "6px 8px",
                        cursor: "pointer",
                        borderTop: "1px solid var(--border)",
                        fontSize: 12,
                        color: "var(--fg)",
                      }}
                    >
                      <span>{t("chat_use_english_retrieval")}</span>
                      <div
                        style={{
                          width: 28,
                          height: 16,
                          borderRadius: 8,
                          background: useEnglishRetrieval ? "var(--accent)" : "var(--border-strong)",
                          position: "relative",
                          transition: "background .15s",
                        }}
                      >
                        <div
                          style={{
                            position: "absolute",
                            top: 2,
                            left: useEnglishRetrieval ? 12 : 2,
                            width: 12,
                            height: 12,
                            borderRadius: "50%",
                            background: "white",
                            transition: "left .15s",
                          }}
                        />
                      </div>
                    </div>
                    {/* Answer language */}
                    <div
                      style={{ padding: "6px 8px 4px", borderTop: "1px solid var(--border)" }}
                    >
                      <div
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          color: "var(--fg-subtle)",
                          marginBottom: 5,
                          letterSpacing: ".05em",
                          textTransform: "uppercase",
                        }}
                      >
                        {t("chat_answer_language")}
                      </div>
                      <div style={{ display: "flex", gap: 4 }}>
                        {(["auto", "zh", "en"] as const).map((l) => (
                          <button
                            key={l}
                            type="button"
                            onClick={() => setAnswerLanguage(l)}
                            style={{
                              flex: 1,
                              padding: "4px 0",
                              fontSize: 11,
                              borderRadius: 6,
                              cursor: "pointer",
                              border: "1px solid var(--border)",
                              background: answerLanguage === l ? "var(--accent-soft)" : "var(--bg-inset)",
                              color: answerLanguage === l ? "var(--accent)" : "var(--fg-subtle)",
                              fontWeight: answerLanguage === l ? 600 : 400,
                              transition: "all .12s",
                            }}
                          >
                            {{ auto: t("chat_lang_auto"), zh: t("chat_lang_zh"), en: t("chat_lang_en") }[l]}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <span style={{ flex: 1 }} />

              {/* Send */}
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={!input.trim() || loading}
                loading={loading}
                style={{ height: 28 }}
              >
                <Icon name="send" size={13} /> {t("ask_send")}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </section>
  );
}
