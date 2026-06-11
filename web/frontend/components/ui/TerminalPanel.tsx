"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface SystemInfo {
  cwd: string;
  data_dir: string;
  db_file: string;
  docs_dir: string;
  python_version: string;
  platform: string;
}

interface FileEntry {
  name: string;
  type: "file" | "dir";
  size_bytes: number | null;
  modified_at: string | null;
}

interface FileList {
  path: string;
  entries: FileEntry[];
}

interface TerminalPanelProps {
  collapsed?: boolean;
  triggerLabel?: string;
  triggerTitle?: string;
  triggerIcon?: React.ReactNode;
  panelTitle?: string;
  variant?: "floating" | "embedded";
}

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function TerminalPanel({
  collapsed = false,
  triggerLabel = "运行目录",
  triggerTitle = "调试 · 运行目录",
  triggerIcon,
  panelTitle = ">_ 运行目录",
  variant = "floating",
}: TerminalPanelProps) {
  const embedded = variant === "embedded";
  const [open, setOpen] = useState(false);
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [curDir, setCurDir] = useState("");
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const visible = embedded || open;

  const fetchSysInfo = useCallback(async () => {
    try {
      const response = await fetch("/api/system/info");
      if (!response.ok) {
        setAvailable(false);
        return;
      }
      setSysInfo(await response.json());
      setAvailable(true);
    } catch {
      setAvailable(false);
    }
  }, []);

  const fetchFiles = useCallback(async (dir: string) => {
    setLoading(true);
    try {
      const qs = dir ? `?dir=${encodeURIComponent(dir)}` : "";
      const response = await fetch(`/api/files/list${qs}`);
      if (response.ok) {
        setFiles(await response.json());
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    fetchSysInfo();
    fetchFiles(curDir);
  }, [visible, fetchSysInfo, fetchFiles, curDir]);

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
    fetchSysInfo();
    fetchFiles(curDir);
  }

  function drillInto(entry: FileEntry) {
    if (entry.type !== "dir") return;
    setCurDir(curDir ? `${curDir}/${entry.name}` : entry.name);
  }

  function goRoot() {
    setCurDir("");
  }

  function goUp() {
    const parts = curDir.split("/").filter(Boolean);
    parts.pop();
    setCurDir(parts.join("/"));
  }

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
            ? "min(720px, calc(100vw - 84px))"
            : "min(720px, calc(100vw - var(--rail-w, 220px) - 36px))",
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
        zIndex: embedded ? undefined : 9500,
        animation: embedded ? undefined : "terminalIn 0.16s cubic-bezier(0.4,0,0.2,1) both",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "12px 16px 10px",
          borderBottom: "1px solid var(--border)",
          gap: 8,
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-geist-mono, monospace)",
            fontSize: 12,
            color: "var(--fg-muted)",
            flex: 1,
          }}
        >
          {panelTitle}
        </span>
        <button
          onClick={refresh}
          title="刷新"
          style={{
            background: "none",
            border: "none",
            color: "var(--fg-subtle)",
            cursor: "pointer",
            padding: 4,
            display: "flex",
            alignItems: "center",
            fontSize: 13,
          }}
        >
          ↻
        </button>
        {!embedded && (
          <button
            onClick={() => setOpen(false)}
            title="关闭"
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

      {!available ? (
        <div style={{ padding: 16, fontSize: 12, color: "var(--fg-subtle)" }}>
          运行目录接口暂不可用
        </div>
      ) : (
        <>
          {sysInfo && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: "8px 14px",
                padding: "12px 16px",
                borderBottom: "1px solid var(--border)",
                flexShrink: 0,
              }}
            >
              {[
                ["工作目录", sysInfo.cwd],
                ["数据目录", sysInfo.data_dir],
                ["数据库", sysInfo.db_file],
                ["Python", `${sysInfo.python_version} · ${sysInfo.platform}`],
              ].map(([label, value]) => (
                <div key={label} style={{ minWidth: 0 }}>
                  <div style={{ color: "var(--fg-subtle)", fontSize: 10, marginBottom: 2 }}>
                    {label}
                  </div>
                  <div
                    style={{
                      color: "var(--fg)",
                      fontFamily: "var(--font-geist-mono, monospace)",
                      fontSize: 11,
                      lineHeight: 1.45,
                      wordBreak: "break-all",
                    }}
                  >
                    {value}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 0" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "0 16px 8px",
                fontSize: 11,
                color: "var(--fg-subtle)",
              }}
            >
              <button
                onClick={goRoot}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--accent)",
                  fontSize: 11,
                  padding: 0,
                  fontFamily: "inherit",
                  fontWeight: 700,
                }}
              >
                data/
              </button>
              {curDir.split("/").filter(Boolean).map((seg, i, arr) => {
                const path = arr.slice(0, i + 1).join("/");
                return (
                  <React.Fragment key={path}>
                    <span>/</span>
                    <button
                      onClick={() => setCurDir(path)}
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        color: i === arr.length - 1 ? "var(--fg)" : "var(--accent)",
                        fontSize: 11,
                        padding: 0,
                        fontFamily: "inherit",
                        fontWeight: i === arr.length - 1 ? 700 : 500,
                      }}
                    >
                      {seg}
                    </button>
                  </React.Fragment>
                );
              })}
            </div>

            {curDir && (
              <button
                onClick={goUp}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  padding: "7px 16px",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 12,
                  color: "var(--fg-muted)",
                  fontFamily: "inherit",
                  textAlign: "left",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
              >
                <span style={{ fontSize: 14 }}>↑</span>
                <span>..</span>
              </button>
            )}

            {loading ? (
              <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--fg-subtle)" }}>
                加载中...
              </div>
            ) : (files?.entries ?? []).map((entry) => (
              <button
                key={entry.name}
                onClick={() => drillInto(entry)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  padding: "7px 16px",
                  background: "none",
                  border: "none",
                  cursor: entry.type === "dir" ? "pointer" : "default",
                  fontSize: 12,
                  fontFamily: "inherit",
                  textAlign: "left",
                  minHeight: 34,
                }}
                onMouseEnter={(e) => { if (entry.type === "dir") e.currentTarget.style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
              >
                <span style={{ fontSize: 14, flexShrink: 0 }}>{entry.type === "dir" ? "📁" : "📄"}</span>
                <span
                  style={{
                    flex: 1,
                    color: entry.type === "dir" ? "var(--accent)" : "var(--fg)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {entry.name}
                </span>
                {entry.type === "file" && (
                  <span style={{ fontSize: 10, color: "var(--fg-subtle)", flexShrink: 0 }}>
                    {fmtSize(entry.size_bytes)}
                  </span>
                )}
              </button>
            ))}

            {!loading && files?.entries.length === 0 && (
              <div style={{ padding: "12px 16px", fontSize: 12, color: "var(--fg-subtle)" }}>
                目录为空
              </div>
            )}
          </div>
        </>
      )}

      <style>{`
        @keyframes terminalIn {
          from { opacity: 0; transform: translateX(-6px) scale(0.97); }
          to   { opacity: 1; transform: translateX(0) scale(1); }
        }`}
      </style>
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
        title={triggerTitle}
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
            fontFamily: "var(--font-geist-mono, monospace)",
            fontSize: 12,
            display: "inline-flex",
          }}
        >
          {triggerIcon ?? ">_"}
        </span>
        {!collapsed && <span>{triggerLabel}</span>}
      </button>

      {open && typeof document !== "undefined" && createPortal(panel, document.body)}
    </div>
  );
}
