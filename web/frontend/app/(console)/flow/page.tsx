"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { DotField } from "@/components/fx/DotField";
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

// ─── 状态元数据 ────────────────────────────────────────────────

type StageStatus = PipelineStage["status"];

const STATUS_META: Record<StageStatus, { key: I18nKey; symbol: string; color: string; soft: string }> = {
  ready:    { key: "flow_status_ready",    symbol: "✓", color: "var(--ok)",        soft: "color-mix(in srgb, var(--ok) 12%, transparent)" },
  degraded: { key: "flow_status_degraded", symbol: "!",  color: "var(--warn)",      soft: "color-mix(in srgb, var(--warn) 14%, transparent)" },
  off:      { key: "flow_status_off",      symbol: "○", color: "var(--fg-subtle)", soft: "var(--bg-inset)" },
  info:     { key: "flow_status_info",     symbol: "•", color: "var(--accent)",    soft: "var(--accent-soft)" },
};

function stripeColor(status: StageStatus): string {
  if (status === "ready")    return "var(--ok)";
  if (status === "degraded") return "var(--warn)";
  if (status === "info")     return "var(--accent)";
  return "var(--border-strong)";
}

function backendLabel(value: string, lang: Lang): string {
  const zh = lang === "zh";
  const map: Record<string, string> = {
    local:          zh ? "本地离线" : "Local",
    external:       zh ? "云端 API"  : "Cloud API",
    milvus:         "Milvus Lite",
    astr:           "AstrBot KB",
    on:             zh ? "开启" : "On",
    off:            zh ? "关闭" : "Off",
    inject:         zh ? "原生注入"  : "Inject",
    query_agent:    zh ? "内部代理"  : "Query Agent",
    rrf_fusion:     "RRF",
    sqlite:         "SQLite",
    sqlite_lexical: "SQLite",
    astrbot_kb:     "AstrBot KB",
  };
  return map[value] ?? value;
}

const SWITCH_MAP: Record<string, { section: string; key: string; toBool?: boolean }> = {
  embedding:    { section: "embedding",  key: "provider" },
  vector_store: { section: "vector_db",  key: "backend" },
  ask:          { section: "ask",        key: "conversation_enhancement_mode" },
  graph:        { section: "graph",      key: "enabled", toBool: true },
};

// ─── StatusDot（带脉冲动效） ───────────────────────────────────

function StatusDot({ status }: { status: StageStatus }) {
  const color = stripeColor(status);
  const isDegraded = status === "degraded";
  return (
    <span
      style={{
        display: "inline-block",
        width: 9,
        height: 9,
        borderRadius: "50%",
        background: color,
        flexShrink: 0,
        boxShadow: status === "ready"
          ? `0 0 0 3px color-mix(in srgb, ${color} 22%, transparent)`
          : isDegraded
            ? `0 0 0 2px color-mix(in srgb, var(--warn) 30%, transparent)`
            : "none",
        animation: isDegraded
          ? "dotPulse 1.8s ease-in-out infinite, dotGlow 1.8s ease-in-out infinite"
          : "none",
      }}
    />
  );
}

// ─── OptionTile（并联选项瓦片） ────────────────────────────────

