import React from "react";

interface EyebrowProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Eyebrow({ children, style }: EyebrowProps) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: ".08em",
        textTransform: "uppercase",
        color: "var(--fg-subtle)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
