import React from "react";

/**
 * QuotaBar — labelled usage meter for R2 / Notion storage. Pass `ratio` (0–1);
 * the fill turns warn at >= `warnThreshold` (default 0.8) and danger at >= 0.95.
 * `label` and `detail` render above the track.
 */
export function QuotaBar({ ratio, label, detail, warnThreshold = 0.8, style }) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const fill =
    ratio >= 0.95 ? "var(--danger)" : ratio >= warnThreshold ? "var(--warn)" : "var(--accent)";

  return (
    <div style={{ fontFamily: "var(--font-sans)", ...style }}>
      {(label || detail) && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 7 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--heading)" }}>{label}</span>
          <span style={{ fontSize: 11, color: "var(--fg-muted)", fontFamily: "var(--font-mono)" }}>{detail}</span>
        </div>
      )}
      <div
        style={{
          height: 8,
          borderRadius: "var(--radius-pill)",
          background: "var(--bg-inset)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            borderRadius: "var(--radius-pill)",
            background: fill,
            transition: "width .4s cubic-bezier(0.4,0,0.2,1), background .2s",
          }}
        />
      </div>
    </div>
  );
}
