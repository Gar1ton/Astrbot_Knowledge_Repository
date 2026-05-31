"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { useI18n, Lang } from "@/lib/i18n";
import { setPalette, Palette } from "@/lib/theme";
import { getEffectiveConfig, EffectiveConfig } from "@/lib/api";
import { SunBloom } from "@/components/fx/SunBloom";

// ─── 外观控件 ─────────────────────────────────────────────────

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        background: "var(--bg-inset)",
        border: "1px solid var(--border)",
        borderRadius: 999,
        padding: 2,
        gap: 2,
      }}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            border: "none",
            borderRadius: 999,
            padding: "5px 14px",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "inherit",
            transition: "all .15s",
            background: value === opt.value ? "var(--surface)" : "transparent",
            color: value === opt.value ? "var(--accent)" : "var(--fg-muted)",
            boxShadow: value === opt.value ? "var(--shadow)" : "none",
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function PaletteSwatch({ p, active, onClick }: { p: Palette; active: boolean; onClick: () => void }) {
  const COLORS: Record<Palette, string> = {
    default: "#df7a18",
    moirai: "#6b7adb",
    forest: "#3d8a4f",
    graphite: "#6e7480",
  };
  return (
    <button
      onClick={onClick}
      title={p}
      style={{
        width: 28, height: 28, borderRadius: "50%",
        background: COLORS[p],
        border: `2px solid ${active ? "var(--fg)" : "transparent"}`,
        boxShadow: active ? "0 0 0 2px var(--ring)" : "none",
        cursor: "pointer",
        transition: "all .15s",
        padding: 0,
      }}
    />
  );
}

// ─── 配置卡片 ─────────────────────────────────────────────────

function ConfigCard({ title, data }: { title: string; data?: Record<string, unknown> }) {
  if (!data) return null;
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "14px 16px",
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--fg-muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {title}
      </div>
      <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "130px 1fr", gap: "5px 10px" }}>
        {Object.entries(data).map(([k, v]) => (
          <React.Fragment key={k}>
            <dt style={{ fontSize: 12, color: "var(--fg-subtle)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k}</dt>
            <dd
              style={{
                margin: 0, fontSize: 12,
                color: String(v).includes("****") ? "var(--fg-muted)" : "var(--fg)",
                fontFamily: "var(--font-geist-mono)",
                wordBreak: "break-all",
              }}
            >
              {String(v === null || v === undefined ? "—" : v)}
            </dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}

// ─── 设置页 ───────────────────────────────────────────────────

export default function SettingsPage() {
  const { t, lang, setLang } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const [palette, setPaletteState] = useState<Palette>("default");
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);

  useEffect(() => {
    const saved = typeof localStorage !== "undefined"
      ? (localStorage.getItem("kr-palette") as Palette | null)
      : null;
    if (saved) setPaletteState(saved);
  }, []);

  useEffect(() => {
    getEffectiveConfig()
      .then(setConfig)
      .catch(() => {})
      .finally(() => setLoadingConfig(false));
  }, []);

  function handlePalette(p: Palette) {
    setPaletteState(p);
    setPalette(p);
  }

  const PALETTES: Palette[] = ["default", "moirai", "forest", "graphite"];

  return (
    <div
      style={{
        display: "flex", flexDirection: "column", height: "100vh",
        overflow: "hidden", position: "relative",
      }}
    >
      {/* 装饰 SunBloom */}
      <SunBloom
        size={400}
        style={{ top: -80, right: -80, opacity: 0.7 }}
      />

      {/* 外观区 sticky 头部 */}
      <div
        className="fx-glass"
        style={{
          position: "sticky", top: 0, zIndex: 3,
          padding: "16px 24px",
        }}
      >
        <h1 style={{ margin: "0 0 14px", fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
          {t("settings_appearance")}
        </h1>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "center" }}>
          {/* 主题 */}
          <div>
            <div style={{ fontSize: 11, color: "var(--fg-muted)", marginBottom: 6, fontWeight: 600 }}>
              {t("settings_theme")}
            </div>
            <SegmentedControl
              options={[
                { value: "light", label: t("settings_theme_light") },
                { value: "dark", label: t("settings_theme_dark") },
                { value: "system", label: t("settings_theme_system") },
              ]}
              value={(resolvedTheme === "dark" ? "dark" : "light")}
              onChange={(v) => setTheme(v)}
            />
          </div>

          {/* 语言 */}
          <div>
            <div style={{ fontSize: 11, color: "var(--fg-muted)", marginBottom: 6, fontWeight: 600 }}>
              {t("settings_lang")}
            </div>
            <SegmentedControl
              options={[
                { value: "zh" as Lang, label: "中文" },
                { value: "en" as Lang, label: "English" },
              ]}
              value={lang}
              onChange={setLang}
            />
          </div>

          {/* 色系 */}
          <div>
            <div style={{ fontSize: 11, color: "var(--fg-muted)", marginBottom: 6, fontWeight: 600 }}>
              {t("settings_palette")}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {PALETTES.map((p) => (
                <PaletteSwatch
                  key={p}
                  p={p}
                  active={palette === p}
                  onClick={() => handlePalette(p)}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 配置只读区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        <h2 style={{ margin: "0 0 14px", fontSize: 14, fontWeight: 700, color: "var(--heading)" }}>
          {t("settings_config_title")}
        </h2>

        {loadingConfig ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 13 }}>{t("loading")}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
            <ConfigCard title={t("settings_config_source")} data={config?.source_store as Record<string, unknown>} />
            <ConfigCard title={t("settings_config_r2")} data={config?.r2_sync as Record<string, unknown>} />
            <ConfigCard title={t("settings_config_notion")} data={config?.notion_sync as Record<string, unknown>} />
            <ConfigCard title={t("settings_config_web")} data={config?.web_console as Record<string, unknown>} />
            <ConfigCard title={t("settings_config_graph")} data={config?.graph as Record<string, unknown>} />
            <ConfigCard title={t("settings_config_ask")} data={config?.ask as Record<string, unknown>} />
          </div>
        )}
      </div>
    </div>
  );
}
