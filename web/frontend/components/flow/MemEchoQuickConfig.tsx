import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import {
  clearMemEchoApiKey,
  createMemEchoVault,
  getMemEchoConfig,
  importCollectionToMemEcho,
  listMemEchoVaults,
  probeMemEcho,
  saveMemEchoApiKey,
  type MemEchoConfig,
  type MemEchoProbeResult,
  type MemEchoVault,
} from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import {
  AdvancedSection,
  FieldControl,
  booleanField,
  fieldInitialValue,
  numberField,
  readBoolean,
  readNumberString,
  readString,
  textField,
  useQuickConfigDraft,
  type QuickConfigField,
  type QuickConfigHandle,
  type QuickConfigPanelProps,
} from "./QuickConfigPanel";

const ADVANCED_KEYS = new Set([
  "query_readonly",
  "write_back_enabled",
  "timeout_seconds",
  "import_timeout_seconds",
  "import_preset",
]);

// memecho 段的可编辑字段（enabled 由节点头部开关切换，不在此列；API Key 走独立机密框）。
function editableFields(config: QuickConfigPanelProps["config"]): QuickConfigField[] {
  return [
    textField(
      "memecho",
      "base_url",
      "flow_quick_memecho_base_url",
      readString(config, "memecho", "base_url", "https://api.artific.social"),
      true,
    ),
    textField(
      "memecho",
      "default_vault_id",
      "flow_quick_memecho_vault",
      readString(config, "memecho", "default_vault_id"),
      true,
    ),
    booleanField(
      "memecho",
      "query_readonly",
      "flow_quick_memecho_query_readonly",
      readBoolean(config, "memecho", "query_readonly", true),
    ),
    booleanField(
      "memecho",
      "write_back_enabled",
      "flow_quick_memecho_write_back",
      readBoolean(config, "memecho", "write_back_enabled", false),
    ),
    numberField(
      "memecho",
      "timeout_seconds",
      "flow_quick_memecho_timeout",
      readNumberString(config, "memecho", "timeout_seconds", 30),
    ),
    // 导入是 SSE 长任务，与上面的普通请求超时分档（后端 memecho.import_timeout_seconds）。
    numberField(
      "memecho",
      "import_timeout_seconds",
      "flow_quick_memecho_import_timeout",
      readNumberString(config, "memecho", "import_timeout_seconds", 300),
    ),
    textField(
      "memecho",
      "import_preset",
      "flow_quick_memecho_import_preset",
      readString(config, "memecho", "import_preset", "default"),
      true,
    ),
  ];
}

