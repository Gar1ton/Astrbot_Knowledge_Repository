import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { EffectiveConfig, PipelineStage } from "@/lib/api";
import type { I18nKey, Lang } from "@/lib/i18n";
import { backendLabel, type FlowStageId } from "./model";
import { DirPickerDialog } from "./DirPickerDialog";
import { ZoteroQuickConfig } from "./ZoteroQuickConfig";

export type FlowConfigSnapshot = EffectiveConfig;
export type QuickConfigValue = string | number | boolean;
export type QuickConfigValues = Record<string, string | boolean>;
export type QuickConfigUpdate = { section: string; key: string; value: QuickConfigValue };

export type ConfigSection =
  | "source_store"
  | "r2_sync"
  | "notion_sync"
  | "graph"
  | "vector_db"
  | "embedding"
  | "zotero_sync"
  | "rerank"
  | "deep_thinking";

// 由各 panel 上报给 FlowNode 头部徽章的草稿态；徽章据此变「保存」。
export type QuickConfigDirty = { count: number; canSave: boolean };
// FlowNode 通过 ref 触发 panel 提交（头部徽章充当唯一保存入口）。
export type QuickConfigHandle = { save: () => void };

export const ZOTERO_SYNC_MODES = ["strict_mirror", "conservative", "archive"];
export const ZOTERO_STORAGE_MODES = ["managed_copy", "linked"];

type QuickConfigFieldBase = {
  id: string;
  section: ConfigSection;
  key: string;
  labelKey: I18nKey;
  wide?: boolean;
  helpKey?: I18nKey;
};

export type QuickConfigField =
  | (QuickConfigFieldBase & { kind: "text"; value: string; placeholder?: string; browseDir?: boolean })
  | (QuickConfigFieldBase & { kind: "number"; value: string; min?: number; step?: number })
  | (QuickConfigFieldBase & { kind: "boolean"; value: boolean })
  | (QuickConfigFieldBase & { kind: "select"; value: string; options: string[] })
  | (QuickConfigFieldBase & { kind: "readonly"; value: string });

// 三段式：required（保证该模块能 run 的必要配置）+ advanced（可折叠的全部相关可写设置）。
type QuickConfigModel = {
  required: QuickConfigField[];
  advanced: QuickConfigField[];
  hints: I18nKey[];
};

const QUERY_MODES = ["mix", "local", "global", "hybrid", "naive", "bypass"];
const RERANK_PROVIDERS = ["cross_encoder", "noop"];
const LIGHTRAG_LLM_PROVIDERS = ["main", "external"];

function fieldId(section: ConfigSection, key: string): string {
  return `${section}.${key}`;
}

export function textField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  wide = false,
  browseDir = false,
  helpKey?: I18nKey,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "text", section, key, labelKey, value, wide, browseDir, helpKey };
}

export function numberField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  helpKey?: I18nKey,
  min = 1,
  step?: number,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "number", section, key, labelKey, value, helpKey, min, step };
}

export function booleanField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: boolean,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "boolean", section, key, labelKey, value };
}

export function selectField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  options: string[],
  wide = false,
  helpKey?: I18nKey,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "select", section, key, labelKey, value, options, wide, helpKey };
}

export function readonlyField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  wide = false,
  helpKey?: I18nKey,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "readonly", section, key, labelKey, value, wide, helpKey };
}

function sectionData(config: FlowConfigSnapshot, section: ConfigSection): Record<string, unknown> {
  return (config[section] ?? {}) as Record<string, unknown>;
}

export function readString(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback = ""): string {
  const value = sectionData(config, section)[key];
  if (value === null || value === undefined) return fallback;
  return String(value);
}

export function readNumberString(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback: number): string {
  const value = sectionData(config, section)[key];
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? String(parsed) : String(fallback);
}

