"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useI18n, I18nKey, Lang } from "@/lib/i18n";
import { getEffectiveConfig, EffectiveConfig, updateConfigValue, testEmbeddingConnection, EmbeddingTestResult, listLocalModels, deleteLocalModel, LocalModel } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { HelpTip } from "@/components/ui/HelpTip";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

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
  const [vectorBackend, setVectorBackend] = useState<"astr" | "milvus">("milvus");
  const [embedProvider, setEmbedProvider] = useState<"local" | "external" | "astr">("local");
  const [embedModel, setEmbedModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [embedMaxTokenSize, setEmbedMaxTokenSize] = useState(512);
  const [autoIndexEnabled, setAutoIndexEnabled] = useState(true);
  const [askEnhancementMode, setAskEnhancementMode] = useState<"inject" | "query_agent">("inject");
  const [graphEnabled, setGraphEnabled] = useState(false);
  const [graphQueryMode, setGraphQueryMode] = useState("mix");
  const [graphLlmMaxAsync, setGraphLlmMaxAsync] = useState(4);
  const [graphEmbeddingMaxAsync, setGraphEmbeddingMaxAsync] = useState(8);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<EmbeddingTestResult | null>(null);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [deletingModel, setDeletingModel] = useState<string | null>(null);
  // 标记表单是否已由服务端值初始化，防止保存后重拉的空值覆盖用户输入
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!config) return;
    if (!initializedRef.current) {
      // 首次加载：全量同步
      initializedRef.current = true;
      if (config.vector_db) {
        setVectorBackend((config.vector_db.backend as "astr" | "milvus") || "milvus");
        setAutoIndexEnabled(Boolean(config.vector_db.auto_index_enabled ?? true));
      }
      if (config.embedding) {
        setEmbedProvider((config.embedding.provider as "local" | "external" | "astr") || "local");
        setEmbedModel((config.embedding.model as string) || "");
        setBaseUrl((config.embedding.base_url as string) || "");
        setEmbedMaxTokenSize(Number(config.embedding.max_token_size) || 512);
      }
      if (config.ask) {
        setAskEnhancementMode((config.ask.conversation_enhancement_mode as "inject" | "query_agent") || "inject");
      }
      if (config.graph) {
        setGraphEnabled(Boolean(config.graph.enabled));
        setGraphQueryMode((config.graph.query_mode as string) || "mix");
        setGraphLlmMaxAsync(Number(config.graph.llm_max_async) || 4);
        setGraphEmbeddingMaxAsync(Number(config.graph.embedding_max_async) || 8);
      }
    } else {
      // 保存后重拉：只更新枚举型选择项，不覆盖用户已编辑的文本框
      if (config.vector_db) {
        setVectorBackend((config.vector_db.backend as "astr" | "milvus") || "milvus");
        setAutoIndexEnabled(Boolean(config.vector_db.auto_index_enabled ?? true));
      }
      if (config.embedding) {
        setEmbedProvider((config.embedding.provider as "local" | "external" | "astr") || "local");
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
      const updates: [string, string, unknown][] = [
        ["vector_db", "backend", vectorBackend],
        ["vector_db", "auto_index_enabled", autoIndexEnabled],
        ["embedding", "provider", embedProvider],
        ["embedding", "model", embedModel],
        ["embedding", "base_url", baseUrl],
        ["embedding", "max_token_size", embedMaxTokenSize],
        ["ask", "conversation_enhancement_mode", askEnhancementMode],
        ["graph", "enabled", graphEnabled],
        ["graph", "query_mode", graphQueryMode],
        ["graph", "llm_max_async", graphLlmMaxAsync],
        ["graph", "embedding_max_async", graphEmbeddingMaxAsync],
      ];
      const results: Awaited<ReturnType<typeof updateConfigValue>>[] = [];
      for (const [section, key, value] of updates) {
        results.push(await updateConfigValue(section, key, value));
      }
      const restart = results.some((result) => result.restart_required);
      const rebuild = results.some((result) => result.rebuild_required);
      setSaveMessage(
        lang === "zh"
          ? `配置已保存。${restart ? "需要重启插件。" : ""}${rebuild ? "需要重建 Milvus 与 LightRAG 索引。" : ""}`
          : `Configuration saved.${restart ? " Restart required." : ""}${rebuild ? " Rebuild Milvus and LightRAG indexes." : ""}`
      );
      
      const freshConfig = await getEffectiveConfig();
      setConfig(freshConfig);
    } catch (err: unknown) {
      setSaveMessage(`${lang === "zh" ? "保存失败" : "Save failed"}: ${errorMessage(err)}`);
    } finally {
      setSaving(false);
    }
  }


  async function handleDeleteModel(name: string) {
    if (!confirm(`确认删除本地模型 ${name}？此操作不可撤销。`)) return;
    setDeletingModel(name);
    try {
      await deleteLocalModel(name);
      setLocalModels((prev) => prev.filter((m) => m.name !== name));
    } catch { /* silent */ } finally {
      setDeletingModel(null);
    }
  }

  useEffect(() => {
    if (embedProvider !== "local") return;
    listLocalModels().then(setLocalModels).catch(() => {});
  }, [embedProvider]);

  async function handleTestEmbedding() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testEmbeddingConnection(baseUrl, embedModel);
      setTestResult(result);
    } catch (err: unknown) {
      setTestResult({ status: "error", message: errorMessage(err) });
    } finally {
      setTesting(false);
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

  // 数据流概览与后端切换已迁至独立的「数据流 / 配置向导」页（/flow）；此处仅保留诊断提示与高级字段编辑。
  const diagnostics = config?.diagnostics ?? [];

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
          <Link
            href="/flow"
            style={{
              display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
              textDecoration: "none",
              background: "var(--accent-soft)", border: "1px solid var(--accent-border)",
              borderRadius: 10, padding: "12px 16px",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--accent)" }}>
              {lang === "zh" ? "数据流 / 配置向导" : "Data Flow / Setup"}
            </span>
            <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>
              {lang === "zh"
                ? "查看各环节当前后端、按需切换、并安装可选依赖 →"
                : "See active backends per stage, switch on demand, install optional deps →"}
            </span>
          </Link>

          {diagnostics.length > 0 && (
            <div style={{ background: "color-mix(in srgb, var(--warn, #e09a5b) 10%, transparent)", border: "1px solid color-mix(in srgb, var(--warn, #e09a5b) 35%, transparent)", borderRadius: 10, padding: "10px 12px", color: "var(--fg-muted)", fontSize: 11, lineHeight: 1.55 }}>
              <strong style={{ color: "var(--warn, #e09a5b)" }}>{lang === "zh" ? "运行时提示：" : "Runtime diagnostics: "}</strong>
              {diagnostics.join(" · ")}
            </div>
          )}

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

              <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={autoIndexEnabled}
                  disabled={vectorBackend !== "milvus"}
                  onChange={(e) => setAutoIndexEnabled(e.target.checked)}
                />
                <span style={{ opacity: vectorBackend === "milvus" ? 1 : .5 }}>
                  <strong style={{ display: "block", color: "var(--fg)", fontSize: 12 }}>
                    {lang === "zh" ? "上传后自动建立 Milvus 索引" : "Build Milvus index after upload"}
                  </strong>
                  <span style={{ display: "block", marginTop: 2, fontSize: 10, color: "var(--fg-subtle)" }}>
                    {lang === "zh" ? "关闭后 PDF 与 SQLite 分块仍会保存并可词汇召回" : "PDFs and SQLite chunks remain available for lexical retrieval when off"}
                  </span>
                </span>
              </label>

              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                  {t("settings_embed_provider")}
                </div>
                <SegmentedControl
                  options={[
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
                    {lang === "zh" ? "AstrBot Embedding 尚未接入" : "AstrBot Embedding is not implemented"}
                  </div>
                  {lang === "zh"
                    ? "该旧配置会禁用 Milvus 与 LightRAG。请选择“本地离线”或“云端 API”后保存并重启。"
                    : "This legacy value disables Milvus and LightRAG. Choose Local or Cloud API, save, and restart."}
                </div>
              ) : (
                <>
                  {/* ── Embedding 模型名称（combobox 风格） ── */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                      {t("settings_embed_model")}
                    </div>
                    {/* 主输入框 */}
                    <input
                      type="text"
                      value={embedModel}
                      onChange={(e) => setEmbedModel(e.target.value)}
                      placeholder={embedProvider === "local" ? "intfloat/multilingual-e5-small" : "text-embedding-3-small"}
                      style={{
                        background: "var(--bg-inset)", border: "1px solid var(--border)",
                        borderRadius: 8, padding: "8px 12px", fontSize: 13,
                        color: "var(--fg)", outline: "none", width: "100%",
                        fontFamily: "var(--font-geist-mono)", marginBottom: 8,
                      }}
                    />
                    {/* 快速填入 chips */}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                      {(embedProvider === "local"
                        ? [
                            { value: "intfloat/multilingual-e5-small", hint: lang === "zh" ? "多语言·轻量默认" : "Multilingual·Default" },
                            { value: "BAAI/bge-m3", hint: lang === "zh" ? "多语言·长文本" : "Multilingual·Long" },
                            { value: "BAAI/bge-small-zh-v1.5", hint: lang === "zh" ? "中文·轻量" : "ZH·Small" },
                          ]
                        : [
                            { value: "text-embedding-3-small", hint: "OpenAI" },
                            { value: "text-embedding-3-large", hint: "OpenAI" },
                            { value: "BAAI/bge-m3", hint: lang === "zh" ? "硅基流动" : "SiliconFlow" },
                          ]
                      ).map((p) => (
                        <button
                          key={p.value}
                          type="button"
                          onClick={() => {
                            setEmbedModel(p.value);
                            if (embedProvider === "local") {
                              setEmbedMaxTokenSize(p.value === "BAAI/bge-m3" ? 8192 : 512);
                            }
                          }}
                          style={{
                            padding: "3px 9px", borderRadius: 999, fontSize: 11, fontFamily: "inherit",
                            border: "1px solid var(--border)", cursor: "pointer", transition: "all .1s",
                            background: embedModel === p.value ? "var(--accent-soft)" : "var(--bg-inset)",
                            color: embedModel === p.value ? "var(--accent)" : "var(--fg-muted)",
                            fontWeight: embedModel === p.value ? 600 : 400,
                          }}
                        >
                          {p.value.split("/").pop()} <span style={{ opacity: 0.6 }}>· {p.hint}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {embedProvider === "external" ? (
                    <>
                      <div style={{ background: "var(--accent-soft)", border: "1px solid var(--accent-border)", borderRadius: 10, padding: "10px 12px", fontSize: 11, lineHeight: 1.6, color: "var(--accent)" }}>
                        {lang === "zh"
                          ? "API Key 仅从环境变量 KR_EMBEDDING_API_KEY 读取，Web 设置页不会接收或持久化密钥。"
                          : "The API key is read only from KR_EMBEDDING_API_KEY. The Web settings page never accepts or persists it."}
                      </div>

                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-muted)", marginBottom: 6 }}>
                          {t("settings_base_url")}
                        </div>
                        <input
                          type="text"
                          value={baseUrl}
                          onChange={(e) => { setBaseUrl(e.target.value); setTestResult(null); }}
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

                      {/* 连接测试 */}
                      <div>
                        <button
                          type="button"
                          onClick={handleTestEmbedding}
                          disabled={testing || !baseUrl || !embedModel}
                          style={{
                            padding: "7px 14px", fontSize: 12, fontWeight: 600,
                            borderRadius: 8, border: "1px solid var(--border)",
                            background: testing ? "var(--bg-inset)" : "var(--surface)",
                            color: testing ? "var(--fg-muted)" : "var(--fg)",
                            cursor: testing || !baseUrl || !embedModel ? "not-allowed" : "pointer",
                            opacity: !baseUrl || !embedModel ? 0.5 : 1,
                            fontFamily: "inherit", transition: "all .15s",
                          }}
                        >
                          {testing
                            ? (lang === "zh" ? "测试中..." : "Testing...")
                            : (lang === "zh" ? "测试连接" : "Test Connection")}
                        </button>
                        {testResult && (
                          <div style={{
                            marginTop: 8, padding: "8px 12px", borderRadius: 8, fontSize: 12,
                            background: testResult.status === "ok" ? "color-mix(in srgb, var(--accent) 10%, transparent)" : "color-mix(in srgb, #e05b5b 10%, transparent)",
                            border: `1px solid ${testResult.status === "ok" ? "var(--accent-border)" : "#e05b5b44"}`,
                            color: testResult.status === "ok" ? "var(--accent)" : "#e05b5b",
                            lineHeight: 1.5,
                          }}>
                            {testResult.status === "ok"
                              ? `✓ ${lang === "zh" ? "连接成功" : "Connected"} · ${lang === "zh" ? "向量维度" : "dim"} ${testResult.dimension}`
                              : `✗ ${testResult.message}`}
                          </div>
                        )}
                      </div>
                    </>
                  ) : (
                    <div
                      style={{
                        background: "var(--accent-soft)",
                        border: "1px solid var(--accent-border)",
                        borderRadius: 10,
                        padding: "14px 16px",
                        fontSize: 12,
                        color: "var(--accent)",
                        lineHeight: 1.65,
                      }}
                    >
                      <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 13 }}>
                        💡 {lang === "zh" ? "本地离线 Embedding 部署指引" : "Local Embedding Setup Guide"}
                      </div>
                      <div style={{ marginBottom: 10, color: "var(--fg)" }}>
                        {lang === "zh"
                          ? "本地模式不会随插件自动安装，避免首次安装下载大型 PyTorch/CUDA。单一 Additional Requirements 文件会同时安装全部扩展功能与开发工具。"
                          : "Local mode is not auto-installed, avoiding large PyTorch/CUDA downloads during plugin setup. The single Additional Requirements file installs all extensions and development tools."}
                      </div>
                      <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--accent)" }}>
                        {lang === "zh" ? "第 1 步：安装依赖" : "Step 1: Install dependencies"}
                      </div>
                      <code style={{ display: "block", background: "var(--bg-inset)", border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 6, marginBottom: 10, fontFamily: "var(--font-geist-mono)", color: "var(--fg)", fontSize: 11 }}>
                        python -m pip install torch --index-url https://download.pytorch.org/whl/cpu &amp;&amp; python -m pip install -r requirements-additional.txt
                      </code>
                      <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--accent)" }}>
                        {lang === "zh" ? "第 2 步：选择模型（首次运行自动下载）" : "Step 2: Pick a model (auto-downloaded on first run)"}
                      </div>
                      <div style={{ marginBottom: 10, color: "var(--fg-muted)", fontSize: 11 }}>
                        {lang === "zh"
                          ? "安装 requirements-additional.txt 后，默认 intfloat/multilingual-e5-small 可为 Milvus 与 LightRAG 提供多语言向量；需要更长上下文时可切换 BAAI/bge-m3。"
                          : "After installing requirements-additional.txt, the default intfloat/multilingual-e5-small provides multilingual vectors for Milvus and LightRAG; use BAAI/bge-m3 for longer context."}
                      </div>
                      <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--accent)" }}>
                        {lang === "zh" ? "国内网络加速（可选）" : "China mirror (optional)"}
                      </div>
                      <code style={{ display: "block", background: "var(--bg-inset)", border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 6, fontFamily: "var(--font-geist-mono)", color: "var(--fg)", fontSize: 11 }}>
                        {`HF_ENDPOINT=https://hf-mirror.com python -m pip install -r requirements-additional.txt`}
                      </code>

                      {/* 已安装本地模型列表 */}
                      <div style={{ marginTop: 14, fontWeight: 600, fontSize: 12, color: "var(--fg-muted)", marginBottom: 8 }}>
                        {lang === "zh" ? "已安装的本地模型" : "Installed Local Models"}
                      </div>
                      {localModels.length === 0 ? (
                        <div style={{ fontSize: 11, color: "var(--fg-subtle)", padding: "8px 0" }}>
                          {lang === "zh" ? "暂未检测到本地缓存模型" : "No cached models detected"}
                        </div>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {localModels.map((m) => {
                            const isCurrent = m.name === embedModel;
                            const sizeMb = (m.size_bytes / 1024 / 1024).toFixed(0);
                            return (
                              <div
                                key={m.name}
                                style={{
                                  display: "flex", alignItems: "center", gap: 8,
                                  background: isCurrent ? "var(--accent-soft)" : "var(--bg-inset)",
                                  border: `1px solid ${isCurrent ? "var(--accent-border)" : "var(--border)"}`,
                                  borderRadius: 8, padding: "6px 10px",
                                }}
                              >
                                <span style={{ flex: 1, fontSize: 11, fontFamily: "var(--font-geist-mono)", color: isCurrent ? "var(--accent)" : "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {m.name}
                                </span>
                                {isCurrent && (
                                  <span style={{ fontSize: 9, fontWeight: 700, background: "var(--accent)", color: "#fff", borderRadius: 999, padding: "1px 6px", flexShrink: 0 }}>
                                    {lang === "zh" ? "当前" : "Active"}
                                  </span>
                                )}
                                <span style={{ fontSize: 10, color: "var(--fg-subtle)", flexShrink: 0 }}>{sizeMb} MB</span>
                                <button
                                  onClick={() => handleDeleteModel(m.name)}
                                  disabled={deletingModel === m.name}
                                  title={lang === "zh" ? "删除此模型" : "Delete model"}
                                  style={{ background: "none", border: "none", cursor: deletingModel === m.name ? "wait" : "pointer", color: "var(--fg-subtle)", padding: 2, display: "flex", alignItems: "center", flexShrink: 0, transition: "color .15s" }}
                                  onMouseEnter={(e) => { e.currentTarget.style.color = "var(--danger)"; }}
                                  onMouseLeave={(e) => { e.currentTarget.style.color = "var(--fg-subtle)"; }}
                                >
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                    <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>
                                  </svg>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--heading)" }}>{t("graph_config_section_title")}</div>
              <span style={{ borderRadius: 999, padding: "2px 7px", background: graphEnabled ? "var(--accent-soft)" : "var(--bg-inset)", border: `1px solid ${graphEnabled ? "var(--accent-border)" : "var(--border)"}`, color: graphEnabled ? "var(--accent)" : "var(--fg-subtle)", fontSize: 9, fontWeight: 700 }}>
                {graphEnabled ? (lang === "zh" ? "已启用" : "Enabled") : (lang === "zh" ? "可选 / 默认关闭" : "Optional / Off by default")}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.55, marginBottom: 12 }}>
              {lang === "zh"
                ? "仅供 Web Research Agent 的指定 Collection 高精度召回；上传不会自动构建，也不会影响默认 Milvus 召回。"
                : "Used only for high-precision retrieval on a selected collection in Web Research Agent. Uploads never auto-build it and default Milvus retrieval remains independent."}
            </div>
            <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
              <input type="checkbox" checked={graphEnabled} onChange={(e) => setGraphEnabled(e.target.checked)} />
              {t("graph_config_enabled")}
              <HelpTip text={t("graph_config_enabled_help")} />
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, opacity: graphEnabled ? 1 : .45, pointerEvents: graphEnabled ? "auto" : "none" }}>
              <label style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                {t("graph_config_max_token_size")}
                <input
                  type="number"
                  min={1}
                  value={embedMaxTokenSize}
                  onChange={(e) => setEmbedMaxTokenSize(Number(e.target.value))}
                  style={{ display: "block", width: "100%", marginTop: 5 }}
                />
              </label>
              <label style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                {t("graph_config_query_mode")}
                <HelpTip text={t("graph_config_query_mode_help")} />
                <Select
                  value={graphQueryMode}
                  onChange={setGraphQueryMode}
                  options={(["mix", "local", "global", "hybrid", "naive", "bypass"] as const).map((mode) => ({
                    value: mode,
                    label: t(`graph_mode_${mode}` as I18nKey),
                  }))}
                  style={{ display: "block", width: "100%", marginTop: 5 }}
                />
              </label>
              {([
                [t("graph_config_llm_max_async"), t("graph_config_llm_max_async_help"), graphLlmMaxAsync, setGraphLlmMaxAsync],
                [t("graph_config_embedding_max_async"), t("graph_config_embedding_max_async_help"), graphEmbeddingMaxAsync, setGraphEmbeddingMaxAsync],
              ] as [string, string, number, React.Dispatch<React.SetStateAction<number>>][]).map(([label, help, value, setter]) => (
                <label key={label} style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                  {label}
                  <HelpTip text={help} />
                  <input type="number" min={1} value={value} onChange={(e) => setter(Number(e.target.value))} style={{ display: "block", width: "100%", marginTop: 5 }} />
                </label>
              ))}
              <label style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                {t("graph_config_working_dir")}
                <HelpTip text={t("graph_config_working_dir_help")} />
                <input readOnly value={String(config?.graph?.working_dir ?? "lightrag_workspaces")} style={{ display: "block", width: "100%", marginTop: 5, opacity: .7 }} />
              </label>
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: "var(--warn)" }}>{t("graph_config_rebuild_warn")}</div>
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
            <ConfigCard title={t("settings_config_embedding")} data={config?.embedding as Record<string, unknown>} />
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
