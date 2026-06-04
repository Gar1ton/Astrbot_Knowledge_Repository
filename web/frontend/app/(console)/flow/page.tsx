"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useI18n, I18nKey, Lang } from "@/lib/i18n";
import { useToast } from "@/components/ui/Toast";
import {
  getCapabilities,
  recheckDependencies,
  installDependency,
  updateConfigValue,
  CapabilitiesData,
  PipelineStage,
  DependencyStatus,
} from "@/lib/api";

// ─── 状态 / 后端值 → 展示元数据 ────────────────────────────────

type StageStatus = PipelineStage["status"];

const STATUS_META: Record<StageStatus, { key: I18nKey; symbol: string; color: string; soft: string }> = {
  ready: { key: "flow_status_ready", symbol: "✓", color: "var(--ok)", soft: "color-mix(in srgb, var(--ok) 12%, transparent)" },
  degraded: { key: "flow_status_degraded", symbol: "!", color: "var(--warn)", soft: "color-mix(in srgb, var(--warn) 14%, transparent)" },
  off: { key: "flow_status_off", symbol: "○", color: "var(--fg-subtle)", soft: "var(--bg-inset)" },
  info: { key: "flow_status_info", symbol: "•", color: "var(--accent)", soft: "var(--accent-soft)" },
};

function backendLabel(value: string, lang: Lang): string {
  const zh = lang === "zh";
  const map: Record<string, string> = {
    local: zh ? "本地离线" : "Local",
    external: zh ? "云端 API" : "Cloud API",
    milvus: "Milvus Lite",
    astr: "AstrBot KB",
    on: zh ? "开启" : "On",
    off: zh ? "关闭" : "Off",
    inject: zh ? "原生注入" : "Inject",
    query_agent: zh ? "内部代理" : "Query Agent",
    rrf_fusion: "RRF",
    sqlite: "SQLite",
    sqlite_lexical: "SQLite",
    astrbot_kb: "AstrBot KB",
  };
  return map[value] ?? value;
}

// 每个可切换环节 → 配置写入映射。未列入者在 UI 中为信息性展示（不可切换）。
const SWITCH_MAP: Record<string, { section: string; key: string; toBool?: boolean }> = {
  embedding: { section: "embedding", key: "provider" },
  vector_store: { section: "vector_db", key: "backend" },
  ask: { section: "ask", key: "conversation_enhancement_mode" },
  graph: { section: "graph", key: "enabled", toBool: true },
};

// ─── 分段切换控件（与设置页同款） ──────────────────────────────

function SegmentedControl({
  options,
  value,
  onChange,
  disabled,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        background: "var(--bg-inset)",
        border: "1px solid var(--border)",
        borderRadius: 999,
        padding: 2,
        gap: 2,
        opacity: disabled ? 0.55 : 1,
        pointerEvents: disabled ? "none" : "auto",
      }}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            border: "none",
            borderRadius: 999,
            padding: "5px 14px",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "inherit",
            transition: "all .15s",
            background: value === opt.value ? "var(--surface)" : "transparent",
            color: value === opt.value ? "var(--accent)" : "var(--fg-muted)",
            boxShadow: value === opt.value ? "var(--shadow)" : "none",
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ─── 流程节点 ─────────────────────────────────────────────────

function StatusBadge({ status, t }: { status: StageStatus; t: (k: I18nKey) => string }) {
  const meta = STATUS_META[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        borderRadius: 999,
        padding: "2px 9px",
        fontSize: 11,
        fontWeight: 700,
        color: meta.color,
        background: meta.soft,
        border: `1px solid ${meta.color}`,
      }}
    >
      <span aria-hidden style={{ fontSize: 11 }}>{meta.symbol}</span>
      {t(meta.key)}
    </span>
  );
}

