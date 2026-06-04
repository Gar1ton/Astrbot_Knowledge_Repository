"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";

// ─── 终端色板（硬编码，不跟随主题） ─────────────────────────────
const T = {
  bg:        "#0d1117",
  bgBar:     "#161b22",
  border:    "#30363d",
  fg:        "#e6edf3",
  fgMuted:   "#8b949e",
  green:     "#3fb950",
  yellow:    "#e3b341",
  red:       "#f85149",
  blue:      "#79c0ff",
  purple:    "#d2a8ff",
} as const;

// ─── 类型 ──────────────────────────────────────────────────────
interface LogLine { ts: number; level: string; name: string; msg: string; }

interface SystemInfo {
  cwd?: string; data_dir?: string; db_file?: string; python_version?: string; platform?: string;
}

type Level = "DEBUG" | "INFO" | "WARNING" | "ERROR";
const ALL_LEVELS: Level[] = ["DEBUG", "INFO", "WARNING", "ERROR"];

// Agent 相关模块名（Ask 检索 + 事件处理）
const AGENT_MODULES = [
  "KnowledgeRepositoryApi",
  "RetrievalOrchestrator",
  "LightRAGCoreRegistry",
  "EventHandler",
  "IngestManager",
  "LocalEmbeddingProvider",
  "ExternalEmbeddingProvider",
  "MilvusLiteVectorStore",
];

