"use client";

export { useTheme } from "next-themes";

export type Palette = "default" | "moirai" | "forest" | "graphite";

const PALETTE_KEY = "kr-palette";

export function getPalette(): Palette {
  if (typeof localStorage === "undefined") return "default";
  return (localStorage.getItem(PALETTE_KEY) as Palette) ?? "default";
}

export function setPalette(p: Palette) {
  if (typeof document === "undefined") return;
  const html = document.documentElement;
  if (p === "default") {
    html.removeAttribute("data-palette");
  } else {
    html.setAttribute("data-palette", p);
  }
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(PALETTE_KEY, p);
  }
}

export function initPalette() {
  const p = getPalette();
  if (p !== "default") setPalette(p);

  if (typeof localStorage !== "undefined" && typeof document !== "undefined") {
    const hue = localStorage.getItem("kr-hue");
    const sat = localStorage.getItem("kr-sat");
    const light = localStorage.getItem("kr-light");
    
    if (hue !== null) {
      document.documentElement.style.setProperty("--accent-h", hue);
    }
    if (sat !== null) {
      document.documentElement.style.setProperty("--accent-s", sat.includes("%") ? sat : `${sat}%`);
    }
    if (light !== null) {
      document.documentElement.style.setProperty("--accent-l", light.includes("%") ? light : `${light}%`);
    }
  }
}
