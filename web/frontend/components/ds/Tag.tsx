import React from "react";

interface TagProps {
  label: string;
  accent?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
  style?: React.CSSProperties;
}

export function Tag({ label, accent = false, onRemove, onClick, style }: TagProps) {
  return (
    <span
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: accent ? "var(--accent-soft)" : "var(--bg-inset)",
        border: `1px solid ${accent ? "var(--accent-border)" : "transparent"}`,
        color: accent ? "var(--accent)" : "var(--fg-muted)",
        borderRadius: "var(--radius-pill)",
        padding: "1px 9px",
        fontSize: 11,
        fontWeight: 500,
        lineHeight: "19px",
        whiteSpace: "nowrap",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >
      {label}
      {onRemove && (
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            color: "inherit",
            opacity: 0.55,
            fontSize: 13,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}
