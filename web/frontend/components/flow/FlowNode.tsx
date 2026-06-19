import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { DependencyStatus, PipelineStage } from "@/lib/api";
import type { FlowConfigSnapshot, QuickConfigDirty, QuickConfigHandle, QuickConfigUpdate } from "./QuickConfigPanel";
import type { I18nKey, Lang } from "@/lib/i18n";
import {
  backendLabel,
  buildDetailParts,
  FIELD_LABEL_KEYS,
  isFlowStageId,
  STAGE_META,
  SWITCH_MAP,
  type FlowStageId,
  type FlowStageStatus,
} from "./model";
import { AlertIcon, ArrowIcon, LockIcon, PortalIcon, StageIcon } from "./Icons";
import { QuickConfigPanel } from "./QuickConfigPanel";

const STATUS_CLASS: Record<FlowStageStatus, string> = {
  ready: "is-ready",
  degraded: "is-degraded",
  off: "is-off-status",
  info: "is-info",
};

const STATUS_KEY: Record<FlowStageStatus, I18nKey> = {
  ready: "flow_status_ready",
  degraded: "flow_status_degraded",
  off: "flow_status_off",
  info: "flow_status_info",
};

function StatusChip({ status, t }: { status: FlowStageStatus; t: (k: I18nKey) => string }) {
  return (
    <span className={`flow-status-chip ${STATUS_CLASS[status]}`}>
      <span className="flow-status-dot" />
      {t(STATUS_KEY[status])}
    </span>
  );
}

function Field({ label, locked, children }: React.PropsWithChildren<{ label: string; locked?: boolean }>) {
  return (
    <div className="flow-field">
      <div className="flow-field-label">
        {label}
        {locked && <span className="flow-field-lock"><LockIcon /></span>}
      </div>
      {children}
    </div>
  );
}

function Segmented({
  options,
  value,
  lang,
  disabled,
  status,
  justActivatedValue,
  lockedOptions,
  lockedTitle,
  onChange,
}: {
  options: string[];
  value: string;
  lang: Lang;
  disabled: boolean;
  status: FlowStageStatus;
  justActivatedValue: string | null;
  lockedOptions?: Set<string>;
  lockedTitle?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flow-segmented" role="group">
      {options.map((option) => {
        const active = option === value;
        const locked = lockedOptions?.has(option) ?? false;
        return (
          <button
            key={option}
            type="button"
            className={`flow-segmented-option ${active ? "is-active" : ""} ${locked ? "is-locked" : ""} ${active && justActivatedValue === option ? "seg-flash" : ""} ${STATUS_CLASS[status]}`}
            disabled={disabled || active || locked}
            title={locked ? lockedTitle : undefined}
            onClick={(event) => {
              event.stopPropagation();
              if (!active && !locked) onChange(option);
            }}
          >
            {locked && <span className="flow-seg-lock"><LockIcon /></span>}
            {backendLabel(option, lang)}
          </button>
        );
      })}
    </div>
  );
}

function ReadonlyField({ value, lang }: { value: string; lang: Lang }) {
  return <div className="flow-readonly-field">{backendLabel(value, lang)}</div>;
}

function DepRow({
  dep,
  installing,
  t,
  onInstall,
}: {
  dep: DependencyStatus;
  installing: string | null;
  t: (k: I18nKey) => string;
  onInstall: (dep: DependencyStatus) => void;
}) {
  const depName = t(`flow_dep_${dep.key}` as I18nKey);
  const isInstalling = installing === dep.key;
  return (
    <div className="flow-dep-row" onClick={(event) => event.stopPropagation()}>
      <span className="flow-dep-icon"><AlertIcon /></span>
      <div className="flow-dep-text">
        <span className="flow-dep-name">{t(dep.required ? "flow_missing_required_dep" : "flow_missing_dep")}: {depName}</span>
        <code className="flow-dep-pip">{dep.pip_spec}</code>
      </div>
      <button
        type="button"
        className="flow-dep-button"
        disabled={isInstalling}
        onClick={(event) => {
          event.stopPropagation();
          onInstall(dep);
        }}
      >
        {isInstalling ? t("flow_deps_installing") : t("flow_install_now")}
      </button>
    </div>
  );
}

