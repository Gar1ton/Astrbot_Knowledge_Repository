"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/components/ds/Modal";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { Select } from "@/components/ds/Select";
import { Toggle } from "@/components/ds/Toggle";
import { useTheme } from "@/lib/theme";
import { useI18n, type I18nKey } from "@/lib/i18n";
import { useToast } from "@/components/ui/Toast";
import { TerminalPanel } from "@/components/ui/TerminalPanel";
import {
  getEffectiveConfig, getZoteroConfig, syncZoteroPull, backupNow, restoreBackup, logout,
  updateConfigValue, saveZoteroServerKey, deleteZoteroServerKey,
  resolveZoteroAccountChange, getR2Status, getR2Job,
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

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{label}</div>
        {hint && (
          <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2, lineHeight: 1.45 }}>
            {hint}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

function Card({
  title,
  icon,
  badge,
  children,
}: {
  title: string;
  icon?: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: "4px 16px 12px",
        marginBottom: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 4px" }}>
        {icon && <Icon name={icon} size={16} style={{ color: "var(--accent)" }} />}
        <span style={{ fontSize: 13.5, fontWeight: 650, color: "var(--heading)", flex: 1 }}>
          {title}
        </span>
        {badge}
      </div>
      {children}
    </div>
  );
}

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

function Swatch({ h, active, onClick }: { h: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: 30,
        height: 30,
        borderRadius: "var(--radius-md)",
        border: active ? "2px solid var(--fg)" : "2px solid transparent",
        boxShadow: active ? "0 0 0 1px var(--surface) inset" : "none",
        background: `hsl(${h} 70% 56%)`,
        cursor: "pointer",
        padding: 0,
        flexShrink: 0,
      }}
    />
  );
}

// ─── Accent state helpers ─────────────────────────────────────

function getAccentFromDOM() {
  if (typeof document === "undefined") return { h: 225, s: 72, l: 56 };
  const el = document.documentElement;
  const h = parseFloat(el.style.getPropertyValue("--accent-h") || "") || 225;
  const s = parseFloat(el.style.getPropertyValue("--accent-s") || "") || 72;
  const l = parseFloat(el.style.getPropertyValue("--accent-l") || "") || 56;
  return { h, s, l };
}

function applyAccent(h: number, s: number, l: number) {
  if (typeof document === "undefined") return;
  document.documentElement.style.setProperty("--accent-h", String(h));
  document.documentElement.style.setProperty("--accent-s", `${s}%`);
  document.documentElement.style.setProperty("--accent-l", `${l}%`);
  localStorage.setItem("kr-hue", String(h));
  localStorage.setItem("kr-sat", `${s}%`);
  localStorage.setItem("kr-light", `${l}%`);
}

// ─── Tab: General (previously Appearance) ─────────────────────

