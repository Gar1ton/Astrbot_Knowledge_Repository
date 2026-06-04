"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// ─── 类型 ──────────────────────────────────────────────────────

interface OpStat {
  count: number;
  avg_ms: number;
  p95_ms: number;
  last_ms: number;
}

interface MetricsSummary {
  ops: Record<string, OpStat>;
  total_records: number;
}

// ─── 延迟颜色编码 ─────────────────────────────────────────────

function latencyColor(ms: number): string {
  if (ms < 1000) return "var(--ok)";
  if (ms < 3000) return "var(--warn)";
  return "var(--danger)";
}

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

const OP_LABELS: [string, string][] = [
  ["embed_query",   "Embedding"],
  ["vector_search", "向量检索"],
  ["llm_generate",  "LLM 生成"],
  ["ask_total",     "Ask 全流程"],
];

function MiniBar({ ms, max }: { ms: number; max: number }) {
  const ratio = max > 0 ? Math.min(ms / max, 1) : 0;
  return (
    <div style={{ height: 4, borderRadius: 2, background: "var(--bg-inset)", overflow: "hidden", marginTop: 4 }}>
      <div style={{ height: "100%", width: `${ratio * 100}%`, background: latencyColor(ms), borderRadius: 2, transition: "width 0.4s ease" }} />
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────

interface PerfPanelProps {
  /** 折叠侧边栏模式：只显示图标，不显示文字 */
  collapsed?: boolean;
}

// ─── 主组件（内嵌于侧边栏，向右弹出面板） ─────────────────────

export function PerfPanel({ collapsed = false }: PerfPanelProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<MetricsSummary | null>(null);
  const [available, setAvailable] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch("/api/metrics");
      if (!res.ok) { setAvailable(false); return; }
      const json: MetricsSummary = await res.json();
      setData(json);
      setLastRefresh(new Date());
      setAvailable(true);
    } catch {
      setAvailable(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }
    fetchMetrics();
    timerRef.current = setInterval(fetchMetrics, 2000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [open, fetchMetrics]);

  // 点击面板外部时关闭
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!available) return null;

  const maxMs = data
    ? Math.max(...OP_LABELS.map(([op]) => data.ops[op]?.p95_ms ?? 0), 1)
    : 1;

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      {/* 触发按钮：样式跟 Rail 底部其他按钮一致 */}
      <button
        onClick={() => setOpen((v) => !v)}
        title="性能监控"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : undefined,
          gap: collapsed ? 0 : 8,
          width: "100%",
          padding: collapsed ? "8px" : "7px 10px",
          borderRadius: 10,
          fontSize: 13,
          color: open ? "var(--accent)" : "var(--fg-muted)",
          background: open ? "var(--accent-soft)" : "none",
          border: open ? "1px solid var(--accent-border)" : "1px solid transparent",
          cursor: "pointer",
          transition: "all 0.15s",
          textAlign: "left",
          fontFamily: "inherit",
        }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.background = "var(--surface-hover)";
        }}
        onMouseLeave={(e) => {
          if (!open) e.currentTarget.style.background = "none";
        }}
      >
        <span style={{ opacity: open ? 1 : 0.7, fontSize: 14 }}>⚡</span>
        {!collapsed && <span>性能监控</span>}
      </button>

      {/* 向右弹出的面板 — Portal 渲染到 body，绕开 Rail 的 overflow:hidden 裁切 */}
      {open && typeof document !== "undefined" && createPortal(
        <div
          style={{
            position: "fixed",
            bottom: 16,
            left: `calc(${collapsed ? "68px" : "var(--rail-w, 220px)"} + 8px)`,
            width: 252,
            background: "color-mix(in srgb, var(--surface) 92%, transparent)",
            backdropFilter: "saturate(1.3) blur(14px)",
            WebkitBackdropFilter: "saturate(1.3) blur(14px)",
            border: "1px solid var(--border)",
            borderRadius: 14,
            boxShadow: "var(--shadow-pop)",
            overflow: "hidden",
            zIndex: 9500,
            animation: "perfPanelIn 0.16s cubic-bezier(0.4,0,0.2,1) both",
          }}
        >
          {/* 标题栏 */}
          <div style={{ display: "flex", alignItems: "center", padding: "10px 14px 8px", borderBottom: "1px solid var(--border)", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em", color: "var(--fg-subtle)", textTransform: "uppercase", flex: 1 }}>
              ⚡ 性能监控
            </span>
            <button
              onClick={() => setOpen(false)}
              style={{ background: "none", border: "none", color: "var(--fg-subtle)", cursor: "pointer", padding: 2, display: "flex", alignItems: "center" }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          {/* 内容 */}
          <div style={{ padding: "10px 14px" }}>
            {data && data.total_records > 0 ? (
              <>
                {OP_LABELS.map(([op, label]) => {
                  const stat = data.ops[op];
                  if (!stat) return null;
                  return (
                    <div key={op} style={{ marginBottom: 8 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <span style={{ fontSize: 11, color: "var(--fg-muted)", fontWeight: 500 }}>{label}</span>
                        <span style={{ fontSize: 11, fontWeight: 700, color: latencyColor(stat.last_ms), fontVariantNumeric: "tabular-nums" }}>
                          {fmtMs(stat.last_ms)}
                        </span>
                      </div>
                      <MiniBar ms={stat.p95_ms} max={maxMs} />
                      <div style={{ fontSize: 9, color: "var(--fg-subtle)", marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
                        avg {fmtMs(stat.avg_ms)} · p95 {fmtMs(stat.p95_ms)} · ×{stat.count}
                      </div>
                    </div>
                  );
                })}
                {lastRefresh && (
                  <div style={{ fontSize: 9, color: "var(--fg-subtle)", textAlign: "right", borderTop: "1px solid var(--border)", paddingTop: 6 }}>
                    刷新于 {lastRefresh.toLocaleTimeString()}
                  </div>
                )}
              </>
            ) : (
              <div style={{ color: "var(--fg-subtle)", fontSize: 12, textAlign: "center", padding: "12px 0" }}>
                暂无监控数据
                <br />
                <span style={{ fontSize: 10 }}>发起一次 Ask 查询后即可看到指标</span>
              </div>
            )}
          </div>
          <style>{`
            @keyframes perfPanelIn {
              from { opacity: 0; transform: translateX(-6px) scale(0.97); }
              to   { opacity: 1; transform: translateX(0) scale(1); }
            }
          `}</style>
        </div>,
        document.body
      )}
    </div>
  );
}
