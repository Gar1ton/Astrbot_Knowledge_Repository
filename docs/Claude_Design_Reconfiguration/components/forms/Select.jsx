import React from "react";

/**
 * Select — custom dropdown matching the warm surface system. Options are
 * `{ value, label }`. Renders a pill-bordered trigger with a chevron and an
 * animated popover with a check on the active row. Sizes: sm | md.
 */
export function Select({ value, onChange, options, placeholder, size = "sm", disabled = false, style }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const height = size === "sm" ? 32 : 36;
  const fontSize = size === "sm" ? 12 : 13;

  const selected = options.find((o) => o.value === value);
  const label = selected ? selected.label : placeholder != null ? placeholder : value;

  React.useEffect(() => {
    if (!open) return;
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block", ...style }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        style={{
          height,
          paddingLeft: 11,
          paddingRight: 30,
          background: open ? "var(--surface-hover)" : "var(--surface)",
          border: `1px solid ${open ? "var(--accent)" : "var(--border)"}`,
          borderRadius: "var(--radius-md)",
          color: "var(--fg)",
          fontSize,
          fontWeight: 500,
          fontFamily: "var(--font-sans)",
          cursor: disabled ? "not-allowed" : "pointer",
          display: "flex",
          alignItems: "center",
          whiteSpace: "nowrap",
          width: "100%",
          textAlign: "left",
          gap: 6,
          boxShadow: open ? "0 0 0 3px var(--ring)" : "var(--shadow)",
          transition: "border-color .15s, box-shadow .15s, background .15s",
          position: "relative",
          opacity: disabled ? 0.55 : 1,
        }}
      >
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
        <svg
          width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--fg-subtle)"
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          style={{
            position: "absolute", right: 9, top: "50%",
            transform: `translateY(-50%) rotate(${open ? 180 : 0}deg)`,
            transition: "transform .2s", pointerEvents: "none",
          }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, minWidth: "100%",
            background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-pop)",
            padding: 4, zIndex: 600, animation: "krSelectIn .12s cubic-bezier(0.4,0,0.2,1) both",
          }}
        >
          {options.map((opt) => {
            const isActive = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => { onChange && onChange(opt.value); setOpen(false); }}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 9px", borderRadius: "var(--radius-sm)",
                  background: isActive ? "var(--accent-soft)" : "transparent",
                  color: isActive ? "var(--accent)" : "var(--fg)",
                  border: "none", cursor: "pointer", fontSize, fontWeight: isActive ? 600 : 400,
                  fontFamily: "var(--font-sans)", textAlign: "left", whiteSpace: "nowrap",
                  transition: "background .1s",
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = "var(--bg-inset)"; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
              >
                {isActive ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <span style={{ width: 10, flexShrink: 0 }} />
                )}
                {opt.label}
              </button>
            );
          })}
        </div>
      )}

      <style>{`@keyframes krSelectIn { from { opacity: 0; transform: translateY(-4px) scale(0.97); } to { opacity: 1; transform: translateY(0) scale(1); } }`}</style>
    </div>
  );
}