export const MemEchoQuickConfig = forwardRef<QuickConfigHandle, QuickConfigPanelProps>(
  function MemEchoQuickConfig(
    { config, lang, t, saving, onSave, onRefresh, onDirtyChange, advancedOpen, onToggleAdvanced, advancedSlot },
    ref,
  ) {
    const { toast } = useToast();
    const fields = useMemo(() => editableFields(config), [config]);
    const { draft, setDraft, updates, hasInvalidNumber } = useQuickConfigDraft(fields);
    const canSave = updates.length > 0 && !hasInvalidNumber && !saving;

    useImperativeHandle(
      ref,
      () => ({ save: () => { if (canSave) onSave("memecho", updates); } }),
      [canSave, updates, onSave],
    );
    useEffect(() => {
      onDirtyChange?.({ count: updates.length, canSave });
    }, [updates.length, canSave, onDirtyChange]);

    const coreFields = fields.filter((f) => !ADVANCED_KEYS.has(f.key));
    const advancedFields = fields.filter((f) => ADVANCED_KEYS.has(f.key));

    // ── API Key（加密 secret_store；masked/present 单独取 memecho config）─────
    const [memechoCfg, setMemechoCfg] = useState<MemEchoConfig | null>(null);
    const [keyDraft, setKeyDraft] = useState("");
    const [keyBusy, setKeyBusy] = useState(false);
    const [keyError, setKeyError] = useState("");

    const reloadCfg = useCallback(async () => {
      try {
        setMemechoCfg(await getMemEchoConfig());
      } catch {
        /* 忽略：面板可用性不依赖此次刷新 */
      }
    }, []);
    useEffect(() => {
      void reloadCfg();
    }, [reloadCfg]);

    const cfgMemecho = (config.memecho ?? {}) as Record<string, unknown>;
    const keyPresent = memechoCfg?.api_key_present ?? Boolean(cfgMemecho.api_key_present);
    const keyMasked = memechoCfg?.api_key_masked ?? "";

    const handleKeySave = useCallback(async () => {
      const k = keyDraft.trim();
      if (!k) return;
      setKeyBusy(true);
      setKeyError("");
      try {
        await saveMemEchoApiKey(k);
        setKeyDraft("");
        await reloadCfg();
        await onRefresh?.();
      } catch (err: unknown) {
        setKeyError(err instanceof Error ? err.message : String(err));
      } finally {
        setKeyBusy(false);
      }
    }, [keyDraft, reloadCfg, onRefresh]);

    const handleKeyClear = useCallback(async () => {
      setKeyBusy(true);
      setKeyError("");
      try {
        await clearMemEchoApiKey();
        setKeyDraft("");
        await reloadCfg();
        await onRefresh?.();
      } catch (err: unknown) {
        setKeyError(err instanceof Error ? err.message : String(err));
      } finally {
        setKeyBusy(false);
      }
    }, [reloadCfg, onRefresh]);

    // ── 连通探针 + 记忆库列表 ───────────────────────────────────────
    const [probing, setProbing] = useState(false);
    const [probe, setProbe] = useState<MemEchoProbeResult | null>(null);
    const [vaults, setVaults] = useState<MemEchoVault[]>([]);

    const handleProbe = useCallback(async () => {
      setProbing(true);
      try {
        const p = await probeMemEcho();
        setProbe(p);
        if (p.ok) {
          try {
            setVaults(await listMemEchoVaults());
          } catch {
            /* vault 列举失败不影响连通判定 */
          }
        }
      } catch (err: unknown) {
        setProbe({ ok: false, error: err instanceof Error ? err.message : String(err) });
      } finally {
        setProbing(false);
      }
    }, []);

    const pickVault = useCallback(
      (id: string) => {
        setDraft((cur) => ({ ...cur, "memecho.default_vault_id": id }));
      },
      [setDraft],
    );
    const activeVault = String(draft["memecho.default_vault_id"] ?? readString(config, "memecho", "default_vault_id"));

    // ── 新建记忆库 ────────────────────────────────────────────────
    const [newVaultName, setNewVaultName] = useState("");
    const [creatingVault, setCreatingVault] = useState(false);
    const handleCreateVault = useCallback(async () => {
      const name = newVaultName.trim();
      if (!name) return;
      setCreatingVault(true);
      try {
        const v = await createMemEchoVault(name);
        setNewVaultName("");
        if (v.id) pickVault(v.id);
        toast(t("flow_quick_memecho_vault_created"), "ok");
        try {
          setVaults(await listMemEchoVaults());
        } catch {
          /* ignore */
        }
      } catch (err: unknown) {
        toast(err instanceof Error ? err.message : String(err), "error");
      } finally {
        setCreatingVault(false);
      }
    }, [newVaultName, pickVault, t, toast]);

    // ── 导入集合到记忆库（同步返回汇总）──────────────────────────────
    const [importCollection, setImportCollection] = useState("");
    const [importing, setImporting] = useState(false);
    const handleImport = useCallback(async () => {
      setImporting(true);
      try {
        const s = await importCollectionToMemEcho(importCollection.trim());
        toast(
          `${t("flow_quick_memecho_import_done")}: +${s.imported}/${s.total}`,
          s.failed.length ? "error" : "ok",
        );
      } catch (err: unknown) {
        toast(err instanceof Error ? err.message : String(err), "error");
      } finally {
        setImporting(false);
      }
    }, [importCollection, t, toast]);

    const renderField = (field: QuickConfigField) => (
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
          onChange={(value) => setDraft((cur) => ({ ...cur, [field.id]: value }))}
        />
      </label>
    );

    return (
      <div
        className="flow-quick-config"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {/* API Key（机密框） */}
        <div className="flow-zotero-key-box">
          <div className="flow-zotero-key-head">
            <span>
              {t("flow_quick_memecho_api_key")}
              <span className="flow-help-dot" title={t("flow_quick_memecho_api_key_help")}>?</span>
            </span>
            <code>{keyPresent ? (keyMasked || "****") : t("flow_value_empty")}</code>
          </div>
          <div className="flow-zotero-key-row">
            <input
              className="flow-quick-input"
              type="password"
              autoComplete="off"
              value={keyDraft}
              placeholder={t("flow_quick_memecho_api_key_placeholder")}
              disabled={saving || keyBusy}
              onChange={(event) => setKeyDraft(event.target.value)}
            />
            <button
              type="button"
              className="flow-quick-save"
              disabled={!keyDraft.trim() || saving || keyBusy}
              onClick={handleKeySave}
            >
              {keyBusy ? t("flow_quick_saving") : t("flow_quick_save_key")}
            </button>
            <button
              type="button"
              className="flow-quick-save flow-quick-save--ghost"
              disabled={!keyPresent || saving || keyBusy}
              onClick={handleKeyClear}
            >
              {t("flow_quick_clear_key")}
            </button>
          </div>
          {keyError && <div className="flow-quick-error">{keyError}</div>}
        </div>

        {/* 核心配置字段 */}
        <div className="flow-quick-grid">{coreFields.map(renderField)}</div>

        {/* 连通探针 */}
        <div className="flow-quick-diag">
          <span className={`flow-quick-dot ${probe?.ok ? "is-ok" : "is-off"}`} />
          <span className="flow-quick-diag-label">
            {probe
              ? probe.ok
                ? t("flow_quick_memecho_connected")
                : t("flow_quick_memecho_disconnected")
              : t("flow_quick_memecho_not_probed")}
          </span>
          <button
            type="button"
            className="flow-quick-save flow-quick-save--ghost"
            disabled={probing}
            onClick={handleProbe}
          >
            {probing ? t("flow_quick_memecho_probing") : t("flow_quick_memecho_probe")}
          </button>
          {probe?.ok && typeof probe.vault_count === "number" && (
            <span className="flow-quick-diag-counts">
              {t("flow_quick_memecho_vault_count")} {probe.vault_count}
            </span>
          )}
          {probe && !probe.ok && probe.error && (
            <span className="flow-quick-diag-counts" title={probe.error}>
              {probe.error}
            </span>
          )}
        </div>

        {/* 记忆库选择（探测后可用） */}
        {vaults.length > 0 && (
          <label className="flow-quick-field flow-quick-field--wide">
            <span>{t("flow_quick_memecho_pick_vault")}</span>
            <div className="flow-quick-modetab" role="tablist">
              {vaults.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  role="tab"
                  aria-selected={activeVault === v.id}
                  className={`flow-quick-modetab-btn ${activeVault === v.id ? "is-active" : ""}`}
                  onClick={() => pickVault(v.id)}
                  title={v.id}
                >
                  {v.name || v.id.slice(0, 8)}
                </button>
              ))}
            </div>
          </label>
        )}

        {/* 新建记忆库 */}
        <div className="flow-zotero-key-row">
          <input
            className="flow-quick-input"
            value={newVaultName}
            placeholder={t("flow_quick_memecho_new_vault_placeholder")}
            disabled={creatingVault}
            onChange={(event) => setNewVaultName(event.target.value)}
          />
          <button
            type="button"
            className="flow-quick-save"
            disabled={!newVaultName.trim() || creatingVault}
            onClick={handleCreateVault}
          >
            {creatingVault ? t("flow_quick_saving") : t("flow_quick_memecho_create_vault")}
          </button>
        </div>

        {/* 高级：只读/写回/超时/预设 + 集合导入 */}
        <AdvancedSection open={advancedOpen} onToggle={onToggleAdvanced} label={t("flow_quick_advanced")} slot={advancedSlot}>
          <div className="flow-quick-grid">{advancedFields.map(renderField)}</div>
          <div className="flow-quick-syncbar">
            <input
              className="flow-quick-input"
              value={importCollection}
              placeholder={t("flow_quick_memecho_import_collection_placeholder")}
              disabled={importing}
              onChange={(event) => setImportCollection(event.target.value)}
            />
            <button type="button" className="flow-quick-save" disabled={importing} onClick={handleImport}>
              {importing ? t("flow_quick_memecho_importing") : t("flow_quick_memecho_import")}
            </button>
          </div>
        </AdvancedSection>

        {hasInvalidNumber && <div className="flow-quick-error">{t("flow_quick_number_invalid")}</div>}
      </div>
    );
  },
);
