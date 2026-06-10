"use client";

import React from "react";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
}

export function Toggle({ checked, onChange, disabled, label }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        background: "none",
        border: "none",
        padding: 0,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        userSelect: "none",
        fontFamily: "inherit",
        fontSize: "inherit",
        color: "inherit",
      }}
    >
      <span
        style={{
          position: "relative",
          display: "inline-block",
          width: 32,
          height: 18,
          borderRadius: 999,
          background: checked ? "var(--accent)" : "var(--bg-inset)",
          border: `1.5px solid ${checked ? "var(--accent)" : "var(--border)"}`,
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
            background: checked ? "var(--accent-fg)" : "var(--fg-subtle)",
            transition: "left .15s, background .15s",
          }}
        />
      </span>
      {label && <span>{label}</span>}
    </button>
  );
}
