"use client";
import React, { useState } from "react";
import { Icon } from "./Icon";
import { Tooltip } from "./Tooltip";

interface IconButtonProps {
  name?: string;
  label?: string;
  size?: number;
  active?: boolean;
  side?: "bottom" | "top" | "left" | "right";
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}

export function IconButton({
  name,
  label,
  size = 16,
  active = false,
  side = "bottom",
  onClick,
  style,
  children,
}: IconButtonProps) {
  const [hover, setHover] = useState(false);
  return (
    <Tooltip label={label} side={side}>
      <button
        onClick={onClick}
        aria-label={label}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          width: 26,
          height: 26,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          border: "none",
          borderRadius: "var(--radius-sm)",
          cursor: "pointer",
          background: active
            ? "var(--accent-soft)"
            : hover
            ? "var(--bg-inset)"
            : "transparent",
          color: active
            ? "var(--accent)"
            : hover
            ? "var(--fg)"
            : "var(--fg-subtle)",
          transition: "background .12s, color .12s",
          ...style,
        }}
      >
        {children ?? (name ? <Icon name={name} size={size} /> : null)}
      </button>
    </Tooltip>
  );
}
