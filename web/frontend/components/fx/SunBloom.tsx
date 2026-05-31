"use client";

import React from "react";

interface SunBloomProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

export function SunBloom({ size = 320, className, style }: SunBloomProps) {
  const dotSpacing = 8;
  const cols = Math.ceil(size / dotSpacing);
  const rows = Math.ceil(size / dotSpacing);
  const cx = size / 2;
  const cy = size / 2;
  const maxR = size / 2;

  return (
    <div
      aria-hidden
      className={className}
      style={{
        position: "absolute",
        width: size,
        height: size,
        pointerEvents: "none",
        ...style,
      }}
    >
      {/* 点阵层，缓旋 + 呼吸 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          animation: [
            "sunSpin 90s linear infinite",
            "sunBreathe 8s ease-in-out infinite",
          ].join(", "),
        }}
      >
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {Array.from({ length: rows }, (_, ry) =>
            Array.from({ length: cols }, (_, rx) => {
              const px = rx * dotSpacing;
              const py = ry * dotSpacing;
              const dist = Math.sqrt((px - cx) ** 2 + (py - cy) ** 2);
              if (dist > maxR) return null;
              const alpha = Math.max(0, 1 - dist / maxR);
              return (
                <circle
                  key={`${rx}-${ry}`}
                  cx={px}
                  cy={py}
                  r={1.1}
                  fill="var(--accent)"
                  opacity={alpha * 0.55}
                />
              );
            })
          )}
        </svg>
      </div>

      {/* 内层柔光 radial */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: "50%",
          background: `radial-gradient(circle at 50% 50%, var(--accent-soft) 0%, transparent 70%)`,
          opacity: 0.6,
        }}
      />
    </div>
  );
}
