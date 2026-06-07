import React, { useEffect, useMemo, useState } from "react";
import type { EffectiveConfig, PipelineStage } from "@/lib/api";
import type { I18nKey, Lang } from "@/lib/i18n";
import { backendLabel, type FlowStageId } from "./model";

export type FlowConfigSnapshot = EffectiveConfig;
export type QuickConfigValue = string | number | boolean;
export type QuickConfigValues = Record<string, string | boolean>;
export type QuickConfigUpdate = { section: string; key: string; value: QuickConfigValue };

type ConfigSection = "source_store" | "r2_sync" | "notion_sync" | "graph" | "vector_db" | "embedding";

type QuickConfigFieldBase = {
  id: string;
  section: ConfigSection;
  key: string;
  labelKey: I18nKey;
  wide?: boolean;
};

type QuickConfigField =
  | (QuickConfigFieldBase & { kind: "text"; value: string; placeholder?: string })
  | (QuickConfigFieldBase & { kind: "number"; value: string })
  | (QuickConfigFieldBase & { kind: "boolean"; value: boolean })
  | (QuickConfigFieldBase & { kind: "select"; value: string; options: string[] });

type QuickConfigModel = {
  fields: QuickConfigField[];
  hints: I18nKey[];
};

const QUERY_MODES = ["mix", "local", "global", "hybrid", "naive", "bypass"];
const LIGHTRAG_LLM_PROVIDERS = ["main", "local", "api"];

function fieldId(section: ConfigSection, key: string): string {
  return `${section}.${key}`;
}

function textField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  wide = false,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "text", section, key, labelKey, value, wide };
}

function numberField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "number", section, key, labelKey, value };
}

function booleanField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: boolean,
): QuickConfigField {
  return { id: fieldId(section, key), kind: "boolean", section, key, labelKey, value };
}

function selectField(
  section: ConfigSection,
  key: string,
  labelKey: I18nKey,
  value: string,
  options: string[],
): QuickConfigField {
  return { id: fieldId(section, key), kind: "select", section, key, labelKey, value, options };
}

function sectionData(config: FlowConfigSnapshot, section: ConfigSection): Record<string, unknown> {
  return (config[section] ?? {}) as Record<string, unknown>;
}

