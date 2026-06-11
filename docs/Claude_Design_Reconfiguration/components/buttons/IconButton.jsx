import React from "react";

/**
 * IconButton — a square, quiet button for a single icon (toolbar toggles,
 * close buttons, panel collapse). Pass an inline SVG (or any node) as children.
 * `active` paints it with the accent-soft surface.
 */
export function IconButton({
  size = 28,
  active = false,
  title,
  children,
  style,
  ...rest
}) {
  return (
    <button
      title={title}
      aria-pressed={active}
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border)",
        background: active ? "var(--accent-soft)" : "var(--bg-inset)",
        color: active ? "var(--accent)" : "var(--fg-subtle)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        transition: "background .15s, color .15s, border-color .15s",
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!active) { e.currentTarget.style.background = "var(--surface-hover)"; e.currentTarget.style.color = "var(--fg)"; }
      }}
      onMouseLeave={(e) => {
        if (!active) { e.currentTarget.style.background = "var(--bg-inset)"; e.currentTarget.style.color = "var(--fg-subtle)"; }
      }}
      {...rest}
    >
      {children}
    </button>
  );
}
