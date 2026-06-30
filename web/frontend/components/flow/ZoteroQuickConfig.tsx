import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import {
  deleteZoteroServerKey,
  getActiveZoteroSyncJob,
  getZoteroSyncStatus,
  probeZoteroLocal,
  resolveZoteroAccountChange,
  saveZoteroServerKey,
  syncZoteroPull,
  type ZoteroProbeResult,
  type ZoteroSyncResult,
  type ZoteroAccountChangeRequired,
} from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { Modal } from "@/components/ds/Modal";
import { Button } from "@/components/ds/Button";
import { DirPickerDialog } from "./DirPickerDialog";
import {
  AdvancedSection,
  FieldControl,
  ZOTERO_STORAGE_MODES,
  ZOTERO_SYNC_MODES,
  booleanField,
  fieldInitialValue,
  numberField,
  readBoolean,
  readNumberString,
  readString,
  selectField,
  textField,
  useQuickConfigDraft,
  type QuickConfigField,
  type QuickConfigHandle,
  type QuickConfigPanelProps,
} from "./QuickConfigPanel";

type AccessMode = "local" | "server";

// 当前 access_mode 下需要被 Save 按钮统一提交的可编辑字段（access_mode 由标签即时保存，不在此列）。
function editableFields(config: QuickConfigPanelProps["config"], tab: AccessMode): QuickConfigField[] {
  const fields: QuickConfigField[] = [];
  if (tab === "local") {
    fields.push(numberField("zotero_sync", "api_port", "flow_quick_zotero_api_port", readNumberString(config, "zotero_sync", "api_port", 23119), "flow_help_zotero_local_api"));
    fields.push(textField("zotero_sync", "zotero_data_dir", "flow_quick_zotero_data_dir_override", readString(config, "zotero_sync", "zotero_data_dir"), true, true));
  }
  // 高级（折叠）：同步与存储策略，两种模式共用。
  fields.push(selectField("zotero_sync", "sync_mode", "flow_quick_zotero_sync_mode", readString(config, "zotero_sync", "sync_mode", "conservative"), ZOTERO_SYNC_MODES, false, "flow_help_zotero_sync_mode"));
  const storageMode = readString(config, "zotero_sync", "storage_mode", "managed_copy");
  fields.push(selectField("zotero_sync", "storage_mode", "flow_quick_zotero_storage_mode", storageMode, ZOTERO_STORAGE_MODES));
  if (storageMode === "linked") {
    fields.push(textField("zotero_sync", "linked_root", "flow_quick_zotero_linked_root", readString(config, "zotero_sync", "linked_root"), true, false, "flow_help_zotero_linked_storage"));
  }
  fields.push(booleanField("zotero_sync", "auto_sync_enabled", "flow_quick_zotero_auto_sync", readBoolean(config, "zotero_sync", "auto_sync_enabled", false)));
  if (readBoolean(config, "zotero_sync", "auto_sync_enabled", false)) {
    fields.push(numberField("zotero_sync", "auto_sync_interval_sec", "flow_quick_zotero_interval", readNumberString(config, "zotero_sync", "auto_sync_interval_sec", 3600)));
  }
  return fields;
}

const ADVANCED_KEYS = new Set(["sync_mode", "storage_mode", "linked_root", "auto_sync_enabled", "auto_sync_interval_sec"]);

