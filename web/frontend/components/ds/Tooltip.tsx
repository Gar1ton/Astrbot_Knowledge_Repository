"use client";
import React, { useState } from "react";

interface TooltipProps {
  label?: string;
  side?: "bottom" | "top" | "left" | "right";
  children: React.ReactNode;
}

export function Tooltip({ label, side = "bottom", children }: TooltipProps) {
  const [show, setShow] = useState(false);

  const pos: React.CSSProperties =
    side === "bottom"
      ? { top: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" }
      : side === "left"
      ? { right: "calc(100% + 7px)", top: "50%", transform: "translateY(-50%)" }
      : side === "right"
      ? { left: "calc(100% + 7px)", top: "50%", transform: "translateY(-50%)" }
      : { bottom: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" };

  return (
    <span
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && label && (
        <span
          style={{
            position: "absolute",
            ...pos,
            zIndex: 900,
            whiteSpace: "nowrap",
            background: "#26272b",
            color: "#fff",
            fontSize: 11,
            fontWeight: 500,
            padding: "4px 8px",
            borderRadius: 6,
            pointerEvents: "none",
            boxShadow: "0 4px 14px rgba(0,0,0,.22)",
            letterSpacing: ".01em",
          }}
        >
          {label}
        </span>
      )}
    </span>
  );
}