export function FlowNode({
  stage,
  depMap,
  lang,
  t,
  saving,
  installing,
  justActivatedValue,
  rebuildingIndex,
  restartPending,
  selected,
  onEditingChange,
  onSelect,
  config,
  onSwitch,
  onQuickConfigSave,
  onRefresh,
  onInstall,
  onRebuildIndex,
  onClose,
}: {
  stage: PipelineStage;
  depMap: Map<string, DependencyStatus>;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  installing: string | null;
  justActivatedValue: string | null;
  rebuildingIndex: boolean;
  restartPending: boolean;
  selected: boolean;
  config: FlowConfigSnapshot;
  onEditingChange?: (stageId: string, editing: boolean) => void;
  onSelect: () => void;
  onSwitch: (stage: PipelineStage, value: string) => void;
  onQuickConfigSave: (stageId: FlowStageId, updates: QuickConfigUpdate[]) => void;
  onRefresh?: () => Promise<void>;
  onInstall: (dep: DependencyStatus) => void;
  onRebuildIndex: () => void;
  onClose?: () => void;
}) {
  if (!isFlowStageId(stage.id)) return null;

  const id = stage.id as FlowStageId;
  const meta = STAGE_META[id];
  const canSwitch = Boolean(SWITCH_MAP[id]) && stage.candidates.length > 1;
  const lockedOptions = id === "vector_store" ? new Set(["astr"]) : undefined;
  const isDest = meta.kind === "dest";
  const isOff = stage.status === "off";
  const detailParts = buildDetailParts(stage, lang, t("flow_engines"));
  const missingDeps = stage.required_deps
    .map((key) => depMap.get(key))
    .filter((dep): dep is DependencyStatus => Boolean(dep && !dep.installed));
  const fieldKey = FIELD_LABEL_KEYS[id] ?? "flow_current";
  const needsMilvusRebuild =
    id === "vector_store" &&
    stage.current === "milvus" &&
    (stage.detail.rebuild_required === true ||
      Number(stage.detail.pending_reindex_count ?? 0) > 0);
  const milvusReason =
    typeof stage.detail.reason === "string" && stage.detail.reason
      ? stage.detail.reason
      : "";

  // 头部徽章承担唯一保存入口：草稿态由 QuickConfigPanel 经 onDirtyChange 上报，save 经 ref 触发。
  const panelRef = useRef<QuickConfigHandle>(null);
  const [dirty, setDirty] = useState<QuickConfigDirty>({ count: 0, canSave: false });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // 高级折叠通过 Portal 渲到节点最底部的槽位（按钮在底、浮层紧贴节点底，不挤动其他节点）。
  const [advancedSlot, setAdvancedSlot] = useState<HTMLElement | null>(null);
  const handleDirtyChange = useCallback((state: QuickConfigDirty) => {
    setDirty((prev) => (prev.count === state.count && prev.canSave === state.canSave ? prev : state));
  }, []);
  const handleToggleAdvanced = useCallback(() => setAdvancedOpen((v) => !v), []);
  const isDirty = dirty.count > 0;
  const showRestartPending = !isDirty && restartPending;

  // 向上报告本节点是否处于编辑（dirty）态，供页面暂停自动刷新；卸载时报告 false。
  const stageId = stage.id;
  useEffect(() => {
    onEditingChange?.(stageId, isDirty);
  }, [isDirty, stageId, onEditingChange]);
  useEffect(() => () => onEditingChange?.(stageId, false), [stageId, onEditingChange]);

  return (
    <div
      className={`flow-node ${isDest ? "flow-node--dest" : ""} ${selected ? "is-selected" : ""} ${isOff ? "is-off" : ""} ${STATUS_CLASS[stage.status]} ${isDirty ? "is-dirty" : ""} ${showRestartPending ? "is-restart-pending" : ""} ${advancedOpen ? "is-advanced-open" : ""}`}
      onClick={onSelect}
    >
      <div className="flow-node-head">
        <span className="flow-node-icon">
          <StageIcon name={meta.icon} />
          {isDest && <span className="flow-node-portal"><PortalIcon /></span>}
        </span>
        <div className="flow-node-titles">
          <div className="flow-node-title-row">
            <span className="flow-node-title">{t(meta.titleKey)}</span>
            <span className={`flow-node-role ${isDest ? "flow-node-role--dest" : ""}`}>{t(meta.roleKey)}</span>
          </div>
          <span className="flow-node-step">STAGE {String(meta.idx).padStart(2, "0")}</span>
        </div>
        {isDirty ? (
          <button
            type="button"
            className="flow-status-chip flow-status-chip--dirty"
            disabled={!dirty.canSave || saving}
            onClick={(event) => { event.stopPropagation(); panelRef.current?.save(); }}
          >
            <span className="flow-status-dot" />
            {saving ? t("flow_quick_saving") : t("flow_quick_save")}
          </button>
        ) : showRestartPending ? (
          <span className="flow-status-chip flow-status-chip--pending-restart">
            <span className="flow-status-dot" />
            {t("flow_status_pending_restart")}
          </span>
        ) : (
          <StatusChip status={stage.status} t={t} />
        )}
      </div>

      <p className="flow-node-desc">{t(meta.descKey)}</p>

      <div className="flow-node-body">
        {canSwitch ? (
          <Field label={t(fieldKey)}>
            <Segmented
              options={stage.candidates}
              value={stage.current}
              lang={lang}
              disabled={saving}
              status={stage.status}
              justActivatedValue={justActivatedValue}
              lockedOptions={lockedOptions}
              lockedTitle={t("flow_vector_astr_locked")}
              onChange={(value) => onSwitch(stage, value)}
            />
          </Field>
        ) : (
          <Field label={t(fieldKey)} locked>
            <ReadonlyField value={stage.current} lang={lang} />
          </Field>
        )}

        {detailParts.length > 0 && (
          <div className="flow-meta-strip">
            {detailParts.map((part) => <span key={part} className="flow-meta-chip">{part}</span>)}
          </div>
        )}

        {canSwitch && stage.consequence !== "none" && (
          <div className={`flow-consequence ${stage.consequence === "rebuild" ? "flow-consequence--warn" : ""}`}>
            {stage.consequence === "rebuild" ? t("flow_consequence_rebuild") : t("flow_consequence_restart")}
          </div>
        )}

        <QuickConfigPanel
          ref={panelRef}
          stage={stage}
          config={config}
          lang={lang}
          t={t}
          saving={saving}
          onSave={onQuickConfigSave}
          onRefresh={onRefresh}
          onDirtyChange={handleDirtyChange}
          advancedOpen={advancedOpen}
          onToggleAdvanced={handleToggleAdvanced}
          advancedSlot={advancedSlot}
        />

        {missingDeps.map((dep) => (
          <DepRow key={dep.key} dep={dep} installing={installing} t={t} onInstall={onInstall} />
        ))}

        {needsMilvusRebuild && (
          <div className="flow-dep-row" onClick={(event) => event.stopPropagation()}>
            <span className="flow-dep-icon"><AlertIcon /></span>
            <div className="flow-dep-text">
              <span className="flow-dep-name">{t("flow_milvus_rebuild_required")}</span>
              {milvusReason && <code className="flow-dep-pip">{milvusReason}</code>}
            </div>
            <button
              type="button"
              className="flow-dep-button"
              disabled={rebuildingIndex}
              onClick={(event) => {
                event.stopPropagation();
                onRebuildIndex();
              }}
            >
              {rebuildingIndex ? t("flow_milvus_rebuild_running") : t("flow_milvus_rebuild")}
            </button>
          </div>
        )}

        {meta.link && (
          id === "ask" && onClose ? (
            <button
              type="button"
              className={`flow-open-link ${meta.link.primary ? "flow-open-link--primary" : ""}`}
              onClick={(event) => { event.stopPropagation(); onClose(); }}
            >
              {t(meta.link.labelKey)}
              <span className="flow-open-arrow"><ArrowIcon /></span>
            </button>
          ) : (
            <Link
              href={meta.link.href}
              className={`flow-open-link ${meta.link.primary ? "flow-open-link--primary" : ""}`}
              onClick={(event) => event.stopPropagation()}
            >
              {t(meta.link.labelKey)}
              <span className="flow-open-arrow"><ArrowIcon /></span>
            </Link>
          )
        )}

        {/* 高级折叠槽位：始终是节点 body 最后一项 → 折叠按钮在节点最底部；浮层经 Portal 渲到此处。 */}
        <div ref={setAdvancedSlot} className="flow-node-advanced-slot" />
      </div>
    </div>
  );
}