function OptionTile({
  value,
  label,
  active,
  justActivated,
  detail,
  missingDeps,
  installing,
  disabled,
  onClick,
  onInstall,
  t,
}: {
  value: string;
  label: string;
  active: boolean;
  justActivated: boolean;
  detail?: string;
  missingDeps: DependencyStatus[];
  installing: string | null;
  disabled: boolean;
  onClick: () => void;
  onInstall: (dep: DependencyStatus) => void;
  t: (k: I18nKey) => string;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      role={active ? undefined : "button"}
      tabIndex={active || disabled ? undefined : 0}
      onClick={active || disabled ? undefined : onClick}
      onKeyDown={(e) => { if (!active && !disabled && (e.key === "Enter" || e.key === " ")) onClick(); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flex: 1,
        minWidth: 0,
        borderRadius: 12,
        border: active ? `1.5px solid var(--accent)` : `1.5px dashed var(--border-strong)`,
        background: active ? "var(--accent-soft)" : "var(--bg-inset)",
        padding: "11px 14px",
        position: "relative",
        cursor: active ? "default" : disabled ? "wait" : "pointer",
        transition: "opacity .18s, filter .18s, box-shadow .18s",
        opacity: active ? 1 : hovered ? 0.82 : 0.58,
        filter: active ? "none" : "saturate(0.25)",
        boxShadow: active
          ? "0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent), var(--shadow)"
          : "none",
        animation: active && justActivated ? "tileActivate .65s ease forwards" : "none",
      }}
    >
      {/* 激活绿点 */}
      {active && (
        <span
          style={{
            position: "absolute",
            top: 9,
            right: 10,
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "var(--ok)",
            boxShadow: "0 0 0 2px color-mix(in srgb, var(--ok) 28%, transparent)",
          }}
        />
      )}

      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: active ? "var(--accent)" : "var(--fg-muted)",
          paddingRight: active ? 18 : 0,
          lineHeight: 1.3,
        }}
      >
        {label}
      </div>

      {active && detail && (
        <div
          style={{
            fontSize: 11,
            color: "var(--fg-subtle)",
            fontFamily: "var(--font-geist-mono)",
            marginTop: 5,
            lineHeight: 1.5,
          }}
        >
          {detail}
        </div>
      )}

      {active && missingDeps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 8 }}>
          {missingDeps.map((dep) => (
            <div
              key={dep.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
                background: "color-mix(in srgb, var(--warn) 10%, transparent)",
                border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
                borderRadius: 8,
                padding: "7px 10px",
                fontSize: 11,
              }}
            >
              <span style={{ color: "var(--warn)", fontWeight: 600 }}>
                {t("flow_missing_dep")}: {t(`flow_dep_${dep.key}` as I18nKey)}
              </span>
              <code style={{ fontFamily: "var(--font-geist-mono)", fontSize: 10, color: "var(--fg-muted)" }}>
                {dep.pip_spec}
              </code>
              <button
                onClick={(e) => { e.stopPropagation(); onInstall(dep); }}
                disabled={installing === dep.key}
                style={{
                  marginLeft: "auto",
                  padding: "3px 10px",
                  fontSize: 11,
                  fontWeight: 600,
                  borderRadius: 7,
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

// ─── FlowNode ─────────────────────────────────────────────────

function FlowNode({
  stage,
  index,
  depMap,
  lang,
  t,
  saving,
  installing,
  justActivatedId,
  onSwitch,
  onInstall,
}: {
  stage: PipelineStage;
  index: number;
  depMap: Map<string, DependencyStatus>;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  installing: string | null;
  justActivatedId: string | null;
  onSwitch: (stage: PipelineStage, value: string) => void;
  onInstall: (dep: DependencyStatus) => void;
}) {
  const isOff = stage.status === "off";
  const switchable = stage.id in SWITCH_MAP && stage.candidates.length > 1;
  const stripe = stripeColor(stage.status);

  const allMissingDeps = stage.required_deps
    .map((k) => depMap.get(k))
    .filter((d): d is DependencyStatus => !!d && !d.installed);

  const engines = (stage.detail.engines as string[] | undefined) ?? [];
  const model   = stage.detail.model as string | undefined;
  const dim     = stage.detail.actual_dimension as number | undefined;

  function buildDetail(): string | undefined {
    const parts: string[] = [];
    if (model) parts.push(model);
    if (dim)   parts.push(`${dim}d`);
    if (stage.id === "retrieval" && engines.length > 0)
      parts.push(`${t("flow_engines")}: ${engines.map((e) => backendLabel(e, lang)).join(" + ")}`);
    return parts.length > 0 ? parts.join(" · ") : undefined;
  }

  return (
    <div
      style={{
        background: "var(--surface)",
        border: isOff
          ? "1px dashed var(--border)"
          : `1px solid color-mix(in srgb, ${stripe} 22%, var(--border))`,
        borderLeft: `3px solid ${stripe}`,
        borderRadius: 14,
        padding: "14px 16px",
        boxShadow: isOff ? "none" : "var(--shadow)",
        opacity: isOff ? 0.62 : 1,
        filter: isOff ? "saturate(0.18)" : "none",
        display: "flex",
        flexDirection: "column",
        gap: 9,
        /* 错落进场动画 */
        animation: "fadeUp .32s ease both",
        animationDelay: `${index * 65}ms`,
      }}
    >
      {/* 头部：状态点 + 节点名（无徽章） */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <StatusDot status={stage.status} />
        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.01em" }}>
          {t(`flow_stage_${stage.id}` as I18nKey)}
        </span>
      </div>

      {/* 描述 */}
      <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.55, paddingLeft: 17 }}>
        {t(`flow_stage_${stage.id}_desc` as I18nKey)}
      </div>

      {/* 选项区 */}
      <div style={{ paddingLeft: 17 }}>
        {switchable ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {stage.candidates.map((c) => (
              <OptionTile
                key={c}
                value={c}
                label={backendLabel(c, lang)}
                active={c === stage.current}
                justActivated={justActivatedId === `${stage.id}-${c}`}
                detail={c === stage.current ? buildDetail() : undefined}
                missingDeps={c === stage.current ? allMissingDeps : []}
                installing={installing}
                disabled={saving}
                onClick={() => onSwitch(stage, c)}
                onInstall={onInstall}
                t={t}
              />
            ))}
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                fontFamily: "var(--font-geist-mono)",
                fontWeight: 600,
                fontSize: 12,
                color: "var(--fg)",
                background: "var(--bg-inset)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: "2px 9px",
              }}
            >
              {backendLabel(stage.current, lang)}
            </span>
            {buildDetail() && (
              <span style={{ fontSize: 11, color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)" }}>
                {buildDetail()}
              </span>
            )}
          </div>
        )}
      </div>

      {/* 切换后果提示 */}
      {switchable && stage.consequence !== "none" && (
        <div
          style={{
            paddingLeft: 17,
            fontSize: 11,
            color: stage.consequence === "rebuild" ? "var(--warn)" : "var(--fg-subtle)",
          }}
        >
          {stage.consequence === "rebuild"
            ? t("flow_consequence_rebuild")
            : t("flow_consequence_restart")}
        </div>
      )}

      {/* 缺依赖（非 switchable 节点） */}
      {!switchable && allMissingDeps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 17 }}>
          {allMissingDeps.map((dep) => (
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
              <code style={{ fontFamily: "var(--font-geist-mono)", fontSize: 11, color: "var(--fg-muted)" }}>
                {dep.pip_spec}
              </code>
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

// ─── Connector（描边绘制动画） ─────────────────────────────────

function Connector({ nextIsOff, index }: { nextIsOff: boolean; index: number }) {
  const color = nextIsOff ? "var(--border-strong)" : "var(--accent-border)";
  // 连接线出现在节点 index 之前，延迟略早于目标节点
  const delay = Math.max(0, index * 65 - 22);

  if (nextIsOff) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "1px 0" }}>
        <svg width="20" height="26" viewBox="0 0 20 26" fill="none">
          <line x1="10" y1="1" x2="10" y2="19" stroke={color} strokeWidth="2" strokeLinecap="round" strokeDasharray="5 4" />
          <polyline points="4 14 10 20 16 14" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "1px 0" }}>
      <svg width="20" height="26" viewBox="0 0 20 26" fill="none">
        <line
          x1="10" y1="1" x2="10" y2="19"
          stroke={color} strokeWidth="2" strokeLinecap="round"
          strokeDasharray="19" strokeDashoffset="19"
          style={{ animation: `connectorDraw .35s ease forwards`, animationDelay: `${delay}ms` }}
        />
        <polyline
          points="4 14 10 20 16 14"
          stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"
          strokeDasharray="18" strokeDashoffset="18"
          style={{ animation: `connectorDraw .28s ease forwards`, animationDelay: `${delay + 130}ms` }}
        />
      </svg>
    </div>
  );
}

