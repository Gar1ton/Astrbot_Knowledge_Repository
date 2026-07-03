"use client";
import React, { useState } from "react";
import { Icon } from "@/components/ds/Icon";
import { useI18n, type I18nKey } from "@/lib/i18n";
import { THEMES, type ThemeName, getColorTheme, setColorTheme } from "@/lib/theme";

/*
 * ThemeGallery：2×3 主题预览卡片网格。
 * 卡片内层 div 设 data-theme={name}，构成 ds-tokens.css 的「主题边界」——
 * 派生块选择器为 `:root, [data-theme]` / `.dark, .dark [data-theme]`，
 * 因此内部 var(--bg)/--surface/--accent… 即为目标主题的真实 token，
 * 页面处于 .dark 时自动呈现该主题的暗色变体，无需任何 JS 取色。
 */

const THEME_LABEL_KEY: Record<ThemeName, I18nKey> = {
  venus: "settings_theme_venus",
  nox: "settings_theme_nox",
  juno: "settings_theme_juno",
  augustus: "settings_theme_augustus",
  selune: "settings_theme_selune",
  folio: "settings_theme_folio",
};

export function ThemeGallery() {
  const [current, setCurrent] = useState<ThemeName>(() => getColorTheme());

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: 10,
        padding: "10px 0 4px",
      }}
    >
      {THEMES.map((name) => (
        <ThemeCard
          key={name}
          name={name}
          active={name === current}
          onSelect={() => {
            setColorTheme(name);
            setCurrent(name);
          }}
        />
      ))}
    </div>
  );
}

function ThemeCard({
  name,
  active,
  onSelect,
}: {
  name: ThemeName;
  active: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      onClick={onSelect}
      aria-pressed={active}
      style={{
        padding: 0,
        borderRadius: "var(--radius-lg)",
        cursor: "pointer",
        textAlign: "left",
        // 外层选中态用「当前生效主题」的 token（在主题边界之外）
        border: active ? "2px solid var(--accent)" : "2px solid var(--border)",
        boxShadow: active ? "0 0 0 3px var(--ring)" : "none",
        overflow: "hidden",
        background: "var(--surface)",
        transition: "border-color .15s, box-shadow .15s",
      }}
    >
      {/* 主题边界：内部全部 token 解析为目标主题；归零 --mode-tint 使预览不受 LightRAG 偏色影响 */}
      <div
        data-theme={name}
        style={
          {
            background: "var(--bg)",
            padding: 10,
            "--mode-tint": "0%",
          } as React.CSSProperties
        }
      >
        {/* 迷你顶栏：surface 条 + accent 圆点 + 占位文字线 */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 5,
            padding: "5px 7px",
            display: "flex",
            gap: 5,
            alignItems: "center",
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: 99, background: "var(--accent)", flexShrink: 0 }} />
          <span style={{ flex: 1, height: 4, borderRadius: 99, background: "var(--fg-subtle)" }} />
        </div>
        {/* 文字层级两行 */}
        <div style={{ marginTop: 8, height: 5, width: "62%", borderRadius: 99, background: "var(--fg)" }} />
        <div style={{ marginTop: 4, height: 4, width: "84%", borderRadius: 99, background: "var(--fg-muted)" }} />
        {/* 主色按钮丸 */}
        <div
          style={{
            marginTop: 9,
            display: "inline-block",
            padding: "3px 10px",
            borderRadius: 5,
            background: "var(--accent)",
            color: "var(--accent-fg)",
            fontSize: 9,
            fontWeight: 600,
            lineHeight: 1.3,
          }}
        >
          Aa
        </div>
      </div>
      {/* 名称条：主题边界之外，用当前生效主题的 token */}
      <div
        style={{
          padding: "6px 9px",
          fontSize: 11.5,
          fontWeight: active ? 600 : 500,
          color: active ? "var(--fg)" : "var(--fg-muted)",
          borderTop: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 6,
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {t(THEME_LABEL_KEY[name])}
        </span>
        {active && <Icon name="check" size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />}
      </div>
    </button>
  );
}
