import React from "react";

/**
 * Button — the primary pill-shaped action control.
 * Variants: primary (filled accent), outline (accent hairline), ghost (quiet),
 * danger (destructive). Sizes: sm | md. Pass `loading` for an inline spinner.
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  children,
  style,
  ...rest
}) {
  const sizes = {
    sm: { fontSize: 12, padding: "6px 12px" },
    md: { fontSize: 13, padding: "8px 16px" },
  };

  const variants = {
    primary: {
      background: "var(--accent)",
      color: "var(--accent-fg)",
      border: "1px solid transparent",
      boxShadow: "var(--shadow)",
    },
    outline: {
      background: "transparent",
      color: "var(--accent)",
      border: "1px solid var(--accent-border)",
    },
    ghost: {
      background: "transparent",
      color: "var(--fg-muted)",
      border: "1px solid var(--border)",
    },
    danger: {
      background: "var(--danger)",
      color: "#fff",
      border: "1px solid transparent",
    },
  };

  const isDisabled = disabled || loading;

  return (
    <button
      disabled={isDisabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        fontFamily: "var(--font-sans)",
        fontWeight: 500,
        lineHeight: 1.2,
        borderRadius: "var(--radius-pill)",
        cursor: isDisabled ? "not-allowed" : "pointer",
        opacity: isDisabled ? 0.5 : 1,
        userSelect: "none",
        transition: "background .15s, border-color .15s, transform .1s, box-shadow .15s, opacity .15s",
        ...sizes[size],
        ...variants[variant],
        ...style,
      }}
      onMouseDown={(e) => { if (!isDisabled) e.currentTarget.style.transform = "scale(0.97)"; }}
      onMouseUp={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          style={{
            width: 12,
            height: 12,
            border: "2px solid currentColor",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.6s linear infinite",
            display: "inline-block",
          }}
        />
      )}
      {children}
    </button>
  );
}
