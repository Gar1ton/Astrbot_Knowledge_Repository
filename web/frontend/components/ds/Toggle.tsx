"use client";
import React from "react";

interface ToggleProps {
  checked: boolean;
  onChange?: (val: boolean) => void;
  disabled?: boolean;
  label?: string;
  style?: React.CSSProperties;
}

export function Toggle({ checked, onChange, disabled, label, style }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange?.(!checked)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        background: "none",
        border: "none",
        padding: 0,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontFamily: "var(--font-sans)",
        fontSize: 13,
        color: "var(--fg)",
        ...style,
      }}
    >
      <span
        style={{
          position: "relative",
          width: 32,
          height: 18,
          borderRadius: 999,
          background: checked ? "var(--accent)" : "var(--bg-inset)",
          border: `1.5px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
          transition: "background .15s, border-color .15s",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 2,
            left: checked ? 14 : 2,
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: checked ? "#fff" : "var(--fg-subtle)",
            transition: "left .15s",
          }}
        />
      </span>
      {label && <span>{label}</span>}
    </button>
  );
}
