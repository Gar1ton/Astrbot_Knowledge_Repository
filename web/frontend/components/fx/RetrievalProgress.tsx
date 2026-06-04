"use client";
/* eslint-disable react-hooks/immutability, react-hooks/set-state-in-effect */

import React, { useEffect, useRef, useState } from "react";

// ─── 阶段颜色映射（冷→暖，呼应「升温」语义） ──────────────────────
const STAGE_COLORS: Record<string, string> = {
  embed_query:    "#4f46e5", // 深蓝：生成向量
  vector_search:  "#0ea5e9", // 青色：向量召回
  lightrag_context: "#8b5cf6", // 紫色：按需 LightRAG 上下文
  graph_expand:   "#8b5cf6", // 紫色：图谱扩展
  rrf_fusion:     "#0d9488", // 青绿：排名融合
  llm_generate:   "var(--accent)", // 暖橙：LLM 生成
  done:           "var(--ok)",     // 绿色：完成
};

function stageColor(stage: string): string {
  return STAGE_COLORS[stage] ?? STAGE_COLORS.embed_query;
}

// ─── 进度条组件 ───────────────────────────────────────────────────

interface RetrievalProgressProps {
  conversationId: string | null;
  active: boolean;
  onDone?: () => void;
}

interface ProgressState {
  stage: string;
  pct: number;
}

export function RetrievalProgress({ conversationId, active, onDone }: RetrievalProgressProps) {
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [visible, setVisible] = useState(false);
  const [fading, setFading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reducedMotion =
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false;

  useEffect(() => {
    if (!active || !conversationId) {
      stopPoll();
      return;
    }
    setVisible(true);
    setFading(false);
    setProgress({ stage: "embed_query", pct: 0 });
    startPoll(conversationId);
    return () => stopPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, conversationId]);

  function startPoll(cid: string) {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/ask/progress/${encodeURIComponent(cid)}`);
        if (!res.ok) return;
        const data: ProgressState = await res.json();
        setProgress(data);
        if (data.stage === "done") {
          stopPoll();
          scheduleHide();
          onDone?.();
        }
      } catch {
        // 网络错误时静默忽略
      }
    }, 250);
  }

  function stopPoll() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function scheduleHide() {
    if (reducedMotion) {
      setVisible(false);
      setProgress(null);
      return;
    }
    // 绿色脉冲 200ms → 淡出 600ms
    setTimeout(() => {
      setFading(true);
      setTimeout(() => {
        setVisible(false);
        setProgress(null);
        setFading(false);
      }, 600);
    }, 200);
  }

  if (!visible || !progress) return null;

  const color = stageColor(progress.stage);
  const pct = Math.max(0, Math.min(100, progress.pct));

  return (
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        bottom: 0,
        left: 0,
        right: 0,
        height: 3,
        pointerEvents: "none",
        zIndex: 10,
        opacity: fading ? 0 : 1,
        transition: fading ? "opacity 0.6s ease" : "none",
      }}
    >
      {/* 基础轨道 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "color-mix(in srgb, var(--border) 60%, transparent)",
        }}
      />
      {/* 进度填充 + 辉光 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          bottom: 0,
          width: `${pct}%`,
          background: color,
          filter: `drop-shadow(0 0 4px ${color}) drop-shadow(0 0 8px ${color})`,
          opacity: 0.9,
          transition: reducedMotion
            ? "none"
            : "width 0.3s cubic-bezier(0.4,0,0.2,1), background 0.4s ease, filter 0.4s ease",
        }}
      />
    </div>
  );
}
