"use client";

// 统一进度面板（左下角浮动停靠）。
//
// 为什么存在：Milvus 构建、LightRAG 图谱、Zotero 同步、文档摄入原本各自散落（FilePanel 内卡片、
// 未挂载的 BuildWidget、纯 spinner）。本组件聚合四类后台任务的 `/active` 轮询，统一成一个可收起/展开、
// 空闲时完全隐藏、优先于 Modal（低于 Toast）的浮动停靠面板。泛化自 `components/build/BuildWidget.tsx`。

import React, { useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  cancelBuildJob,
  getActiveBuildJob,
  getActiveIngestJob,
  getActiveMilvusBuildJob,
  getActiveNotionSyncJob,
  getActiveZoteroSyncJob,
  pauseBuildJob,
  resumeBuildJob,
} from "@/lib/api";
import { I18nContext } from "@/lib/i18n";
import { useConsole } from "@/lib/ConsoleContext";
import { Z } from "@/lib/zLayers";
import { useToast } from "@/components/ui/Toast";

// ─── 归一化模型 ───────────────────────────────────────────────

type DockKind = "zotero_sync" | "notion_sync" | "milvus_build" | "graph_build" | "ingest";

interface DockJob {
  key: string;
  kind: DockKind;
  jobId: string;
  label: string;
  sub: string; // stage_label / collection / title
  pct: number | null;
  detail: string; // 计数明细行
  status: string;
  active: boolean;
  paused: boolean;
  recentError: string;
  collection: string; // graph 行的暂停/跳转需要
}

const POLL_ACTIVE_MS = 1200;
const POLL_IDLE_MS = 3000;

function pctOf(percent: number | null | undefined): number | null {
  return typeof percent === "number" && percent >= 0 ? Math.min(100, Math.round(percent)) : null;
}

// ─── 轮询 hook：四源并行拉取并归一化 ──────────────────────────

