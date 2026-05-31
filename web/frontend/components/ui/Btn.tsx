"use client";

import React from "react";

type Variant = "primary" | "ghost" | "danger" | "outline";
type Size = "sm" | "md";

interface BtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const BASE =
  "inline-flex items-center gap-1.5 font-medium cursor-pointer rounded-full border transition-all focus-visible:outline-none disabled:opacity-50 disabled:cursor-not-allowed select-none";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-[--accent] text-[--accent-fg] border-transparent hover:opacity-90 active:scale-[.97] shadow-sm",
  ghost:
    "bg-transparent text-[--fg-muted] border-[--border] hover:bg-[--surface-hover] hover:text-[--fg] active:scale-[.97]",
  danger:
    "bg-[--danger] text-white border-transparent hover:opacity-90 active:scale-[.97]",
  outline:
    "bg-transparent text-[--accent] border-[--accent-border] hover:bg-[--accent-soft] active:scale-[.97]",
};

const SIZES: Record<Size, string> = {
  sm: "text-xs px-3 py-1.5",
  md: "text-sm px-4 py-2",
};

export function Btn({
  variant = "primary",
  size = "md",
  loading,
  children,
  className,
  disabled,
  ...rest
}: BtnProps) {
  return (
    <button
      className={[BASE, VARIANTS[variant], SIZES[size], className].filter(Boolean).join(" ")}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <span
          style={{
            display: "inline-block",
            width: 12,
            height: 12,
            border: "2px solid currentColor",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.6s linear infinite",
          }}
        />
      )}
      {children}
    </button>
  );
}
