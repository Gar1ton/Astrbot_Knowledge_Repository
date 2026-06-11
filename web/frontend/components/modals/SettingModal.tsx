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
  getEffectiveConfig, getZoteroConfig, syncZoteroPull, backupNow,
  EffectiveConfig, ZoteroConfig,
} from "@/lib/api";

interface SettingModalProps {
  onClose: () => void;
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

// ─── Tab: Appearance ──────────────────────────────────────────

function AppearanceTab() {
  const { theme, setTheme } = useTheme();
  const { lang, setLang, t } = useI18n();
  const [accent, setAccent] = useState({ h: 225, s: 72, l: 56 });

  useEffect(() => {
    setAccent(getAccentFromDOM());
  }, []);

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
    </>
  );
}

// ─── Tab: Sync/Backup ─────────────────────────────────────────

function SyncTab() {
  const { toast } = useToast();
  const [zotero, setZotero] = useState<ZoteroConfig | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [backing, setBacking] = useState(false);

  useEffect(() => {
    getZoteroConfig().then(setZotero).catch(() => {});
  }, []);

  async function handleZoteroSync() {
    setSyncing(true);
    try {
      const r = await syncZoteroPull(true);
      toast(
        r.status === "success"
          ? `同步完成：${r.items_mirrored ?? 0} 条目`
          : (r.message ?? "同步完成"),
        "ok",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "同步失败", "error");
    } finally {
      setSyncing(false);
    }
  }

  async function handleBackup() {
    setBacking(true);
    try {
      await backupNow();
      toast("备份任务已提交", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : "备份失败", "error");
    } finally {
      setBacking(false);
    }
  }

  const zoteroConnected = zotero?.connection?.connected ?? false;

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
        <Field label="单向 Pull 镜像" hint="只读镜像 Zotero 条目 / 集合 / 标签 / PDF，清洗为 Markdown">
          <Button variant="outline" size="sm" loading={syncing} onClick={handleZoteroSync}>
            <Icon name="sync" size={13} /> 立即同步
          </Button>
        </Field>
        <Field
          label="自动同步"
          hint={`间隔 ${zotero?.auto_sync_interval_sec ?? 3600} 秒`}
        >
          <Toggle checked={zotero?.auto_sync_enabled ?? false} onChange={() => {}} />
        </Field>
        {zotero?.availability && !zotero.availability.available && (
          <div
            style={{
              fontSize: 11,
              color: "var(--warn)",
              marginTop: 4,
              padding: "6px 0",
              lineHeight: 1.5,
            }}
          >
            ⚠ {zotero.availability.reason}
          </div>
        )}
      </Card>

      <Card
        title="Cloudflare R2 备份"
        icon="cloud"
        badge={<Badge tone="neutral">按需触发</Badge>}
      >
        <Field label="对象存储备份" hint="将知识库数据备份到 R2">
          <Button variant="outline" size="sm" loading={backing} onClick={handleBackup}>
            立即备份
          </Button>
        </Field>
      </Card>

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
  const [config, setConfig] = useState<EffectiveConfig | null>(null);

  useEffect(() => {
    getEffectiveConfig().then(setConfig).catch(() => {});
  }, []);

  const SENSITIVE_KEYS = ["password", "api_key", "secret", "token", "key"];

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
        只读核对后端有效配置（
        <code style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
          GET /api/config/effective
        </code>
        ），敏感字段已打码。
      </div>
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

export function SettingModal({ onClose }: SettingModalProps) {
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
          {tab === "appearance" && <AppearanceTab />}
          {tab === "sync" && <SyncTab />}
          {tab === "config" && <ConfigTab />}
          {tab === "terminal" && <TerminalPanel variant="embedded" />}
        </div>
      </div>
    </Modal>
  );
}