function useProgressJobs(): DockJob[] {
  const { t } = useContext(I18nContext);
  const { toast } = useToast();
  const [jobs, setJobs] = useState<DockJob[]>([]);
  const anyActiveRef = useRef(false);
  const notifiedZoteroRef = useRef<Set<string>>(new Set());
  const notifiedNotionRef = useRef<Set<string>>(new Set());
  // 单次轮询请求超时/网络抖动不代表任务已结束：失败的那一路沿用上次成功值，
  // 避免后端短暂阻塞（如同步期间的 PDF 解析）把整个面板闪没。
  const lastRef = useRef<{
    zotero: Awaited<ReturnType<typeof getActiveZoteroSyncJob>>;
    notion: Awaited<ReturnType<typeof getActiveNotionSyncJob>>;
    milvus: Awaited<ReturnType<typeof getActiveMilvusBuildJob>>;
    graph: Awaited<ReturnType<typeof getActiveBuildJob>>;
    ingest: Awaited<ReturnType<typeof getActiveIngestJob>>;
  }>({ zotero: null, notion: null, milvus: null, graph: null, ingest: null });

  const poll = useCallback(async () => {
    const [zoteroResult, notionResult, milvusResult, graphResult, ingestResult] =
      await Promise.allSettled([
        getActiveZoteroSyncJob(),
        getActiveNotionSyncJob(),
        getActiveMilvusBuildJob(),
        getActiveBuildJob(),
        getActiveIngestJob(),
      ]);
    const last = lastRef.current;
    const zotero = zoteroResult.status === "fulfilled" ? zoteroResult.value : last.zotero;
    const notion = notionResult.status === "fulfilled" ? notionResult.value : last.notion;
    const milvus = milvusResult.status === "fulfilled" ? milvusResult.value : last.milvus;
    const graph = graphResult.status === "fulfilled" ? graphResult.value : last.graph;
    const ingest = ingestResult.status === "fulfilled" ? ingestResult.value : last.ingest;
    lastRef.current = { zotero, notion, milvus, graph, ingest };
    const next: DockJob[] = [];

    if (zotero) {
      if (zotero.status !== "running") {
        const notifyKey = `${zotero.job_id}:${zotero.status}`;
        if (!notifiedZoteroRef.current.has(notifyKey)) {
          notifiedZoteroRef.current.add(notifyKey);
          if (zotero.status === "success") toast(t("zotero_sync_done"), "ok");
          else if (zotero.status === "partial_failure") {
            toast(zotero.recent_error || t("zotero_sync_partial"), "error");
          } else if (zotero.status === "error") {
            toast(zotero.recent_error || t("zotero_sync_failed"), "error");
          }
        }
      }
      // 增量同步里，未变化文档会被跳过（skipped_unchanged），后端 progress_percent() 已把它计入完成度；
      // 这里的分子同口径纳入 skipped/failed，否则百分比条前进但计数不动，看起来像卡死。
      const zoteroDone =
        (zotero.docs_processed ?? 0) + (zotero.docs_failed ?? 0) + (zotero.skipped_unchanged ?? 0);
      next.push({
        key: `zotero_sync:${zotero.job_id}`,
        kind: "zotero_sync",
        jobId: zotero.job_id,
        label: t("progress_dock_zotero"),
        sub: zotero.stage_label || zotero.stage || "",
        pct: pctOf(zotero.progress_percent),
        detail: `${zoteroDone}/${zotero.docs_total ?? 0} docs · +${zotero.new ?? 0} ~${zotero.changed ?? 0} · ${zotero.skipped_unchanged ?? 0} skipped`,
        status: zotero.status,
        active: zotero.status === "running",
        paused: false,
        recentError: zotero.recent_error || "",
        collection: "",
      });
    }
    if (notion) {
      if (notion.status !== "running") {
        const notifyKey = `${notion.job_id}:${notion.status}`;
        if (!notifiedNotionRef.current.has(notifyKey)) {
          notifiedNotionRef.current.add(notifyKey);
          if (notion.status === "success") toast(t("notion_sync_done"), "ok");
          else if (notion.status === "partial_failure") {
            toast(notion.recent_error || t("notion_sync_partial"), "error");
          } else if (notion.status === "error") {
            toast(notion.recent_error || t("notion_sync_failed"), "error");
          }
        }
      }
      const notionDone = notion.docs_processed ?? 0;
      const prunedBits = notion.tags_pruned ? ` · ${notion.tags_pruned} tags` : "";
      next.push({
        key: `notion_sync:${notion.job_id}`,
        kind: "notion_sync",
        jobId: notion.job_id,
        label: t("progress_dock_notion"),
        sub: notion.stage_label || notion.stage || "",
        pct: pctOf(notion.progress_percent),
        detail: `${notionDone}/${notion.docs_total ?? 0} docs · +${notion.docs_created ?? 0} ~${notion.docs_updated ?? 0} · ${notion.docs_archived ?? 0} arch${prunedBits}`,
        status: notion.status,
        active: notion.status === "running",
        paused: false,
        recentError: notion.recent_error || "",
        collection: "",
      });
    }
    if (milvus) {
      next.push({
        key: `milvus_build:${milvus.job_id}`,
        kind: "milvus_build",
        jobId: milvus.job_id,
        label: t("progress_dock_milvus"),
        sub: milvus.stage_label || milvus.stage || "",
        pct: pctOf(milvus.progress_percent),
        detail: `${milvus.processed_docs ?? 0}/${milvus.total_docs ?? 0} docs${milvus.failed_docs ? ` · ${milvus.failed_docs} failed` : ""}`,
        status: milvus.status,
        active: milvus.status === "running",
        paused: false,
        recentError: milvus.recent_error || "",
        collection: "",
      });
    }
    if (graph) {
      const gpct =
        pctOf(graph.progress_percent) ??
        (graph.total_chunks && graph.total_chunks > 0
          ? Math.round(((graph.processed_chunks ?? 0) / graph.total_chunks) * 100)
          : null);
      next.push({
        key: `graph_build:${graph.job_id}`,
        kind: "graph_build",
        jobId: graph.job_id,
        label: t("progress_dock_graph"),
        sub: graph.progress_label || graph.stage || graph.collection || "",
        pct: gpct,
        detail:
          graph.processed_chunks != null && graph.total_chunks
            ? `${graph.processed_chunks}/${graph.total_chunks} chunks`
            : graph.collection || "",
        status: graph.status,
        active:
          ["queued", "running", "pause_requested", "paused", "waiting_agent"].includes(
            graph.status
          ) || !!graph.paused,
        paused: !!graph.paused,
        recentError: graph.recent_error || "",
        collection: graph.collection || "",
      });
    }
    if (ingest) {
      next.push({
        key: `ingest:${ingest.job_id}`,
        kind: "ingest",
        jobId: ingest.job_id,
        label: t("progress_dock_ingest"),
        sub: ingest.stage_label || ingest.stage || "",
        pct: pctOf(ingest.progress_percent),
        detail: ingest.title || "",
        status: ingest.status,
        active: ingest.status === "running",
        paused: false,
        recentError: ingest.recent_error || "",
        collection: "",
      });
    }

    anyActiveRef.current = next.some((j) => j.active);
    setJobs(next);
  }, [t, toast]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (cancelled) return;
      try {
        await poll();
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, anyActiveRef.current ? POLL_ACTIVE_MS : POLL_IDLE_MS);
        }
      }
    }
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [poll]);

  return jobs;
}

// ─── 组件 ─────────────────────────────────────────────────────

