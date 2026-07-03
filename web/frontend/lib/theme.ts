"use client";

// 明暗模式（light/dark/system）继续由 next-themes 管理，这里仅转发。
export { useTheme } from "next-themes";

// ─── 命名主题（色彩主题，与明暗模式正交） ─────────────────────
// 每套主题在 ds-tokens.css 中定义亮/暗双模式的完整种子变量；
// html 的 data-theme 属性恒被设置（含默认 nox），首帧由 app/layout.tsx 内联脚本写入。

export type ThemeName = "venus" | "nox" | "juno" | "augustus" | "selune" | "folio";

export const THEMES: readonly ThemeName[] = [
  "venus",
  "nox",
  "juno",
  "augustus",
  "selune",
  "folio",
];

export const DEFAULT_THEME: ThemeName = "nox";

const THEME_KEY = "kr-theme";

// 旧版换肤系统遗留键：kr-palette（旧 data-palette 预设名）、kr-hue/sat/light（HSL 滑杆）
const LEGACY_KEYS = ["kr-palette", "kr-hue", "kr-sat", "kr-light"] as const;

function isThemeName(v: string | null): v is ThemeName {
  return v !== null && (THEMES as readonly string[]).includes(v);
}

export function getColorTheme(): ThemeName {
  if (typeof localStorage === "undefined") return DEFAULT_THEME;
  const v = localStorage.getItem(THEME_KEY);
  return isThemeName(v) ? v : DEFAULT_THEME;
}

export function setColorTheme(t: ThemeName) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", t);
  }
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(THEME_KEY, t);
  }
}

export function initColorTheme() {
  if (typeof localStorage === "undefined" || typeof document === "undefined") return;

  // 迁移：kr-theme 缺失时，旧 kr-palette 值若恰为新主题名则平移（venus 等 6 名是旧 Palette 子集）
  if (localStorage.getItem(THEME_KEY) === null) {
    const legacy = localStorage.getItem("kr-palette");
    localStorage.setItem(THEME_KEY, isThemeName(legacy) ? legacy : DEFAULT_THEME);
  }

  // 清理旧键与旧版可能残留的行内 HSL 变量（行内样式优先级高于任何样式表，必须显式移除）
  for (const k of LEGACY_KEYS) localStorage.removeItem(k);
  const style = document.documentElement.style;
  style.removeProperty("--accent-h");
  style.removeProperty("--accent-s");
  style.removeProperty("--accent-l");

  // 兜底同步属性（正常情况下 layout 内联脚本已在首帧设置）
  setColorTheme(getColorTheme());
}