export function readBoolean(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback: boolean): boolean {
  const value = sectionData(config, section)[key];
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value.toLowerCase() === "true";
  if (typeof value === "number") return value !== 0;
  return fallback;
}

function stageStringDetail(stage: PipelineStage, key: string, fallback = ""): string {
  const value = stage.detail[key];
  return value === null || value === undefined ? fallback : String(value);
}

function buildQuickConfig(stage: PipelineStage, config: FlowConfigSnapshot): QuickConfigModel {
  const id = stage.id as FlowStageId;
  const required: QuickConfigField[] = [];
  const advanced: QuickConfigField[] = [];
  const hints: I18nKey[] = [];

  // Zotero 阶段由独立的 <ZoteroQuickConfig> 渲染（标签式面板），不走通用字段模型。

  if (id === "ingest") {
    required.push(booleanField("source_store", "ocr_enabled", "flow_quick_ocr_enabled", readBoolean(config, "source_store", "ocr_enabled", false)));
    advanced.push(textField("source_store", "default_collection", "flow_quick_default_collection", readString(config, "source_store", "default_collection", "default"), true));
    return { required, advanced, hints };
  }

  if (id === "embedding") {
    const provider = readString(config, "embedding", "provider", stage.current);
    const modelFallback = stageStringDetail(stage, "model");
    required.push(textField("embedding", "model", "flow_quick_model", readString(config, "embedding", "model", modelFallback), true));
    if (provider === "external") {
      required.push(textField("embedding", "base_url", "flow_quick_base_url", readString(config, "embedding", "base_url"), true));
      hints.push("flow_quick_api_key_hint");
    } else {
      hints.push("flow_quick_local_embedding_hint");
    }
    return { required, advanced, hints };
  }

  if (id === "vector_store") {
    const backend = readString(config, "vector_db", "backend", stage.current);
    if (backend === "milvus") {
      required.push(booleanField("vector_db", "auto_index_enabled", "flow_quick_auto_index_enabled", readBoolean(config, "vector_db", "auto_index_enabled", true)));
    }
    return { required, advanced, hints };
  }

  if (id === "graph") {
    const enabled = readBoolean(config, "graph", "enabled", stage.current === "on");
    if (!enabled) return { required, advanced, hints };
    required.push(selectField("graph", "query_mode", "flow_quick_query_mode", readString(config, "graph", "query_mode", "mix"), QUERY_MODES));
    // 高级：LightRAG 专用 LLM + 并发/容量调参（全部 api 可写）。working_dir 为结构性参数，只读展示。
    advanced.push(selectField("graph", "lightrag_llm_provider", "flow_quick_lightrag_llm_provider", readString(config, "graph", "lightrag_llm_provider", "main"), LIGHTRAG_LLM_PROVIDERS));
    advanced.push(textField("graph", "lightrag_llm_base_url", "flow_quick_lightrag_llm_base_url", readString(config, "graph", "lightrag_llm_base_url"), true));
    advanced.push(textField("graph", "lightrag_llm_model", "flow_quick_lightrag_llm_model", readString(config, "graph", "lightrag_llm_model"), true));
    advanced.push(numberField("graph", "lightrag_llm_timeout_seconds", "flow_quick_lightrag_llm_timeout_seconds", readNumberString(config, "graph", "lightrag_llm_timeout_seconds", 900)));
    advanced.push(numberField("graph", "llm_max_async", "flow_quick_llm_max_async", readNumberString(config, "graph", "llm_max_async", 4)));
    advanced.push(numberField("graph", "embedding_max_async", "flow_quick_embedding_max_async", readNumberString(config, "graph", "embedding_max_async", 8)));
    advanced.push(numberField("graph", "max_doc_chars", "flow_quick_max_doc_chars", readNumberString(config, "graph", "max_doc_chars", 30000)));
    advanced.push(readonlyField("graph", "working_dir", "flow_quick_graph_working_dir", readString(config, "graph", "working_dir"), true, "flow_quick_graph_working_dir_help"));
    return { required, advanced, hints };
  }

  if (id === "ask") {
    required.push(
      selectField(
        "rerank",
        "provider",
        "flow_quick_rerank_provider",
        readString(config, "rerank", "provider", stageStringDetail(stage, "rerank_provider", "noop")),
        RERANK_PROVIDERS,
        false,
        "flow_quick_rerank_provider_help",
      ),
    );
    required.push(
      textField(
        "rerank",
        "model",
        "flow_quick_rerank_model",
        readString(config, "rerank", "model", stageStringDetail(stage, "rerank_model", "Alibaba-NLP/gte-reranker-modernbert-base")),
        true,
        false,
        "flow_quick_rerank_model_help",
      ),
    );
    required.push(
      readonlyField(
        "rerank",
        "runtime_status",
        "flow_quick_rerank_status",
        stageStringDetail(stage, "rerank_status", "off"),
        true,
      ),
    );
    // 高级：Deep Thinking（FAIR-RAG 迭代检索）全部 api 可写键。
    advanced.push(numberField("deep_thinking", "max_rounds", "flow_quick_dt_max_rounds", readNumberString(config, "deep_thinking", "max_rounds", 4)));
    advanced.push(numberField("deep_thinking", "max_sub_queries", "flow_quick_dt_max_sub_queries", readNumberString(config, "deep_thinking", "max_sub_queries", 4)));
    advanced.push(numberField("deep_thinking", "wide_top_k", "flow_quick_dt_wide_top_k", readNumberString(config, "deep_thinking", "wide_top_k", 24)));
    advanced.push(numberField("deep_thinking", "rerank_weight", "flow_quick_dt_rerank_weight", readNumberString(config, "deep_thinking", "rerank_weight", 0.2), undefined, 0, 0.05));
    advanced.push(booleanField("deep_thinking", "verify_enabled", "flow_quick_dt_verify_enabled", readBoolean(config, "deep_thinking", "verify_enabled", true)));
    advanced.push(numberField("deep_thinking", "max_verify_rounds", "flow_quick_dt_max_verify_rounds", readNumberString(config, "deep_thinking", "max_verify_rounds", 1)));
    advanced.push(textField("deep_thinking", "llm_base_url", "flow_quick_dt_llm_base_url", readString(config, "deep_thinking", "llm_base_url"), true));
    advanced.push(textField("deep_thinking", "llm_model", "flow_quick_dt_llm_model", readString(config, "deep_thinking", "llm_model"), true));
    hints.push("flow_quick_rerank_hint");
    return { required, advanced, hints };
  }

  if (id === "sync") {
    required.push(booleanField("r2_sync", "enabled", "flow_quick_r2_enabled", readBoolean(config, "r2_sync", "enabled", false)));
    required.push(booleanField("notion_sync", "enabled", "flow_quick_notion_enabled", readBoolean(config, "notion_sync", "enabled", false)));
    hints.push("flow_quick_sync_secret_hint");
    return { required, advanced, hints };
  }

  return { required, advanced, hints };
}

