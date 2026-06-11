import React from "react";

/**
 * Tag — small pill for document tags, retrieval-mode labels, and filters.
 * `accent` highlights an active/selected tag; pass `onRemove` to show a × button.
 */
export function Tag({ label, onRemove, accent = false, style, ...rest }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: accent ? "var(--accent-soft)" : "var(--bg-inset)",
        border: `1px solid ${accent ? "var(--accent-border)" : "var(--border)"}`,
        color: accent ? "var(--accent)" : "var(--fg-muted)",
        borderRadius: "var(--radius-pill)",
        padding: "1px 8px",
        fontSize: 11,
        fontWeight: 500,
        lineHeight: "20px",
        whiteSpace: "nowrap",
        fontFamily: "var(--font-sans)",
        ...style,
      }}
      {...rest}
    >
      {label}
      {onRemove && (
        <button
          onClick={onRemove}
          aria-label={`移除标签 ${label}`}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            color: "inherit",
            display: "flex",
            alignItems: "center",
            opacity: 0.6,
            lineHeight: 1,
            fontSize: 13,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}
