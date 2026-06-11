"use client";
import React, { useState, useRef, useEffect } from "react";
import { Icon } from "./Icon";

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onChange?: (value: string) => void;
  options: SelectOption[];
  size?: "sm" | "md";
  style?: React.CSSProperties;
  disabled?: boolean;
}

export function Select({ value, onChange, options, size = "sm", style, disabled }: SelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const h = size === "sm" ? 30 : 34;
  const fs = size === "sm" ? 12 : 13;
  const sel = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block", ...style }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        style={{
          height: h,
          paddingLeft: 11,
          paddingRight: 28,
          width: "100%",
          textAlign: "left",
          background: "var(--surface)",
          border: `1px solid ${open ? "var(--accent)" : "var(--border-strong)"}`,
          borderRadius: "var(--radius-md)",
          color: "var(--fg)",
          fontSize: fs,
          fontWeight: 500,
          fontFamily: "var(--font-sans)",
          cursor: disabled ? "not-allowed" : "pointer",
          display: "flex",
          alignItems: "center",
          position: "relative",
          boxShadow: open ? "0 0 0 3px var(--ring)" : "none",
          transition: "border-color .14s, box-shadow .14s",
          opacity: disabled ? 0.55 : 1,
        }}
      >
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {sel ? sel.label : value}
        </span>
        <Icon
          name="chevD"
          size={13}
          style={{
            position: "absolute",
            right: 9,
            color: "var(--fg-subtle)",
            transform: open ? "rotate(180deg)" : undefined,
            transition: "transform .18s",
          }}
        />
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 5px)",
            left: 0,
            minWidth: "100%",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-lg)",
            boxShadow: "var(--shadow-pop)",
            padding: 4,
            zIndex: 700,
          }}
        >
          {options.map((o) => {
            const active = o.value === value;
            return (
              <button
                key={o.value}
                onClick={() => { onChange?.(o.value); setOpen(false); }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  padding: "6px 9px",
                  borderRadius: "var(--radius-sm)",
                  background: active ? "var(--accent-soft)" : "transparent",
                  color: active ? "var(--accent)" : "var(--fg)",
                  border: "none",
                  cursor: "pointer",
                  fontSize: fs,
                  fontWeight: active ? 600 : 400,
                  fontFamily: "var(--font-sans)",
                  textAlign: "left",
                  whiteSpace: "nowrap",
                }}
                onMouseEnter={(e) => { if (!active) (e.currentTarget).style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { if (!active) (e.currentTarget).style.background = "transparent"; }}
              >
                {active
                  ? <Icon name="check" size={12} />
                  : <span style={{ width: 12, display: "inline-block" }} />
                }
                {o.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
