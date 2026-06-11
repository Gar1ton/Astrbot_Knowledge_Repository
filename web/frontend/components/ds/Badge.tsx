import React from "react";

type Tone = "neutral" | "accent" | "info" | "ok" | "warn" | "danger" | "violet";

interface BadgeProps {
  tone?: Tone;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: "var(--bg-inset)", fg: "var(--fg-muted)" },
  accent:  { bg: "var(--accent-soft)", fg: "var(--accent)" },
  info:    { bg: "var(--info-soft)", fg: "var(--info)" },
  ok:      { bg: "var(--ok-soft)", fg: "var(--ok)" },
  warn:    { bg: "var(--warn-soft)", fg: "var(--warn)" },
  danger:  { bg: "var(--danger-soft)", fg: "var(--danger)" },
  violet:  { bg: "var(--ann-purple-bg)", fg: "var(--ann-purple)" },
};

export function Badge({ tone = "neutral", children, style }: BadgeProps) {
  const t = TONES[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10.5,
        fontWeight: 600,
        padding: "1.5px 7px",
        borderRadius: "var(--radius-sm)",
        background: t.bg,
        color: t.fg,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
}