function StageNode({
  stage,
  depMap,
  lang,
  t,
  saving,
  installing,
  onSwitch,
  onInstall,
}: {
  stage: PipelineStage;
  depMap: Map<string, DependencyStatus>;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  installing: string | null;
  onSwitch: (stage: PipelineStage, value: string) => void;
  onInstall: (dep: DependencyStatus) => void;
}) {
  const switchable = stage.id in SWITCH_MAP && stage.candidates.length > 1;
  const missingDeps = stage.required_deps
    .map((k) => depMap.get(k))
    .filter((d): d is DependencyStatus => !!d && !d.installed);
  const engines = (stage.detail.engines as string[] | undefined) ?? [];
  const model = stage.detail.model as string | undefined;
  const dim = stage.detail.actual_dimension as number | undefined;

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        padding: "16px 18px",
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--heading)" }}>
          {t(`flow_stage_${stage.id}` as I18nKey)}
        </div>
        <StatusBadge status={stage.status} t={t} />
      </div>

      <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.55 }}>
        {t(`flow_stage_${stage.id}_desc` as I18nKey)}
      </div>

      {/* 当前后端 + 模型/维度/引擎等细节 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12 }}>
        <span style={{ color: "var(--fg-subtle)" }}>{t("flow_current")}:</span>
        <span
          style={{
            fontFamily: "var(--font-geist-mono)",
            fontWeight: 600,
            color: "var(--fg)",
            background: "var(--bg-inset)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "2px 8px",
          }}
        >
          {backendLabel(stage.current, lang)}
        </span>
        {model && (
          <span style={{ color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)", fontSize: 11 }}>
            {model}{dim ? ` · ${dim}d` : ""}
          </span>
        )}
        {stage.id === "retrieval" && engines.length > 0 && (
          <span style={{ color: "var(--fg-subtle)", fontSize: 11 }}>
            {t("flow_engines")}: {engines.map((e) => backendLabel(e, lang)).join(" + ")}
          </span>
        )}
      </div>

      {/* 切换控件 */}
      {switchable && (
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <SegmentedControl
            options={stage.candidates.map((c) => ({ value: c, label: backendLabel(c, lang) }))}
            value={stage.current}
            onChange={(v) => onSwitch(stage, v)}
            disabled={saving}
          />
          <span style={{ fontSize: 11, color: stage.consequence === "rebuild" ? "var(--warn)" : "var(--fg-subtle)" }}>
            {stage.consequence === "rebuild"
              ? t("flow_consequence_rebuild")
              : stage.consequence === "restart"
                ? t("flow_consequence_restart")
                : ""}
          </span>
        </div>
      )}

      {/* 缺少依赖 → 去安装 */}
      {missingDeps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {missingDeps.map((dep) => (
            <div
              key={dep.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                background: "color-mix(in srgb, var(--warn) 9%, transparent)",
                border: "1px solid color-mix(in srgb, var(--warn) 32%, transparent)",
                borderRadius: 10,
                padding: "8px 12px",
                fontSize: 12,
              }}
            >
              <span style={{ color: "var(--warn)", fontWeight: 600 }}>
                {t("flow_missing_dep")}: {t(`flow_dep_${dep.key}` as I18nKey)}
              </span>
              <code style={{ fontFamily: "var(--font-geist-mono)", fontSize: 11, color: "var(--fg-muted)" }}>{dep.pip_spec}</code>
              <button
                onClick={() => onInstall(dep)}
                disabled={installing === dep.key}
                style={{
                  marginLeft: "auto",
                  padding: "4px 12px",
                  fontSize: 12,
                  fontWeight: 600,
                  borderRadius: 8,
                  border: "1px solid var(--accent-border)",
                  background: "var(--accent-soft)",
                  color: "var(--accent)",
                  cursor: installing === dep.key ? "wait" : "pointer",
                  fontFamily: "inherit",
                }}
              >
                {installing === dep.key ? t("flow_deps_installing") : t("flow_install_now")}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Connector() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "2px 0" }}>
      <svg width="18" height="22" viewBox="0 0 18 22" fill="none" stroke="var(--border-strong)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="9" y1="1" x2="9" y2="15" />
        <polyline points="4 11 9 16 14 11" />
      </svg>
    </div>
  );
}

// ─── 依赖管理面板 ─────────────────────────────────────────────

function DependencyPanel({
  deps,
  lang,
  t,
  installing,
  onInstall,
}: {
  deps: DependencyStatus[];
  lang: Lang;
  t: (k: I18nKey) => string;
  installing: string | null;
  onInstall: (dep: DependencyStatus) => void;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        padding: "18px 20px",
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--heading)" }}>{t("flow_deps_title")}</div>
        <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.55, marginTop: 4 }}>
          {t("flow_deps_desc")}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 4 }}>{t("flow_deps_docker_hint")}</div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {deps.map((dep) => (
          <div
            key={dep.key}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              background: "var(--bg-inset)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              padding: "10px 12px",
            }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", minWidth: 130 }}>
              {t(`flow_dep_${dep.key}` as I18nKey)}
            </span>
            <code style={{ fontFamily: "var(--font-geist-mono)", fontSize: 11, color: "var(--fg-subtle)", flex: 1, minWidth: 160 }}>
              {dep.pip_spec}
            </code>
            {dep.installed ? (
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--ok)" }}>
                ✓ {t("flow_deps_installed")}{dep.version ? ` · ${dep.version}` : ""}
              </span>
            ) : (
              <>
                <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-subtle)" }}>○ {t("flow_deps_missing")}</span>
                <button
                  onClick={() => onInstall(dep)}
                  disabled={installing === dep.key}
                  style={{
                    padding: "5px 14px",
                    fontSize: 12,
                    fontWeight: 600,
                    borderRadius: 8,
                    border: "1px solid var(--accent-border)",
                    background: "var(--accent)",
                    color: "var(--accent-fg, #fff)",
                    cursor: installing === dep.key ? "wait" : "pointer",
                    fontFamily: "inherit",
                  }}
                >
                  {installing === dep.key ? t("flow_deps_installing") : t("flow_deps_install")}
                </button>
              </>
            )}
          </div>
        ))}
      </div>

      <Link href="/terminal" style={{ fontSize: 12, color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}>
        → {t("flow_deps_terminal_link")}
      </Link>
    </div>
  );
}

