import React from "react";

/**
 * Badge — a soft status/origin pill (本地上传 / Zotero 同步 / 只读 / 已脱管 /
 * 即将上线). `tone` selects the semantic color: neutral | accent | info |
 * ok | warn | danger | violet.
 */
export function Badge({ tone = "neutral", children, style, ...rest }) {
  const tones = {
    neutral: { bg: "var(--bg-inset)", fg: "var(--fg-muted)" },
    accent: { bg: "var(--accent-soft)", fg: "var(--accent)" },
    info: { bg: "rgba(52,120,200,0.12)", fg: "#2e6bb0" },
    ok: { bg: "var(--ok-soft)", fg: "var(--ok)" },
    warn: { bg: "var(--warn-soft)", fg: "var(--warn)" },
    danger: { bg: "var(--danger-soft)", fg: "var(--danger)" },
    violet: { bg: "rgba(140,90,200,0.14)", fg: "#7a3fb0" },
  };
  const c = tones[tone] || tones.neutral;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        fontWeight: 600,
        lineHeight: 1.4,
        padding: "2px 9px",
        borderRadius: "var(--radius-pill)",
        background: c.bg,
        color: c.fg,
        fontFamily: "var(--font-sans)",
        whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
