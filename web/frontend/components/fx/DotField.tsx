"use client";

import React from "react";

const DOTS = Array.from({ length: 12 }, (_, i) => ({
  x: (i * 37 + 13) % 100,
  y: (i * 53 + 7) % 100,
  s: 2 + (i % 3),
  d: (i % 6) * 0.7,
  dur: 7 + (i % 5) * 1.6,
}));

interface DotFieldProps {
  className?: string;
}

export function DotField({ className }: DotFieldProps) {
  return (
    <div
      aria-hidden
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
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
            opacity: 0.18,
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