export function fieldInitialValue(field: QuickConfigField): string | boolean {
  return field.kind === "boolean" ? field.value : field.value;
}

function graphModeLabel(value: string, t: (k: I18nKey) => string): string {
  const key = `graph_mode_${value}` as I18nKey;
  return t(key);
}

// ─── Flow-themed custom select ────────────────────────────────

interface FlowSelectProps {
  value: string;
  options: string[];
  disabled: boolean;
  getLabel: (v: string) => string;
  onChange: (v: string) => void;
}

function FlowSelect({ value, options, disabled, getLabel, onChange }: FlowSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="flow-custom-select" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`flow-custom-select-trigger${open ? " is-open" : ""}${disabled ? " is-disabled" : ""}`}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flow-custom-select-label">{getLabel(value)}</span>
        <svg
          width="11" height="11" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          className={`flow-custom-select-chevron${open ? " is-open" : ""}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div className="flow-custom-select-menu">
          {options.map((opt) => {
            const isActive = opt === value;
            return (
              <button
                key={opt}
                type="button"
                className={`flow-custom-select-opt${isActive ? " is-active" : ""}`}
                onClick={() => { onChange(opt); setOpen(false); }}
              >
                {isActive ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="flow-custom-select-check">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <span className="flow-custom-select-check" />
                )}
                {getLabel(opt)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Field control ────────────────────────────────────────────

export function FieldControl({
  field,
  value,
  lang,
  t,
  saving,
  onChange,
  onBrowseDir,
}: {
  field: QuickConfigField;
  value: string | boolean;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  onChange: (value: string | boolean) => void;
  onBrowseDir?: () => void;
}) {
  if (field.kind === "readonly") {
    const raw = String(value);
    const display = raw
      ? field.id === "rerank.runtime_status"
        ? backendLabel(raw, lang)
        : raw
      : t("flow_value_empty");
    return (
      <div
        className={`flow-quick-readonly ${raw ? "" : "is-empty"}`}
        title={raw || undefined}
      >
        {display}
      </div>
    );
  }

  if (field.kind === "boolean") {
    const enabled = Boolean(value);
    return (
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        className={`flow-quick-toggle ${enabled ? "is-on" : ""}`}
        disabled={saving}
        onClick={() => onChange(!enabled)}
      >
        <span className="flow-quick-toggle-knob" />
        {enabled ? t("flow_quick_on") : t("flow_quick_off")}
      </button>
    );
  }

  if (field.kind === "select") {
    const getLabel =
      field.section === "graph" && field.key === "query_mode"
        ? (v: string) => graphModeLabel(v, t)
        : (v: string) => backendLabel(v, lang);
    return (
      <FlowSelect
        value={String(value)}
        options={field.options}
        disabled={saving}
        getLabel={getLabel}
        onChange={onChange}
      />
    );
  }

  if (field.kind === "text" && field.browseDir) {
    return (
      <div className="flow-quick-dir-row">
        <input
          className="flow-quick-input"
          type="text"
          value={String(value)}
          disabled={saving}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="flow-quick-dir-btn"
          disabled={saving}
          title={t("dir_picker_title")}
          onClick={onBrowseDir}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <input
      className="flow-quick-input"
      type={field.kind === "number" ? "number" : "text"}
      inputMode={field.kind === "number" ? (field.step ? "decimal" : "numeric") : undefined}
      min={field.kind === "number" ? (field.min ?? 1) : undefined}
      step={field.kind === "number" ? field.step : undefined}
      value={String(value)}
      disabled={saving}
      placeholder={field.kind === "text" ? field.placeholder : undefined}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

// ─── 共享：草稿计算 + hook + 字段网格 + 高级折叠 ────────────────

// 比对 draft 与初值得出待提交 updates（required+advanced 合并；Generic 与 Zotero 共用）。
export function computeUpdates(
  fields: QuickConfigField[],
  draft: QuickConfigValues,
): { updates: QuickConfigUpdate[]; hasInvalidNumber: boolean } {
  const updates: QuickConfigUpdate[] = [];
  let hasInvalidNumber = false;

  for (const field of fields) {
    const current = draft[field.id] ?? fieldInitialValue(field);
    const initial = fieldInitialValue(field);

    if (field.kind === "readonly") continue;

    if (field.kind === "boolean") {
      const value = Boolean(current);
      if (value !== field.value) updates.push({ section: field.section, key: field.key, value });
      continue;
    }

    const raw = String(current);
    if (raw === String(initial)) continue;

    if (field.kind === "number") {
      if (raw.trim() === "") continue;
      const parsed = Number(raw);
      const min = field.min ?? 1;
      if (!Number.isFinite(parsed) || parsed < min) {
        hasInvalidNumber = true;
        continue;
      }
      updates.push({ section: field.section, key: field.key, value: parsed });
      continue;
    }

    updates.push({ section: field.section, key: field.key, value: raw });
  }

  return { updates, hasInvalidNumber };
}

function buildDraftFromFields(fields: QuickConfigField[]): QuickConfigValues {
  const next: QuickConfigValues = {};
  for (const field of fields) next[field.id] = fieldInitialValue(field);
  return next;
}

// 字段集 → 草稿态。字段签名变化时以派生初始值重置草稿，并即时计算 updates。
export function useQuickConfigDraft(fields: QuickConfigField[]) {
  const fieldSignature = useMemo(
    () => fields.map((f) => `${f.id}:${String(fieldInitialValue(f))}`).join("|"),
    [fields],
  );
  const initialDraft = useMemo(() => buildDraftFromFields(fields), [fields]);
  const [draftState, setDraftState] = useState(() => ({
    signature: fieldSignature,
    values: initialDraft,
  }));
  const draft = draftState.signature === fieldSignature ? draftState.values : initialDraft;
  const setDraft = useCallback<React.Dispatch<React.SetStateAction<QuickConfigValues>>>(
    (updater) => {
      setDraftState((current) => {
        const base = current.signature === fieldSignature ? current.values : initialDraft;
        const values = typeof updater === "function" ? updater(base) : updater;
        return { signature: fieldSignature, values };
      });
    },
    [fieldSignature, initialDraft],
  );

  const { updates, hasInvalidNumber } = useMemo(() => computeUpdates(fields, draft), [draft, fields]);
  return { draft, setDraft, updates, hasInvalidNumber };
}

export function QuickConfigFieldGrid({
  fields,
  draft,
  setDraft,
  lang,
  t,
  saving,
  onBrowseDir,
}: {
  fields: QuickConfigField[];
  draft: QuickConfigValues;
  setDraft: React.Dispatch<React.SetStateAction<QuickConfigValues>>;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  onBrowseDir?: (fieldId: string) => void;
}) {
  return (
    <div className="flow-quick-grid">
      {fields.map((field) => (
        <label key={field.id} className={`flow-quick-field ${field.wide ? "flow-quick-field--wide" : ""}`}>
          <span>
            {t(field.labelKey)}
            {field.helpKey && <span className="flow-help-dot" title={t(field.helpKey)}>?</span>}
          </span>
          <FieldControl
            field={field}
            value={draft[field.id] ?? fieldInitialValue(field)}
            lang={lang}
            t={t}
            saving={saving}
            onChange={(value) => setDraft((current) => ({ ...current, [field.id]: value }))}
            onBrowseDir={() => onBrowseDir?.(field.id)}
          />
        </label>
      ))}
    </div>
  );
}

// 高级折叠：折叠按钮 + 展开浮层。slot 非空时整体 Portal 到节点底部槽位（按钮在节点最底部，
// 浮层紧贴节点底）；展开浮层绝对定位、不计入节点测量高度，故展开/收起不影响边对齐。
export function AdvancedSection({
  open,
  onToggle,
  label,
  slot,
  children,
}: React.PropsWithChildren<{ open: boolean; onToggle: () => void; label: string; slot?: HTMLElement | null }>) {
  const content = (
    <div className="flow-quick-advanced" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
      <button type="button" className="flow-quick-advanced-toggle" onClick={onToggle}>
        <span className={`flow-quick-advanced-caret ${open ? "is-open" : ""}`}>▸</span>
        {label}
      </button>
      {open && <div className="flow-quick-advanced-panel">{children}</div>}
    </div>
  );
  return slot ? createPortal(content, slot) : content;
}

// ─── Panel ────────────────────────────────────────────────────

export type QuickConfigPanelProps = {
  stage: PipelineStage;
  config: FlowConfigSnapshot;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  onSave: (stageId: FlowStageId, updates: QuickConfigUpdate[]) => void;
  onRefresh?: () => Promise<void>;
  // 头部徽章充当唯一保存入口：panel 上报草稿态，FlowNode 通过 ref 触发提交。
  onDirtyChange?: (state: QuickConfigDirty) => void;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  // 高级折叠 Portal 到的节点底部槽位（FlowNode 提供）。
  advancedSlot?: HTMLElement | null;
};

const GenericQuickConfig = forwardRef<QuickConfigHandle, QuickConfigPanelProps>(function GenericQuickConfig(
  { stage, config, lang, t, saving, onSave, onDirtyChange, advancedOpen, onToggleAdvanced, advancedSlot },
  ref,
) {
  const model = useMemo(() => buildQuickConfig(stage, config), [config, stage]);
  const allFields = useMemo(() => [...model.required, ...model.advanced], [model]);
  const { draft, setDraft, updates, hasInvalidNumber } = useQuickConfigDraft(allFields);
  const [dirPickerFieldId, setDirPickerFieldId] = useState<string | null>(null);

  const canSave = updates.length > 0 && !hasInvalidNumber && !saving;
  const stageId = stage.id as FlowStageId;

  useImperativeHandle(
    ref,
    () => ({
      save: () => {
        if (updates.length > 0 && !hasInvalidNumber && !saving) onSave(stageId, updates);
      },
    }),
    [updates, hasInvalidNumber, saving, onSave, stageId],
  );

  useEffect(() => {
    onDirtyChange?.({ count: updates.length, canSave });
  }, [updates.length, canSave, onDirtyChange]);

  const dirPickerField = dirPickerFieldId
    ? (allFields.find((f) => f.id === dirPickerFieldId) ?? null)
    : null;

  const handleDirSelect = useCallback((path: string) => {
    if (!dirPickerFieldId) return;
    setDraft((cur) => ({ ...cur, [dirPickerFieldId]: path }));
    setDirPickerFieldId(null);
  }, [dirPickerFieldId, setDraft]);

  if (model.required.length === 0 && model.advanced.length === 0 && model.hints.length === 0) return null;

  return (
    <>
      <div
        className="flow-quick-config"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {model.required.length > 0 && (
          <QuickConfigFieldGrid
            fields={model.required}
            draft={draft}
            setDraft={setDraft}
            lang={lang}
            t={t}
            saving={saving}
            onBrowseDir={setDirPickerFieldId}
          />
        )}

        {hasInvalidNumber && <div className="flow-quick-error">{t("flow_quick_number_invalid")}</div>}
        {model.hints.map((hint) => <div key={hint} className="flow-quick-hint">{t(hint)}</div>)}

        {model.advanced.length > 0 && (
          <AdvancedSection open={advancedOpen} onToggle={onToggleAdvanced} label={t("flow_quick_advanced")} slot={advancedSlot}>
            <QuickConfigFieldGrid
              fields={model.advanced}
              draft={draft}
              setDraft={setDraft}
              lang={lang}
              t={t}
              saving={saving}
              onBrowseDir={setDirPickerFieldId}
            />
          </AdvancedSection>
        )}
      </div>

      {dirPickerField && (
        <DirPickerDialog
          initialPath={
            dirPickerField.kind === "text"
              ? (String(draft[dirPickerField.id] ?? dirPickerField.value) || undefined)
              : undefined
          }
          t={t}
          onSelect={handleDirSelect}
          onClose={() => setDirPickerFieldId(null)}
        />
      )}
    </>
  );
});

// Zotero 阶段走标签式专用面板，其余阶段走通用字段面板。
export const QuickConfigPanel = forwardRef<QuickConfigHandle, QuickConfigPanelProps>(function QuickConfigPanel(props, ref) {
  if (props.stage.id === "zotero") return <ZoteroQuickConfig ref={ref} {...props} />;
  return <GenericQuickConfig ref={ref} {...props} />;
});
