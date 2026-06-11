import React from "react";

/**
 * StatusChip — dot + label capsule for pipeline/connection state, mirroring the
 * Data-Flow nodes. `status`: ready | degraded | off | info. A degraded dot pulses.
 */
export function StatusChip({ status = "off", children, style }) {
  const colors = {
    ready: "var(--ok)",
    degraded: "var(--warn)",
    off: "var(--fg-subtle)",
    info: "#6c79c4",
  };
  const c = colors[status] || colors.off;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        padding: "3px 9px",
        borderRadius: "var(--radius-pill)",
        border: `1px solid color-mix(in srgb, ${c} 30%, transparent)`,
        color: c,
        background: `color-mix(in srgb, ${c} 9%, transparent)`,
        fontFamily: "var(--font-sans)",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          flexShrink: 0,
          background: c,
          animation: status === "degraded" ? "krDotPulse 1.7s ease-in-out infinite" : "none",
        }}
      />
      {children}
      <style>{`@keyframes krDotPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
    </span>
  );
}