export const ZoteroQuickConfig = forwardRef<QuickConfigHandle, QuickConfigPanelProps>(function ZoteroQuickConfig(
  { config, lang, t, saving, onSave, onRefresh, onDirtyChange, advancedOpen, onToggleAdvanced, advancedSlot },
  ref,
) {
  const { toast } = useToast();
  const tab = (readString(config, "zotero_sync", "access_mode", "local") === "server" ? "server" : "local") as AccessMode;

  const fields = useMemo(() => editableFields(config, tab), [config, tab]);
  const { draft, setDraft, updates, hasInvalidNumber } = useQuickConfigDraft(fields);
  const [dirPickerFieldId, setDirPickerFieldId] = useState<string | null>(null);

  const dirPickerField = dirPickerFieldId ? (fields.find((f) => f.id === dirPickerFieldId) ?? null) : null;
  const handleDirSelect = useCallback((path: string) => {
    if (!dirPickerFieldId) return;
    setDraft((cur) => ({ ...cur, [dirPickerFieldId]: path }));
    setDirPickerFieldId(null);
  }, [dirPickerFieldId, setDraft]);

  const canSave = updates.length > 0 && !hasInvalidNumber && !saving;

  // 头部徽章充当唯一保存入口：上报草稿态 + 暴露 save。access_mode 标签切换/服务器 Key/立即同步仍各自保留按钮。
  useImperativeHandle(
    ref,
    () => ({
      save: () => {
        if (updates.length > 0 && !hasInvalidNumber && !saving) onSave("zotero", updates);
      },
    }),
    [updates, hasInvalidNumber, saving, onSave],
  );

  useEffect(() => {
    onDirtyChange?.({ count: updates.length, canSave });
  }, [updates.length, canSave, onDirtyChange]);

  // ── 标签切换：即时持久化 access_mode ───────────────────────────
  const switchTab = useCallback((mode: AccessMode) => {
    if (mode === tab) return;
    onSave("zotero", [{ section: "zotero_sync", key: "access_mode", value: mode }]);
  }, [onSave, tab]);

  // ── 服务器 API Key ────────────────────────────────────────────
  const serverKeyPresent = readBoolean(config, "zotero_sync", "server_key_present", false);
  const serverKeyMasked = readString(config, "zotero_sync", "server_key_masked");
  const serverUsername = readString(config, "zotero_sync", "server_username") || readString(config, "zotero_sync", "server_user_id");
  const [serverKeyDraft, setServerKeyDraft] = useState("");
  const [serverKeyBusy, setServerKeyBusy] = useState(false);
  const [serverKeyError, setServerKeyError] = useState("");
  const [accountChange, setAccountChange] = useState<ZoteroAccountChangeRequired | null>(null);

  const handleServerKeySave = useCallback(async () => {
    const key = serverKeyDraft.trim();
    if (!key) return;
    setServerKeyBusy(true);
    setServerKeyError("");
    try {
      const result = await saveZoteroServerKey(key);
      if ("status" in result && result.status === "account_change_required") {
        setAccountChange(result);
      } else {
        setServerKeyDraft("");
        await onRefresh?.();
      }
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeyBusy(false);
    }
  }, [onRefresh, serverKeyDraft]);

  const handleAccountChange = useCallback(async (action: "replace_local" | "cancel") => {
    if (!accountChange) return;
    setServerKeyBusy(true);
    try {
      await resolveZoteroAccountChange(accountChange.change_id, action);
      if (action === "replace_local") {
        setServerKeyDraft("");
        toast("Zotero 本地镜像已重置，新账号同步已启动", "ok");
      }
      setAccountChange(null);
      await onRefresh?.();
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeyBusy(false);
    }
  }, [accountChange, onRefresh, toast]);

  const handleServerKeyDelete = useCallback(async () => {
    setServerKeyBusy(true);
    setServerKeyError("");
    try {
      await deleteZoteroServerKey();
      setServerKeyDraft("");
      await onRefresh?.();
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeyBusy(false);
    }
  }, [onRefresh]);

  // ── 本地探针（连接 + 干跑计数）────────────────────────────────
  const baselineConnected = Boolean(config.zotero_sync && (config.zotero_sync as Record<string, unknown>).connection
    ? ((config.zotero_sync as Record<string, unknown>).connection as { connected?: boolean }).connected
    : undefined);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<ZoteroProbeResult | null>(null);
  const [probeError, setProbeError] = useState("");

  const handleProbe = useCallback(async () => {
    setProbing(true);
    setProbeError("");
    try {
      setProbe(await probeZoteroLocal());
    } catch (err: unknown) {
      setProbeError(err instanceof Error ? err.message : String(err));
      setProbe(null);
    } finally {
      setProbing(false);
    }
  }, []);

  const connected = probe ? probe.connection.connected : baselineConnected;

  // ── 立即同步 + 上次同步状态 ───────────────────────────────────
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<ZoteroSyncResult | null>(null);

  useEffect(() => {
    let alive = true;
    getZoteroSyncStatus().then((s) => { if (alive) setSyncStatus(s); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const handleSyncNow = useCallback(async () => {
    try {
      await syncZoteroPull(true);
      toast(t("zotero_sync_started"), "ok");
      setSyncing(true);
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : String(err), "error");
      setSyncStatus({ status: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }, [t, toast]);

  useEffect(() => {
    if (!syncing) return;
    let cancelled = false;
    async function poll() {
      const job = await getActiveZoteroSyncJob().catch(() => null);
      if (cancelled) return;
      if (!job || job.status !== "running") {
        const s = await getZoteroSyncStatus().catch(() => null);
        if (!cancelled) {
          if (s) setSyncStatus(s);
          setSyncing(false);
          onRefresh?.().catch(() => {});
        }
      } else {
        setTimeout(poll, 2000);
      }
    }
    poll();
    return () => { cancelled = true; };
  }, [syncing, onRefresh]);

  const syncSummary = useMemo(() => {
    if (!syncStatus || (!syncStatus.finished_at && !syncStatus.status)) return t("flow_quick_zotero_never_synced");
    if (syncStatus.status === "error") return syncStatus.message || "error";
    const n = syncStatus.new?.length ?? 0;
    const c = syncStatus.changed?.length ?? 0;
    const r = syncStatus.removed?.length ?? 0;
    const when = syncStatus.finished_at ? new Date(syncStatus.finished_at).toLocaleString() : "";
    return `+${n} ~${c} -${r}${when ? ` · ${when}` : ""}`;
  }, [syncStatus, t]);

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
        onBrowseDir={() => setDirPickerFieldId(field.id)}
      />
    </label>
  );

  const coreFields = fields.filter((f) => !ADVANCED_KEYS.has(f.key));
  const advancedFields = fields.filter((f) => ADVANCED_KEYS.has(f.key));

  return (
    <>
      <div
        className="flow-quick-config"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {/* 标签式连接模式切换（local / server） */}
        <div className="flow-quick-modetab" role="tablist">
          {(["local", "server"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={tab === m}
              className={`flow-quick-modetab-btn ${tab === m ? "is-active" : ""}`}
              disabled={saving}
              onClick={() => switchTab(m)}
            >
              {t(m === "local" ? "flow_quick_zotero_tab_local" : "flow_quick_zotero_tab_server")}
            </button>
          ))}
        </div>

        {/* 本地页签 */}
        {tab === "local" && (
          <>
            <div className="flow-quick-grid">
              {coreFields.map(renderField)}
              <label className="flow-quick-field flow-quick-field--wide">
                <span>{t("flow_quick_zotero_resolved_data_dir")}</span>
                <div
                  className={`flow-quick-readonly ${readString(config, "zotero_sync", "resolved_data_dir") ? "" : "is-empty"}`}
                  title={readString(config, "zotero_sync", "resolved_data_dir") || undefined}
                >
                  {readString(config, "zotero_sync", "resolved_data_dir") || t("flow_value_empty")}
                </div>
              </label>
            </div>

            <div className="flow-quick-diag">
              <span className={`flow-quick-dot ${connected ? "is-ok" : "is-off"}`} />
              <span className="flow-quick-diag-label">
                {connected ? t("flow_quick_zotero_connected") : t("flow_quick_zotero_disconnected")}
              </span>
              <button type="button" className="flow-quick-save flow-quick-save--ghost" disabled={probing} onClick={handleProbe}>
                {probing ? t("flow_quick_zotero_probe_running") : t("flow_quick_zotero_probe")}
              </button>
              {probe?.read.available && (
                <span className="flow-quick-diag-counts">
                  {t("flow_quick_zotero_items")} {probe.read.item_count ?? 0} · {t("flow_quick_zotero_attachments")} {probe.read.attachment_count ?? 0}（{t("flow_quick_zotero_pdf")} {probe.read.pdf_attachment_count ?? 0}）
                </span>
              )}
            </div>
            {probe && !probe.read.available && probe.read.reason && (
              <div className="flow-quick-hint">{probe.read.reason}</div>
            )}
            {probeError && <div className="flow-quick-error">{probeError}</div>}
          </>
        )}

        {/* 在线 API 页签 */}
        {tab === "server" && (
          <>
            <div className="flow-zotero-key-box">
              <div className="flow-zotero-key-head">
                <span>
                  {t("flow_quick_zotero_server_key")}
                  <span className="flow-help-dot" title={t("flow_help_zotero_server_key")}>?</span>
                </span>
                <code>{serverKeyPresent ? (serverKeyMasked || "****") : t("flow_value_empty")}</code>
              </div>
              <div className="flow-zotero-key-row">
                <input
                  className="flow-quick-input"
                  type="password"
                  autoComplete="off"
                  value={serverKeyDraft}
                  placeholder={t("flow_quick_zotero_server_key_placeholder")}
                  disabled={saving || serverKeyBusy}
                  onChange={(event) => setServerKeyDraft(event.target.value)}
                />
                <button type="button" className="flow-quick-save" disabled={!serverKeyDraft.trim() || saving || serverKeyBusy} onClick={handleServerKeySave}>
                  {serverKeyBusy ? t("flow_quick_saving") : t("flow_quick_save_key")}
                </button>
                <button type="button" className="flow-quick-save flow-quick-save--ghost" disabled={!serverKeyPresent || saving || serverKeyBusy} onClick={handleServerKeyDelete}>
                  {t("flow_quick_clear_key")}
                </button>
              </div>
              {serverKeyError && <div className="flow-quick-error">{serverKeyError}</div>}
            </div>
            <div className="flow-quick-diag">
              <span className={`flow-quick-dot ${serverKeyPresent ? "is-ok" : "is-off"}`} />
              <span className="flow-quick-diag-label">{t("flow_quick_zotero_server_user")}</span>
              <span className="flow-quick-diag-counts">{serverUsername || t("flow_value_empty")}</span>
            </div>
          </>
        )}

        {/* 高级（折叠浮层；Portal 到节点底部槽位，不影响节点测量高度） */}
        <AdvancedSection open={advancedOpen} onToggle={onToggleAdvanced} label={t("flow_quick_zotero_advanced")} slot={advancedSlot}>
          <div className="flow-quick-grid">{advancedFields.map(renderField)}</div>
        </AdvancedSection>

        {hasInvalidNumber && <div className="flow-quick-error">{t("flow_quick_number_invalid")}</div>}

        {/* 同步动作条 */}
        <div className="flow-quick-syncbar">
          <button type="button" className="flow-quick-save" disabled={syncing} onClick={handleSyncNow}>
            {syncing ? t("flow_quick_saving") : t("flow_quick_zotero_sync_now")}
          </button>
          <span className="flow-quick-syncbar-status" title={syncSummary}>
            {t("flow_quick_zotero_last_sync")}: {syncSummary}
          </span>
        </div>
      </div>

      {dirPickerField && (
        <DirPickerDialog
          initialPath={dirPickerField.kind === "text" ? (String(draft[dirPickerField.id] ?? dirPickerField.value) || undefined) : undefined}
          t={t}
          onSelect={handleDirSelect}
          onClose={() => setDirPickerFieldId(null)}
        />
      )}
      {accountChange && (
        <Modal
          title="检测到 Zotero 账号变化"
          icon="book"
          width={500}
          height="auto"
          onClose={() => handleAccountChange("cancel")}
          footer={<><Button variant="outline" onClick={() => handleAccountChange("cancel")}>取消更改</Button><Button variant="danger" onClick={() => handleAccountChange("replace_local")}>覆盖并重置本地 Zotero 库</Button></>}
        >
          <div style={{ padding: 22, color: "var(--fg)", fontSize: 13, lineHeight: 1.7 }}>
            <p>当前账号：{accountChange.current_account.account_name || accountChange.current_account.account_id}</p>
            <p>新账号：{accountChange.new_account.account_name || accountChange.new_account.account_id}</p>
            <p style={{ color: "var(--danger)" }}>继续会删除全部本地 Zotero 镜像及其 Milvus / LightRAG 索引；LOCAL 数据不受影响。确认后将自动拉取新账号。</p>
          </div>
        </Modal>
      )}
    </>
  );
});
