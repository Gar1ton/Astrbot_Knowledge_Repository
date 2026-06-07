import React from "react";
import Link from "next/link";
import type { DependencyStatus, PipelineStage } from "@/lib/api";
import type { FlowConfigSnapshot, QuickConfigUpdate } from "./QuickConfigPanel";
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
  onChange,
}: {
  options: string[];
  value: string;
  lang: Lang;
  disabled: boolean;
  status: FlowStageStatus;
  justActivatedValue: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flow-segmented" role="group">
      {options.map((option) => {
        const active = option === value;
        return (
          <button
            key={option}
            type="button"
            className={`flow-segmented-option ${active ? "is-active" : ""} ${active && justActivatedValue === option ? "seg-flash" : ""} ${STATUS_CLASS[status]}`}
            disabled={disabled || active}
            onClick={(event) => {
              event.stopPropagation();
              if (!active) onChange(option);
            }}
          >
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
        <span className="flow-dep-name">{t("flow_missing_dep")}: {depName}</span>
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
  selected,
  onSelect,
  config,
  onSwitch,
  onQuickConfigSave,
  onInstall,
}: {
  stage: PipelineStage;
  depMap: Map<string, DependencyStatus>;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  installing: string | null;
  justActivatedValue: string | null;
  selected: boolean;
  config: FlowConfigSnapshot;
  onSelect: () => void;
  onSwitch: (stage: PipelineStage, value: string) => void;
  onQuickConfigSave: (stageId: FlowStageId, updates: QuickConfigUpdate[]) => void;
  onInstall: (dep: DependencyStatus) => void;
}) {
  if (!isFlowStageId(stage.id)) return null;

  const id = stage.id as FlowStageId;
  const meta = STAGE_META[id];
  const canSwitch = Boolean(SWITCH_MAP[id]) && stage.candidates.length > 1;
  const isDest = meta.kind === "dest";
  const isOff = stage.status === "off";
  const detailParts = buildDetailParts(stage, lang, t("flow_engines"));
  const missingDeps = stage.required_deps
    .map((key) => depMap.get(key))
    .filter((dep): dep is DependencyStatus => Boolean(dep && !dep.installed));
  const fieldKey = FIELD_LABEL_KEYS[id] ?? "flow_current";

  return (
    <div
      className={`flow-node ${isDest ? "flow-node--dest" : ""} ${selected ? "is-selected" : ""} ${isOff ? "is-off" : ""} ${STATUS_CLASS[stage.status]}`}
      onClick={onSelect}
    >
      <span className="flow-node-stripe" />
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
        <StatusChip status={stage.status} t={t} />
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
          stage={stage}
          config={config}
          lang={lang}
          t={t}
          saving={saving}
          onSave={onQuickConfigSave}
        />

        {missingDeps.map((dep) => (
          <DepRow key={dep.key} dep={dep} installing={installing} t={t} onInstall={onInstall} />
        ))}

        {meta.link && (
          <Link
            href={meta.link.href}
            className={`flow-open-link ${meta.link.primary ? "flow-open-link--primary" : ""}`}
            onClick={(event) => event.stopPropagation()}
          >
            {t(meta.link.labelKey)}
            <span className="flow-open-arrow"><ArrowIcon /></span>
          </Link>
        )}
      </div>
    </div>
  );
}