export function ProgressDock() {
  const { t } = useContext(I18nContext);
  const { setWorkflowOpen } = useConsole();
  const jobs = useProgressJobs();
  const [collapsed, setCollapsed] = useState(false);

  // 不提供手动关闭：面板只随后台任务存在与否自动出现/消失（任务达终态后由 /active 短暂展示再返回
  // null，见 api.get_active_zotero_sync_job），保证「任务成功后才结束」，用户只能收起/展开。
  if (jobs.length === 0) return null;

  return (
    <div
      className="fx-glass"
      style={{
        position: "fixed",
        bottom: 20,
        left: 20,
        zIndex: Z.progressDock,
        width: 300,
        borderRadius: "var(--radius-3xl)",
        padding: "10px 12px",
        boxShadow: "var(--shadow-pop)",
        border: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: collapsed ? 0 : 8,
      }}
    >
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "展开" : "收起"}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "var(--fg-muted)", fontSize: 11, lineHeight: 1, padding: 0,
            transform: collapsed ? "rotate(-90deg)" : "none", transition: "transform 0.15s",
          }}
        >
          ▼
        </button>
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--fg)", flex: 1 }}>
          {t("progress_dock_title")}
          <span style={{ marginLeft: 6, color: "var(--fg-muted)", fontWeight: 500 }}>
            ({jobs.length})
          </span>
        </span>
      </div>

      {/* rows */}
      {!collapsed &&
        jobs.map((job) => (
          <ProgressRow key={job.key} job={job} onGotoGraph={() => setWorkflowOpen(true)} />
        ))}

      <style>{`
        @keyframes progressDockPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
      `}</style>
    </div>
  );
}

// ─── 单行 ─────────────────────────────────────────────────────

function ProgressRow({
  job,
  onGotoGraph,
}: {
  job: DockJob;
  onGotoGraph: () => void;
}) {
  const { t } = useContext(I18nContext);
  const { toast } = useToast();
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const terminal = job.status === "error" || job.status === "partial_failure";
  const color = job.status === "error"
    ? "var(--danger)"
    : job.paused
    ? "var(--warn)"
    : terminal
    ? "var(--warn)"
    : "var(--accent)";

  async function handlePause() {
    try { await pauseBuildJob(job.jobId); } catch { /* ignore */ }
  }
  async function handleResume() {
    try { await resumeBuildJob(job.jobId); } catch { /* ignore */ }
  }
  async function handleCancelConfirmed() {
    setCancelling(true);
    try {
      await cancelBuildJob(job.jobId, true);
      toast(t("build_widget_cancel_success"), "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : t("build_widget_cancel_error"), "error");
    } finally {
      setCancelling(false);
      setConfirmingCancel(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {job.active && !job.paused && (
          <span
            style={{
              width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0,
              animation: "progressDockPulse 1.4s ease-in-out infinite",
            }}
          />
        )}
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg)" }}>{job.label}</span>
        <span
          style={{
            fontSize: 10, color: "var(--fg-muted)", flex: 1, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
          title={job.sub}
        >
          {job.sub}
        </span>
        {job.pct != null && (
          <span style={{ fontSize: 10, color: "var(--fg-muted)" }}>{job.pct}%</span>
        )}
      </div>

      <div style={{ height: 4, borderRadius: "var(--radius-pill)", background: "var(--border)", overflow: "hidden" }}>
        <div
          style={{
            height: "100%", width: job.pct != null ? `${job.pct}%` : "30%",
            background: color, borderRadius: "var(--radius-pill)", transition: "width 0.4s ease",
            opacity: job.pct != null ? 1 : 0.5,
          }}
        />
      </div>

      {job.detail && (
        <span style={{ fontSize: 10, color: "var(--fg-subtle)" }}>{job.detail}</span>
      )}
      {job.recentError && (
        <span style={{ fontSize: 10, color: "var(--danger)", wordBreak: "break-word" }}>
          {job.recentError.slice(0, 120)}
        </span>
      )}

      {job.kind === "graph_build" && job.active && confirmingCancel && (
        <div
          style={{
            fontSize: 10, color: "var(--fg-muted)", background: "var(--surface)",
            border: "1px solid var(--border)", borderRadius: 8, padding: "6px 8px",
            display: "flex", flexDirection: "column", gap: 6,
          }}
        >
          <span>{t("build_widget_cancel_confirm_body")}</span>
          <div style={{ display: "flex", gap: 6 }}>
            <RowButton
              onClick={handleCancelConfirmed}
              label={cancelling ? t("build_widget_cancelling") : t("build_widget_cancel_confirm_yes")}
              disabled={cancelling}
              primary
            />
            <RowButton
              onClick={() => setConfirmingCancel(false)}
              label={t("build_widget_cancel_confirm_no")}
              disabled={cancelling}
            />
          </div>
        </div>
      )}

      {job.kind === "graph_build" && !confirmingCancel && (
        <div style={{ display: "flex", gap: 6 }}>
          {job.active ? (
            <>
              {job.paused ? (
                <RowButton onClick={handleResume} label={t("build_widget_resume")} primary />
              ) : (
                <RowButton onClick={handlePause} label={t("build_widget_pause")} />
              )}
              <RowButton onClick={() => setConfirmingCancel(true)} label={t("build_widget_cancel")} />
            </>
          ) : (
            <RowButton onClick={onGotoGraph} label={t("build_widget_goto_graph")} />
          )}
        </div>
      )}
    </div>
  );
}

function RowButton({
  onClick,
  label,
  primary,
  disabled,
}: {
  onClick: () => void;
  label: string;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1, padding: "3px 0", fontSize: 11, fontWeight: primary ? 600 : 500,
        background: primary ? "var(--accent)" : "transparent",
        color: primary ? "var(--accent-fg)" : "var(--fg-muted)",
        border: primary ? "none" : "1px solid var(--border)",
        borderRadius: 999, cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  );
}
