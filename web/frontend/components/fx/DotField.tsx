"use client";
import React from "react";

const DOTS = Array.from({ length: 22 }, (_, i) => {
  const isNear = i % 5 === 0;
  return {
    x: (i * 17 + 11) % 100,
    y: (i * 29 + 7) % 100,
    s: isNear ? 4 + (i % 2) : 1.5 + (i % 2),
    d: (i % 7) * 0.8,
    dur: 9 + (i % 6) * 2,
    isNear,
  };
});

interface DotFieldProps {
  className?: string;
  style?: React.CSSProperties;
}

export function DotField({ className, style }: DotFieldProps) {
  return (
    <div
      aria-hidden
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
        zIndex: 1,
        ...style,
      }}
    >
      {DOTS.map((p, i) => (
        <span
          key={i}
          style={{
            position: "absolute",
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.s,
            height: p.s,
            borderRadius: 99,
            background: "var(--accent)",
            opacity: p.isNear ? 0.32 : 0.16,
            boxShadow: p.isNear ? "0 0 8px 1px var(--accent)" : "none",
            animation: [
              `dotDrift ${p.dur}s ${p.d}s ease-in-out infinite`,
              `dotTwinkle ${p.dur * 0.6}s ${p.d}s ease-in-out infinite`,
            ].join(", "),
          }}
        />
      ))}
    </div>
  );
}