// ─── 页面 ─────────────────────────────────────────────────────

type Banner = { kind: "restart" | "rebuild" | "install"; msg?: string } | null;

export default function FlowPage() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [caps, setCaps] = useState<CapabilitiesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [installingKey, setInstallingKey] = useState<string | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  useEffect(() => {
    getCapabilities()
      .then(setCaps)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const depMap = new Map((caps?.dependencies ?? []).map((d) => [d.key, d]));

  async function handleSwitch(stage: PipelineStage, value: string) {
    const map = SWITCH_MAP[stage.id];
    if (!map || value === stage.current) return;
    const writeValue: string | boolean = map.toBool ? value === "on" : value;
    setSavingId(stage.id);
    try {
      const result = await updateConfigValue(map.section, map.key, writeValue);
      if (result.rebuild_required) setBanner({ kind: "rebuild" });
      else if (result.restart_required) setBanner({ kind: "restart" });
      else toast(t("flow_saved"), "ok");
      const fresh = await getCapabilities();
      setCaps(fresh);
    } catch (err: unknown) {
      toast(`${t("flow_save_failed")}: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setSavingId(null);
    }
  }

  async function handleInstall(dep: DependencyStatus) {
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
      const fresh = await recheckDependencies();
      setCaps(fresh);
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setInstallingKey(null);
    }
  }

  async function handleRecheck() {
    setRechecking(true);
    try {
      const fresh = await recheckDependencies();
      setCaps(fresh);
    } catch {
      /* silent */
    } finally {
      setRechecking(false);
    }
  }

  const bannerText =
    banner?.kind === "rebuild"
      ? t("flow_rebuild_banner")
      : banner?.kind === "install"
        ? banner.msg || t("flow_deps_restart_hint")
        : banner?.kind === "restart"
          ? t("flow_restart_banner")
          : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      {/* 粘性玻璃头部 */}
      <div
        className="fx-glass"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 3,
          padding: "16px 24px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
              {t("flow_title")}
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5, maxWidth: 640 }}>
              {t("flow_subtitle")}
            </p>
          </div>
          <button
            onClick={handleRecheck}
            disabled={rechecking}
            style={{
              padding: "7px 16px",
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--surface)",
              color: "var(--fg)",
              cursor: rechecking ? "wait" : "pointer",
              fontFamily: "inherit",
              transition: "all .15s",
            }}
          >
            {rechecking ? t("flow_rechecking") : t("flow_recheck")}
          </button>
        </div>

        {banner && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: banner.kind === "rebuild" ? "color-mix(in srgb, var(--warn) 12%, transparent)" : "var(--accent-soft)",
              border: `1px solid ${banner.kind === "rebuild" ? "color-mix(in srgb, var(--warn) 38%, transparent)" : "var(--accent-border)"}`,
              borderRadius: 10,
              padding: "10px 14px",
              fontSize: 12,
              color: banner.kind === "rebuild" ? "var(--warn)" : "var(--accent)",
              lineHeight: 1.5,
            }}
          >
            <span>{bannerText}</span>
            <button
              onClick={() => setBanner(null)}
              style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 16, lineHeight: 1, padding: 0 }}
              aria-label="dismiss"
            >
              ×
            </button>
          </div>
        )}
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {loading ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 13 }}>{t("flow_loading")}</div>
        ) : !caps ? (
          <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("error_generic")}</div>
        ) : (
          <div style={{ maxWidth: 780, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>
            {/* 数据流程图 */}
            <div style={{ display: "flex", flexDirection: "column" }}>
              {caps.pipeline.map((stage, i) => (
                <React.Fragment key={stage.id}>
                  {i > 0 && <Connector />}
                  <StageNode
                    stage={stage}
                    depMap={depMap}
                    lang={lang}
                    t={t}
                    saving={savingId === stage.id}
                    installing={installingKey}
                    onSwitch={handleSwitch}
                    onInstall={handleInstall}
                  />
                </React.Fragment>
              ))}
            </div>

            {/* 依赖管理面板 */}
            <DependencyPanel
              deps={caps.dependencies}
              lang={lang}
              t={t}
              installing={installingKey}
              onInstall={handleInstall}
            />
          </div>
        )}
      </div>
    </div>
  );
}
