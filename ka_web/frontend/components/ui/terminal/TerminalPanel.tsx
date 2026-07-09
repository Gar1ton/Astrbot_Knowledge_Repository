"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * 终端日志面板容器：浮层/内嵌两种形态、触发按钮、滚动与跳转行为。
 *
 * 数据与过滤逻辑在 useTerminalLogs；工具栏与单行渲染分别在
 * TerminalToolbar / LogRow。本文件只负责组合与滚动交互。
 */
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Z } from "@/lib/zLayers";
import { useI18n } from "@/lib/i18n";
import { buildLogText } from "./format";
import { LogRow } from "./LogRow";
import { TerminalToolbar } from "./TerminalToolbar";
import { useTerminalLogs } from "./useTerminalLogs";

interface TerminalPanelProps {
  collapsed?: boolean;
  triggerLabel?: string;
  triggerTitle?: string;
  triggerIcon?: React.ReactNode;
  panelTitle?: string;
  variant?: "floating" | "embedded";
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
  const [autoScroll, setAutoScroll] = useState(true);
  const [newCount, setNewCount] = useState(0);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const newCountBaseRef = useRef(0);
  const errorJumpIndexRef = useRef(-1);
  const copiedTimerRef = useRef(0);
  const visible = embedded || open;
  const logs = useTerminalLogs(visible);

  const resolvedTriggerLabel = triggerLabel ?? t("terminal_trigger");
  const resolvedTriggerTitle = triggerTitle ?? t("terminal_trigger_title");
  const resolvedPanelTitle = panelTitle ?? t("terminal_panel_title");

  // 自动滚动：可见行变化时贴底。
  useEffect(() => {
    if (!autoScroll) return;
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [logs.visible, autoScroll]);

  // 上翻阅读时统计新到日志（"↓ N 条新日志" pill）。
  useEffect(() => {
    if (autoScroll) {
      newCountBaseRef.current = logs.appendedTotal;
      setNewCount(0);
    } else {
      setNewCount(logs.appendedTotal - newCountBaseRef.current);
    }
  }, [logs.appendedTotal, autoScroll]);

  // 浮层形态：点击面板外关闭。
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

  useEffect(() => () => window.clearTimeout(copiedTimerRef.current), []);

  function onScroll() {
    const node = scrollRef.current;
    if (!node) return;
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    setAutoScroll(distanceToBottom < 24);
  }

  function scrollToBottom() {
    setAutoScroll(true);
    window.requestAnimationFrame(() => {
      const node = scrollRef.current;
      if (node) node.scrollTop = node.scrollHeight;
    });
  }

  function toggleAutoScroll() {
    if (autoScroll) setAutoScroll(false);
    else scrollToBottom();
  }

  function jumpToNextError() {
    const node = scrollRef.current;
    if (!node) return;
    const errors = node.querySelectorAll<HTMLElement>('[data-loglevel="ERROR"]');
    if (errors.length === 0) return;
    errorJumpIndexRef.current = (errorJumpIndexRef.current + 1) % errors.length;
    setAutoScroll(false);
    errors[errorJumpIndexRef.current].scrollIntoView({ block: "center" });
  }

  async function copyVisible() {
    try {
      await navigator.clipboard.writeText(buildLogText(logs.visible));
      setCopied(true);
      window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard 不可用（非安全上下文）时静默失败，用户可改用下载。
    }
  }

  function downloadVisible() {
    const pad = (n: number) => String(n).padStart(2, "0");
    const d = new Date();
    const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    const blob = new Blob([buildLogText(logs.visible)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kr-terminal-${stamp}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const emptyText = !logs.available
    ? t("terminal_unavailable")
    : logs.loading && logs.visible.length === 0
      ? t("terminal_loading")
      : logs.visible.length === 0
        ? (logs.hasAnyLines ? t("terminal_no_match") : t("terminal_empty"))
        : null;

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
      <TerminalToolbar
        title={resolvedPanelTitle}
        levels={logs.levels}
        onToggleLevel={logs.toggleLevel}
        category={logs.category}
        categories={logs.categories}
        onCategoryChange={logs.setCategory}
        query={logs.query}
        onQueryChange={logs.setQuery}
        paused={logs.paused}
        onTogglePause={logs.togglePause}
        autoScroll={autoScroll}
        onToggleAutoScroll={toggleAutoScroll}
        errorCount={logs.errorCount}
        onJumpError={jumpToNextError}
        copied={copied}
        onCopy={copyVisible}
        onDownload={downloadVisible}
        onClear={logs.clear}
        loading={logs.loading}
        onRefresh={logs.refresh}
        onClose={embedded ? undefined : () => setOpen(false)}
      />

      <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
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
          {emptyText ? (
            <div
              style={{
                padding: "12px 16px",
                fontSize: 12,
                color: logs.available ? "var(--fg-subtle)" : "var(--danger)",
              }}
            >
              {emptyText}
            </div>
          ) : (
            logs.visible.map((line, index) => (
              <LogRow key={`${line.ts}:${line.name}:${index}`} line={line} />
            ))
          )}
        </div>

        {!autoScroll && newCount > 0 && (
          <button
            onClick={scrollToBottom}
            style={{
              position: "absolute",
              bottom: 12,
              left: "50%",
              transform: "translateX(-50%)",
              height: 26,
              padding: "0 12px",
              borderRadius: 13,
              border: "1px solid var(--accent-border)",
              background: "var(--accent-soft)",
              color: "var(--accent)",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "var(--font-sans)",
              fontWeight: 600,
              boxShadow: "var(--shadow-pop)",
              whiteSpace: "nowrap",
            }}
          >
            ↓ {t("terminal_new_logs", { n: newCount })}
          </button>
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
