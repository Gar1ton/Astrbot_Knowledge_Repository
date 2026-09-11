"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/components/ds/Modal";
import { Badge } from "@/components/ds/Badge";
import { ThemeGallery } from "@/components/modals/ThemeGallery";
import { Button } from "@/components/ds/Button";
import { Card, Field } from "@/components/ds/Card";
import { Icon } from "@/components/ds/Icon";
import { Select } from "@/components/ds/Select";
import { Toggle } from "@/components/ds/Toggle";
import { useTheme } from "@/lib/theme";
import { useI18n, type I18nKey } from "@/lib/i18n";
import { useToast } from "@/components/ui/Toast";
import { TerminalPanel } from "@/components/ui/terminal/TerminalPanel";
import {
  ApiError,
  getEffectiveConfig, getZoteroConfig, syncZoteroPull, backupNow, restoreBackup, logout,
  updateConfigValue, saveZoteroServerKey, deleteZoteroServerKey,
  resolveZoteroAccountChange, getR2Status, getR2Job, notionInit, syncDocuments,
  EffectiveConfig, ZoteroConfig, ZoteroAccountChangeRequired, R2Status, R2BackupJob,
} from "@/lib/api";

interface SettingModalProps {
  onClose: () => void;
  onLogout: () => void;
}

function formatBytes(value: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = Math.max(0, value);
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${index === 0 ? amount.toFixed(0) : amount.toFixed(2)} ${units[index]}`;
}

// ─── Shared primitives ────────────────────────────────────────

function ConfigKV({ k, v, masked }: { k: string; v: unknown; masked?: boolean }) {
  const display = masked ? "••••••••" : v == null ? "—" : String(v);
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span style={{ width: 170, flexShrink: 0, fontSize: 12, color: "var(--fg-muted)" }}>{k}</span>
      <span
        style={{
          flex: 1,
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          color: masked ? "var(--fg-subtle)" : "var(--fg)",
          wordBreak: "break-all",
        }}
      >
        {display}
      </span>
    </div>
  );
}

// ─── Tab: General (previously Appearance) ─────────────────────

function AppearanceTab({ onLogout }: { onLogout: () => void }) {
  const { theme, setTheme } = useTheme();
  const { lang, setLang, t } = useI18n();

  return (
    <>
      <Card title={t("settings_card_appearance")} icon="sun">
        <Field label={t("settings_theme_mode")} hint={t("settings_theme_hint")}>
          <Select
            value={theme ?? "system"}
            onChange={(v) => setTheme(v)}
            options={[
              { value: "light", label: t("settings_theme_light") },
              { value: "dark", label: t("settings_theme_dark") },
              { value: "system", label: t("settings_theme_system") },
            ]}
          />
        </Field>
        <Field label={t("settings_lang")} hint={t("settings_lang_hint")}>
          <Select
            value={lang}
            onChange={(v) => setLang(v as "zh" | "en")}
            options={[
              { value: "zh", label: t("chat_lang_zh") },
              { value: "en", label: t("chat_lang_en") },
            ]}
          />
        </Field>
      </Card>

      <Card
        title={t("settings_theme_gallery")}
        icon="sparkle"
        badge={<Badge tone="accent">{t("settings_theme_gallery_badge")}</Badge>}
      >
        <div
          style={{
            fontSize: 12,
            color: "var(--fg-muted)",
            lineHeight: 1.55,
            marginTop: 4,
          }}
        >
          {t("settings_theme_gallery_hint")}
        </div>
        <ThemeGallery />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <Button variant="primary" size="sm">{t("settings_theme_preview_primary")}</Button>
          <Button variant="outline" size="sm">{t("settings_theme_preview_outline")}</Button>
          <Badge tone="accent">{t("settings_theme_preview_badge")}</Badge>
        </div>
      </Card>

      <Card title={t("settings_section_account")} icon="user">
        <div style={{ padding: "8px 0 4px" }}>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => { await logout(); onLogout(); }}
          >
            {t("settings_logout_btn")}
          </Button>
        </div>
      </Card>
    </>
  );
}

// ─── Tab: Sync/Backup ─────────────────────────────────────────

const ZOTERO_SYNC_MODES = ["strict_mirror", "conservative", "archive"];
const ZOTERO_SYNC_MODE_LABEL_KEYS: Record<string, I18nKey> = {
  strict_mirror: "sync_mode_strict_mirror",
  conservative: "sync_mode_conservative",
  archive: "sync_mode_archive",
};

function ZoteroSyncModeLabel({ value }: { value: string }) {
  const { t } = useI18n();
  const key = ZOTERO_SYNC_MODE_LABEL_KEYS[value];
  return <>{key ? t(key) : value}</>;
}

function SyncTab() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [zotero, setZotero] = useState<ZoteroConfig | null>(null);
  const [effectiveConfig, setEffectiveConfig] = useState<EffectiveConfig | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [backing, setBacking] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [r2Status, setR2Status] = useState<R2Status | null>(null);
  const [r2Job, setR2Job] = useState<R2BackupJob | null>(null);
  const [accountChange, setAccountChange] = useState<ZoteroAccountChangeRequired | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // local/server mode
  const [accessMode, setAccessMode] = useState<"local" | "server">("local");
  // local mode fields
  const [apiPort, setApiPort] = useState("23119");
  const [dataDirOverride, setDataDirOverride] = useState("");
  // server mode fields
  const [serverKeyDraft, setServerKeyDraft] = useState("");
  const [serverKeySaving, setServerKeySaving] = useState(false);
  const [serverKeyError, setServerKeyError] = useState("");
  // common fields
  const [syncMode, setSyncMode] = useState("conservative");
  const [autoSync, setAutoSync] = useState(false);
  const [syncInterval, setSyncInterval] = useState("3600");
  // Notion 同步
  const [notionEnabled, setNotionEnabled] = useState(false);
  const [notionReady, setNotionReady] = useState(false);
  const [notionSyncMode, setNotionSyncMode] = useState("preserve");
  const [notionInterval, setNotionInterval] = useState("0");
  const [notionPushing, setNotionPushing] = useState(false);
  const [notionInitializing, setNotionInitializing] = useState(false);

  useEffect(() => {
    Promise.all([getZoteroConfig(), getEffectiveConfig()]).then(([z, cfg]) => {
      setZotero(z);
      setEffectiveConfig(cfg);
      const zs = (cfg.zotero_sync ?? {}) as Record<string, unknown>;
      const mode = String(zs.access_mode ?? z.access_mode ?? "local") as "local" | "server";
      setAccessMode(mode);
      setApiPort(String(zs.api_port ?? 23119));
      setDataDirOverride(String(zs.zotero_data_dir ?? ""));
      setSyncMode(String(zs.sync_mode ?? z.sync_mode ?? "conservative"));
      setAutoSync(Boolean(zs.auto_sync_enabled ?? z.auto_sync_enabled ?? false));
      setSyncInterval(String(zs.auto_sync_interval_sec ?? z.auto_sync_interval_sec ?? 3600));
      const ns = (cfg.notion_sync ?? {}) as Record<string, unknown>;
      setNotionEnabled(Boolean(ns.enabled ?? false));
      setNotionReady(Boolean(ns.database_id) && Boolean(ns.qa_database_id));
      setNotionSyncMode(String(ns.sync_mode ?? "preserve"));
      setNotionInterval(String(ns.auto_sync_interval_sec ?? 0));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      const status = await getR2Status().catch(() => null);
      if (alive && status) {
        setR2Status(status);
        setR2Job(status.job ?? null);
      }
    };
    refresh();
    const timer = window.setInterval(async () => {
      const job = await getR2Job().catch(() => null);
      if (!alive) return;
      setR2Job(job);
      if (!job || job.status !== "running") refresh();
    }, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  async function save(section: string, key: string, value: string | boolean | number) {
    const id = `${section}.${key}`;
    setSaving(id);
    try {
      await updateConfigValue(section, key, value);
    } catch (e) {
      toast(e instanceof Error ? e.message : t("toast_save_failed"), "error");
    } finally {
      setSaving(null);
    }
  }

  async function handleModeSwitch(mode: "local" | "server") {
    setAccessMode(mode);
    await save("zotero_sync", "access_mode", mode);
  }

  async function handleZoteroSync() {
    setSyncing(true);
    try {
      await syncZoteroPull(true);
      toast(t("toast_zotero_sync_started"), "ok");
    } catch (e) {
      // 这里的请求是「触发即轮询」：5s 后放弃等待属于预期，后端仍在同步，
      // 进度看左下角进度条。把它当失败弹红字只会让用户以为同步没跑起来。
      if (e instanceof ApiError && e.timedOut) toast(t("toast_zotero_sync_background"), "ok");
      else toast(e instanceof Error ? e.message : t("toast_sync_failed"), "error");
    } finally {
      setSyncing(false);
    }
  }

  async function handleBackup(force = false) {
    setBacking(true);
    try {
      await backupNow(force);
      toast(force ? t("toast_backup_forced_started") : t("toast_backup_incremental_started"), "ok");
      setR2Job(await getR2Job().catch(() => null));
    } catch (e) {
      toast(e instanceof Error ? e.message : t("toast_backup_failed"), "error");
    } finally {
      setBacking(false);
    }
  }

  async function handleRestore() {
    setRestoreConfirm(false);
    setRestoring(true);
    try {
      await restoreBackup(true);
      toast(t("toast_restore_started"), "ok");
      setR2Job(await getR2Job().catch(() => null));
    } catch (e) {
      toast(e instanceof Error ? e.message : t("toast_restore_failed"), "error");
    } finally {
      setRestoring(false);
    }
  }

  async function handleNotionInit() {
    setNotionInitializing(true);
    try {
      const res = await notionInit("", "");
      if (res.status === "success") {
        setNotionReady(Boolean(res.database_id) && Boolean(res.qa_database_id));
        toast(t("toast_notion_init_done"), "ok");
      } else {
        toast(t("toast_notion_init_need_parent"), "error");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : t("toast_init_failed"), "error");
    } finally {
      setNotionInitializing(false);
    }
  }

  async function handleNotionPush() {
    setNotionPushing(true);
    try {
      // 推送已改为后台单任务：立即返回任务快照，进度与完成提示由左下角进度条呈现。
      const res = await syncDocuments("notion");
      if ("reserved" in res) {
        toast(t("toast_notion_port_reserved"), "error");
      } else if (res.status === "error") {
        toast(t("toast_notion_push_start_failed"), "error");
      } else {
        toast(t("toast_notion_push_started"), "ok");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : t("toast_push_failed"), "error");
    } finally {
      setNotionPushing(false);
    }
  }

  async function handleServerKeySave() {
    const key = serverKeyDraft.trim();
    if (!key) return;
    setServerKeySaving(true);
    setServerKeyError("");
    try {
      const updated = await saveZoteroServerKey(key);
      if ("status" in updated && updated.status === "account_change_required") {
        setAccountChange(updated);
      } else {
        setZotero(updated as ZoteroConfig);
        setServerKeyDraft("");
        toast(t("toast_api_key_saved"), "ok");
      }
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeySaving(false);
    }
  }

  async function handleAccountChange(action: "replace_local" | "cancel") {
    if (!accountChange) return;
    setServerKeySaving(true);
    try {
      await resolveZoteroAccountChange(accountChange.change_id, action);
      if (action === "replace_local") {
        setServerKeyDraft("");
        toast(t("toast_zotero_mirror_reset"), "ok");
      } else {
        toast(t("toast_account_change_cancelled"), "ok");
      }
      setAccountChange(null);
      setZotero(await getZoteroConfig());
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeySaving(false);
    }
  }

  async function handleServerKeyDelete() {
    setServerKeySaving(true);
    setServerKeyError("");
    try {
      const updated = await deleteZoteroServerKey();
      setZotero(updated);
      toast(t("toast_api_key_cleared"), "ok");
    } catch (err: unknown) {
      setServerKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setServerKeySaving(false);
    }
  }

  const zoteroConnected = zotero?.connection?.connected ?? false;
  const resolvedDataDir = String((effectiveConfig?.zotero_sync as Record<string, unknown> | undefined)?.resolved_data_dir ?? "");
  const serverKeyPresent = Boolean((effectiveConfig?.zotero_sync as Record<string, unknown> | undefined)?.server_key_present ?? zotero?.server_key_present);
  const serverKeyMasked = String((effectiveConfig?.zotero_sync as Record<string, unknown> | undefined)?.server_key_masked ?? "");
  const serverUsername = String((effectiveConfig?.zotero_sync as Record<string, unknown> | undefined)?.server_username ?? (effectiveConfig?.zotero_sync as Record<string, unknown> | undefined)?.server_user_id ?? "");

  // Segmented control pill style
  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "5px 0",
    textAlign: "center",
    fontSize: 12,
    fontWeight: active ? 600 : 500,
    color: active ? "var(--accent)" : "var(--fg-muted)",
    background: active ? "var(--accent-soft)" : "transparent",
    border: "none",
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    fontFamily: "inherit",
    transition: "all .15s",
  });

  const inputStyle: React.CSSProperties = {
    height: 30,
    padding: "0 10px",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-md)",
    background: "var(--surface)",
    color: "var(--fg)",
    fontSize: 12,
    fontFamily: "inherit",
    outline: "none",
    width: 180,
  };

  return (
    <>
      <Card
        title={t("sync_zotero_title")}
        icon="book"
        badge={
          <Badge tone={zoteroConnected ? "ok" : "warn"}>
            {zoteroConnected ? t("sync_connected") : t("sync_disconnected")}
          </Badge>
        }
      >
        {/* Mode switcher */}
        <div
          style={{
            display: "flex",
            gap: 2,
            padding: "4px",
            background: "var(--bg-inset)",
            borderRadius: "var(--radius-lg)",
            margin: "8px 0 4px",
          }}
        >
          <button type="button" style={tabStyle(accessMode === "local")} onClick={() => handleModeSwitch("local")}>
            {t("sync_tab_local")}
          </button>
          <button type="button" style={tabStyle(accessMode === "server")} onClick={() => handleModeSwitch("server")}>
            {t("sync_tab_server")}
          </button>
        </div>

        {/* Local panel */}
        {accessMode === "local" && (
          <div style={{ paddingTop: 4 }}>
            <Field label={t("sync_field_local_port")}>
              <input
                style={inputStyle}
                type="number"
                value={apiPort}
                onChange={(e) => setApiPort(e.target.value)}
                onBlur={() => {
                  const n = parseInt(apiPort, 10);
                  if (Number.isFinite(n) && n > 0) save("zotero_sync", "api_port", n);
                }}
                disabled={saving === "zotero_sync.api_port"}
              />
            </Field>
            {resolvedDataDir && (
              <Field label={t("sync_field_auto_dir")} hint={t("sync_field_auto_dir_hint")}>
                <span style={{ fontSize: 11, color: "var(--fg-muted)", fontFamily: "var(--font-mono)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {resolvedDataDir}
                </span>
              </Field>
            )}
            <Field label={t("sync_field_dir_override")} hint={t("sync_field_dir_override_hint")}>
              <input
                style={{ ...inputStyle, width: 200 }}
                type="text"
                value={dataDirOverride}
                placeholder={t("sync_placeholder_auto_detect")}
                onChange={(e) => setDataDirOverride(e.target.value)}
                onBlur={() => save("zotero_sync", "zotero_data_dir", dataDirOverride)}
                disabled={saving === "zotero_sync.zotero_data_dir"}
              />
            </Field>
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", padding: "6px 0 4px", lineHeight: 1.5 }}>
              {t("sync_local_notice", { port: apiPort || "23119" })}
            </div>
          </div>
        )}

        {/* Online panel */}
        {accessMode === "server" && (
          <div style={{ paddingTop: 4 }}>
            <Field
              label="Zotero API Key"
              hint={serverKeyPresent ? t("sync_key_current", { masked: serverKeyMasked || "****" }) : t("sync_key_unset")}
            >
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  style={{ ...inputStyle, width: 160 }}
                  type="password"
                  autoComplete="off"
                  value={serverKeyDraft}
                  placeholder={t("sync_placeholder_web_api_key")}
                  disabled={serverKeySaving}
                  onChange={(e) => setServerKeyDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && serverKeyDraft.trim()) handleServerKeySave(); }}
                />
                <Button
                  variant="outline" size="sm"
                  loading={serverKeySaving && serverKeyDraft !== ""}
                  onClick={handleServerKeySave}
                  style={{ opacity: serverKeyDraft.trim() ? 1 : 0.4, pointerEvents: serverKeyDraft.trim() ? undefined : "none" }}
                >
                  {t("sync_btn_save")}
                </Button>
                {serverKeyPresent && (
                  <Button variant="ghost" size="sm" onClick={handleServerKeyDelete} loading={serverKeySaving && serverKeyDraft === ""}>
                    {t("sync_btn_clear")}
                  </Button>
                )}
              </div>
            </Field>
            {serverKeyError && (
              <div style={{ fontSize: 11, color: "var(--danger)", padding: "2px 0 6px" }}>{serverKeyError}</div>
            )}
            {serverUsername && (
              <Field label={t("sync_field_username")} hint={t("sync_field_username_hint")}>
                <span style={{ fontSize: 12, color: "var(--fg-muted)", fontFamily: "var(--font-mono)" }}>{serverUsername}</span>
              </Field>
            )}
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", padding: "6px 0 4px", lineHeight: 1.5 }}>
              {t("sync_server_notice")}
            </div>
          </div>
        )}

        {/* Availability warning */}
        {zotero?.availability && !zotero.availability.available && (
          <div style={{ fontSize: 11, color: "var(--warn)", marginTop: 4, padding: "6px 0", lineHeight: 1.5 }}>
            ⚠ {zotero.availability.reason}
          </div>
        )}

        {/* Common fields */}
        <div style={{ height: 1, background: "var(--border)", margin: "8px 0" }} />

        <Field label={t("sync_field_mode")}>
          <select
            value={syncMode}
            onChange={(e) => { setSyncMode(e.target.value); save("zotero_sync", "sync_mode", e.target.value); }}
            style={{ ...inputStyle, width: 140 }}
            disabled={saving === "zotero_sync.sync_mode"}
          >
            {ZOTERO_SYNC_MODES.map((m) => (
              <option key={m} value={m}><ZoteroSyncModeLabel value={m} /></option>
            ))}
          </select>
        </Field>

        <Field label={t("sync_field_auto")}>
          <Toggle
            checked={autoSync}
            onChange={(v) => { setAutoSync(v); save("zotero_sync", "auto_sync_enabled", v); }}
          />
        </Field>

        {autoSync && (
          <Field label={t("sync_field_interval")}>
            <input
              style={inputStyle}
              type="number"
              value={syncInterval}
              min={60}
              onChange={(e) => setSyncInterval(e.target.value)}
              onBlur={() => {
                const n = parseInt(syncInterval, 10);
                if (Number.isFinite(n) && n >= 60) save("zotero_sync", "auto_sync_interval_sec", n);
              }}
              disabled={saving === "zotero_sync.auto_sync_interval_sec"}
            />
          </Field>
        )}

        <Field label={t("sync_field_pull_mirror")} hint={t("sync_field_pull_mirror_hint")}>
          <Button variant="outline" size="sm" loading={syncing} onClick={handleZoteroSync}>
            <Icon name="sync" size={13} /> {t("sync_btn_sync_now")}
          </Button>
        </Field>
      </Card>

      <Card
        title={t("r2_title")}
        icon="cloud"
        badge={<Badge tone={r2Status?.status === "ok" ? "ok" : "neutral"}>{r2Job?.status === "running" ? `${r2Job.stage} ${r2Job.progress}%` : t("r2_badge_full_snapshot")}</Badge>}
      >
        <Field label={t("r2_field_bucket")} hint={t("r2_field_bucket_hint")}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg-muted)" }}>
            {formatBytes(r2Status?.bucket_used_bytes ?? 0)} / {formatBytes(r2Status?.plugin_used_bytes ?? 0)} · {r2Status?.plugin_object_count ?? 0} objects
          </span>
        </Field>
        <Field label={t("r2_field_snapshot")} hint={t("r2_field_snapshot_hint")}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-subtle)" }}>
            {r2Status?.snapshot
              ? `${r2Status.snapshot.snapshot_id} · ${r2Status.snapshot.file_count} files · ${r2Status.snapshot.updated_at}`
              : t("r2_no_snapshot")}
          </span>
        </Field>
        <Field label={t("r2_field_size")} hint={t("r2_field_size_hint")}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg-muted)" }}>
            {formatBytes(r2Status?.snapshot?.logical_bytes ?? 0)} / {formatBytes(r2Status?.snapshot?.deduplicated_bytes ?? 0)}
          </span>
        </Field>
        {r2Job?.status === "running" && (
          <div style={{ padding: "8px 0" }}>
            <div style={{ height: 6, borderRadius: "var(--radius-pill)", background: "var(--bg-inset)", overflow: "hidden" }}>
              <div style={{ width: `${r2Job.progress}%`, height: "100%", background: "var(--accent)", transition: "width .2s" }} />
            </div>
          </div>
        )}
        {r2Job?.status === "error" && (
          <div style={{ padding: "7px 10px", borderRadius: "var(--radius-md)", background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12 }}>
            {r2Job.error || t("r2_job_failed")}
          </div>
        )}
        <Field label={t("r2_field_backup_restore")} hint={t("r2_field_backup_restore_hint")}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button variant="outline" size="sm" loading={backing} disabled={r2Job?.status === "running"} onClick={() => handleBackup(false)}>
            {t("r2_btn_backup_now")}
          </Button>
          <Button variant="outline" size="sm" disabled={backing || r2Job?.status === "running"} onClick={() => handleBackup(true)}>
            {t("r2_btn_backup_force")}
          </Button>
          <Button variant="danger" size="sm" loading={restoring} disabled={r2Job?.status === "running"} onClick={() => setRestoreConfirm(true)}>
            {t("r2_btn_restore")}
          </Button>
          </div>
        </Field>
      </Card>

      {accountChange && (
        <Modal
          title={t("zotero_account_change_title")}
          icon="book"
          width={500}
          height="auto"
          onClose={() => handleAccountChange("cancel")}
          footer={<><Button variant="outline" onClick={() => handleAccountChange("cancel")}>{t("zotero_account_change_cancel")}</Button><Button variant="danger" onClick={() => handleAccountChange("replace_local")}>{t("zotero_account_change_replace")}</Button></>}
        >
          <div style={{ padding: 22, color: "var(--fg)", fontSize: 13, lineHeight: 1.7 }}>
            <p>{t("zotero_account_current", { account: accountChange.current_account.account_name || accountChange.current_account.account_id })}</p>
            <p>{t("zotero_account_new", { account: accountChange.new_account.account_name || accountChange.new_account.account_id })}</p>
            <p style={{ color: "var(--danger)" }}>{t("settings_account_change_warning")}</p>
          </div>
        </Modal>
      )}

      {restoreConfirm && (
        <Modal
          title={t("r2_restore_title")}
          icon="cloud"
          width={500}
          height="auto"
          onClose={() => setRestoreConfirm(false)}
          footer={<><Button variant="outline" onClick={() => setRestoreConfirm(false)}>{t("btn_cancel")}</Button><Button variant="danger" onClick={handleRestore}>{t("r2_restore_confirm")}</Button></>}
        >
          <div style={{ padding: 22, color: "var(--fg)", fontSize: 13, lineHeight: 1.7 }}>
            {t("r2_restore_warning")}
          </div>
        </Modal>
      )}

      <Card
        title={t("notion_title")}
        icon="layers"
        badge={
          <Badge tone={notionEnabled ? (notionReady ? "ok" : "warn") : "neutral"}>
            {notionEnabled ? (notionReady ? t("notion_ready") : t("notion_uninitialised")) : t("notion_disabled")}
          </Badge>
        }
      >
        <Field
          label={t("notion_field_push")}
          hint={t("notion_field_push_hint")}
        >
          <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}>
            {notionEnabled ? t("notion_enabled_in_config") : t("notion_disabled_hint")}
          </span>
        </Field>

        <Field
          label={t("notion_field_cleanup")}
          hint={t("notion_field_cleanup_hint")}
        >
          <select
            value={notionSyncMode}
            onChange={(e) => {
              setNotionSyncMode(e.target.value);
              save("notion_sync", "sync_mode", e.target.value);
            }}
            style={{ ...inputStyle, width: 180 }}
            disabled={!notionEnabled || saving === "notion_sync.sync_mode"}
          >
            <option value="preserve">{t("notion_opt_preserve")}</option>
            <option value="strict">{t("notion_opt_strict")}</option>
          </select>
        </Field>

        <Field
          label={t("notion_field_interval")}
          hint={t("notion_field_interval_hint")}
        >
          <input
            style={inputStyle}
            type="number"
            value={notionInterval}
            min={0}
            disabled={!notionEnabled || saving === "notion_sync.auto_sync_interval_sec"}
            onChange={(e) => setNotionInterval(e.target.value)}
            onBlur={() => {
              const n = parseInt(notionInterval, 10);
              if (Number.isFinite(n) && n >= 0) save("notion_sync", "auto_sync_interval_sec", n);
            }}
          />
        </Field>

        <Field label={t("notion_field_init")} hint={t("notion_field_init_hint")}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button
              variant="outline"
              size="sm"
              loading={notionInitializing}
              disabled={!notionEnabled}
              onClick={handleNotionInit}
            >
              {t("notion_btn_init")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              loading={notionPushing}
              disabled={!notionEnabled || !notionReady}
              onClick={handleNotionPush}
            >
              <Icon name="sync" size={13} /> {t("sync_btn_sync_now")}
            </Button>
          </div>
        </Field>
      </Card>
    </>
  );
}

// ─── Tab: Backend Config ──────────────────────────────────────

function ConfigTab() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    getEffectiveConfig().then(setConfig).catch(() => {});
  }, []);

  const SENSITIVE_KEYS = ["password", "api_key", "secret", "token", "key"];
  const inputStyle: React.CSSProperties = {
    height: 30,
    padding: "0 10px",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-md)",
    background: "var(--surface)",
    color: "var(--fg)",
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    outline: "none",
    width: 220,
  };

  function section(name: keyof EffectiveConfig): Record<string, unknown> {
    return (config?.[name] ?? {}) as Record<string, unknown>;
  }

  function valueOf(sectionName: keyof EffectiveConfig, key: string, fallback = ""): string {
    const value = section(sectionName)[key];
    if (value === null || value === undefined) return fallback;
    return String(value);
  }

  function boolOf(sectionName: keyof EffectiveConfig, key: string, fallback = false): boolean {
    const value = section(sectionName)[key];
    if (typeof value === "boolean") return value;
    if (typeof value === "string") return value.toLowerCase() === "true";
    if (typeof value === "number") return value !== 0;
    return fallback;
  }

  function setLocal(sectionName: keyof EffectiveConfig, key: string, value: unknown) {
    setConfig((current) => {
      if (!current) return current;
      const currentSection = (current[sectionName] ?? {}) as Record<string, unknown>;
      return {
        ...current,
        [sectionName]: {
          ...currentSection,
          [key]: value,
        },
      };
    });
  }

  async function saveValue(sectionName: string, key: string, value: string | boolean | number) {
    const id = `${sectionName}.${key}`;
    setSaving(id);
    try {
      const result = await updateConfigValue(sectionName, key, value);
      if (result.rebuild_required) toast(t("cfg_saved_rebuild"), "info");
      else if (result.restart_required) toast(t("cfg_saved_restart"), "info");
      else toast(t("cfg_saved"), "ok");
      const fresh = await getEffectiveConfig();
      setConfig(fresh);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("toast_save_failed"), "error");
      getEffectiveConfig().then(setConfig).catch(() => {});
    } finally {
      setSaving(null);
    }
  }

  function textConfigField(
    sectionName: keyof EffectiveConfig,
    key: string,
    label: string,
    hint?: string,
    width = 220,
  ) {
    const id = `${sectionName}.${key}`;
    const value = valueOf(sectionName, key);
    return (
      <Field label={label} hint={hint}>
        <input
          style={{ ...inputStyle, width }}
          value={value}
          disabled={saving === id}
          onChange={(event) => setLocal(sectionName, key, event.target.value)}
          onBlur={() => saveValue(sectionName, key, valueOf(sectionName, key))}
        />
      </Field>
    );
  }

  function numberConfigField(
    sectionName: keyof EffectiveConfig,
    key: string,
    label: string,
    hint?: string,
    parser: "int" | "float" = "int",
  ) {
    const id = `${sectionName}.${key}`;
    const value = valueOf(sectionName, key);
    return (
      <Field label={label} hint={hint}>
        <input
          style={{ ...inputStyle, width: 92, textAlign: "center" }}
          type="number"
          step={parser === "float" ? "0.1" : "1"}
          value={value}
          disabled={saving === id}
          onChange={(event) => setLocal(sectionName, key, event.target.value)}
          onBlur={() => {
            const raw = valueOf(sectionName, key);
            const parsed = parser === "float" ? Number(raw) : parseInt(raw, 10);
            if (!Number.isFinite(parsed)) {
              toast(t("cfg_invalid_number"), "error");
              getEffectiveConfig().then(setConfig).catch(() => {});
              return;
            }
            saveValue(sectionName, key, parsed);
          }}
        />
      </Field>
    );
  }

  function toggleConfigField(sectionName: keyof EffectiveConfig, key: string, label: string, hint?: string) {
    const id = `${sectionName}.${key}`;
    const checked = boolOf(sectionName, key);
    return (
      <Field label={label} hint={hint}>
        <Toggle
          checked={checked}
          onChange={(value) => {
            setLocal(sectionName, key, value);
            saveValue(sectionName, key, value);
          }}
          disabled={saving === id}
        />
      </Field>
    );
  }

  function readonlyConfigField(label: string, value: unknown, hint?: string) {
    return (
      <Field label={label} hint={hint}>
        <span
          style={{
            display: "inline-block",
            maxWidth: 240,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
            color: "var(--fg-subtle)",
          }}
          title={value == null ? "" : String(value)}
        >
          {value == null || value === "" ? "env-only" : String(value)}
        </span>
      </Field>
    );
  }

  function renderSection(name: string, data?: Record<string, unknown>) {
    if (!data) return null;
    const icon: Record<string, string> = {
      source_store: "db",
      web_console: "globe",
      r2_sync: "cloud",
      notion_sync: "layers",
      graph: "graph",
      ask: "sparkle",
      vector_db: "db",
      embedding: "layers",
      zotero_sync: "book",
    };
    return (
      <Card key={name} title={name} icon={icon[name] ?? "file"}>
        {Object.entries(data).map(([k, v]) => {
          const masked = SENSITIVE_KEYS.some((s) => k.toLowerCase().includes(s));
          return <ConfigKV key={k} k={k} v={v} masked={masked} />;
        })}
      </Card>
    );
  }

  if (!config) {
    return (
      <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "var(--fg-subtle)" }}>
        {t("cfg_loading")}
      </div>
    );
  }

  return (
    <>
      <div
        style={{
          fontSize: 12,
          color: "var(--fg-muted)",
          marginBottom: 14,
          lineHeight: 1.55,
        }}
      >
        {t("cfg_migration_notice_head")}
        <code style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
          GET /api/config/effective
        </code>
        {t("cfg_migration_notice_tail")}
      </div>

      <Card title={t("cfg_card_source_store")} icon="db" badge={<Badge tone="neutral">WebUI</Badge>}>
        {textConfigField(
          "source_store",
          "default_collection",
          t("cfg_default_collection"),
          t("cfg_default_collection_hint"),
        )}
      </Card>

      <Card title={t("cfg_card_graph_llm")} icon="graph" badge={<Badge tone="warn">{t("cfg_badge_restart")}</Badge>}>
        <Field label={t("cfg_graph_llm_provider")} hint={t("cfg_graph_llm_provider_hint")}>
          <Select
            value={valueOf("graph", "lightrag_llm_provider", "main")}
            onChange={(value) => {
              setLocal("graph", "lightrag_llm_provider", value);
              saveValue("graph", "lightrag_llm_provider", value);
            }}
            options={[
              { value: "main", label: "main" },
              { value: "local", label: "local" },
              { value: "api", label: "api" },
            ]}
          />
        </Field>
        {textConfigField("graph", "lightrag_llm_base_url", t("cfg_graph_llm_base_url"), t("cfg_graph_llm_base_url_hint"), 260)}
        {textConfigField("graph", "lightrag_llm_model", t("cfg_graph_llm_model"), t("cfg_graph_llm_model_hint"), 220)}
        {readonlyConfigField(
          t("cfg_graph_workspace"),
          valueOf("graph", "working_dir", "lightrag_workspaces"),
          t("cfg_graph_workspace_hint"),
        )}
      </Card>

      <Card title={t("cfg_card_deep_thinking")} icon="sparkle" badge={<Badge tone="accent">{t("cfg_badge_instant_or_restart")}</Badge>}>
        {numberConfigField("deep_thinking", "max_rounds", t("cfg_dt_max_rounds"), t("cfg_dt_max_rounds_hint"))}
        {numberConfigField("deep_thinking", "max_sub_queries", t("cfg_dt_max_sub_queries"))}
        {numberConfigField("deep_thinking", "wide_top_k", t("cfg_dt_wide_top_k"))}
        {numberConfigField("deep_thinking", "rerank_weight", t("cfg_rerank_weight"), undefined, "float")}
        {toggleConfigField(
          "deep_thinking",
          "verify_enabled",
          t("cfg_dt_verify"),
          t("cfg_dt_verify_hint"),
        )}
        {numberConfigField("deep_thinking", "max_verify_rounds", t("cfg_dt_max_verify_rounds"))}
        {textConfigField("deep_thinking", "llm_base_url", t("cfg_dt_llm_base_url"), t("cfg_dt_llm_base_url_hint"), 260)}
        {textConfigField("deep_thinking", "llm_model", t("cfg_dt_llm_model"), t("cfg_dt_llm_model_hint"), 220)}
        {readonlyConfigField(
          t("cfg_dt_llm_api_key"),
          valueOf("deep_thinking", "llm_api_key"),
          t("cfg_dt_llm_api_key_hint"),
        )}
      </Card>

      <Card title={t("cfg_card_enhanced")} icon="sparkle" badge={<Badge tone="accent">{t("cfg_badge_instant")}</Badge>}>
        {numberConfigField("enhanced_recall", "max_sub_queries", t("cfg_er_max_sub_queries"), t("cfg_er_max_sub_queries_hint"))}
        {numberConfigField("enhanced_recall", "wide_top_k", t("cfg_er_wide_top_k"))}
        {numberConfigField("enhanced_recall", "max_final_evidence", t("cfg_er_max_final_evidence"))}
        {numberConfigField("enhanced_recall", "rerank_weight", t("cfg_rerank_weight"), undefined, "float")}
        {toggleConfigField(
          "enhanced_recall",
          "corrective_enabled",
          t("cfg_er_corrective"),
          t("cfg_er_corrective_hint"),
        )}
      </Card>

      {Object.entries(config)
        .filter(([k]) => k !== "diagnostics")
        .map(([k, v]) => renderSection(k, v as Record<string, unknown>))}
    </>
  );
}

// ─── SettingModal ─────────────────────────────────────────────

const TABS = [
  { id: "appearance", labelKey: "settings_appearance", icon: "sun" },
  { id: "sync", labelKey: "settings_tab_sync", icon: "sync" },
  { id: "config", labelKey: "settings_tab_config", icon: "db" },
  { id: "terminal", labelKey: "settings_tab_terminal", icon: "terminal" },
] as const satisfies readonly { id: string; labelKey: I18nKey; icon: string }[];

type TabId = (typeof TABS)[number]["id"];

export function SettingModal({ onClose, onLogout }: SettingModalProps) {
  const [tab, setTab] = useState<TabId>("appearance");
  const { t } = useI18n();

  return (
    <Modal title={t("settings_modal_title")} icon="settings" onClose={onClose} width={920}>
      <div style={{ display: "flex", height: "100%" }}>
        {/* Left tab rail */}
        <div
          style={{
            width: 168,
            flexShrink: 0,
            borderRight: "1px solid var(--border)",
            background: "var(--surface)",
            padding: 10,
          }}
        >
          {TABS.map((tabItem) => (
            <button
              key={tabItem.id}
              onClick={() => setTab(tabItem.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                width: "100%",
                padding: "8px 10px",
                borderRadius: "var(--radius-md)",
                border: "none",
                background: tab === tabItem.id ? "var(--accent-soft)" : "transparent",
                color: tab === tabItem.id ? "var(--accent)" : "var(--fg-muted)",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: tab === tabItem.id ? 600 : 450,
                fontFamily: "var(--font-sans)",
                marginBottom: 2,
                textAlign: "left",
              }}
            >
              <Icon name={tabItem.icon} size={15} /> {t(tabItem.labelKey)}
            </button>
          ))}
        </div>

        {/* Content area */}
        <div
          style={{
            flex: 1,
            overflow: tab === "terminal" ? "hidden" : "auto",
            padding: tab === "terminal" ? 0 : "18px 22px",
            minHeight: 0,
          }}
        >
          {tab === "appearance" && <AppearanceTab onLogout={onLogout} />}
          {tab === "sync" && <SyncTab />}
          {tab === "config" && <ConfigTab />}
          {tab === "terminal" && <TerminalPanel variant="embedded" />}
        </div>
      </div>
    </Modal>
  );
}
