"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Z } from "@/lib/zLayers";
import { getLogs, type LogLine } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface TerminalPanelProps {
  collapsed?: boolean;
  triggerLabel?: string;
  triggerTitle?: string;
  triggerIcon?: React.ReactNode;
  panelTitle?: string;
  variant?: "floating" | "embedded";
}

const LOG_LIMIT = 200;
const POLL_MS = 2500;

function formatTime(ts: number): string {
  if (!Number.isFinite(ts)) return "--:--:--";
  return new Date(ts * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function levelColor(level: string): string {
  const normalized = level.toUpperCase();
  if (normalized === "ERROR" || normalized === "CRITICAL") return "var(--danger)";
  if (normalized === "WARNING" || normalized === "WARN") return "var(--warn)";
  if (normalized === "DEBUG") return "var(--fg-subtle)";
  return "var(--accent)";
}

function rowKey(line: LogLine, index: number): string {
  return `${line.ts}:${line.level}:${line.name}:${index}`;
}

function sourceLabel(line: LogLine): string {
  return line.category || line.source || line.name || "log";
}

export function TerminalPanel({
  collapsed = false,
  triggerLabel,
  triggerTitle,
  triggerIcon,
  panelTitle,
  variant = "floating",
}: TerminalPanelProps) {
  const { t } = useI18n();
  const embedded = variant === "embedded";
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTsRef = useRef(0);
  const loadInFlightRef = useRef(false);
  const visible = embedded || open;

  const resolvedTriggerLabel = triggerLabel ?? t("terminal_trigger");
  const resolvedTriggerTitle = triggerTitle ?? t("terminal_trigger_title");
  const resolvedPanelTitle = panelTitle ?? t("terminal_panel_title");

  const loadLogs = useCallback(async (mode: "replace" | "append") => {
    if (mode === "replace") setLoading(true);
    if (loadInFlightRef.current) {
      if (mode === "replace") setLoading(false);
      return;
    }
    loadInFlightRef.current = true;
    try {
      const after = mode === "append" ? lastTsRef.current : 0;
      const result = await getLogs(after, LOG_LIMIT);
      setAvailable(true);
      if (result.lines.length > 0) {
        lastTsRef.current = Math.max(lastTsRef.current, ...result.lines.map((line) => line.ts));
      }
      setLines((prev) => {
        if (mode === "replace") return result.lines;
        if (result.lines.length === 0) return prev;
        return [...prev, ...result.lines].slice(-LOG_LIMIT);
      });
    } catch {
      setAvailable(false);
    } finally {
      loadInFlightRef.current = false;
      if (mode === "replace") setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    loadLogs("replace");
  }, [visible, loadLogs]);

  useEffect(() => {
    if (!visible) return;
    const timer = window.setInterval(() => {
      loadLogs("append");
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [visible, loadLogs]);

  useEffect(() => {
    if (!autoScroll) return;
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [lines, autoScroll]);

  useEffect(() => {
    if (embedded || !open) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (
        !containerRef.current?.contains(target)
        && !panelRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [embedded, open]);

  function refresh() {
    loadLogs("replace");
  }

  function clearVisibleLogs() {
    setLines([]);
  }

  function onScroll() {
    const node = scrollRef.current;
    if (!node) return;
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    setAutoScroll(distanceToBottom < 24);
  }

  function toggleAutoScroll() {
    setAutoScroll((next) => {
      const enabled = !next;
      if (enabled) {
        window.requestAnimationFrame(() => {
          const node = scrollRef.current;
          if (node) node.scrollTop = node.scrollHeight;
        });
      }
      return enabled;
    });
  }

  const actionButtonStyle: React.CSSProperties = {
    height: 26,
    padding: "0 8px",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--border)",
    background: "var(--surface)",
    color: "var(--fg-muted)",
    cursor: "pointer",
    fontSize: 11,
    fontFamily: "var(--font-sans)",
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
  };

  const panel = (
    <div
      ref={panelRef}
      style={{
        position: embedded ? "relative" : "fixed",
        bottom: embedded ? undefined : 16,
        left: embedded ? undefined : collapsed ? 64 : "calc(var(--rail-w, 220px) + 12px)",
        width: embedded
          ? "100%"
          : collapsed
            ? "min(760px, calc(100vw - 84px))"
            : "min(760px, calc(100vw - var(--rail-w, 220px) - 36px))",
        height: embedded ? "100%" : "min(76vh, 680px)",
        minHeight: embedded ? 0 : 420,
        display: "flex",
        flexDirection: "column",
        background: embedded
          ? "var(--surface)"
          : "color-mix(in srgb, var(--surface) 92%, transparent)",
        backdropFilter: embedded ? undefined : "saturate(1.3) blur(14px)",
        WebkitBackdropFilter: embedded ? undefined : "saturate(1.3) blur(14px)",
        border: "1px solid var(--border)",
        borderRadius: embedded ? "var(--radius-xl)" : 14,
        boxShadow: embedded ? "var(--shadow-card)" : "var(--shadow-pop)",
        overflow: "hidden",
        zIndex: embedded ? undefined : Z.panel,
        animation: embedded ? undefined : "terminalIn 0.16s cubic-bezier(0.4,0,0.2,1) both",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "10px 12px 10px 16px",
          borderBottom: "1px solid var(--border)",
          gap: 8,
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--fg-muted)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {resolvedPanelTitle}
        </span>
        <button onClick={toggleAutoScroll} title={t("terminal_auto_scroll")} style={{
          ...actionButtonStyle,
          color: autoScroll ? "var(--accent)" : "var(--fg-muted)",
          borderColor: autoScroll ? "var(--accent-border)" : "var(--border)",
          background: autoScroll ? "var(--accent-soft)" : "var(--surface)",
        }}>
          {t("terminal_auto_scroll_short")}
        </button>
        <button onClick={clearVisibleLogs} title={t("terminal_clear")} style={actionButtonStyle}>
          {t("terminal_clear")}
        </button>
        <button onClick={refresh} title={t("terminal_refresh")} style={actionButtonStyle}>
          {loading ? "..." : t("terminal_refresh")}
        </button>
        {!embedded && (
          <button
            onClick={() => setOpen(false)}
            title={t("btn_close")}
            style={{
              background: "none",
              border: "none",
              color: "var(--fg-subtle)",
              cursor: "pointer",
              padding: 4,
              display: "flex",
              alignItems: "center",
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "10px 0",
          background: "color-mix(in srgb, var(--bg-inset) 64%, transparent)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {!available ? (
          <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--danger)" }}>
            {t("terminal_unavailable")}
          </div>
        ) : loading && lines.length === 0 ? (
          <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--fg-subtle)" }}>
            {t("terminal_loading")}
          </div>
        ) : lines.length === 0 ? (
          <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--fg-subtle)" }}>
            {t("terminal_empty")}
          </div>
        ) : (
          lines.map((line, index) => (
            <div
              key={rowKey(line, index)}
              style={{
                display: "grid",
                gridTemplateColumns: "76px 76px 104px minmax(0, 1fr)",
                gap: 10,
                alignItems: "start",
                padding: "4px 16px",
                borderBottom: "1px solid color-mix(in srgb, var(--border) 42%, transparent)",
                fontSize: 11,
                lineHeight: 1.5,
              }}
            >
              <span style={{ color: "var(--fg-subtle)", whiteSpace: "nowrap" }}>
                {formatTime(line.ts)}
              </span>
              <span style={{ color: levelColor(line.level), fontWeight: 700, whiteSpace: "nowrap" }}>
                {line.level || "INFO"}
              </span>
              <span
                title={line.name}
                style={{
                  color: "var(--fg-muted)",
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {sourceLabel(line)}
              </span>
              <span
                style={{
                  color: "var(--fg)",
                  minWidth: 0,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {line.msg}
              </span>
            </div>
          ))
        )}
      </div>

      <style>{`
        @keyframes terminalIn {
          from { opacity: 0; transform: translateX(-6px) scale(0.97); }
          to   { opacity: 1; transform: translateX(0) scale(1); }
        }
      `}</style>
    </div>
  );

  if (embedded) {
    return (
      <div ref={containerRef} style={{ position: "relative", height: "100%", minHeight: 0 }}>
        {panel}
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={resolvedTriggerTitle}
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
        onMouseEnter={(e) => { if (!open) e.currentTarget.style.background = "var(--surface-hover)"; }}
        onMouseLeave={(e) => { if (!open) e.currentTarget.style.background = "none"; }}
      >
        <span
          style={{
            opacity: open ? 1 : 0.7,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            display: "inline-flex",
          }}
        >
          {triggerIcon ?? ">_"}
        </span>
        {!collapsed && <span>{resolvedTriggerLabel}</span>}
      </button>

      {open && typeof document !== "undefined" && createPortal(panel, document.body)}
    </div>
  );
}