// ─── DependencyPanel（2 列网格） ───────────────────────────────

function DepCard({
  dep,
  t,
  installing,
  onInstall,
}: {
  dep: DependencyStatus;
  t: (k: I18nKey) => string;
  installing: string | null;
  onInstall: (dep: DependencyStatus) => void;
}) {
  return (
    <div
      style={{
        background: "var(--bg-inset)",
        border: `1px solid ${dep.installed ? "color-mix(in srgb, var(--ok) 30%, var(--border))" : "var(--border)"}`,
        borderRadius: 11,
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 5,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>
          {t(`flow_dep_${dep.key}` as I18nKey)}
        </span>
        {dep.installed ? (
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--ok)", flexShrink: 0 }}>
            ✓{dep.version ? ` ${dep.version}` : ""}
          </span>
        ) : (
          <button
            onClick={() => onInstall(dep)}
            disabled={installing === dep.key}
            style={{
              padding: "3px 11px",
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 7,
              border: "1px solid var(--accent-border)",
              background: "var(--accent)",
              color: "var(--accent-fg, #fff)",
              cursor: installing === dep.key ? "wait" : "pointer",
              fontFamily: "inherit",
              flexShrink: 0,
            }}
          >
            {installing === dep.key ? t("flow_deps_installing") : t("flow_deps_install")}
          </button>
        )}
      </div>
      <code style={{ fontSize: 10, fontFamily: "var(--font-geist-mono)", color: "var(--fg-subtle)", wordBreak: "break-all" }}>
        {dep.pip_spec}
      </code>
      {!dep.installed && (
        <span style={{ fontSize: 10, color: "var(--fg-subtle)" }}>○ {t("flow_deps_missing")}</span>
      )}
    </div>
  );
}

function DependencyPanel({
  deps,
  t,
  installing,
  onInstall,
}: {
  deps: DependencyStatus[];
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
        padding: "16px 18px",
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--heading)" }}>{t("flow_deps_title")}</div>
        <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5, marginTop: 3 }}>{t("flow_deps_desc")}</div>
        <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2 }}>{t("flow_deps_docker_hint")}</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
        {deps.map((dep) => (
          <DepCard key={dep.key} dep={dep} t={t} installing={installing} onInstall={onInstall} />
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
  const [justActivatedId, setJustActivatedId] = useState<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getCapabilities()
      .then(setCaps)
      .catch(() => {})
      .finally(() => setLoading(false));
    return () => { if (flashTimer.current) clearTimeout(flashTimer.current); };
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
      // 触发激活瓦片 flash
      setJustActivatedId(`${stage.id}-${value}`);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setJustActivatedId(null), 700);
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
    } catch { /* silent */ }
    finally { setRechecking(false); }
  }

  const bannerText =
    banner?.kind === "rebuild"  ? t("flow_rebuild_banner")  :
    banner?.kind === "install"  ? (banner.msg || t("flow_deps_restart_hint")) :
    banner?.kind === "restart"  ? t("flow_restart_banner")  : "";

  const pipeline = caps?.pipeline ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      {/* 粘性玻璃头部 */}
      <div
        className="fx-glass"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 3,
          padding: "14px 24px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
              {t("flow_title")}
            </h1>
            <p style={{ margin: "3px 0 0", fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5, maxWidth: 560 }}>
              {t("flow_subtitle")}
            </p>
          </div>
          <button
            onClick={handleRecheck}
            disabled={rechecking}
            style={{
              padding: "6px 15px",
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--surface)",
              color: "var(--fg)",
              cursor: rechecking ? "wait" : "pointer",
              fontFamily: "inherit",
              transition: "all .15s",
              flexShrink: 0,
            }}
          >
            {rechecking ? t("flow_rechecking") : t("flow_recheck")}
          </button>
        </div>

        {/* 图例行 */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {(["ready", "degraded", "off"] as StageStatus[]).map((s) => {
            const meta = STATUS_META[s];
            return (
              <span
                key={s}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontSize: 11,
                  color: meta.color,
                  background: meta.soft,
                  border: `1px solid ${meta.color}`,
                  borderRadius: 999,
                  padding: "2px 9px",
                  fontWeight: 600,
                  opacity: 0.85,
                }}
              >
                <span aria-hidden style={{ fontSize: 10 }}>{meta.symbol}</span>
                {t(meta.key)}
              </span>
            );
          })}
        </div>

        {banner && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: banner.kind === "rebuild"
                ? "color-mix(in srgb, var(--warn) 12%, transparent)"
                : "var(--accent-soft)",
              border: `1px solid ${banner.kind === "rebuild"
                ? "color-mix(in srgb, var(--warn) 38%, transparent)"
                : "var(--accent-border)"}`,
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

      {/* 内容区（DotField 背景 + 内容层） */}
      <div style={{ flex: 1, overflowY: "auto", position: "relative" }}>
        <DotField style={{ opacity: 0.45 }} />
        <div style={{ position: "relative", zIndex: 1, padding: "20px 24px" }}>
          {loading ? (
            <div style={{ color: "var(--fg-muted)", fontSize: 13 }}>{t("flow_loading")}</div>
          ) : !caps ? (
            <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("error_generic")}</div>
          ) : (
            <div style={{ maxWidth: 800, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>
              {/* 数据流程图 */}
              <div style={{ display: "flex", flexDirection: "column" }}>
                {pipeline.map((stage, i) => (
                  <React.Fragment key={stage.id}>
                    {i > 0 && (
                      <Connector
                        nextIsOff={stage.status === "off"}
                        index={i}
                      />
                    )}
                    <FlowNode
                      stage={stage}
                      index={i}
                      depMap={depMap}
                      lang={lang}
                      t={t}
                      saving={savingId === stage.id}
                      installing={installingKey}
                      justActivatedId={justActivatedId}
                      onSwitch={handleSwitch}
                      onInstall={handleInstall}
                    />
                  </React.Fragment>
                ))}
              </div>

              {/* 依赖管理面板 */}
              <DependencyPanel
                deps={caps.dependencies}
                t={t}
                installing={installingKey}
                onInstall={handleInstall}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