function levelColor(level: string): string {
  if (level === "ERROR" || level === "CRITICAL") return T.red;
  if (level === "WARNING") return T.yellow;
  if (level === "DEBUG") return T.blue;
  return T.green; // INFO
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

// ─── 主页面 ───────────────────────────────────────────────────
export default function TerminalPage() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [visibleLevels, setVisibleLevels] = useState<Set<Level>>(new Set(ALL_LEVELS));
  const [agentOnly, setAgentOnly] = useState(false);
  const [sysInfo, setSysInfo] = useState<SystemInfo>({});
  const [sysOpen, setSysOpen] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [lastTs, setLastTs] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 拉取系统信息（一次性）
  useEffect(() => {
    fetch("/api/system/info")
      .then((r) => r.json())
      .then(setSysInfo)
      .catch(() => {});
  }, []);

  const fetchLogs = useCallback(async (after: number) => {
    try {
      const r = await fetch(`/api/logs?after=${after}&limit=200`);
      if (!r.ok) return after;
      const data: { lines: LogLine[]; server_ts: number } = await r.json();
      if (data.lines.length > 0) {
        setLines((prev) => [...prev, ...data.lines]);
        setLastTs(data.server_ts);
        return data.server_ts;
      }
      return data.server_ts || after;
    } catch {
      return after;
    }
  }, []);

  // 轮询
  useEffect(() => {
    let ts = 0;
    // 首次全量拉取
    fetchLogs(0).then((newTs) => { ts = newTs; });

    pollRef.current = setInterval(async () => {
      ts = await fetchLogs(ts);
    }, 1500);

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchLogs]);

  // 自动滚到底部
  useEffect(() => {
    if (!autoScrollRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    autoScrollRef.current = atBottom;
    setAutoScroll(atBottom);
  }

  function toggleLevel(level: Level) {
    setVisibleLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) { next.delete(level); } else { next.add(level); }
      return next;
    });
  }

  const filtered = lines.filter((l) => {
    const levelOk = visibleLevels.has((l.level || "INFO") as Level) || !ALL_LEVELS.includes(l.level as Level);
    const agentOk = !agentOnly || AGENT_MODULES.some((m) => l.name.startsWith(m));
    return levelOk && agentOk;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: T.bg, color: T.fg, fontFamily: '"Consolas", "Menlo", "Courier New", monospace', fontSize: 12, lineHeight: 1.6 }}>

      {/* ── 顶部工具栏 ── */}
      <div style={{ background: T.bgBar, borderBottom: `1px solid ${T.border}`, height: 44, display: "flex", alignItems: "center", padding: "0 16px", gap: 10, flexShrink: 0 }}>
        {/* 标题 */}
        <span style={{ color: T.fgMuted, fontSize: 11, letterSpacing: "0.04em", flexShrink: 0 }}>
          OUTPUT &mdash; knowledge-repo
        </span>

        <div style={{ flex: 1 }} />

        {/* Agent 分类过滤 */}
        <button
          onClick={() => setAgentOnly((v) => !v)}
          title="仅显示 Ask/检索/事件处理相关日志"
          style={{
            padding: "2px 10px", borderRadius: 4, fontSize: 10, fontFamily: "inherit",
            border: `1px solid ${agentOnly ? T.purple : T.border}`,
            background: agentOnly ? `${T.purple}22` : "transparent",
            color: agentOnly ? T.purple : T.fgMuted,
            cursor: "pointer", transition: "all .15s", flexShrink: 0,
          }}
        >
          AGENT
        </button>

        {/* 分隔 */}
        <span style={{ color: T.border, fontSize: 14, flexShrink: 0 }}>|</span>

        {/* 级别过滤 */}
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          {ALL_LEVELS.map((lv) => (
            <button
              key={lv}
              onClick={() => toggleLevel(lv)}
              style={{
                padding: "2px 8px", borderRadius: 4, fontSize: 10, fontFamily: "inherit",
                border: `1px solid ${visibleLevels.has(lv) ? levelColor(lv) : T.border}`,
                background: visibleLevels.has(lv) ? `${levelColor(lv)}22` : "transparent",
                color: visibleLevels.has(lv) ? levelColor(lv) : T.fgMuted,
                cursor: "pointer", transition: "all .15s",
              }}
            >
              {lv}
            </button>
          ))}
        </div>

        {/* 分隔 */}
        <span style={{ color: T.border, fontSize: 14, flexShrink: 0 }}>|</span>

        {/* 自动滚动指示 */}
        <span style={{ fontSize: 10, color: autoScroll ? T.green : T.fgMuted, flexShrink: 0 }}>
          {autoScroll ? "▼ auto" : "⏸"}
        </span>

        {/* 清空 */}
        <button
          onClick={() => setLines([])}
          style={{ padding: "2px 10px", borderRadius: 4, fontSize: 10, border: `1px solid ${T.border}`, background: "transparent", color: T.fgMuted, cursor: "pointer", fontFamily: "inherit" }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = T.red; e.currentTarget.style.color = T.red; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = T.border; e.currentTarget.style.color = T.fgMuted; }}
        >
          清空
        </button>
      </div>

      {/* ── 系统信息折叠区 ── */}
      <div style={{ borderBottom: `1px solid ${T.border}`, flexShrink: 0 }}>
        <button
          onClick={() => setSysOpen((v) => !v)}
          style={{ width: "100%", textAlign: "left", padding: "4px 16px", background: "transparent", border: "none", cursor: "pointer", color: T.fgMuted, fontSize: 11, fontFamily: "inherit", display: "flex", alignItems: "center", gap: 6 }}
        >
          <span style={{ color: T.green }}>{sysOpen ? "▼" : "▶"}</span>
          System Info
        </button>
        {sysOpen && (
          <div style={{ padding: "4px 16px 10px", display: "flex", flexDirection: "column", gap: 2 }}>
            {[
              ["cwd   ", sysInfo.cwd],
              ["data  ", sysInfo.data_dir],
              ["db    ", sysInfo.db_file],
              ["python", sysInfo.python_version ? `${sysInfo.python_version} · ${sysInfo.platform}` : undefined],
            ].map(([k, v]) => v ? (
              <div key={String(k)} style={{ display: "flex", gap: 8 }}>
                <span style={{ color: T.green }}>$</span>
                <span style={{ color: T.fgMuted, minWidth: 52 }}>{k}</span>
                <span style={{ color: T.blue, wordBreak: "break-all" }}>{v}</span>
              </div>
            ) : null)}
          </div>
        )}
      </div>

      {/* ── 日志流区 ── */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}
      >
        {filtered.length === 0 ? (
          <div style={{ padding: "16px 16px", color: T.fgMuted }}>
            Waiting for log output...
            <span style={{ animation: "blink 1.2s step-end infinite", display: "inline-block", marginLeft: 2 }}>▌</span>
          </div>
        ) : (
          filtered.map((line, i) => (
            <div
              key={`${line.ts}-${i}`}
              style={{ display: "flex", padding: "0 16px", lineHeight: 1.55 }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(177,186,196,.06)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              {/* 时间戳 */}
              <span style={{ color: T.fgMuted, flexShrink: 0, userSelect: "none", marginRight: 8, minWidth: 90 }}>
                {fmtTime(line.ts)}
              </span>
              {/* 级别 */}
              <span style={{ color: levelColor(line.level), flexShrink: 0, minWidth: 72, fontWeight: 600 }}>
                {(line.level || "INFO").padEnd(8)}
              </span>
              {/* 模块名 */}
              <span style={{ color: T.blue, flexShrink: 0, minWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginRight: 8 }}>
                {line.name}
              </span>
              {/* 消息 */}
              <span style={{ color: T.fg, wordBreak: "break-all", whiteSpace: "pre-wrap" }}>
                {line.msg}
              </span>
            </div>
          ))
        )}
        {/* 闪烁光标 */}
        {filtered.length > 0 && (
          <div style={{ padding: "0 16px", color: T.green }}>
            <span style={{ animation: "blink 1.2s step-end infinite" }}>▌</span>
          </div>
        )}
      </div>

      <style>{`
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>
    </div>
  );
}
