"use client";
import React from "react";
import { Icon } from "./Icon";

type Variant = "primary" | "outline" | "ghost" | "danger" | "tab";
type Size = "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  active?: boolean;
  loading?: boolean;
}

const SIZES: Record<Size, React.CSSProperties> = {
  sm: { fontSize: 12, padding: "5px 10px", height: 28 },
  md: { fontSize: 13, padding: "7px 13px", height: 32 },
};

export function Button({
  variant = "primary",
  size = "md",
  active = false,
  loading = false,
  disabled,
  children,
  style,
  onMouseDown,
  onMouseUp,
  onMouseLeave,
  ...rest
}: ButtonProps) {
  const dis = disabled || loading;

  const variantStyle: Record<Variant, React.CSSProperties> = {
    primary: { background: "var(--accent)", color: "var(--accent-fg)", border: "1px solid transparent", boxShadow: "0 1px 2px rgba(22,23,26,.12)" },
    outline: { background: "var(--surface)", color: "var(--fg)", border: "1px solid var(--border-strong)" },
    ghost: { background: "transparent", color: "var(--fg-muted)", border: "1px solid transparent" },
    danger: { background: "var(--danger)", color: "#fff", border: "1px solid transparent" },
    tab: {
      background: "var(--surface)",
      color: active ? "var(--accent)" : "var(--fg)",
      border: `1px solid ${active ? "var(--accent-border)" : "var(--border-strong)"}`,
      boxShadow: active ? "0 0 0 3px var(--ring)" : "var(--shadow-card)",
    },
  };

  return (
    <button
      disabled={dis}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        fontFamily: "var(--font-sans)",
        fontWeight: 500,
        lineHeight: 1,
        borderRadius: "var(--radius-md)",
        cursor: dis ? "not-allowed" : "pointer",
        opacity: dis ? 0.55 : 1,
        userSelect: "none",
        transition: "background .14s, border-color .14s, box-shadow .14s, transform .08s",
        ...SIZES[size],
        ...variantStyle[variant],
        ...style,
      }}
      onMouseDown={(e) => {
        if (!dis) (e.currentTarget as HTMLButtonElement).style.transform = "scale(0.975)";
        onMouseDown?.(e);
      }}
      onMouseUp={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
        onMouseUp?.(e);
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {loading && (
        <Icon
          name="sync"
          size={12}
          style={{ animation: "spin .6s linear infinite" }}
        />
      )}
      {children}
    </button>
  );
}
