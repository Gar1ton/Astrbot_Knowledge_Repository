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
  getEffectiveConfig,
  getZoteroConfig,
  installDependency,
  rebuildIndexPending,
  recheckDependencies,
  updateConfigValue,
  type CapabilitiesData,
  type DependencyStatus,
  type EffectiveConfig,
  type PipelineStage,
} from "@/lib/api";

type Banner = { kind: "restart" | "rebuild" | "install"; msg?: string } | null;

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
  const [justActivatedId, setJustActivatedId] = useState<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(false);
  const refreshInFlight = useRef(false);

  const refreshFlow = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const [freshCaps, freshConfig, zoteroConfig] = await Promise.all([
        recheckDependencies(),
        getEffectiveConfig(),
        getZoteroConfig(),
      ]);
      if (!mountedRef.current) return;
      setCaps(freshCaps);
      setConfig({
        ...freshConfig,
        zotero_sync: {
          ...(freshConfig.zotero_sync ?? {}),
          ...zoteroConfig,
        },
      });
    } finally {
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    refreshFlow()
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    const timer = window.setInterval(() => {
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
      await refreshFlow();
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
      await refreshFlow();
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
      await refreshFlow();
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setInstallingKey(null);
    }
  }, [t, toast]);

  const handleRebuildIndex = useCallback(async () => {
    // 后台触发即返回：详细进度/成败由 FilePanel 底部的 MilvusBuildCard 展示，
    // 构建期间向量库节点由能力健康检查保持黄色（degraded）。
    setRebuildingIndex(true);
    try {
      await rebuildIndexPending();
      toast(t("flow_milvus_rebuild_running"), "info");
      await refreshFlow();
    } catch (err: unknown) {
      toast(`${t("flow_milvus_rebuild_failed")}: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setRebuildingIndex(false);
    }
  }, [refreshFlow, t, toast]);

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
          onSwitch={handleSwitch}
          onQuickConfigSave={handleQuickConfigSave}
          onRefresh={refreshFlow}
          onInstall={handleInstall}
          onRebuildIndex={handleRebuildIndex}
          onClose={onClose}
        />
      )}
    </div>
  );
}
