"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { useI18n, Lang } from "@/lib/i18n";
import { getEffectiveConfig, EffectiveConfig, updateConfigValue } from "@/lib/api";

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

  // Form states for editable config
  const [vectorBackend, setVectorBackend] = useState<"astr" | "milvus">("astr");
  const [embedProvider, setEmbedProvider] = useState<"local" | "external" | "astr">("local");
  const [embedModel, setEmbedModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [askEnhancementMode, setAskEnhancementMode] = useState<"inject" | "query_agent">("inject");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  useEffect(() => {
    if (config) {
      if (config.vector_db) {
        setVectorBackend((config.vector_db.backend as "astr" | "milvus") || "astr");
        setEmbedProvider((config.vector_db.embedding_provider as "local" | "external" | "astr") || "local");
        setEmbedModel((config.vector_db.embedding_model as string) || "");
        setApiKey((config.vector_db.api_key as string) || "");
        setBaseUrl((config.vector_db.base_url as string) || "");
      }
      if (config.ask) {
        setAskEnhancementMode((config.ask.conversation_enhancement_mode as "inject" | "query_agent") || "inject");
      }
    }
  }, [config]);

  async function handleSaveConfig() {
    setSaving(true);
    setSaveMessage("");
    try {
      await updateConfigValue("vector_db", "backend", vectorBackend);
      await updateConfigValue("vector_db", "embedding_provider", embedProvider);
      await updateConfigValue("vector_db", "embedding_model", embedModel);
      await updateConfigValue("vector_db", "api_key", apiKey);
      await updateConfigValue("vector_db", "base_url", baseUrl);
      await updateConfigValue("ask", "conversation_enhancement_mode", askEnhancementMode);

      setSaveMessage(lang === "zh" ? "配置更新成功并已成功重载！" : "Configuration updated and reloaded successfully!");
      
      const freshConfig = await getEffectiveConfig();
      setConfig(freshConfig);
    } catch (err: any) {
      setSaveMessage(`${lang === "zh" ? "保存失败" : "Save failed"}: ${err.message || err}`);
    } finally {
      setSaving(false);
    }
  }


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
        {/* 配置修改编辑区 */}
        <h2 style={{ margin: "0 0 14px", fontSize: 14, fontWeight: 700, color: "var(--heading)" }}>
          {t("settings_edit_title")}
        </h2>

        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 14,
            padding: "20px 24px",
            marginBottom: 28,
            boxShadow: "var(--shadow)",
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24 }}>
            {/* Left Column: Backend and Provider selectors */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                  {t("settings_vector_backend")}
                </div>
                <SegmentedControl
                  options={[
                    { value: "astr", label: "AstrBot" },
                    { value: "milvus", label: "Milvus Lite" },
                  ]}
                  value={vectorBackend}
                  onChange={(v) => setVectorBackend(v as "astr" | "milvus")}
                />
              </div>

              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                  {t("settings_embed_provider")}
                </div>
                <SegmentedControl
                  options={[
                    { value: "astr", label: lang === "zh" ? "AstrBot 内置" : "AstrBot" },
                    { value: "local", label: lang === "zh" ? "本地离线" : "Local" },
                    { value: "external", label: lang === "zh" ? "云端 API" : "Cloud API" },
                  ]}
                  value={embedProvider}
                  onChange={(v) => setEmbedProvider(v as "local" | "external" | "astr")}
                />
              </div>

              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                  {t("settings_ask_mode")}
                </div>
                <SegmentedControl
                  options={[
                    { value: "inject", label: lang === "zh" ? "原生召回注入" : "Inject" },
                    { value: "query_agent", label: lang === "zh" ? "内部代理询问" : "Query Agent" },
                  ]}
                  value={askEnhancementMode}
                  onChange={(v) => setAskEnhancementMode(v as "inject" | "query_agent")}
                />
              </div>
            </div>

            {/* Right Column: Model Name, API Key, Base URL inputs */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {embedProvider === "astr" ? (
                <div
                  style={{
                    background: "var(--accent-soft)",
                    border: "1px solid var(--accent-border)",
                    borderRadius: 10,
                    padding: "12px 16px",
                    fontSize: 12,
                    color: "var(--accent)",
                    lineHeight: 1.6,
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>
                    {lang === "zh" ? "复用 AstrBot 内置 Embedding" : "Reuse AstrBot Embedding"}
                  </div>
                  {lang === "zh"
                    ? "将直接调用 AstrBot 主框架已配置的 Embedding 模型，无需单独安装依赖或填写 API Key。模型名称与参数由 AstrBot 自身管理。"
                    : "Uses the embedding model already configured in AstrBot. No extra dependencies or API keys required — model settings are managed by AstrBot."}
                </div>
              ) : (
                <>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                      {t("settings_embed_model")}
                    </div>
                    <input
                      type="text"
                      value={embedModel}
                      onChange={(e) => setEmbedModel(e.target.value)}
                      placeholder="e.g. BAAI/bge-m3, text-embedding-3-small"
                      style={{
                        background: "var(--bg-inset)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        padding: "8px 12px",
                        fontSize: 13,
                        color: "var(--fg)",
                        outline: "none",
                        width: "100%",
                        fontFamily: "inherit",
                      }}
                    />
                  </div>

                  {embedProvider === "external" ? (
                    <>
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                          {t("settings_api_key")}
                        </div>
                        <input
                          type="password"
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="sk-..."
                          style={{
                            background: "var(--bg-inset)",
                            border: "1px solid var(--border)",
                            borderRadius: 8,
                            padding: "8px 12px",
                            fontSize: 13,
                            color: "var(--fg)",
                            outline: "none",
                            width: "100%",
                            fontFamily: "inherit",
                          }}
                        />
                      </div>

                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                          {t("settings_base_url")}
                        </div>
                        <input
                          type="text"
                          value={baseUrl}
                          onChange={(e) => setBaseUrl(e.target.value)}
                          placeholder="https://api.openai.com/v1"
                          style={{
                            background: "var(--bg-inset)",
                            border: "1px solid var(--border)",
                            borderRadius: 8,
                            padding: "8px 12px",
                            fontSize: 13,
                            color: "var(--fg)",
                            outline: "none",
                            width: "100%",
                            fontFamily: "inherit",
                          }}
                        />
                      </div>
                    </>
                  ) : (
                    <div
                      style={{
                        background: "var(--accent-soft)",
                        border: "1px solid var(--accent-border)",
                        borderRadius: 10,
                        padding: "12px 16px",
                        fontSize: 12,
                        color: "var(--accent)",
                        lineHeight: 1.5,
                      }}
                    >
                      <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("settings_local_guide")}</div>
                      {t("settings_local_guide_text")}
                      <code style={{
                        display: "block",
                        background: "var(--bg-inset)",
                        border: "1px solid var(--border)",
                        padding: "6px 10px",
                        borderRadius: 6,
                        marginTop: 6,
                        fontFamily: "var(--font-geist-mono)",
                        color: "var(--fg)",
                      }}>
                        pip install sentence-transformers
                      </code>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 10 }}>
            <button
              onClick={handleSaveConfig}
              disabled={saving}
              style={{
                background: "var(--accent)",
                color: "var(--surface)",
                border: "none",
                borderRadius: 8,
                padding: "10px 24px",
                fontSize: 13,
                fontWeight: 600,
                cursor: saving ? "not-allowed" : "pointer",
                opacity: saving ? 0.7 : 1,
                transition: "all 0.15s",
                boxShadow: "0 2px 8px var(--accent-soft)",
              }}
            >
              {saving ? t("settings_saving") : t("settings_save")}
            </button>
            {saveMessage && (
              <span
                style={{
                  fontSize: 12,
                  color: saveMessage.includes("成功") || saveMessage.includes("success") ? "var(--accent)" : "#ef4444",
                  fontWeight: 500,
                }}
              >
                {saveMessage}
              </span>
            )}
          </div>
        </div>

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
