"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { AskResult, AskSource, ApiError, EffectiveConfig, ask, listKbCollections, getEffectiveConfig } from "@/lib/api";
import { RetrievalProgress } from "@/components/fx/RetrievalProgress";

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
  const [retrievalActive, setRetrievalActive] = useState(false);
  const [modeInfo, setModeInfo] = useState<string>("embedding + RRF");
  const [personaEnabled, setPersonaEnabled] = useState(false);
  const [showCollectionPicker, setShowCollectionPicker] = useState(false);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [showSources, setShowSources] = useState(true);

  useEffect(() => {
    listKbCollections().then(setCollections).catch(() => {});
    // 拉取一次配置，组合显示向量后端 + embedding + 增强模式
    getEffectiveConfig().then((cfg: EffectiveConfig) => {
      const vdb = cfg.vector_db as Record<string, string> | undefined;
      const ask = cfg.ask as Record<string, string> | undefined;
      const backend = vdb?.backend ?? "astr";
      const provider = vdb?.embedding_provider ?? "external";
      const mode = ask?.conversation_enhancement_mode ?? "inject";
      const backendLabel = backend === "milvus" ? "Milvus" : "AstrBot KB";
      const providerLabel = provider === "local" ? "本地 Embedding" : "API Embedding";
      const modeLabel = mode === "inject" ? "注入增强" : "代理增强";
      setModeInfo(`${backendLabel} · ${providerLabel} · ${modeLabel}`);
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

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
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
      });

      setConversationId(result.conversation_id);
      setSources(result.sources);
      if (result.sources.length > 0) setShowSources(true);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
      setRetrievalActive(false);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>

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
                      {[null, ...collections].map((c) => (
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
                      background: personaEnabled || showSettingsMenu ? "var(--accent-soft)" : "var(--bg-inset)",
                      color: personaEnabled || showSettingsMenu ? "var(--accent)" : "var(--fg-subtle)",
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
                      <div style={{ fontSize: 10, color: "var(--fg-subtle)", padding: "2px 8px 4px", marginTop: 2, borderTop: "1px solid var(--border)" }}>
                        embedding + RRF 检索
                      </div>
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
        <SourcesPanel sources={sources} activeN={activeN} onClose={() => setShowSources(false)} />
      )}
    </div>
  );
}