function AppearanceTab({ onLogout }: { onLogout: () => void }) {
  const { theme, setTheme } = useTheme();
  const { lang, setLang, t } = useI18n();
  const [accent, setAccent] = useState(() => getAccentFromDOM());

  function updateAccent(patch: Partial<typeof accent>) {
    const next = { ...accent, ...patch };
    setAccent(next);
    applyAccent(next.h, next.s, next.l);
  }

  const PRESETS = [225, 200, 265, 160, 32, 12, 340];

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
        title="全局强调色"
        icon="sparkle"
        badge={<Badge tone="accent">一处生效</Badge>}
      >
        <div
          style={{
            fontSize: 12,
            color: "var(--fg-muted)",
            lineHeight: 1.55,
            marginBottom: 12,
          }}
        >
          所有控件的主题色 / 强调色统一由此驱动；调节后全站实时级联渲染并本地持久化。
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {PRESETS.map((h) => (
            <Swatch
              key={h}
              h={h}
              active={Math.abs(accent.h - h) < 6}
              onClick={() => updateAccent({ h })}
            />
          ))}
        </div>
        {(
          [
            ["色相 H", "h", 0, 360, "°"],
            ["饱和度 S", "s", 0, 100, "%"],
            ["明度 L", "l", 20, 80, "%"],
          ] as const
        ).map(([lbl, key, min, max, unit]) => (
          <div
            key={key}
            style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}
          >
            <span style={{ width: 60, fontSize: 12, color: "var(--fg-muted)" }}>{lbl}</span>
            <input
              type="range"
              min={min}
              max={max}
              value={accent[key]}
              onChange={(e) => updateAccent({ [key]: +e.target.value })}
              style={{ flex: 1, accentColor: "var(--accent)" }}
            />
            <span
              style={{
                width: 36,
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--fg)",
                textAlign: "right",
              }}
            >
              {accent[key]}{unit}
            </span>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <Button variant="primary" size="sm">主按钮</Button>
          <Button variant="outline" size="sm">次按钮</Button>
          <Badge tone="accent">徽章</Badge>
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
const ZOTERO_SYNC_MODE_LABELS: Record<string, string> = {
  strict_mirror: "严格镜像",
  conservative: "保守同步",
  archive: "归档堆栈",
};

function ZoteroSyncModeLabel({ value }: { value: string }) {
  return <>{ZOTERO_SYNC_MODE_LABELS[value] ?? value}</>;
}

function SyncTab() {
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
      toast(e instanceof Error ? e.message : "保存失败", "error");
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
      toast("Zotero 同步已启动", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : "同步失败", "error");
    } finally {
      setSyncing(false);
    }
  }

  async function handleBackup(force = false) {
    setBacking(true);
    try {
      await backupNow(force);
      toast(force ? "强制完整备份已启动" : "增量完整备份已启动", "ok");
      setR2Job(await getR2Job().catch(() => null));
    } catch (e) {
      toast(e instanceof Error ? e.message : "备份失败", "error");
    } finally {
      setBacking(false);
    }
  }

  async function handleRestore() {
    setRestoreConfirm(false);
    setRestoring(true);
    try {
      await restoreBackup(true);
      toast("完整恢复已启动；校验完成后插件会自动重启", "ok");
      setR2Job(await getR2Job().catch(() => null));
    } catch (e) {
      toast(e instanceof Error ? e.message : "恢复失败", "error");
    } finally {
      setRestoring(false);
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
        toast("API Key 已保存", "ok");
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
        toast("本地 Zotero 镜像已重置，新账号同步已启动", "ok");
      } else {
        toast("已取消账号更换，旧数据保持不变", "ok");
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
      toast("API Key 已清除", "ok");
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
        title="Zotero 同步"
        icon="book"
        badge={
          <Badge tone={zoteroConnected ? "ok" : "warn"}>
            {zoteroConnected ? "已连接" : "未连接"}
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
            本地离线
          </button>
          <button type="button" style={tabStyle(accessMode === "server")} onClick={() => handleModeSwitch("server")}>
            在线服务
          </button>
        </div>

        {/* Local panel */}
        {accessMode === "local" && (
          <div style={{ paddingTop: 4 }}>
            <Field label="本地通讯端口">
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
              <Field label="自动解析目录" hint="只读，由插件自动探测">
                <span style={{ fontSize: 11, color: "var(--fg-muted)", fontFamily: "var(--font-mono)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {resolvedDataDir}
                </span>
              </Field>
            )}
            <Field label="目录覆盖" hint="留空使用自动解析路径">
              <input
                style={{ ...inputStyle, width: 200 }}
                type="text"
                value={dataDirOverride}
                placeholder="留空自动探测"
                onChange={(e) => setDataDirOverride(e.target.value)}
                onBlur={() => save("zotero_sync", "zotero_data_dir", dataDirOverride)}
                disabled={saving === "zotero_sync.zotero_data_dir"}
              />
            </Field>
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", padding: "6px 0 4px", lineHeight: 1.5 }}>
              ℹ Zotero 需在同一设备运行，插件将自动探测 {apiPort || "23119"} 端口
            </div>
          </div>
        )}

        {/* Online panel */}
        {accessMode === "server" && (
          <div style={{ paddingTop: 4 }}>
            <Field
              label="Zotero API Key"
              hint={serverKeyPresent ? `当前：${serverKeyMasked || "****"}` : "未设置"}
            >
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  style={{ ...inputStyle, width: 160 }}
                  type="password"
                  autoComplete="off"
                  value={serverKeyDraft}
                  placeholder="输入 Web API key"
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
                  保存
                </Button>
                {serverKeyPresent && (
                  <Button variant="ghost" size="sm" onClick={handleServerKeyDelete} loading={serverKeySaving && serverKeyDraft === ""}>
                    清除
                  </Button>
                )}
              </div>
            </Field>
            {serverKeyError && (
              <div style={{ fontSize: 11, color: "var(--danger)", padding: "2px 0 6px" }}>{serverKeyError}</div>
            )}
            {serverUsername && (
              <Field label="用户名" hint="只读，从 API Key 解析">
                <span style={{ fontSize: 12, color: "var(--fg-muted)", fontFamily: "var(--font-mono)" }}>{serverUsername}</span>
              </Field>
            )}
            <div style={{ fontSize: 11, color: "var(--fg-subtle)", padding: "6px 0 4px", lineHeight: 1.5 }}>
              ℹ 在 zotero.org → 设置 → API Keys 中生成私有 API Key
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

        <Field label="同步模式">
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

        <Field label="自动同步">
          <Toggle
            checked={autoSync}
            onChange={(v) => { setAutoSync(v); save("zotero_sync", "auto_sync_enabled", v); }}
          />
        </Field>

        {autoSync && (
          <Field label="同步间隔（秒）">
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

        <Field label="单向 Pull 镜像" hint="只读镜像 Zotero 条目 / 集合 / PDF，清洗为 Markdown">
          <Button variant="outline" size="sm" loading={syncing} onClick={handleZoteroSync}>
            <Icon name="sync" size={13} /> 立即同步
          </Button>
        </Field>
      </Card>

      <Card
        title="Cloudflare R2 备份"
        icon="cloud"
        badge={<Badge tone={r2Status?.status === "ok" ? "ok" : "neutral"}>{r2Job?.status === "running" ? `${r2Job.stage} ${r2Job.progress}%` : "完整快照"}</Badge>}
      >
        <Field label="Bucket / 插件占用" hint="Bucket 总量包含同一 Bucket 中的非插件对象">
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg-muted)" }}>
            {formatBytes(r2Status?.bucket_used_bytes ?? 0)} / {formatBytes(r2Status?.plugin_used_bytes ?? 0)} · {r2Status?.plugin_object_count ?? 0} objects
          </span>
        </Field>
        <Field label="当前快照" hint="仅保留最新完整快照；未变化文件按内容哈希去重">
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-subtle)" }}>
            {r2Status?.snapshot
              ? `${r2Status.snapshot.snapshot_id} · ${r2Status.snapshot.file_count} files · ${r2Status.snapshot.updated_at}`
              : "尚无快照"}
          </span>
        </Field>
        <Field label="逻辑大小 / 去重节省" hint="逻辑大小是完整恢复所需文件总量；去重节省按当前 blob 物理量计算">
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg-muted)" }}>
            {formatBytes(r2Status?.snapshot?.logical_bytes ?? 0)} / {formatBytes(r2Status?.snapshot?.deduplicated_bytes ?? 0)}
          </span>
        </Field>
        {r2Job?.status === "running" && (
          <div style={{ padding: "8px 0" }}>
            <div style={{ height: 6, borderRadius: 99, background: "var(--surface-strong)", overflow: "hidden" }}>
              <div style={{ width: `${r2Job.progress}%`, height: "100%", background: "var(--accent)", transition: "width .2s" }} />
            </div>
          </div>
        )}
        {r2Job?.status === "error" && (
          <div style={{ padding: "7px 10px", borderRadius: "var(--radius-md)", background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12 }}>
            {r2Job.error || "R2 任务失败"}
          </div>
        )}
        <Field label="完整备份与恢复" hint="恢复会整体覆盖本地持久化数据并自动重启；密钥和依赖不在快照内">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button variant="outline" size="sm" loading={backing} disabled={r2Job?.status === "running"} onClick={() => handleBackup(false)}>
            立即备份
          </Button>
          <Button variant="outline" size="sm" disabled={backing || r2Job?.status === "running"} onClick={() => handleBackup(true)}>
            强制备份
          </Button>
          <Button variant="danger" size="sm" loading={restoring} disabled={r2Job?.status === "running"} onClick={() => setRestoreConfirm(true)}>
            一键恢复
          </Button>
          </div>
        </Field>
      </Card>

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
            <p style={{ color: "var(--danger)" }}>继续会删除全部本地 Zotero 镜像及其 Milvus / LightRAG 索引；本地上传的 collection 与文件不会被删除。确认后将自动拉取新账号。</p>
          </div>
        </Modal>
      )}

      {restoreConfirm && (
        <Modal
          title="恢复 R2 完整快照"
          icon="cloud"
          width={500}
          height="auto"
          onClose={() => setRestoreConfirm(false)}
          footer={<><Button variant="outline" onClick={() => setRestoreConfirm(false)}>取消</Button><Button variant="danger" onClick={handleRestore}>覆盖本地并恢复</Button></>}
        >
          <div style={{ padding: 22, color: "var(--fg)", fontSize: 13, lineHeight: 1.7 }}>
            最新快照会先完整下载并校验，再覆盖本地数据库、原件、Milvus 与 LightRAG 数据。密钥、依赖和设备路径保持当前环境设置。
          </div>
        </Modal>
      )}

      <Card title="Notion 镜像" icon="layers" badge={<Badge tone="warn">即将上线</Badge>}>
        <Field label="从 Notion 拉取元数据" hint="端口预留中，UI 优雅降级">
          <Button variant="ghost" size="sm" disabled>
            拉取
          </Button>
        </Field>
      </Card>
    </>
  );
}

// ─── Tab: Backend Config ──────────────────────────────────────

function ConfigTab() {
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
      if (result.rebuild_required) toast("配置已保存，重启插件并重建索引后完全生效", "info");
      else if (result.restart_required) toast("配置已保存，重启插件后生效", "info");
      else toast("配置已保存", "ok");
      const fresh = await getEffectiveConfig();
      setConfig(fresh);
    } catch (error) {
      toast(error instanceof Error ? error.message : "保存失败", "error");
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
              toast("请输入有效数字", "error");
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
        加载中…
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
        临时迁移入口用于承接已从 AstrBot 配置面板移出的高级项；下方仍保留后端有效配置核对（
        <code style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
          GET /api/config/effective
        </code>
        ），敏感字段已打码。
      </div>

      <Card title="源文档库（迁移）" icon="db" badge={<Badge tone="neutral">WebUI</Badge>}>
        {textConfigField(
          "source_store",
          "default_collection",
          "默认集合",
          "文档上传时未指定集合时归入的默认分组名",
        )}
      </Card>

      <Card title="图谱专用 LLM（迁移）" icon="graph" badge={<Badge tone="warn">重启生效</Badge>}>
        <Field label="图谱构建使用的 LLM" hint="main 复用 AstrBot 主 LLM；local/api 使用单独 OpenAI 兼容端点">
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
        {textConfigField("graph", "lightrag_llm_base_url", "图谱专用 LLM 端点", "仅 provider=local 或 api 时生效", 260)}
        {textConfigField("graph", "lightrag_llm_model", "图谱专用 LLM 模型名", "填写端点上对应的模型标识符", 220)}
        {readonlyConfigField(
          "图谱数据目录",
          valueOf("graph", "working_dir", "lightrag_workspaces"),
          "结构性参数，只读展示；修改目录需手动迁移索引并重启",
        )}
      </Card>

      <Card title="Deep Thinking（迁移）" icon="sparkle" badge={<Badge tone="accent">即时 / 重启</Badge>}>
        {numberConfigField("deep_thinking", "max_rounds", "最大迭代轮数", "轮数越多越全也越慢越贵")}
        {numberConfigField("deep_thinking", "max_sub_queries", "每轮最大子查询数")}
        {numberConfigField("deep_thinking", "wide_top_k", "每个子查询的检索宽度")}
        {numberConfigField("deep_thinking", "rerank_weight", "重排器权重（0~1）", undefined, "float")}
        {toggleConfigField(
          "deep_thinking",
          "verify_enabled",
          "启用答案级校验闭环",
          "合成答案后校验是否被证据完全支撑、是否完整",
        )}
        {numberConfigField("deep_thinking", "max_verify_rounds", "校验不合格后的最大补检轮数")}
        {textConfigField("deep_thinking", "llm_base_url", "深度思考专用 LLM 端点", "填写后使用该 OpenAI-compatible endpoint", 260)}
        {textConfigField("deep_thinking", "llm_model", "深度思考专用 LLM 模型", "填写对应端点上的模型名称", 220)}
        {readonlyConfigField(
          "深度思考专用 LLM API Key",
          valueOf("deep_thinking", "llm_api_key"),
          "机密字段。通过环境变量 KR_DEEP_THINKING_LLM_API_KEY 注入",
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
