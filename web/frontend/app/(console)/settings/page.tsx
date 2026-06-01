"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { useI18n, Lang } from "@/lib/i18n";
import { getEffectiveConfig, EffectiveConfig } from "@/lib/api";

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
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);

  // HSL Accent Colors state
  const [hue, setHue] = useState(32);
  const [sat, setSat] = useState(80);
  const [light, setLight] = useState(48);

  useEffect(() => {
    const defaultH = resolvedTheme === "dark" ? 30 : 32;
    const defaultS = resolvedTheme === "dark" ? 82 : 80;
    const defaultL = resolvedTheme === "dark" ? 54 : 48;

    const savedHue = localStorage.getItem("kr-hue");
    const savedSat = localStorage.getItem("kr-sat");
    const savedLight = localStorage.getItem("kr-light");

    // Theme changes intentionally reset the editor to persisted or themed defaults.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHue(savedHue ? parseInt(savedHue) : defaultH);
    setSat(savedSat ? parseInt(savedSat) : defaultS);
    setLight(savedLight ? parseInt(savedLight) : defaultL);
  }, [resolvedTheme]);

  useEffect(() => {
    getEffectiveConfig()
      .then(setConfig)
      .catch(() => {})
      .finally(() => setLoadingConfig(false));
  }, []);

  function updateAccentColor(h: number, s: number, l: number) {
    if (typeof document !== "undefined") {
      document.documentElement.style.setProperty("--accent-h", String(h));
      document.documentElement.style.setProperty("--accent-s", `${s}%`);
      document.documentElement.style.setProperty("--accent-l", `${l}%`);
    }
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("kr-hue", String(h));
      localStorage.setItem("kr-sat", `${s}%`);
      localStorage.setItem("kr-light", `${l}%`);
      localStorage.removeItem("kr-palette");
      document.documentElement.removeAttribute("data-palette");
    }
  }

  function handlePreset(h: number, s: number, l: number) {
    setHue(h);
    setSat(s);
    setLight(l);
    updateAccentColor(h, s, l);
  }

  return (
    <div
      style={{
        display: "flex", flexDirection: "column", height: "100vh",
        overflow: "hidden", position: "relative",
      }}
    >
      {/* 外观区 sticky 头部 */}
      <div
        className="fx-glass"
        style={{
          position: "sticky", top: 0, zIndex: 3,
          padding: "16px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
          {t("settings_appearance")}
        </h1>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "center" }}>
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
        </div>

        {/* HSL Accent Color Sliders Section */}
        <div 
          style={{ 
            background: "var(--surface)", 
            padding: "16px 20px", 
            borderRadius: 14, 
            border: "1px solid var(--border)", 
            display: "flex", 
            flexDirection: "column", 
            gap: 14,
            boxShadow: "var(--shadow)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--heading)", display: "flex", alignItems: "center" }}>
              自定义强调色 
              <span 
                style={{ 
                  fontFamily: "var(--font-geist-mono)", 
                  fontSize: 11, 
                  background: "var(--accent-soft)", 
                  color: "var(--accent)", 
                  padding: "2px 8px", 
                  borderRadius: 6, 
                  marginLeft: 8,
                  fontWeight: 600,
                  border: "1px solid var(--accent-border)",
                }}
              >
                hsl({hue}, {sat}%, {light}%)
              </span>
            </div>
            
            {/* Elegant 6 Color Presets */}
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "var(--fg-muted)", fontWeight: 500 }}>预设色系:</span>
              {[
                { name: "暖橙", h: 32, s: 80, l: 48 },
                { name: "蓝紫", h: 233, s: 65, l: 58 },
                { name: "森林", h: 135, s: 45, l: 40 },
                { name: "墨灰", h: 220, s: 10, l: 47 },
                { name: "红宝石", h: 350, s: 65, l: 45 },
                { name: "琥珀", h: 45, s: 85, l: 45 },
              ].map((preset) => {
                const presetColor = `hsl(${preset.h}, ${preset.s}%, ${preset.l}%)`;
                const isCurrent = hue === preset.h && sat === preset.s && light === preset.l;
                return (
                  <button
                    key={preset.name}
                    onClick={() => handlePreset(preset.h, preset.s, preset.l)}
                    title={preset.name}
                    style={{
                      width: 20, height: 20, borderRadius: "50%",
                      background: presetColor,
                      border: isCurrent ? "2px solid var(--fg)" : "1px solid var(--border-strong)",
                      boxShadow: isCurrent ? "0 0 0 2px var(--ring)" : "none",
                      cursor: "pointer",
                      padding: 0,
                      transition: "all 0.15s",
                    }}
                  />
                );
              })}
            </div>
          </div>

          <p style={{ margin: 0, fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.5 }}>
            {t("settings_accent_hint")}
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 20 }}>
            {/* Hue Slider */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--fg-muted)", fontWeight: 600 }}>
                <span>{t("settings_hue")}</span>
                <span>{hue}°</span>
              </div>
              <input
                type="range"
                min="0"
                max="360"
                value={hue}
                onChange={(e) => {
                  const h = parseInt(e.target.value);
                  setHue(h);
                  updateAccentColor(h, sat, light);
                }}
                style={{
                  WebkitAppearance: "none",
                  appearance: "none",
                  width: "100%",
                  height: 8,
                  borderRadius: 99,
                  background: `linear-gradient(90deg, 
                    hsl(0, ${sat}%, ${light}%) 0%, 
                    hsl(60, ${sat}%, ${light}%) 17%, 
                    hsl(120, ${sat}%, ${light}%) 33%, 
                    hsl(180, ${sat}%, ${light}%) 50%, 
                    hsl(240, ${sat}%, ${light}%) 67%, 
                    hsl(300, ${sat}%, ${light}%) 83%, 
                    hsl(360, ${sat}%, ${light}%) 100%
                  )`,
                  outline: "none",
                  cursor: "pointer",
                }}
              />
            </div>

            {/* Saturation Slider */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--fg-muted)", fontWeight: 600 }}>
                <span>{t("settings_saturation")}</span>
                <span>{sat}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={sat}
                onChange={(e) => {
                  const s = parseInt(e.target.value);
                  setSat(s);
                  updateAccentColor(hue, s, light);
                }}
                style={{
                  WebkitAppearance: "none",
                  appearance: "none",
                  width: "100%",
                  height: 8,
                  borderRadius: 99,
                  background: `linear-gradient(90deg, 
                    hsl(${hue}, 0%, ${light}%) 0%, 
                    hsl(${hue}, 100%, ${light}%) 100%
                  )`,
                  outline: "none",
                  cursor: "pointer",
                }}
              />
            </div>

            {/* Lightness Slider */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--fg-muted)", fontWeight: 600 }}>
                <span>{t("settings_lightness")}</span>
                <span>{light}%</span>
              </div>
              <input
                type="range"
                min="24"
                max="78"
                value={light}
                onChange={(e) => {
                  const l = parseInt(e.target.value);
                  setLight(l);
                  updateAccentColor(hue, sat, l);
                }}
                style={{
                  WebkitAppearance: "none",
                  appearance: "none",
                  width: "100%",
                  height: 8,
                  borderRadius: 99,
                  background: `linear-gradient(90deg, 
                    hsl(${hue}, ${sat}%, 24%) 0%, 
                    hsl(${hue}, ${sat}%, 50%) 50%, 
                    hsl(${hue}, ${sat}%, 78%) 100%
                  )`,
                  outline: "none",
                  cursor: "pointer",
                }}
              />
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
            <ConfigCard title={t("settings_config_vector_db")} data={config?.vector_db as Record<string, unknown>} />
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
