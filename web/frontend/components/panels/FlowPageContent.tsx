"use client";
/* Extracted from app/(console)/flow/page.tsx — do NOT modify components/flow/ files. */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { FlowDiagram } from "@/components/flow/FlowDiagram";
import { AlertIcon, CheckIcon, XIcon } from "@/components/flow/Icons";
import { SWITCH_MAP, type FlowStageId } from "@/components/flow/model";
import type { QuickConfigUpdate } from "@/components/flow/QuickConfigPanel";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  getCapabilities,
  getEffectiveConfig,
  getZoteroConfig,
  installDependency,
  rebuildIndexPending,
  recheckDependencies,
  restartPlugin,
  updateConfigValue,
  type CapabilitiesData,
  type DependencyStatus,
  type EffectiveConfig,
  type PipelineStage,
} from "@/lib/api";

type Banner = { kind: "restart" | "rebuild" | "install"; msg?: string } | null;
type RefreshOptions = { recheck?: boolean; includeZotero?: boolean; notify?: boolean };

export function FlowPageContent({ onClose }: { onClose?: () => void } = {}) {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [caps, setCaps] = useState<CapabilitiesData | null>(null);
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [installingKey, setInstallingKey] = useState<string | null>(null);
  const [rebuildingIndex, setRebuildingIndex] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [restartPendingIds, setRestartPendingIds] = useState<Set<string>>(new Set());
  const [restarting, setRestarting] = useState(false);
  const [justActivatedId, setJustActivatedId] = useState<string | null>(null);
  // 正在编辑（有未保存改动 / 蓝色 dirty）的节点集合；非空时暂停 5s 自动刷新，避免冲掉输入。
  const [editingIds, setEditingIds] = useState<Set<string>>(new Set());
  const editingRef = useRef(false);
  useEffect(() => {
    editingRef.current = editingIds.size > 0;
  }, [editingIds]);
  const handleEditingChange = useCallback((stageId: string, editing: boolean) => {
    setEditingIds((prev) => {
      if (editing === prev.has(stageId)) return prev;
      const next = new Set(prev);
      if (editing) next.add(stageId);
      else next.delete(stageId);
      return next;
    });
  }, []);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(false);
  const refreshInFlight = useRef(false);
  const rerankStatusRef = useRef<string | null>(null);

  const refreshFlow = useCallback(async (options: RefreshOptions = {}) => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const [capsResult, configResult] = await Promise.allSettled([
        options.recheck ? recheckDependencies() : getCapabilities(),
        getEffectiveConfig(1_500),
      ]);
      if (!mountedRef.current) return;
      if (capsResult.status === "fulfilled") {
        const freshCaps = capsResult.value;
        const askStage = freshCaps.pipeline.find((stage) => stage.id === "ask");
        const runtime = askStage?.detail?.rerank_runtime as Record<string, unknown> | undefined;
        const status = String(runtime?.status ?? askStage?.detail?.rerank_status ?? "");
        const model = String(runtime?.model ?? askStage?.detail?.rerank_model ?? "");
        const error = String(runtime?.last_error ?? "");
        const nextRerankKey = status ? `${status}:${model}:${error}` : null;
        if (
          rerankStatusRef.current &&
          nextRerankKey &&
          nextRerankKey !== rerankStatusRef.current
        ) {
          if (status === "loading") toast(t("flow_rerank_loading"), "info");
          else if (status === "ready") toast(t("flow_rerank_ready"), "ok");
          else if (status === "failed") toast(`${t("flow_rerank_failed")}${error ? `: ${error}` : ""}`, "error");
        }
        rerankStatusRef.current = nextRerankKey;
        setCaps(freshCaps);
      } else if (options.notify) {
        toast(capsResult.reason instanceof Error ? capsResult.reason.message : String(capsResult.reason), "error");
      }
      if (configResult.status === "fulfilled") {
        setConfig(configResult.value);
      } else if (options.notify) {
        toast(configResult.reason instanceof Error ? configResult.reason.message : String(configResult.reason), "error");
      }
      if (options.includeZotero) {
        getZoteroConfig(4_000)
          .then((zoteroConfig) => {
            if (!mountedRef.current) return;
            setConfig((prev) => (
              prev
                ? {
                  ...prev,
                  zotero_sync: {
                    ...(prev.zotero_sync ?? {}),
                    ...zoteroConfig,
                  },
                }
                : prev
            ));
          })
          .catch(() => undefined);
      }
    } finally {
      refreshInFlight.current = false;
    }
  }, [t, toast]);

  useEffect(() => {
    mountedRef.current = true;
    refreshFlow({ includeZotero: true })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    const timer = window.setInterval(() => {
      // 编辑中（有节点处于未保存 dirty 态）暂停自动刷新，避免 config 更新冲掉正在输入的草稿。
      if (editingRef.current) return;
      refreshFlow().catch(() => undefined);
    }, 5000);
    return () => {
      mountedRef.current = false;
      window.clearInterval(timer);
      if (flashTimer.current) clearTimeout(flashTimer.current);
    };
  }, [refreshFlow]);

  const handleSwitch = useCallback(async (stage: PipelineStage, value: string) => {
    const map = SWITCH_MAP[stage.id as keyof typeof SWITCH_MAP];
    if (!map || value === stage.current) return;
    const writeValue: string | boolean = map.toBool ? value === "on" : value;
    setSavingId(stage.id);
    try {
      const result = await updateConfigValue(map.section, map.key, writeValue);
      if (result.rebuild_required) setBanner({ kind: "rebuild" });
      else if (result.restart_required) setBanner({ kind: "restart" });
      else toast(t("flow_saved"), "ok");
      if (result.rebuild_required || result.restart_required) {
        setRestartPendingIds((prev) => new Set(prev).add(stage.id));
      }
      await refreshFlow({ includeZotero: true });
      setJustActivatedId(`${stage.id}-${value}`);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setJustActivatedId(null), 700);
    } catch (err: unknown) {
      toast(`${t("flow_save_failed")}: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setSavingId(null);
    }
  }, [refreshFlow, t, toast]);

  const handleQuickConfigSave = useCallback(async (stageId: FlowStageId, updates: QuickConfigUpdate[]) => {
    if (updates.length === 0) return;
    setSavingId(stageId);
    try {
      const results = [];
      for (const update of updates) {
        results.push(await updateConfigValue(update.section, update.key, update.value));
      }
      if (results.some((r) => r.rebuild_required)) setBanner({ kind: "rebuild" });
      else if (results.some((r) => r.restart_required)) setBanner({ kind: "restart" });
      else toast(t("flow_saved"), "ok");
      if (results.some((r) => r.rebuild_required || r.restart_required)) {
        setRestartPendingIds((prev) => new Set(prev).add(stageId));
      }
      await refreshFlow({ includeZotero: true });
    } catch (err: unknown) {
      toast(`${t("flow_save_failed")}: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setSavingId(null);
    }
  }, [refreshFlow, t, toast]);

  const handleInstall = useCallback(async (dep: DependencyStatus) => {
    setInstallingKey(dep.key);
    toast(t("flow_deps_installing"), "info");
    try {
      const result = await installDependency(dep.key);
      if (result.status === "ok") {
        setBanner({ kind: "install", msg: t("flow_deps_restart_hint") });
        toast(t("flow_deps_restart_hint"), "ok");
      } else {
        toast(result.message || t("flow_save_failed"), "error");
      }
      await refreshFlow({ recheck: true, includeZotero: true });
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setInstallingKey(null);
    }
  }, [refreshFlow, t, toast]);

  const handleRebuildIndex = useCallback(async () => {
    // 后台触发即返回：详细进度/成败由 FilePanel 底部的 MilvusBuildCard 展示，
    // 构建期间向量库节点由能力健康检查保持黄色（degraded）。
    setRebuildingIndex(true);
    try {
      await rebuildIndexPending();
      toast(t("flow_milvus_rebuild_running"), "info");
      await refreshFlow({ includeZotero: true });
    } catch (err: unknown) {
      toast(`${t("flow_milvus_rebuild_failed")}: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setRebuildingIndex(false);
    }
  }, [refreshFlow, t, toast]);

  const handleRestartPlugin = useCallback(async () => {
    setRestarting(true);
    toast(t("flow_restart_running"), "info");
    try {
      await restartPlugin();
    } catch {
      // 软重启会拆掉当前 Web 控制台连接，请求往往以网络错误收尾——视为已触发，转入探活轮询。
    }
    const deadline = Date.now() + 60000;
    const poll = () => {
      window.setTimeout(async () => {
        try {
          await recheckDependencies();
          if (!mountedRef.current) return;
          await refreshFlow({ includeZotero: true });
          setRestartPendingIds(new Set());
          setBanner(null);
          setRestarting(false);
          toast(t("flow_restart_done"), "ok");
        } catch {
          if (Date.now() < deadline) poll();
          else if (mountedRef.current) {
            setRestarting(false);
            toast(t("flow_restart_failed"), "error");
          }
        }
      }, 2500);
    };
    poll();
  }, [refreshFlow, t, toast]);

  const handleManualRefresh = useCallback(() => {
    return refreshFlow({ recheck: true, includeZotero: true, notify: true });
  }, [refreshFlow]);

  const bannerText =
    banner?.kind === "rebuild" ? t("flow_rebuild_banner") :
    banner?.kind === "install" ? (banner.msg || t("flow_deps_restart_hint")) :
    banner?.kind === "restart" ? t("flow_restart_banner") : "";

  return (
    <div
      className="flow-topo-page"
      style={{ flex: "1 1 auto", minHeight: 0, height: "100%", overflow: "hidden" }}
    >
      <header className="flow-topo-header">
        <div className="flow-topo-header-row">
          <div className="flow-topo-title-wrap">
            <h1 className="flow-topo-title">{t("flow_title")}</h1>
            <p className="flow-topo-subtitle">{t("flow_subtitle")}</p>
          </div>
          <div className="flow-topo-actions flow-topo-status-panel">
            <button
              type="button"
              className={`flow-restart-btn ${restartPendingIds.size > 0 ? "is-pending" : ""}`}
              disabled={restarting}
              onClick={handleRestartPlugin}
              title={t("flow_restart_plugin_hint")}
            >
              {restarting ? t("flow_restart_running") : t("flow_restart_plugin")}
              {restartPendingIds.size > 0 && <span className="flow-restart-badge">{restartPendingIds.size}</span>}
            </button>
            <div className="flow-topo-legend">
              <span className="flow-legend-item"><span className="flow-legend-dot ready" />{t("flow_legend_ready")}</span>
              <span className="flow-legend-item"><span className="flow-legend-dot degraded" />{t("flow_legend_degraded")}</span>
              <span className="flow-legend-item"><span className="flow-legend-dot off" />{t("flow_legend_off")}</span>
              <span className="flow-legend-sep" />
              <span className="flow-legend-item flow-legend-branch"><span className="flow-legend-line" />{t("flow_parallel_hint")}</span>
            </div>
            <span className="flow-legend-hint">{t("flow_auto_refresh_hint")}</span>
          </div>
        </div>

        {banner && (
          <div className={`flow-banner ${banner.kind === "rebuild" ? "flow-banner--warn" : ""}`}>
            <span className="flow-banner-icon">{banner.kind === "rebuild" ? <AlertIcon /> : <CheckIcon />}</span>
            <span>{bannerText}</span>
            <button type="button" className="flow-banner-close" onClick={() => setBanner(null)} aria-label="dismiss">
              <XIcon />
            </button>
          </div>
        )}
      </header>

      {loading ? (
        <div className="flow-state-panel">{t("flow_loading")}</div>
      ) : !caps || !config ? (
        <div className="flow-state-panel flow-state-panel--error">{t("error_generic")}</div>
      ) : (
        <FlowDiagram
          stages={caps.pipeline}
          dependencies={caps.dependencies}
          config={config}
          lang={lang}
          t={t}
          savingId={savingId}
          installingKey={installingKey}
          justActivatedId={justActivatedId}
          rebuildingIndex={rebuildingIndex}
          restartPendingIds={restartPendingIds}
          onEditingChange={handleEditingChange}
          onSwitch={handleSwitch}
          onQuickConfigSave={handleQuickConfigSave}
          onRefresh={handleManualRefresh}
          onInstall={handleInstall}
          onRebuildIndex={handleRebuildIndex}
          onClose={onClose}
        />
      )}
    </div>
  );
}
