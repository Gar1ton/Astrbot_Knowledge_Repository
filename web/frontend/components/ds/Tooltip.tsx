"use client";
import React, { useRef, useState } from "react";
import { Popover } from "./Popover";
import { Z } from "@/lib/zLayers";

interface TooltipProps {
  label?: string;
  side?: "bottom" | "top" | "left" | "right";
  children: React.ReactNode;
}

export function Tooltip({ label, side = "bottom", children }: TooltipProps) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  return (
    <span
      ref={ref}
      style={{ display: "inline-flex" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {label && (
        <Popover open={show} anchorRef={ref} side={side} align="center" gap={7} zIndex={Z.tooltip}>
          <span
            style={{
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
        </Popover>
      )}
    </span>
  );
}
