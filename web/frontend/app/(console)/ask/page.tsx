"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Btn } from "@/components/ui/Btn";
import { Tag } from "@/components/ui/Tag";
import { SunBloom } from "@/components/fx/SunBloom";
import { DotField } from "@/components/fx/DotField";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { AskResult, AskSource, ApiError, ask, listKbCollections } from "@/lib/api";

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

function SourcesPanel({ sources, activeN }: { sources: AskSource[]; activeN: number | null }) {
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
        style={{ padding: "12px 14px 10px", position: "sticky", top: 0, zIndex: 2 }}
      >
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)" }}>
          {t("ask_sources")}
        </div>
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
        {isUser
          ? msg.content
          : renderAnswer(msg.content, msg.sources ?? [], activeN, setActiveN)}
      </div>
    </div>
  );
}

// ─── Ask Agent 主页 ───────────────────────────────────────────

export default function AskPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);

  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sources, setSources] = useState<AskSource[]>([]);
  const [activeN, setActiveN] = useState<number | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listKbCollections()
      .then(setCollections)
      .catch(() => {});
  }, []);

  // 自动滚到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);
    setActiveN(null);

    try {
      const result: AskResult = await ask({
        question,
        collection: collection || null,
        top_k: 5,
        conversation_id: conversationId,
      });

      setConversationId(result.conversation_id);
      setSources(result.sources);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>
      {/* 背景 */}
      <SunBloom size={480} style={{ top: -60, left: -60, opacity: 0.75 }} />
      <DotField />

      {/* 对话区 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 1 }}>
        {/* 顶部工具条 */}
        <div
          className="fx-glass"
          style={{ position: "sticky", top: 0, zIndex: 3, padding: "10px 16px", display: "flex", alignItems: "center", gap: 10 }}
        >
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--heading)", flex: 1 }}>
            {t("nav_ask")}
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
        </div>

        {/* 消息列表 */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
          {messages.length === 0 ? (
            <div
              style={{
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                height: "100%", gap: 12, color: "var(--fg-muted)", fontSize: 14,
              }}
            >
              <span style={{ fontSize: 32 }}>✦</span>
              {t("ask_empty")}
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

        {/* 输入框 */}
        <div style={{ padding: "10px 16px 14px" }}>
          <form onSubmit={handleSend}>
            <div
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 16,
                boxShadow: "var(--shadow-pop)",
                overflow: "hidden",
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
                  width: "100%", resize: "none", border: "none", outline: "none",
                  background: "transparent", padding: "12px 14px 6px",
                  fontSize: 13, lineHeight: 1.6, fontFamily: "inherit",
                  color: "var(--fg)",
                }}
              />
              {/* 底部操作行 */}
              <div style={{ display: "flex", alignItems: "center", padding: "6px 10px 10px", gap: 8 }}>
                {/* 集合 chip */}
                <select
                  value={collection ?? ""}
                  onChange={(e) => setCollection(e.target.value || null)}
                  style={{
                    appearance: "none", border: "none", outline: "none",
                    background: "var(--accent-soft)", color: "var(--accent)",
                    fontWeight: 600, fontSize: 11, borderRadius: 999,
                    padding: "3px 10px", cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  <option value="">{t("ask_collection_all")}</option>
                  {collections.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                  embedding + RRF
                </span>
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

      {/* 来源面板 */}
      <SourcesPanel sources={sources} activeN={activeN} />
    </div>
  );
}
