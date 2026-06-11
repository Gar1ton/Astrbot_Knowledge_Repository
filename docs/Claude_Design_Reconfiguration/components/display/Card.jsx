import React from "react";

/**
 * Card — the base surface container (documents inspector, source cards,
 * settings sections, dialogs). `featured` adds a gradient hairline + glow for
 * the Research Agent / primary surfaces. `pad` toggles default padding.
 */
export function Card({ featured = false, pad = true, style, children, ...rest }) {
  return (
    <div
      className={featured ? "fx-gborder" : undefined}
      style={{
        position: "relative",
        background: "var(--surface)",
        border: `1px solid ${featured ? "var(--accent-border)" : "var(--border)"}`,
        borderRadius: "var(--radius-2xl)",
        boxShadow: featured ? "var(--shadow), 0 0 24px var(--accent-soft)" : "var(--shadow)",
        padding: pad ? 16 : 0,
        color: "var(--fg)",
        fontFamily: "var(--font-sans)",
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