function readString(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback = ""): string {
  const value = sectionData(config, section)[key];
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function readNumberString(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback: number): string {
  const value = sectionData(config, section)[key];
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? String(parsed) : String(fallback);
}

function readBoolean(config: FlowConfigSnapshot, section: ConfigSection, key: string, fallback: boolean): boolean {
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
  const fields: QuickConfigField[] = [];
  const hints: I18nKey[] = [];

  if (id === "ingest") {
    fields.push(booleanField("source_store", "ocr_enabled", "flow_quick_ocr_enabled", readBoolean(config, "source_store", "ocr_enabled", false)));
    return { fields, hints };
  }

  if (id === "embedding") {
    const provider = readString(config, "embedding", "provider", stage.current);
    const modelFallback = stageStringDetail(stage, "model");
    fields.push(textField("embedding", "model", "flow_quick_model", readString(config, "embedding", "model", modelFallback), true));
    if (provider === "external") {
      fields.push(textField("embedding", "base_url", "flow_quick_base_url", readString(config, "embedding", "base_url"), true));
      hints.push("flow_quick_api_key_hint");
    } else {
      hints.push("flow_quick_local_embedding_hint");
    }
    return { fields, hints };
  }

  if (id === "vector_store") {
    const backend = readString(config, "vector_db", "backend", stage.current);
    if (backend === "milvus") {
      fields.push(booleanField("vector_db", "auto_index_enabled", "flow_quick_auto_index_enabled", readBoolean(config, "vector_db", "auto_index_enabled", true)));
    }
    return { fields, hints };
  }

  if (id === "graph") {
    const enabled = readBoolean(config, "graph", "enabled", stage.current === "on");
    if (!enabled) return { fields, hints };
    fields.push(selectField("graph", "query_mode", "flow_quick_query_mode", readString(config, "graph", "query_mode", "mix"), QUERY_MODES));
    fields.push(numberField("graph", "llm_max_async", "flow_quick_llm_max_async", readNumberString(config, "graph", "llm_max_async", 4)));
    fields.push(numberField("graph", "embedding_max_async", "flow_quick_embedding_max_async", readNumberString(config, "graph", "embedding_max_async", 8)));
    fields.push(numberField("graph", "max_doc_chars", "flow_quick_max_doc_chars", readNumberString(config, "graph", "max_doc_chars", 30000)));
    fields.push(selectField("graph", "lightrag_llm_provider", "flow_quick_lightrag_llm_provider", readString(config, "graph", "lightrag_llm_provider", "main"), LIGHTRAG_LLM_PROVIDERS));
    fields.push(textField("graph", "lightrag_llm_base_url", "flow_quick_lightrag_llm_base_url", readString(config, "graph", "lightrag_llm_base_url"), true));
    fields.push(textField("graph", "lightrag_llm_model", "flow_quick_lightrag_llm_model", readString(config, "graph", "lightrag_llm_model"), true));
    fields.push(numberField("graph", "lightrag_llm_timeout_seconds", "flow_quick_lightrag_llm_timeout_seconds", readNumberString(config, "graph", "lightrag_llm_timeout_seconds", 900)));
    hints.push("flow_quick_lightrag_llm_hint");
    return { fields, hints };
  }

  if (id === "sync") {
    fields.push(booleanField("r2_sync", "enabled", "flow_quick_r2_enabled", readBoolean(config, "r2_sync", "enabled", false)));
    fields.push(booleanField("notion_sync", "enabled", "flow_quick_notion_enabled", readBoolean(config, "notion_sync", "enabled", false)));
    hints.push("flow_quick_sync_secret_hint");
    return { fields, hints };
  }

  return { fields, hints };
}

function fieldInitialValue(field: QuickConfigField): string | boolean {
  return field.kind === "boolean" ? field.value : field.value;
}

function graphModeLabel(value: string, t: (k: I18nKey) => string): string {
  const key = `graph_mode_${value}` as I18nKey;
  return t(key);
}

function FieldControl({
  field,
  value,
  lang,
  t,
  saving,
  onChange,
}: {
  field: QuickConfigField;
  value: string | boolean;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  onChange: (value: string | boolean) => void;
}) {
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
    return (
      <select
        className="flow-quick-select"
        value={String(value)}
        disabled={saving}
        onChange={(event) => onChange(event.target.value)}
      >
        {field.options.map((option) => (
          <option key={option} value={option}>
            {field.section === "graph" && field.key === "query_mode" ? graphModeLabel(option, t) : backendLabel(option, lang)}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
      className="flow-quick-input"
      type={field.kind === "number" ? "number" : "text"}
      inputMode={field.kind === "number" ? "numeric" : undefined}
      min={field.kind === "number" ? 1 : undefined}
      value={String(value)}
      disabled={saving}
      placeholder={field.kind === "text" ? field.placeholder : undefined}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export function QuickConfigPanel({
  stage,
  config,
  lang,
  t,
  saving,
  onSave,
}: {
  stage: PipelineStage;
  config: FlowConfigSnapshot;
  lang: Lang;
  t: (k: I18nKey) => string;
  saving: boolean;
  onSave: (stageId: FlowStageId, updates: QuickConfigUpdate[]) => void;
}) {
  const model = useMemo(() => buildQuickConfig(stage, config), [config, stage]);
  const fieldSignature = useMemo(
    () => model.fields.map((field) => `${field.id}:${String(fieldInitialValue(field))}`).join("|"),
    [model.fields],
  );
  const [draft, setDraft] = useState<QuickConfigValues>({});

  useEffect(() => {
    const next: QuickConfigValues = {};
    for (const field of model.fields) next[field.id] = fieldInitialValue(field);
    setDraft(next);
  }, [fieldSignature, model.fields]);

  const { updates, hasInvalidNumber } = useMemo(() => {
    const nextUpdates: QuickConfigUpdate[] = [];
    let invalid = false;

    for (const field of model.fields) {
      const current = draft[field.id] ?? fieldInitialValue(field);
      const initial = fieldInitialValue(field);

      if (field.kind === "boolean") {
        const value = Boolean(current);
        if (value !== field.value) nextUpdates.push({ section: field.section, key: field.key, value });
        continue;
      }

      const raw = String(current);
      if (raw === String(initial)) continue;

      if (field.kind === "number") {
        if (raw.trim() === "") continue;
        const parsed = Number(raw);
        if (!Number.isFinite(parsed) || parsed <= 0) {
          invalid = true;
          continue;
        }
        nextUpdates.push({ section: field.section, key: field.key, value: parsed });
        continue;
      }

      nextUpdates.push({ section: field.section, key: field.key, value: raw });
    }

    return { updates: nextUpdates, hasInvalidNumber: invalid };
  }, [draft, model.fields]);

  if (model.fields.length === 0 && model.hints.length === 0) return null;

  const canSave = updates.length > 0 && !hasInvalidNumber && !saving;
  const stageId = stage.id as FlowStageId;

  return (
    <div
      className="flow-quick-config"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flow-quick-config-head">
        <span>{t("flow_quick_title")}</span>
        <button
          type="button"
          className="flow-quick-save"
          disabled={!canSave}
          onClick={() => onSave(stageId, updates)}
        >
          {saving ? t("flow_quick_saving") : t("flow_quick_save")}
        </button>
      </div>

      {model.fields.length > 0 && (
        <div className="flow-quick-grid">
          {model.fields.map((field) => (
            <label key={field.id} className={`flow-quick-field ${field.wide ? "flow-quick-field--wide" : ""}`}>
              <span>{t(field.labelKey)}</span>
              <FieldControl
                field={field}
                value={draft[field.id] ?? fieldInitialValue(field)}
                lang={lang}
                t={t}
                saving={saving}
                onChange={(value) => setDraft((current) => ({ ...current, [field.id]: value }))}
              />
            </label>
          ))}
        </div>
      )}

      {hasInvalidNumber && <div className="flow-quick-error">{t("flow_quick_number_invalid")}</div>}
      {model.hints.map((hint) => <div key={hint} className="flow-quick-hint">{t(hint)}</div>)}
    </div>
  );
}
