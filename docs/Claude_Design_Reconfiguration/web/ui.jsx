/* Knowledge Repository · Shared UI primitives (Heptabase-style, light-first).
   All visual values come from web/tokens.css custom properties. */
(function () {
  const Icon = window.KRIcon;

  /* ── Tooltip wrapper: shows label on hover (used by frameless icon buttons) ── */
  function Tip({ label, side = "bottom", children }) {
    const [show, setShow] = React.useState(false);
    const pos = side === "bottom"
      ? { top: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" }
      : side === "left"
      ? { right: "calc(100% + 7px)", top: "50%", transform: "translateY(-50%)" }
      : { bottom: "calc(100% + 7px)", left: "50%", transform: "translateX(-50%)" };
    return (
      <span style={{ position: "relative", display: "inline-flex" }}
        onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
        {children}
        {show && label && (
          <span style={{
            position: "absolute", ...pos, zIndex: 900, whiteSpace: "nowrap",
            background: "#26272b", color: "#fff", fontSize: 11, fontWeight: 500,
            padding: "4px 8px", borderRadius: 6, pointerEvents: "none",
            boxShadow: "0 4px 14px rgba(0,0,0,.22)", letterSpacing: ".01em",
          }}>{label}</span>
        )}
      </span>
    );
  }

  /* ── Framed button (primary actions, top-right tabs) ── */
  function Button({ variant = "primary", size = "md", active = false, loading = false, disabled = false, children, style, ...rest }) {
    const sizes = { sm: { fontSize: 12, padding: "5px 10px", height: 28 }, md: { fontSize: 13, padding: "7px 13px", height: 32 } };
    const variants = {
      primary: { background: "var(--accent)", color: "var(--accent-fg)", border: "1px solid transparent", boxShadow: "0 1px 2px rgba(22,23,26,.12)" },
      outline: { background: "var(--surface)", color: "var(--fg)", border: "1px solid var(--border-strong)" },
      ghost: { background: "transparent", color: "var(--fg-muted)", border: "1px solid transparent" },
      danger: { background: "var(--danger)", color: "#fff", border: "1px solid transparent" },
      tab: { background: active ? "var(--surface)" : "var(--surface)", color: active ? "var(--accent)" : "var(--fg)", border: `1px solid ${active ? "var(--accent-border)" : "var(--border-strong)"}`, boxShadow: active ? "0 0 0 3px var(--ring)" : "var(--shadow-card)" },
    };
    const dis = disabled || loading;
    return (
      <button disabled={dis} style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        fontFamily: "var(--font-sans)", fontWeight: 500, lineHeight: 1, borderRadius: "var(--radius-md)",
        cursor: dis ? "not-allowed" : "pointer", opacity: dis ? 0.55 : 1, userSelect: "none",
        transition: "background .14s, border-color .14s, box-shadow .14s, transform .08s",
        ...sizes[size], ...variants[variant], ...style,
      }}
        onMouseDown={(e) => { if (!dis) e.currentTarget.style.transform = "scale(0.975)"; }}
        onMouseUp={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
        {...rest}>
        {loading && <span style={{ width: 12, height: 12, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", animation: "spin .6s linear infinite" }} />}
        {children}
      </button>
    );
  }

  /* ── Frameless icon button with hover tooltip (panel header controls) ── */
  function IconBtn({ name, label, size = 16, active = false, side = "bottom", onClick, style, children }) {
    const [hover, setHover] = React.useState(false);
    return (
      <Tip label={label} side={side}>
        <button onClick={onClick} aria-label={label}
          onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
          style={{
            width: 26, height: 26, display: "inline-flex", alignItems: "center", justifyContent: "center",
            border: "none", borderRadius: "var(--radius-sm)", cursor: "pointer",
            background: active ? "var(--accent-soft)" : hover ? "var(--bg-inset)" : "transparent",
            color: active ? "var(--accent)" : hover ? "var(--fg)" : "var(--fg-subtle)",
            transition: "background .12s, color .12s", ...style,
          }}>
          {children || <Icon name={name} size={size} />}
        </button>
      </Tip>
    );
  }

  /* ── Tag pill ── */
  function Tag({ label, accent = false, onRemove, onClick, style }) {
    return (
      <span onClick={onClick} style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        background: accent ? "var(--accent-soft)" : "var(--bg-inset)",
        border: `1px solid ${accent ? "var(--accent-border)" : "transparent"}`,
        color: accent ? "var(--accent)" : "var(--fg-muted)",
        borderRadius: "var(--radius-pill)", padding: "1px 9px", fontSize: 11, fontWeight: 500,
        lineHeight: "19px", whiteSpace: "nowrap", cursor: onClick ? "pointer" : "default", ...style,
      }}>
        {label}
        {onRemove && <button onClick={(e) => { e.stopPropagation(); onRemove(); }} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "inherit", opacity: .55, fontSize: 13, lineHeight: 1 }}>×</button>}
      </span>
    );
  }

  /* ── Badge ── */
  function Badge({ tone = "neutral", children, style }) {
    const t = {
      neutral: { bg: "var(--bg-inset)", fg: "var(--fg-muted)" },
      accent: { bg: "var(--accent-soft)", fg: "var(--accent)" },
      info: { bg: "var(--info-soft)", fg: "var(--info)" },
      ok: { bg: "var(--ok-soft)", fg: "var(--ok)" },
      warn: { bg: "var(--warn-soft)", fg: "var(--warn)" },
      danger: { bg: "var(--danger-soft)", fg: "var(--danger)" },
      violet: { bg: "var(--ann-purple-bg)", fg: "var(--ann-purple)" },
    }[tone];
    return <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 600, padding: "1.5px 7px", borderRadius: "var(--radius-sm)", background: t.bg, color: t.fg, whiteSpace: "nowrap", ...style }}>{children}</span>;
  }

  /* ── Toggle ── */
  function Toggle({ checked, onChange, disabled, label, style }) {
    return (
      <button type="button" role="switch" aria-checked={checked} disabled={disabled}
        onClick={() => !disabled && onChange && onChange(!checked)}
        style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "none", border: "none", padding: 0, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? .5 : 1, fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--fg)", ...style }}>
        <span style={{ position: "relative", width: 32, height: 18, borderRadius: 999, background: checked ? "var(--accent)" : "var(--bg-inset)", border: `1.5px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`, transition: "background .15s, border-color .15s", flexShrink: 0 }}>
          <span style={{ position: "absolute", top: 2, left: checked ? 14 : 2, width: 10, height: 10, borderRadius: "50%", background: checked ? "#fff" : "var(--fg-subtle)", transition: "left .15s" }} />
        </span>
        {label && <span>{label}</span>}
      </button>
    );
  }

  /* ── Select (custom dropdown) ── */
  function Select({ value, onChange, options, size = "sm", style }) {
    const [open, setOpen] = React.useState(false);
    const ref = React.useRef(null);
    const h = size === "sm" ? 30 : 34, fs = size === "sm" ? 12 : 13;
    const sel = options.find((o) => o.value === value);
    React.useEffect(() => {
      if (!open) return;
      const f = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
      document.addEventListener("mousedown", f); return () => document.removeEventListener("mousedown", f);
    }, [open]);
    return (
      <div ref={ref} style={{ position: "relative", display: "inline-block", ...style }}>
        <button type="button" onClick={() => setOpen(v => !v)} style={{
          height: h, paddingLeft: 11, paddingRight: 28, width: "100%", textAlign: "left",
          background: "var(--surface)", border: `1px solid ${open ? "var(--accent)" : "var(--border-strong)"}`,
          borderRadius: "var(--radius-md)", color: "var(--fg)", fontSize: fs, fontWeight: 500, fontFamily: "var(--font-sans)",
          cursor: "pointer", display: "flex", alignItems: "center", position: "relative",
          boxShadow: open ? "0 0 0 3px var(--ring)" : "none", transition: "border-color .14s, box-shadow .14s",
        }}>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sel ? sel.label : value}</span>
          <Icon name="chevD" size={13} style={{ position: "absolute", right: 9, color: "var(--fg-subtle)", transform: open ? "rotate(180deg)" : "none", transition: "transform .18s" }} />
        </button>
        {open && (
          <div style={{ position: "absolute", top: "calc(100% + 5px)", left: 0, minWidth: "100%", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-pop)", padding: 4, zIndex: 700 }}>
            {options.map((o) => {
              const a = o.value === value;
              return (
                <button key={o.value} onClick={() => { onChange && onChange(o.value); setOpen(false); }} style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "6px 9px", borderRadius: "var(--radius-sm)",
                  background: a ? "var(--accent-soft)" : "transparent", color: a ? "var(--accent)" : "var(--fg)", border: "none",
                  cursor: "pointer", fontSize: fs, fontWeight: a ? 600 : 400, fontFamily: "var(--font-sans)", textAlign: "left", whiteSpace: "nowrap",
                }}
                  onMouseEnter={(e) => { if (!a) e.currentTarget.style.background = "var(--bg-inset)"; }}
                  onMouseLeave={(e) => { if (!a) e.currentTarget.style.background = "transparent"; }}>
                  {a ? <Icon name="check" size={12} /> : <span style={{ width: 12 }} />}{o.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  /* ── Panel shell: a Heptabase card with sticky header ── */
  function Panel({ title, crumbs, right, children, style, bodyStyle, flush = false }) {
    return (
      <section style={{
        display: "flex", flexDirection: "column", minHeight: 0, background: "var(--surface)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-2xl)", boxShadow: "var(--shadow-card)",
        overflow: "hidden", ...style,
      }}>
        <header style={{
          height: 38, flexShrink: 0, display: "flex", alignItems: "center", gap: 8, padding: "0 8px 0 13px",
          borderBottom: "1px solid var(--border)", background: "var(--surface)",
        }}>
          <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
            {title && <span style={{ fontWeight: 650, color: "var(--heading)", letterSpacing: "-.01em" }}>{title}</span>}
            {crumbs && crumbs.map((c, i) => (
              <React.Fragment key={i}>
                <span style={{ color: "var(--fg-subtle)" }}>/</span>
                <span style={{ color: i === crumbs.length - 1 ? "var(--fg)" : "var(--fg-muted)", fontWeight: i === crumbs.length - 1 ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220, cursor: c.onClick ? "pointer" : "default" }} onClick={c.onClick}>{c.label || c}</span>
              </React.Fragment>
            ))}
          </div>
          {right && <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>{right}</div>}
        </header>
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: flush ? 0 : 14, ...bodyStyle }}>{children}</div>
      </section>
    );
  }

  /* ── Modal overlay (large pop panels) ── */
  function Modal({ title, icon, onClose, footer, children, width = 880, height = "84vh" }) {
    React.useEffect(() => {
      const f = (e) => { if (e.key === "Escape") onClose(); };
      document.addEventListener("keydown", f); return () => document.removeEventListener("keydown", f);
    }, []);
    return (
      <div onClick={(e) => e.target === e.currentTarget && onClose()} style={{
        position: "fixed", inset: 0, zIndex: 1000, background: "rgba(22,23,26,.38)",
        display: "flex", alignItems: "center", justifyContent: "center",
        animation: "overlayIn .16s ease", padding: 24,
      }}>
        <div style={{
          width, maxWidth: "94vw", height, maxHeight: "92vh", background: "var(--bg)",
          border: "1px solid var(--border)", borderRadius: "var(--radius-2xl)", boxShadow: "var(--shadow-pop)",
          display: "flex", flexDirection: "column", overflow: "hidden", animation: "modalIn .2s cubic-bezier(.2,.7,.2,1)",
        }}>
          <header style={{ height: 52, flexShrink: 0, display: "flex", alignItems: "center", gap: 10, padding: "0 14px 0 18px", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
            {icon && <span style={{ display: "inline-flex", color: "var(--accent)" }}><Icon name={icon} size={18} /></span>}
            <span style={{ flex: 1, fontSize: 15, fontWeight: 650, color: "var(--heading)", letterSpacing: "-.01em" }}>{title}</span>
            <IconBtn name="x" label="关闭" onClick={onClose} />
          </header>
          <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{children}</div>
          {footer && <footer style={{ flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, padding: "12px 18px", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>{footer}</footer>}
        </div>
      </div>
    );
  }

  /* ── Section label ── */
  function Eyebrow({ children, style }) {
    return <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--fg-subtle)", ...style }}>{children}</div>;
  }

  function fmtSize(b) {
    if (!b) return "—";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    return (b / 1048576).toFixed(1) + " MB";
  }

  window.KRUI = { Tip, Button, IconBtn, Tag, Badge, Toggle, Select, Panel, Modal, Eyebrow, fmtSize };
})();
