"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// ─── 类型 ──────────────────────────────────────────────────────

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

// ─── 文件大小格式化 ───────────────────────────────────────────

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ─── Props ────────────────────────────────────────────────────

interface TerminalPanelProps {
  collapsed?: boolean;
}

// ─── 主组件 ───────────────────────────────────────────────────

export function TerminalPanel({ collapsed = false }: TerminalPanelProps) {
  const [open, setOpen] = useState(false);
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [curDir, setCurDir] = useState("");
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchSysInfo = useCallback(async () => {
    try {
      const r = await fetch("/api/system/info");
      if (!r.ok) { setAvailable(false); return; }
      setSysInfo(await r.json());
      setAvailable(true);
    } catch {
      setAvailable(false);
    }
  }, []);

  const fetchFiles = useCallback(async (dir: string) => {
    setLoading(true);
    try {
      const qs = dir ? `?dir=${encodeURIComponent(dir)}` : "";
      const r = await fetch(`/api/files/list${qs}`);
      if (r.ok) setFiles(await r.json());
    } catch { /* silent */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    fetchSysInfo();
    fetchFiles(curDir);
  }, [open, fetchSysInfo, fetchFiles, curDir]);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!available) return null;

  function drillInto(entry: FileEntry) {
    if (entry.type !== "dir") return;
    const next = curDir ? `${curDir}/${entry.name}` : entry.name;
    setCurDir(next);
    fetchFiles(next);
  }

  function goUp() {
    const parts = curDir.split("/").filter(Boolean);
    parts.pop();
    const parent = parts.join("/");
    setCurDir(parent);
    fetchFiles(parent);
  }

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      {/* 触发按钮：与 Rail 底部其他按钮风格一致 */}
      <button
        onClick={() => setOpen((v) => !v)}
        title="调试 · 运行目录"
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
        <span style={{ opacity: open ? 1 : 0.7, fontFamily: "var(--font-geist-mono, monospace)", fontSize: 12 }}>
          {">_"}
        </span>
        {!collapsed && <span>运行目录</span>}
      </button>

      {/* 向右弹出面板 — Portal 渲染到 body，绕开 Rail overflow:hidden 裁切 */}
      {open && typeof document !== "undefined" && createPortal(
        <div
          style={{
            position: "fixed",
            bottom: 56,
            left: collapsed ? 68 : "var(--rail-w, 220px)",
            width: 300,
            maxHeight: "70vh",
            display: "flex",
            flexDirection: "column",
            background: "color-mix(in srgb, var(--surface) 92%, transparent)",
            backdropFilter: "saturate(1.3) blur(14px)",
            WebkitBackdropFilter: "saturate(1.3) blur(14px)",
            border: "1px solid var(--border)",
            borderRadius: 14,
            boxShadow: "var(--shadow-pop)",
            overflow: "hidden",
            zIndex: 9500,
            animation: "terminalIn 0.16s cubic-bezier(0.4,0,0.2,1) both",
          }}
        >
          {/* 标题栏 */}
          <div style={{ display: "flex", alignItems: "center", padding: "10px 14px 8px", borderBottom: "1px solid var(--border)", gap: 6, flexShrink: 0 }}>
            <span style={{ fontFamily: "var(--font-geist-mono, monospace)", fontSize: 11, color: "var(--fg-subtle)", flex: 1 }}>
              &gt;_ 运行目录
            </span>
            <button
              onClick={() => { fetchSysInfo(); fetchFiles(curDir); }}
              title="刷新"
              style={{ background: "none", border: "none", color: "var(--fg-subtle)", cursor: "pointer", padding: 2, display: "flex", alignItems: "center", fontSize: 12 }}
            >
              ↺
            </button>
            <button
              onClick={() => setOpen(false)}
              style={{ background: "none", border: "none", color: "var(--fg-subtle)", cursor: "pointer", padding: 2, display: "flex", alignItems: "center" }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          {/* 路径卡片 */}
          {sysInfo && (
            <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
              {[
                ["工作目录", sysInfo.cwd],
                ["数据目录", sysInfo.data_dir],
                ["数据库", sysInfo.db_file],
                ["Python", sysInfo.python_version],
              ].map(([label, value]) => (
                <div key={label} style={{ display: "flex", gap: 6, fontSize: 11, lineHeight: 1.7 }}>
                  <span style={{ color: "var(--fg-subtle)", minWidth: 56, flexShrink: 0 }}>{label}</span>
                  <span style={{ color: "var(--fg)", fontFamily: "var(--font-geist-mono, monospace)", fontSize: 10, wordBreak: "break-all" }}>{value}</span>
                </div>
              ))}
            </div>
          )}

          {/* 文件列表 */}
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
            {/* 面包屑 */}
            <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 14px 6px", fontSize: 11, color: "var(--fg-subtle)" }}>
              <button
                onClick={() => { setCurDir(""); fetchFiles(""); }}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--accent)", fontSize: 11, padding: 0, fontFamily: "inherit" }}
              >
                data/
              </button>
              {curDir.split("/").filter(Boolean).map((seg, i, arr) => {
                const path = arr.slice(0, i + 1).join("/");
                return (
                  <React.Fragment key={path}>
                    <span>/</span>
                    <button
                      onClick={() => { setCurDir(path); fetchFiles(path); }}
                      style={{ background: "none", border: "none", cursor: "pointer", color: i === arr.length - 1 ? "var(--fg)" : "var(--accent)", fontSize: 11, padding: 0, fontFamily: "inherit" }}
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
                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "5px 14px", background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--fg-muted)", fontFamily: "inherit", textAlign: "left" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
              >
                <span style={{ fontSize: 14 }}>↑</span>
                <span>..</span>
              </button>
            )}

            {loading ? (
              <div style={{ padding: "12px 14px", fontSize: 12, color: "var(--fg-subtle)" }}>加载中...</div>
            ) : files?.entries.map((entry) => (
              <button
                key={entry.name}
                onClick={() => drillInto(entry)}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  width: "100%", padding: "5px 14px",
                  background: "none", border: "none",
                  cursor: entry.type === "dir" ? "pointer" : "default",
                  fontSize: 12, fontFamily: "inherit", textAlign: "left",
                }}
                onMouseEnter={(e) => { if (entry.type === "dir") e.currentTarget.style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
              >
                <span style={{ fontSize: 14, flexShrink: 0 }}>{entry.type === "dir" ? "📁" : "📄"}</span>
                <span style={{ flex: 1, color: entry.type === "dir" ? "var(--accent)" : "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {entry.name}
                </span>
                {entry.type === "file" && (
                  <span style={{ fontSize: 10, color: "var(--fg-subtle)", flexShrink: 0 }}>{fmtSize(entry.size_bytes)}</span>
                )}
              </button>
            ))}

            {!loading && files?.entries.length === 0 && (
              <div style={{ padding: "12px 14px", fontSize: 12, color: "var(--fg-subtle)" }}>目录为空</div>
            )}
          </div>
          <style>{`
            @keyframes terminalIn {
              from { opacity: 0; transform: translateX(-6px) scale(0.97); }
              to   { opacity: 1; transform: translateX(0) scale(1); }
            }`}
          </style>
        </div>,
        document.body
      )}

    </div>
  );
}
