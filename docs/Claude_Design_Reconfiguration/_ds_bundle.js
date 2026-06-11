/* @ds-bundle: {"format":3,"namespace":"KnowledgeRepositoryDesignSystem_3c9571","components":[{"name":"Button","sourcePath":"components/buttons/Button.jsx"},{"name":"IconButton","sourcePath":"components/buttons/IconButton.jsx"},{"name":"Badge","sourcePath":"components/display/Badge.jsx"},{"name":"Card","sourcePath":"components/display/Card.jsx"},{"name":"QuotaBar","sourcePath":"components/display/QuotaBar.jsx"},{"name":"StatusChip","sourcePath":"components/display/StatusChip.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Tag","sourcePath":"components/forms/Tag.jsx"},{"name":"Toggle","sourcePath":"components/forms/Toggle.jsx"}],"sourceHashes":{"components/buttons/Button.jsx":"5f81349c31bc","components/buttons/IconButton.jsx":"46e01bf043ca","components/display/Badge.jsx":"849bfd63eedd","components/display/Card.jsx":"59b5f256cf6d","components/display/QuotaBar.jsx":"1d43c2fa9fb4","components/display/StatusChip.jsx":"853e1b59fa36","components/forms/Input.jsx":"f32169d2eac0","components/forms/Select.jsx":"d51811209c0b","components/forms/Tag.jsx":"139a91694de2","components/forms/Toggle.jsx":"ed29b45d2baa","web/AstrBotModal.jsx":"63594e469fd9","web/ChatPanel.jsx":"ff83a5107ead","web/DocumentsPanel.jsx":"86e915291ddb","web/FilePanel.jsx":"677acd8b1d53","web/NotePanel.jsx":"460a692d374a","web/SettingModal.jsx":"85b82d1c482c","web/WorkflowModal.jsx":"7be25b244c71","web/icons.jsx":"d5131168058b","web/mock.jsx":"274ffa4a74d4","web/ui.jsx":"60567fc0359f"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.KnowledgeRepositoryDesignSystem_3c9571 = window.KnowledgeRepositoryDesignSystem_3c9571 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/buttons/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — the primary pill-shaped action control.
 * Variants: primary (filled accent), outline (accent hairline), ghost (quiet),
 * danger (destructive). Sizes: sm | md. Pass `loading` for an inline spinner.
 */
function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  children,
  style,
  ...rest
}) {
  const sizes = {
    sm: {
      fontSize: 12,
      padding: "6px 12px"
    },
    md: {
      fontSize: 13,
      padding: "8px 16px"
    }
  };
  const variants = {
    primary: {
      background: "var(--accent)",
      color: "var(--accent-fg)",
      border: "1px solid transparent",
      boxShadow: "var(--shadow)"
    },
    outline: {
      background: "transparent",
      color: "var(--accent)",
      border: "1px solid var(--accent-border)"
    },
    ghost: {
      background: "transparent",
      color: "var(--fg-muted)",
      border: "1px solid var(--border)"
    },
    danger: {
      background: "var(--danger)",
      color: "#fff",
      border: "1px solid transparent"
    }
  };
  const isDisabled = disabled || loading;
  return /*#__PURE__*/React.createElement("button", _extends({
    disabled: isDisabled,
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 6,
      fontFamily: "var(--font-sans)",
      fontWeight: 500,
      lineHeight: 1.2,
      borderRadius: "var(--radius-pill)",
      cursor: isDisabled ? "not-allowed" : "pointer",
      opacity: isDisabled ? 0.5 : 1,
      userSelect: "none",
      transition: "background .15s, border-color .15s, transform .1s, box-shadow .15s, opacity .15s",
      ...sizes[size],
      ...variants[variant],
      ...style
    },
    onMouseDown: e => {
      if (!isDisabled) e.currentTarget.style.transform = "scale(0.97)";
    },
    onMouseUp: e => {
      e.currentTarget.style.transform = "scale(1)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.transform = "scale(1)";
    }
  }, rest), loading && /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true,
    style: {
      width: 12,
      height: 12,
      border: "2px solid currentColor",
      borderTopColor: "transparent",
      borderRadius: "50%",
      animation: "spin 0.6s linear infinite",
      display: "inline-block"
    }
  }), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/Button.jsx", error: String((e && e.message) || e) }); }

// components/buttons/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * IconButton — a square, quiet button for a single icon (toolbar toggles,
 * close buttons, panel collapse). Pass an inline SVG (or any node) as children.
 * `active` paints it with the accent-soft surface.
 */
function IconButton({
  size = 28,
  active = false,
  title,
  children,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    title: title,
    "aria-pressed": active,
    style: {
      width: size,
      height: size,
      flexShrink: 0,
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: active ? "var(--accent-soft)" : "var(--bg-inset)",
      color: active ? "var(--accent)" : "var(--fg-subtle)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      cursor: "pointer",
      transition: "background .15s, color .15s, border-color .15s",
      ...style
    },
    onMouseEnter: e => {
      if (!active) {
        e.currentTarget.style.background = "var(--surface-hover)";
        e.currentTarget.style.color = "var(--fg)";
      }
    },
    onMouseLeave: e => {
      if (!active) {
        e.currentTarget.style.background = "var(--bg-inset)";
        e.currentTarget.style.color = "var(--fg-subtle)";
      }
    }
  }, rest), children);
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/display/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Badge — a soft status/origin pill (本地上传 / Zotero 同步 / 只读 / 已脱管 /
 * 即将上线). `tone` selects the semantic color: neutral | accent | info |
 * ok | warn | danger | violet.
 */
function Badge({
  tone = "neutral",
  children,
  style,
  ...rest
}) {
  const tones = {
    neutral: {
      bg: "var(--bg-inset)",
      fg: "var(--fg-muted)"
    },
    accent: {
      bg: "var(--accent-soft)",
      fg: "var(--accent)"
    },
    info: {
      bg: "rgba(52,120,200,0.12)",
      fg: "#2e6bb0"
    },
    ok: {
      bg: "var(--ok-soft)",
      fg: "var(--ok)"
    },
    warn: {
      bg: "var(--warn-soft)",
      fg: "var(--warn)"
    },
    danger: {
      bg: "var(--danger-soft)",
      fg: "var(--danger)"
    },
    violet: {
      bg: "rgba(140,90,200,0.14)",
      fg: "#7a3fb0"
    }
  };
  const c = tones[tone] || tones.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      fontSize: 11,
      fontWeight: 600,
      lineHeight: 1.4,
      padding: "2px 9px",
      borderRadius: "var(--radius-pill)",
      background: c.bg,
      color: c.fg,
      fontFamily: "var(--font-sans)",
      whiteSpace: "nowrap",
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Badge.jsx", error: String((e && e.message) || e) }); }

// components/display/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Card — the base surface container (documents inspector, source cards,
 * settings sections, dialogs). `featured` adds a gradient hairline + glow for
 * the Research Agent / primary surfaces. `pad` toggles default padding.
 */
function Card({
  featured = false,
  pad = true,
  style,
  children,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("div", _extends({
    className: featured ? "fx-gborder" : undefined,
    style: {
      position: "relative",
      background: "var(--surface)",
      border: `1px solid ${featured ? "var(--accent-border)" : "var(--border)"}`,
      borderRadius: "var(--radius-2xl)",
      boxShadow: featured ? "var(--shadow), 0 0 24px var(--accent-soft)" : "var(--shadow)",
      padding: pad ? 16 : 0,
      color: "var(--fg)",
      fontFamily: "var(--font-sans)",
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Card.jsx", error: String((e && e.message) || e) }); }

// components/display/QuotaBar.jsx
try { (() => {
/**
 * QuotaBar — labelled usage meter for R2 / Notion storage. Pass `ratio` (0–1);
 * the fill turns warn at >= `warnThreshold` (default 0.8) and danger at >= 0.95.
 * `label` and `detail` render above the track.
 */
function QuotaBar({
  ratio,
  label,
  detail,
  warnThreshold = 0.8,
  style
}) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const fill = ratio >= 0.95 ? "var(--danger)" : ratio >= warnThreshold ? "var(--warn)" : "var(--accent)";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      ...style
    }
  }, (label || detail) && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: 7
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: "var(--heading)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--fg-muted)",
      fontFamily: "var(--font-mono)"
    }
  }, detail)), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 8,
      borderRadius: "var(--radius-pill)",
      background: "var(--bg-inset)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${pct}%`,
      height: "100%",
      borderRadius: "var(--radius-pill)",
      background: fill,
      transition: "width .4s cubic-bezier(0.4,0,0.2,1), background .2s"
    }
  })));
}
Object.assign(__ds_scope, { QuotaBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/QuotaBar.jsx", error: String((e && e.message) || e) }); }

// components/display/StatusChip.jsx
try { (() => {
/**
 * StatusChip — dot + label capsule for pipeline/connection state, mirroring the
 * Data-Flow nodes. `status`: ready | degraded | off | info. A degraded dot pulses.
 */
function StatusChip({
  status = "off",
  children,
  style
}) {
  const colors = {
    ready: "var(--ok)",
    degraded: "var(--warn)",
    off: "var(--fg-subtle)",
    info: "#6c79c4"
  };
  const c = colors[status] || colors.off;
  return /*#__PURE__*/React.createElement("span", {
    style: {
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
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      flexShrink: 0,
      background: c,
      animation: status === "degraded" ? "krDotPulse 1.7s ease-in-out infinite" : "none"
    }
  }), children, /*#__PURE__*/React.createElement("style", null, `@keyframes krDotPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }`));
}
Object.assign(__ds_scope, { StatusChip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/StatusChip.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Input — single-line text field with warm surface and accent focus ring.
 * Sizes: sm (32px) | md (36px). Set `invalid` to paint a danger ring.
 * Pass `mono` for monospace content (IDs, model names, collection names).
 */
function Input({
  size = "md",
  invalid = false,
  mono = false,
  style,
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  const heights = {
    sm: 32,
    md: 36
  };
  const ringColor = invalid ? "var(--danger)" : "var(--accent)";
  return /*#__PURE__*/React.createElement("input", _extends({
    onFocus: e => {
      setFocused(true);
      rest.onFocus && rest.onFocus(e);
    },
    onBlur: e => {
      setFocused(false);
      rest.onBlur && rest.onBlur(e);
    },
    style: {
      height: heights[size],
      width: "100%",
      boxSizing: "border-box",
      padding: "0 11px",
      background: "var(--surface)",
      border: `1px solid ${focused ? ringColor : invalid ? "var(--danger)" : "var(--border)"}`,
      borderRadius: "var(--radius-md)",
      color: "var(--fg)",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
      fontSize: size === "sm" ? 12 : 13,
      outline: "none",
      boxShadow: focused ? `0 0 0 3px ${invalid ? "color-mix(in srgb, var(--danger) 22%, transparent)" : "var(--ring)"}` : "none",
      transition: "border-color .15s, box-shadow .15s",
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
/**
 * Select — custom dropdown matching the warm surface system. Options are
 * `{ value, label }`. Renders a pill-bordered trigger with a chevron and an
 * animated popover with a check on the active row. Sizes: sm | md.
 */
function Select({
  value,
  onChange,
  options,
  placeholder,
  size = "sm",
  disabled = false,
  style
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const height = size === "sm" ? 32 : 36;
  const fontSize = size === "sm" ? 12 : 13;
  const selected = options.find(o => o.value === value);
  const label = selected ? selected.label : placeholder != null ? placeholder : value;
  React.useEffect(() => {
    if (!open) return;
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return /*#__PURE__*/React.createElement("div", {
    ref: ref,
    style: {
      position: "relative",
      display: "inline-block",
      ...style
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: disabled,
    onClick: () => !disabled && setOpen(v => !v),
    style: {
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
      opacity: disabled ? 0.55 : 1
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, label), /*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "12",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "var(--fg-subtle)",
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      position: "absolute",
      right: 9,
      top: "50%",
      transform: `translateY(-50%) rotate(${open ? 180 : 0}deg)`,
      transition: "transform .2s",
      pointerEvents: "none"
    }
  }, /*#__PURE__*/React.createElement("polyline", {
    points: "6 9 12 15 18 9"
  }))), open && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: "calc(100% + 6px)",
      left: 0,
      minWidth: "100%",
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-pop)",
      padding: 4,
      zIndex: 600,
      animation: "krSelectIn .12s cubic-bezier(0.4,0,0.2,1) both"
    }
  }, options.map(opt => {
    const isActive = opt.value === value;
    return /*#__PURE__*/React.createElement("button", {
      key: opt.value,
      type: "button",
      onClick: () => {
        onChange && onChange(opt.value);
        setOpen(false);
      },
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        padding: "6px 9px",
        borderRadius: "var(--radius-sm)",
        background: isActive ? "var(--accent-soft)" : "transparent",
        color: isActive ? "var(--accent)" : "var(--fg)",
        border: "none",
        cursor: "pointer",
        fontSize,
        fontWeight: isActive ? 600 : 400,
        fontFamily: "var(--font-sans)",
        textAlign: "left",
        whiteSpace: "nowrap",
        transition: "background .1s"
      },
      onMouseEnter: e => {
        if (!isActive) e.currentTarget.style.background = "var(--bg-inset)";
      },
      onMouseLeave: e => {
        if (!isActive) e.currentTarget.style.background = "transparent";
      }
    }, isActive ? /*#__PURE__*/React.createElement("svg", {
      width: "10",
      height: "10",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "3",
      strokeLinecap: "round",
      strokeLinejoin: "round",
      style: {
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement("polyline", {
      points: "20 6 9 17 4 12"
    })) : /*#__PURE__*/React.createElement("span", {
      style: {
        width: 10,
        flexShrink: 0
      }
    }), opt.label);
  })), /*#__PURE__*/React.createElement("style", null, `@keyframes krSelectIn { from { opacity: 0; transform: translateY(-4px) scale(0.97); } to { opacity: 1; transform: translateY(0) scale(1); } }`));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/forms/Tag.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Tag — small pill for document tags, retrieval-mode labels, and filters.
 * `accent` highlights an active/selected tag; pass `onRemove` to show a × button.
 */
function Tag({
  label,
  onRemove,
  accent = false,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      background: accent ? "var(--accent-soft)" : "var(--bg-inset)",
      border: `1px solid ${accent ? "var(--accent-border)" : "var(--border)"}`,
      color: accent ? "var(--accent)" : "var(--fg-muted)",
      borderRadius: "var(--radius-pill)",
      padding: "1px 8px",
      fontSize: 11,
      fontWeight: 500,
      lineHeight: "20px",
      whiteSpace: "nowrap",
      fontFamily: "var(--font-sans)",
      ...style
    }
  }, rest), label, onRemove && /*#__PURE__*/React.createElement("button", {
    onClick: onRemove,
    "aria-label": `移除标签 ${label}`,
    style: {
      background: "none",
      border: "none",
      padding: 0,
      cursor: "pointer",
      color: "inherit",
      display: "flex",
      alignItems: "center",
      opacity: 0.6,
      lineHeight: 1,
      fontSize: 13
    }
  }, "\xD7"));
}
Object.assign(__ds_scope, { Tag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Tag.jsx", error: String((e && e.message) || e) }); }

// components/forms/Toggle.jsx
try { (() => {
/**
 * Toggle — compact switch used for binary settings (auto-index, persona,
 * English recall). Optional trailing `label`. Track turns accent when on.
 */
function Toggle({
  checked,
  onChange,
  disabled = false,
  label,
  style
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    role: "switch",
    "aria-checked": checked,
    disabled: disabled,
    onClick: () => !disabled && onChange && onChange(!checked),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      background: "none",
      border: "none",
      padding: 0,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      userSelect: "none",
      fontFamily: "var(--font-sans)",
      fontSize: 13,
      color: "var(--fg)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "relative",
      display: "inline-block",
      width: 32,
      height: 18,
      borderRadius: "var(--radius-pill)",
      background: checked ? "var(--accent)" : "var(--bg-inset)",
      border: `1.5px solid ${checked ? "var(--accent)" : "var(--border)"}`,
      transition: "background .15s, border-color .15s",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 2,
      left: checked ? 14 : 2,
      width: 10,
      height: 10,
      borderRadius: "50%",
      background: checked ? "var(--accent-fg)" : "var(--fg-subtle)",
      transition: "left .15s, background .15s"
    }
  })), label && /*#__PURE__*/React.createElement("span", null, label));
}
Object.assign(__ds_scope, { Toggle });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Toggle.jsx", error: String((e && e.message) || e) }); }

// web/AstrBotModal.jsx
try { (() => {
/* Knowledge Repository · AstrBot modal — AstrBot-related config (embedding / vector DB / LightRAG core / Ask). */
(function () {
  const {
    Modal,
    Button,
    Toggle,
    Select,
    Badge,
    Tag,
    Eyebrow
  } = window.KRUI;
  const Icon = window.KRIcon;
  function Field({
    label,
    children,
    hint
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 500,
        color: "var(--fg)"
      }
    }, label), hint && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: "var(--fg-subtle)",
        marginTop: 2,
        lineHeight: 1.45
      }
    }, hint)), /*#__PURE__*/React.createElement("div", {
      style: {
        flexShrink: 0
      }
    }, children));
  }
  function Card({
    title,
    icon,
    children,
    badge
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: "4px 16px 12px",
        marginBottom: 14
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "12px 0 4px"
      }
    }, icon && /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 16,
      style: {
        color: "var(--accent)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 650,
        color: "var(--heading)",
        flex: 1
      }
    }, title), badge), children);
  }
  const inputStyle = {
    height: 30,
    padding: "0 10px",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-md)",
    background: "var(--surface)",
    color: "var(--fg)",
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    width: 230,
    outline: "none"
  };
  function AstrBotModal({
    onClose
  }) {
    const [graphOn, setGraphOn] = React.useState(true);
    const [autoIdx, setAutoIdx] = React.useState(true);
    return /*#__PURE__*/React.createElement(Modal, {
      title: "AstrBot \u914D\u7F6E",
      icon: "spark2",
      onClose: onClose,
      width: 760,
      footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
        variant: "ghost",
        onClick: onClose
      }, "\u53D6\u6D88"), /*#__PURE__*/React.createElement(Button, {
        variant: "primary"
      }, "\u4FDD\u5B58\u914D\u7F6E"))
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "18px 22px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "11px 13px",
        background: "var(--warn-soft)",
        border: "1px solid color-mix(in srgb, var(--warn) 28%, transparent)",
        borderRadius: "var(--radius-lg)",
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "spark2",
      size: 16,
      style: {
        color: "var(--warn)",
        marginTop: 1
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--fg)",
        lineHeight: 1.55
      }
    }, "\u4FEE\u6539 Embedding \u63D0\u4F9B\u5546 / \u6A21\u578B / \u63A5\u53E3\u540E\uFF0CMilvus \u4E0E\u5404 collection \u7684 LightRAG \u7D22\u5F15\u5747\u9700\u624B\u52A8\u91CD\u5EFA\u3002\u90E8\u5206\u9879\u9700\u91CD\u542F\u63D2\u4EF6\u751F\u6548\u3002")), /*#__PURE__*/React.createElement(Card, {
      title: "Embedding \u8FD0\u884C\u65F6",
      icon: "layers",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: "ok"
      }, "\u672C\u5730")
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u63D0\u4F9B\u5546",
      hint: "\u672C\u5730\u79BB\u7EBF (sentence-transformers) \u6216\u4E91\u7AEF API"
    }, /*#__PURE__*/React.createElement(Select, {
      value: "local",
      options: [{
        value: "local",
        label: "本地 Embedding"
      }, {
        value: "api",
        label: "API Embedding"
      }]
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u6A21\u578B\u540D\u79F0"
    }, /*#__PURE__*/React.createElement("input", {
      style: inputStyle,
      defaultValue: "intfloat/multilingual-e5-small"
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u5411\u91CF\u7EF4\u5EA6",
      hint: "\u7531\u6A21\u578B\u51B3\u5B9A\uFF0C\u53EA\u8BFB"
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, "384")), /*#__PURE__*/React.createElement(Field, {
      label: "API Key",
      hint: "\u4EC5\u4ECE\u73AF\u5883\u53D8\u91CF KR_EMBEDDING_API_KEY \u8BFB\u53D6"
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        fontFamily: "var(--font-mono)",
        color: "var(--fg-subtle)"
      }
    }, "env-only"))), /*#__PURE__*/React.createElement(Card, {
      title: "\u5411\u91CF\u6570\u636E\u5E93\u4E0E\u68C0\u7D22\u540E\u7AEF",
      icon: "db"
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u5411\u91CF\u540E\u7AEF"
    }, /*#__PURE__*/React.createElement(Select, {
      value: "milvus",
      options: [{
        value: "milvus",
        label: "Milvus Lite"
      }, {
        value: "astrbot",
        label: "AstrBot KB（回退）"
      }]
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u81EA\u52A8\u7D22\u5F15",
      hint: "\u4E0A\u4F20\u540E\u81EA\u52A8\u5EFA\u7ACB Milvus \u7D22\u5F15"
    }, /*#__PURE__*/React.createElement(Toggle, {
      checked: autoIdx,
      onChange: setAutoIdx
    }))), /*#__PURE__*/React.createElement(Card, {
      title: "LightRAG Core",
      icon: "graph",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: graphOn ? "violet" : "neutral"
      }, graphOn ? "已启用" : "关闭")
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u542F\u7528\u56FE\u8C31\u7D22\u5F15",
      hint: "\u624B\u52A8\u89E6\u53D1\u6784\u5EFA\uFF0C\u4E0D\u968F\u4E0A\u4F20\u81EA\u52A8\u6784\u5EFA\uFF08\u6210\u672C\u9694\u79BB\uFF09"
    }, /*#__PURE__*/React.createElement(Toggle, {
      checked: graphOn,
      onChange: setGraphOn
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u68C0\u7D22\u6A21\u5F0F",
      hint: "mix \u5411\u91CF+\u56FE\u8C31\uFF08\u63A8\u8350\uFF09"
    }, /*#__PURE__*/React.createElement(Select, {
      value: "mix",
      options: [{
        value: "mix",
        label: "mix — 混合（推荐）"
      }, {
        value: "local",
        label: "local — 本地图谱"
      }, {
        value: "global",
        label: "global — 全局"
      }, {
        value: "naive",
        label: "naive — 纯向量"
      }]
    })), /*#__PURE__*/React.createElement(Field, {
      label: "LLM \u5E76\u53D1\u4E0A\u9650",
      hint: "\u9ED8\u8BA4 4\uFF0C\u8C03\u9AD8\u66F4\u5FEB\u4F46\u6613\u9650\u6D41"
    }, /*#__PURE__*/React.createElement("input", {
      style: {
        ...inputStyle,
        width: 80,
        textAlign: "center"
      },
      defaultValue: "4"
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u5DE5\u4F5C\u76EE\u5F55",
      hint: "\u53EA\u8BFB\uFF0C\u9700\u6539\u914D\u7F6E\u6587\u4EF6\u5E76\u91CD\u542F"
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        fontFamily: "var(--font-mono)",
        color: "var(--fg-subtle)"
      }
    }, "lightrag_workspaces"))), /*#__PURE__*/React.createElement(Card, {
      title: "Research Agent (Ask)",
      icon: "sparkle"
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u5BF9\u8BDD\u589E\u5F3A\u6A21\u5F0F"
    }, /*#__PURE__*/React.createElement(Select, {
      value: "inject",
      options: [{
        value: "inject",
        label: "注入增强"
      }, {
        value: "agent",
        label: "代理增强"
      }]
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u9ED8\u8BA4 Top-K"
    }, /*#__PURE__*/React.createElement("input", {
      style: {
        ...inputStyle,
        width: 80,
        textAlign: "center"
      },
      defaultValue: "5"
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u5C55\u793A\u5F15\u7528\u6765\u6E90",
      hint: "cite_sources"
    }, /*#__PURE__*/React.createElement(Toggle, {
      checked: true,
      onChange: () => {}
    })))));
  }
  window.KRAstrBotModal = AstrBotModal;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/AstrBotModal.jsx", error: String((e && e.message) || e) }); }

// web/ChatPanel.jsx
try { (() => {
/* Knowledge Repository · Chat panel (Research Agent).
   Citations [n] jump to the cited chunk in Documents (open + scroll + flash).
   Context = selected single doc OR collection. Pin keeps an answer across clears;
   "Add to Linked Notes" saves an answer into the doc's Notes. */
(function () {
  const {
    IconBtn,
    Tag,
    Badge,
    Button,
    Tip
  } = window.KRUI;
  const Icon = window.KRIcon;
  const SEED = [{
    role: "user",
    content: "ReAct 的核心思想是什么？它和纯 Chain-of-Thought 有何不同？"
  }, {
    role: "assistant",
    content: "ReAct 的核心是让大模型以**交替（interleaved）**的方式同时生成「推理轨迹（reasoning trace）」与「具体动作（action）」[1]。这样模型既能用推理来创建、维护和调整高层计划（reason to act），又能通过与外部环境交互把新信息纳入推理（act to reason）。\n\n与纯 Chain-of-Thought 不同，CoT 只在内部推理、不与环境交互，容易产生事实漂移；ReAct 通过动作获取外部观测来纠偏，因此更鲁棒、能处理异常 [3]。在 ALFWorld 与 WebShop 上，ReAct 相对模仿学习/强化学习基线分别有 34% 和 10% 的绝对成功率提升 [2]。",
    mode: "联合检索 · Milvus + 图谱",
    sources: [{
      n: 1,
      doc_id: "d-react",
      chunk_id: "react-3",
      title: "ReAct",
      text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions in an interleaved manner.",
      rrf: 0.0331
    }, {
      n: 2,
      doc_id: "d-react",
      chunk_id: "react-9",
      title: "ReAct",
      text: "ReAct outperforms imitation and RL methods by an absolute success rate of 34% and 10% respectively.",
      rrf: 0.0297
    }, {
      n: 3,
      doc_id: "d-react",
      chunk_id: "react-12",
      title: "ReAct",
      text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions.",
      rrf: 0.0212
    }],
    pinned: false
  }];
  function renderAnswer(text, onCite) {
    return text.split("\n").map((line, li) => {
      const parts = line.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
      return /*#__PURE__*/React.createElement(React.Fragment, {
        key: li
      }, parts.map((p, pi) => {
        if (/^\*\*[^*]+\*\*$/.test(p)) return /*#__PURE__*/React.createElement("strong", {
          key: pi,
          style: {
            fontWeight: 700,
            color: "var(--heading)"
          }
        }, p.slice(2, -2));
        const m = p.match(/^\[(\d+)\]$/);
        if (m) {
          const n = +m[1];
          return /*#__PURE__*/React.createElement("sup", {
            key: pi,
            onClick: () => onCite(n),
            style: {
              cursor: "pointer",
              color: "var(--accent)",
              background: "var(--accent-soft)",
              borderRadius: 3,
              padding: "0 3px",
              fontWeight: 700,
              fontSize: ".72em",
              margin: "0 1px"
            }
          }, "[", n, "]");
        }
        return p;
      }), li < text.split("\n").length - 1 && /*#__PURE__*/React.createElement("br", null));
    });
  }
  function SourceMini({
    s,
    onClick
  }) {
    return /*#__PURE__*/React.createElement("div", {
      onClick: onClick,
      style: {
        display: "flex",
        gap: 7,
        padding: "7px 9px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border)",
        background: "var(--surface)",
        cursor: "pointer",
        marginTop: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 16,
        height: 16,
        flexShrink: 0,
        borderRadius: "50%",
        background: "var(--accent)",
        color: "#fff",
        fontSize: 9.5,
        fontWeight: 700,
        display: "flex",
        alignItems: "center",
        justifyContent: "center"
      }
    }, s.n), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: "var(--heading)"
      }
    }, s.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 9.5,
        fontFamily: "var(--font-mono)",
        color: "var(--fg-subtle)"
      }
    }, s.chunk_id), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 9.5,
        fontFamily: "var(--font-mono)",
        color: "var(--accent)"
      }
    }, "RRF ", s.rrf)), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: "3px 0 0",
        fontSize: 10.5,
        lineHeight: 1.5,
        color: "var(--fg-muted)",
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical",
        overflow: "hidden"
      }
    }, s.text)));
  }
  function Bubble({
    msg,
    onCite,
    onPin,
    onSaveNote
  }) {
    const isUser = msg.role === "user";
    const [hover, setHover] = React.useState(false);
    if (isUser) {
      return /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 14
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          maxWidth: "86%",
          background: "var(--accent)",
          color: "var(--accent-fg)",
          borderRadius: "10px 10px 3px 10px",
          padding: "9px 12px",
          fontSize: 12.5,
          lineHeight: 1.6
        }
      }, msg.content));
    }
    return /*#__PURE__*/React.createElement("div", {
      style: {
        marginBottom: 16
      },
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false)
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: "94%",
        background: "var(--surface)",
        border: "1px solid " + (msg.pinned ? "var(--accent-border)" : "var(--border)"),
        borderRadius: "10px 10px 10px 3px",
        padding: "10px 13px",
        boxShadow: msg.pinned ? "0 0 0 3px var(--ring)" : "var(--shadow-card)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: 7
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "accent"
    }, msg.mode), msg.pinned && /*#__PURE__*/React.createElement(Badge, {
      tone: "warn"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "pin",
      size: 9
    }), " \u5DF2\u9501\u5B9A")), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        lineHeight: 1.7,
        color: "var(--fg)"
      }
    }, renderAnswer(msg.content, onCite)), msg.sources && msg.sources.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 8,
        paddingTop: 8,
        borderTop: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 9.5,
        fontWeight: 700,
        letterSpacing: ".06em",
        textTransform: "uppercase",
        color: "var(--fg-subtle)",
        marginBottom: 2
      }
    }, "\u5F15\u7528\u6765\u6E90 \xB7 \u70B9\u51FB\u5728\u6587\u6863\u4E2D\u6253\u5F00"), msg.sources.map(s => /*#__PURE__*/React.createElement(SourceMini, {
      key: s.n,
      s: s,
      onClick: () => onCite(s.n)
    })))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 4,
        marginTop: 6,
        opacity: hover || msg.pinned ? 1 : 0.4,
        transition: "opacity .15s"
      }
    }, /*#__PURE__*/React.createElement(Tip, {
      label: "\u5B58\u4E3A\u8BE5\u6587\u732E\u7684\u5173\u8054\u7B14\u8BB0"
    }, /*#__PURE__*/React.createElement("button", {
      onClick: onSaveNote,
      style: actionBtn
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "link",
      size: 12
    }), " Add to Linked Notes")), /*#__PURE__*/React.createElement(Tip, {
      label: msg.pinned ? "取消锁定" : "锁定回答：持续保留，清空对话也不消失"
    }, /*#__PURE__*/React.createElement("button", {
      onClick: onPin,
      style: {
        ...actionBtn,
        color: msg.pinned ? "var(--accent)" : "var(--fg-muted)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "pin",
      size: 12
    }), " ", msg.pinned ? "已锁定" : "锁定回答"))));
  }
  const actionBtn = {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    fontSize: 11,
    fontWeight: 500,
    color: "var(--fg-muted)",
    background: "transparent",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-pill)",
    padding: "3px 9px",
    cursor: "pointer",
    fontFamily: "var(--font-sans)"
  };
  function ChatPanel({
    contextLabel,
    contextKind,
    onCite,
    onSaveNote
  }) {
    const [messages, setMessages] = React.useState(SEED);
    const [input, setInput] = React.useState("");
    const scrollRef = React.useRef(null);
    React.useEffect(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages]);
    function handleCite(msg, n) {
      const s = (msg.sources || []).find(x => x.n === n);
      if (s) onCite(s);
    }
    function send() {
      if (!input.trim()) return;
      const q = input.trim();
      setInput("");
      setMessages(m => [...m, {
        role: "user",
        content: q
      }]);
      setTimeout(() => {
        setMessages(m => [...m, {
          role: "assistant",
          mode: contextKind === "lightrag" ? "图谱检索 · LightRAG" : "语义检索 · Milvus",
          content: "基于当前知识库范围检索到的内容，这里是对「" + q + "」的回答示例。引用来源见下方 [1]，点击可在中间面板定位原文。",
          sources: [{
            n: 1,
            doc_id: "d-lightrag",
            chunk_id: "lr-1",
            title: "LightRAG",
            text: "LightRAG incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system.",
            rrf: 0.0309
          }],
          pinned: false
        }]);
      }, 280);
    }
    function clearChat() {
      setMessages(m => m.filter(x => x.pinned));
    }
    function pin(i) {
      setMessages(m => m.map((x, idx) => idx === i ? {
        ...x,
        pinned: !x.pinned
      } : x));
    }
    return /*#__PURE__*/React.createElement("section", {
      style: {
        width: "var(--chat-w)",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-card)",
        overflow: "hidden"
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        height: 38,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 8px 0 13px",
        borderBottom: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "sparkle",
      size: 15,
      style: {
        color: "var(--accent)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12.5,
        fontWeight: 650,
        color: "var(--heading)"
      }
    }, "Chat"), /*#__PURE__*/React.createElement(IconBtn, {
      name: "trash",
      label: "\u6E05\u7A7A\u8BB0\u5F55\uFF08\u4FDD\u7559\u9501\u5B9A\u56DE\u7B54\uFF09",
      onClick: clearChat
    })), /*#__PURE__*/React.createElement("div", {
      ref: scrollRef,
      style: {
        flex: 1,
        minHeight: 0,
        overflow: "auto",
        padding: "14px 12px"
      }
    }, messages.map((m, i) => /*#__PURE__*/React.createElement(Bubble, {
      key: i,
      msg: m,
      onCite: n => handleCite(m, n),
      onPin: () => pin(i),
      onSaveNote: () => onSaveNote(m)
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        flexShrink: 0,
        padding: "8px 12px 12px",
        borderTop: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: 7
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10.5,
        color: "var(--fg-subtle)"
      }
    }, "\u77E5\u8BC6\u5E93\u8303\u56F4"), /*#__PURE__*/React.createElement(Badge, {
      tone: contextKind === "lightrag" ? "violet" : contextKind === "doc" ? "info" : "accent"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: contextKind === "doc" ? "file" : contextKind === "lightrag" ? "graph" : "folder",
      size: 10
    }), " ", contextLabel)), /*#__PURE__*/React.createElement("div", {
      style: {
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-lg)",
        background: "var(--surface)",
        padding: 8,
        boxShadow: "var(--shadow-card)"
      }
    }, /*#__PURE__*/React.createElement("textarea", {
      value: input,
      onChange: e => setInput(e.target.value),
      onKeyDown: e => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      },
      placeholder: "\u5411\u77E5\u8BC6\u5E93\u63D0\u95EE\u2026",
      rows: 2,
      style: {
        width: "100%",
        resize: "none",
        border: "none",
        outline: "none",
        background: "transparent",
        fontSize: 12.5,
        lineHeight: 1.55,
        fontFamily: "var(--font-sans)",
        color: "var(--fg)",
        padding: "2px 4px"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginTop: 4
      }
    }, /*#__PURE__*/React.createElement(IconBtn, {
      name: "settings",
      label: "\u67E5\u8BE2\u8BBE\u7F6E\uFF08\u68C0\u7D22\u65B9\u5F0F / TopK / \u8BED\u8A00\uFF09"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      onClick: send,
      style: {
        height: 28
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "send",
      size: 13
    }), " \u53D1\u9001")))));
  }
  window.KRChatPanel = ChatPanel;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/ChatPanel.jsx", error: String((e && e.message) || e) }); }

// web/DocumentsPanel.jsx
try { (() => {
/* Knowledge Repository · Documents panel.
   List view (Zotero-style rows) ⇄ reading view (breadcrumb + md/PDF toggle).
   Citation jump: scrolls to a chunk anchor and flashes it. */
(function () {
  const {
    Panel,
    IconBtn,
    Tag,
    Badge,
    Button,
    fmtSize,
    Eyebrow
  } = window.KRUI;
  const Icon = window.KRIcon;
  const {
    DOCS,
    CHUNKS
  } = window.KRMock;
  function DocRow({
    d,
    onOpen
  }) {
    const [hover, setHover] = React.useState(false);
    return /*#__PURE__*/React.createElement("div", {
      onClick: () => onOpen(d),
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      style: {
        display: "flex",
        gap: 12,
        padding: "13px 14px",
        borderRadius: "var(--radius-lg)",
        cursor: "pointer",
        background: hover ? "var(--surface-hover)" : "transparent",
        border: "1px solid " + (hover ? "var(--border)" : "transparent"),
        transition: "background .12s, border-color .12s"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 30,
        height: 38,
        flexShrink: 0,
        borderRadius: 4,
        background: d.ext === "md" ? "var(--info-soft)" : "var(--danger-soft)",
        color: d.ext === "md" ? "var(--info)" : "var(--danger)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 8.5,
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        border: "1px solid color-mix(in srgb, currentColor 22%, transparent)"
      }
    }, d.ext), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: "var(--heading)",
        lineHeight: 1.35,
        marginBottom: 3
      }
    }, d.title), d.authors && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        color: "var(--fg-muted)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, d.authors), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginTop: 6,
        flexWrap: "wrap"
      }
    }, d.venue && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        fontStyle: "italic",
        color: "var(--fg)"
      }
    }, d.venue), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--fg-subtle)"
      }
    }, "\xB7 ", d.year, " \xB7 ", d.type), d.lightrag && /*#__PURE__*/React.createElement(Badge, {
      tone: "violet"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "graph",
      size: 10
    }), " LightRAG"), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }), d.tags.slice(0, 3).map(t => /*#__PURE__*/React.createElement(Tag, {
      key: t,
      label: t
    })))), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "flex",
        alignItems: "center",
        color: "var(--fg-subtle)",
        opacity: hover ? 1 : 0
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "chevR",
      size: 16
    })));
  }
  function ListView({
    docs,
    title
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 760,
        margin: "0 auto"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        padding: "4px 14px 10px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 18,
        fontWeight: 700,
        color: "var(--heading)",
        letterSpacing: "-.02em"
      }
    }, title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: "var(--fg-muted)"
      }
    }, "\xB7 ", docs.length, " \u7BC7\u6587\u732E")), docs.length === 0 ? /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 40,
        textAlign: "center",
        color: "var(--fg-subtle)",
        fontSize: 13
      }
    }, "\u8BE5\u96C6\u5408\u6682\u65E0\u6587\u6863") : docs.map(d => /*#__PURE__*/React.createElement(DocRow, {
      key: d.doc_id,
      d: d,
      onOpen: doc => window.__krOpenDoc(doc)
    })));
  }
  function ReadingView({
    doc,
    mode,
    setMode,
    highlight,
    onClearHighlight
  }) {
    const refs = React.useRef({});
    const chunks = CHUNKS[doc.doc_id] || [];
    React.useEffect(() => {
      if (highlight && refs.current[highlight]) {
        const el = refs.current[highlight];
        el.scrollIntoView ? el.scrollIntoView({
          block: "center"
        }) : null;
        el.style.animation = "none";
        // force reflow then flash
        void el.offsetWidth;
        el.style.animation = "citeFlash 1.6s ease-out forwards";
        const t = setTimeout(() => onClearHighlight && onClearHighlight(), 1800);
        return () => clearTimeout(t);
      }
    }, [highlight]);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 720,
        margin: "0 auto",
        padding: "6px 20px 60px"
      }
    }, /*#__PURE__*/React.createElement("h1", {
      style: {
        fontSize: 21,
        fontWeight: 700,
        color: "var(--heading)",
        letterSpacing: "-.02em",
        lineHeight: 1.3,
        margin: "8px 0 10px"
      }
    }, doc.title), doc.authors && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: "var(--fg-muted)",
        marginBottom: 12
      }
    }, doc.authors), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 7,
        flexWrap: "wrap",
        marginBottom: 18,
        paddingBottom: 18,
        borderBottom: "1px solid var(--border)"
      }
    }, doc.venue && /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, doc.venue), /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, doc.year), /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, doc.type), doc.doi && /*#__PURE__*/React.createElement(Badge, {
      tone: "accent"
    }, "DOI ", doc.doi), doc.lightrag && /*#__PURE__*/React.createElement(Badge, {
      tone: "violet"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "graph",
      size: 10
    }), " \u5DF2\u5EFA\u56FE\u8C31")), mode === "pdf" ? /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--bg-inset)",
        border: "1px dashed var(--border-strong)",
        borderRadius: "var(--radius-lg)",
        padding: "60px 20px",
        textAlign: "center",
        color: "var(--fg-subtle)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "file",
      size: 30,
      style: {
        margin: "0 auto 10px"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: "var(--fg-muted)"
      }
    }, "PDF \u539F\u4EF6\u9884\u89C8"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        marginTop: 4
      }
    }, doc.title, " \xB7 ", fmtSize(doc.size)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        marginTop: 10,
        fontFamily: "var(--font-mono)"
      }
    }, "\u9700\u65B0\u7AEF\u53E3 GET /api/documents/{id}/raw\uFF08\u89C1\u62A5\u544A\uFF09")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        marginBottom: 8
      }
    }, "Abstract"), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 13.5,
        lineHeight: 1.75,
        color: "var(--fg)",
        margin: "0 0 24px"
      }
    }, doc.abstract), /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        marginBottom: 8
      }
    }, "\u5206\u5757\u539F\u6587 \xB7 ", chunks.length, " chunks"), chunks.map(c => /*#__PURE__*/React.createElement("div", {
      key: c.chunk_id,
      ref: el => refs.current[c.chunk_id] = el,
      style: {
        padding: "11px 13px",
        borderRadius: "var(--radius-md)",
        marginBottom: 8,
        border: "1px solid var(--border)",
        background: "var(--surface)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        color: "var(--accent)"
      }
    }, "#", c.ordinal), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10,
        color: "var(--fg-subtle)"
      }
    }, "p.", c.page, " \xB7 ", c.chunk_id)), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 13,
        lineHeight: 1.7,
        color: "var(--fg)"
      }
    }, c.text))), chunks.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: "var(--fg-subtle)",
        padding: "16px 0"
      }
    }, "\u8BE5\u6587\u6863\u5206\u5757\u539F\u6587\u672A\u52A0\u8F7D\uFF08\u6F14\u793A\u6570\u636E\uFF09\u3002")));
  }
  function DocumentsPanel({
    selection,
    view,
    doc,
    mode,
    setMode,
    highlight,
    onClearHighlight,
    onBack
  }) {
    const Icon = window.KRIcon;
    let crumbs, right, body;
    if (view === "reading" && doc) {
      crumbs = [{
        label: "Documents",
        onClick: onBack
      }, {
        label: doc.collection || "—",
        onClick: onBack
      }, {
        label: doc.title
      }];
      right = /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          gap: 2,
          background: "var(--bg-inset)",
          borderRadius: "var(--radius-md)",
          padding: 2
        }
      }, ["md", "pdf"].map(m => /*#__PURE__*/React.createElement("button", {
        key: m,
        onClick: () => setMode(m),
        style: {
          fontSize: 11,
          fontWeight: 600,
          padding: "4px 10px",
          borderRadius: "var(--radius-sm)",
          border: "none",
          cursor: "pointer",
          fontFamily: "var(--font-sans)",
          textTransform: "uppercase",
          letterSpacing: ".04em",
          background: mode === m ? "var(--surface)" : "transparent",
          color: mode === m ? "var(--accent)" : "var(--fg-muted)",
          boxShadow: mode === m ? "var(--shadow-card)" : "none"
        }
      }, m)));
      body = /*#__PURE__*/React.createElement(ReadingView, {
        doc: doc,
        mode: mode,
        setMode: setMode,
        highlight: highlight,
        onClearHighlight: onClearHighlight
      });
    } else {
      // list view
      let docs = DOCS,
        title = "全部文档";
      if (selection.type === "collection") {
        docs = DOCS.filter(d => d.collection === selection.name);
        title = selection.name;
      } else if (selection.type === "lightrag") {
        docs = DOCS.filter(d => d.collection === selection.name && d.lightrag);
        title = selection.name;
      }
      crumbs = [{
        label: "Documents"
      }, {
        label: selection.name || "全部"
      }];
      right = /*#__PURE__*/React.createElement(IconBtn, {
        name: "search",
        label: "\u5728\u96C6\u5408\u5185\u67E5\u627E (Find)"
      });
      body = /*#__PURE__*/React.createElement(ListView, {
        docs: docs,
        title: title
      });
    }
    return /*#__PURE__*/React.createElement(Panel, {
      title: view === "reading" ? null : "Documents",
      crumbs: crumbs,
      right: right,
      flush: true,
      style: {
        flex: 1,
        minWidth: 0
      },
      bodyStyle: {
        padding: "14px 0"
      }
    }, body);
  }
  window.KRDocumentsPanel = DocumentsPanel;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/DocumentsPanel.jsx", error: String((e && e.message) || e) }); }

// web/FilePanel.jsx
try { (() => {
/* Knowledge Repository · File panel — tri-section collection tree.
   Sections: Zotero Sync (expandable) · Local Collection · LightRAG Collection.
   Active row: inverse highlight + a theme-color pulse traveling the branch line.
   LightRAG build progress lives inside the LightRAG section. */
(function () {
  const {
    IconBtn,
    Eyebrow,
    Tip
  } = window.KRUI;
  const Icon = window.KRIcon;
  const {
    COLLECTIONS,
    DOCS
  } = window.KRMock;
  function Caret({
    open
  }) {
    return /*#__PURE__*/React.createElement(Icon, {
      name: "chevR",
      size: 13,
      style: {
        transform: open ? "rotate(90deg)" : "none",
        transition: "transform .15s",
        color: "var(--fg-subtle)"
      }
    });
  }

  // a single row in the tree (collection or document leaf)
  function Row({
    depth,
    active,
    leaf,
    label,
    count,
    icon,
    onClick,
    lightragBuilt,
    badge
  }) {
    const [hover, setHover] = React.useState(false);
    return /*#__PURE__*/React.createElement("div", {
      onClick: onClick,
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      style: {
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "5px 8px 5px " + (10 + depth * 16) + "px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        userSelect: "none",
        backgroundColor: active ? "var(--select-bg)" : hover ? "var(--bg-inset)" : "rgba(0,0,0,0)",
        color: active ? "var(--select-fg)" : leaf ? "var(--fg-muted)" : "var(--fg)",
        transition: "background-color .12s, color .12s",
        margin: "1px 0"
      }
    }, active && depth > 0 && /*#__PURE__*/React.createElement("span", {
      "aria-hidden": true,
      style: {
        position: "absolute",
        left: 10 + (depth - 1) * 16 + 3,
        top: "50%",
        width: 13,
        height: 2,
        transform: "translateY(-50%)",
        overflow: "hidden"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        top: 0,
        left: 0,
        width: 8,
        height: 2,
        borderRadius: 2,
        background: "var(--accent)",
        boxShadow: "0 0 6px 1px var(--accent)",
        animation: "branchPulse 1.6s ease-in-out infinite"
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        color: active ? leaf ? "var(--select-muted)" : "var(--select-fg)" : leaf ? "var(--fg-subtle)" : "var(--accent)",
        flexShrink: 0
      }
    }, icon), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12.5,
        fontWeight: active && !leaf ? 600 : leaf ? 400 : 500,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, label), badge, count != null && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10.5,
        fontWeight: 600,
        color: active ? "var(--select-muted)" : "var(--fg-subtle)",
        fontFamily: "var(--font-mono)",
        flexShrink: 0
      }
    }, count), lightragBuilt && /*#__PURE__*/React.createElement("span", {
      title: "\u5DF2\u6784\u5EFA\u56FE\u8C31",
      style: {
        width: 5,
        height: 5,
        borderRadius: "50%",
        background: active ? "var(--accent)" : "var(--ann-purple)",
        flexShrink: 0
      }
    }));
  }
  function SectionHead({
    icon,
    label,
    actions
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 6px 4px 8px",
        marginTop: 2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        color: "var(--fg-subtle)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 14
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: ".07em",
        textTransform: "uppercase",
        color: "var(--fg-subtle)"
      }
    }, label), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 1
      }
    }, actions));
  }
  function docsOf(colName, origin) {
    return DOCS.filter(d => d.collection === colName && d.origin === origin);
  }
  function lightragDocsOf(colName) {
    return DOCS.filter(d => d.collection === colName && d.lightrag);
  }
  function FilePanel({
    selection,
    onSelect,
    onZoteroSync,
    build,
    onToggleBuild
  }) {
    const [open, setOpen] = React.useState({
      "z:RAG & Retrieval": true,
      "z:Agents": false
    });
    const [secOpen, setSecOpen] = React.useState({
      zotero: true,
      local: true,
      lightrag: true
    });
    const isSel = (type, id) => selection.type === type && selection.id === id;
    const tog = k => setOpen(o => ({
      ...o,
      [k]: !o[k]
    }));
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "6px 8px 14px"
      }
    }, /*#__PURE__*/React.createElement(SectionHead, {
      icon: "sync",
      label: "Zotero Sync",
      actions: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(IconBtn, {
        name: "sync",
        label: "Zotero \u540C\u6B65 (Push / Pull)",
        size: 14,
        onClick: onZoteroSync
      }), /*#__PURE__*/React.createElement(IconBtn, {
        name: "plus",
        label: "\u65B0\u5EFA\u96C6\u5408",
        size: 14
      }))
    }), secOpen.zotero && COLLECTIONS.zotero.map(c => {
      const k = "z:" + c.name;
      return /*#__PURE__*/React.createElement("div", {
        key: k
      }, /*#__PURE__*/React.createElement(Row, {
        depth: 0,
        icon: /*#__PURE__*/React.createElement(Caret, {
          open: open[k]
        }),
        label: c.name,
        count: c.count,
        active: isSel("collection", k),
        onClick: () => {
          tog(k);
          onSelect({
            type: "collection",
            id: k,
            name: c.name,
            section: "zotero"
          });
        }
      }), open[k] && docsOf(c.name, "zotero").map(d => /*#__PURE__*/React.createElement(Row, {
        key: d.doc_id,
        depth: 1,
        leaf: true,
        icon: /*#__PURE__*/React.createElement(Icon, {
          name: "file",
          size: 13
        }),
        label: d.title,
        active: isSel("doc", d.doc_id),
        lightragBuilt: d.lightrag,
        onClick: () => onSelect({
          type: "doc",
          id: d.doc_id,
          name: d.title,
          section: "zotero",
          collection: c.name
        })
      })));
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 1,
        background: "var(--border)",
        margin: "10px 6px"
      }
    }), /*#__PURE__*/React.createElement(SectionHead, {
      icon: "folder",
      label: "Local Collection",
      actions: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(IconBtn, {
        name: "upload",
        label: "\u4E0A\u4F20\u6587\u6863",
        size: 14
      }), /*#__PURE__*/React.createElement(IconBtn, {
        name: "plus",
        label: "\u65B0\u5EFA\u96C6\u5408",
        size: 14
      }))
    }), secOpen.local && COLLECTIONS.local.map(c => {
      const k = "l:" + c.name;
      return /*#__PURE__*/React.createElement("div", {
        key: k
      }, /*#__PURE__*/React.createElement(Row, {
        depth: 0,
        icon: /*#__PURE__*/React.createElement(Caret, {
          open: open[k]
        }),
        label: c.name,
        count: c.count,
        active: isSel("collection", k),
        onClick: () => {
          tog(k);
          onSelect({
            type: "collection",
            id: k,
            name: c.name,
            section: "local"
          });
        }
      }), open[k] && docsOf(c.name, "local").map(d => /*#__PURE__*/React.createElement(Row, {
        key: d.doc_id,
        depth: 1,
        leaf: true,
        icon: /*#__PURE__*/React.createElement(Icon, {
          name: d.ext === "md" ? "doc" : "file",
          size: 13
        }),
        label: d.title,
        active: isSel("doc", d.doc_id),
        onClick: () => onSelect({
          type: "doc",
          id: d.doc_id,
          name: d.title,
          section: "local",
          collection: c.name
        })
      })));
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 1,
        background: "var(--border)",
        margin: "10px 6px"
      }
    }), /*#__PURE__*/React.createElement(SectionHead, {
      icon: "graph",
      label: "LightRAG Collection",
      actions: /*#__PURE__*/React.createElement(IconBtn, {
        name: "spark2",
        label: "\u6784\u5EFA / \u589E\u91CF\u7D22\u5F15 (\u9694\u79BB\u4E8E Sync)",
        size: 14,
        onClick: onToggleBuild
      })
    }), secOpen.lightrag && COLLECTIONS.lightrag.map(c => {
      const k = "lr:" + c.name;
      const building = build && build.collection === c.name;
      return /*#__PURE__*/React.createElement("div", {
        key: k
      }, /*#__PURE__*/React.createElement(Row, {
        depth: 0,
        icon: /*#__PURE__*/React.createElement(Icon, {
          name: "layers",
          size: 13
        }),
        label: c.name,
        active: isSel("lightrag", k),
        lightragBuilt: true,
        badge: /*#__PURE__*/React.createElement("span", {
          style: {
            fontSize: 9.5,
            fontFamily: "var(--font-mono)",
            color: isSel("lightrag", k) ? "var(--select-muted)" : "var(--ann-purple)",
            marginRight: 2
          }
        }, c.entities, "e\xB7", c.relations, "r"),
        onClick: () => onSelect({
          type: "lightrag",
          id: k,
          name: c.name,
          section: "lightrag"
        })
      }), building && /*#__PURE__*/React.createElement("div", {
        style: {
          margin: "3px 6px 8px 24px",
          padding: "8px 10px",
          background: "var(--accent-soft)",
          border: "1px solid var(--accent-border)",
          borderRadius: "var(--radius-md)"
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 7
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 9,
          height: 9,
          borderRadius: "50%",
          border: "2px solid var(--accent)",
          borderTopColor: "transparent",
          animation: "spin .7s linear infinite"
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 11,
          fontWeight: 600,
          color: "var(--accent)",
          flex: 1
        }
      }, "\u56FE\u8C31\u6784\u5EFA\u4E2D \xB7 ", build.stage), /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--accent)"
        }
      }, Math.round(build.pct), "%")), /*#__PURE__*/React.createElement("div", {
        style: {
          height: 5,
          borderRadius: 999,
          background: "color-mix(in srgb, var(--accent) 18%, transparent)",
          overflow: "hidden"
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          width: build.pct + "%",
          height: "100%",
          borderRadius: 999,
          background: "linear-gradient(90deg, var(--accent), var(--accent-strong))",
          transition: "width .4s"
        }
      })), /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 10,
          color: "var(--fg-muted)",
          marginTop: 6,
          fontFamily: "var(--font-mono)"
        }
      }, build.processed, "/", build.total, " chunks \xB7 \u9694\u79BB\u6784\u5EFA\uFF0C\u4E0D\u53D7 Sync \u5F71\u54CD")));
    }));
  }
  window.KRFilePanel = FilePanel;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/FilePanel.jsx", error: String((e && e.message) || e) }); }

// web/NotePanel.jsx
try { (() => {
/* Knowledge Repository · Note panel — Zotero-style metadata + annotations + notes.
   Replaces the File panel when a document is opened (Fig4 behavior).
   Data: Zotero-synced annotations (read-only) + local notes (new backend — see report). */
(function () {
  const {
    IconBtn,
    Tag,
    Eyebrow,
    Button
  } = window.KRUI;
  const Icon = window.KRIcon;
  const {
    NOTES,
    CHUNKS
  } = window.KRMock;
  const ANN = {
    purple: {
      bar: "var(--ann-purple)",
      bg: "var(--ann-purple-bg)",
      bd: "var(--ann-purple-border)"
    },
    yellow: {
      bar: "var(--ann-yellow)",
      bg: "var(--ann-yellow-bg)",
      bd: "var(--ann-yellow-border)"
    },
    green: {
      bar: "var(--ann-green)",
      bg: "var(--ann-green-bg)",
      bd: "var(--ann-green-border)"
    },
    red: {
      bar: "var(--ann-red)",
      bg: "var(--ann-red-bg)",
      bd: "var(--ann-red-border)"
    },
    blue: {
      bar: "var(--ann-blue)",
      bg: "var(--ann-blue-bg)",
      bd: "var(--ann-blue-border)"
    }
  };
  function MetaRow({
    k,
    v,
    mono,
    link
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 10,
        padding: "3px 0"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 58,
        flexShrink: 0,
        fontSize: 11,
        color: "var(--fg-subtle)"
      }
    }, k), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 11.5,
        color: link ? "var(--accent)" : "var(--fg)",
        fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
        wordBreak: "break-word",
        lineHeight: 1.45
      }
    }, v));
  }
  function NotePanel({
    doc,
    notes,
    onClose,
    onJumpChunk,
    onAddNote
  }) {
    const data = NOTES[doc.doc_id] || {
      annotations: [],
      notes: []
    };
    const localNotes = notes && notes[doc.doc_id] ? notes[doc.doc_id] : data.notes;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        height: "100%"
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        height: 38,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 8px 0 13px",
        borderBottom: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 650,
        color: "var(--heading)"
      }
    }, "Note"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--fg-subtle)"
      }
    }, "/"), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12,
        color: "var(--fg-muted)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, doc.origin === "zotero" ? "Zotero Sync" : "Local"), /*#__PURE__*/React.createElement(IconBtn, {
      name: "x",
      label: "\u5173\u95ED\u9762\u677F\uFF08\u8FD4\u56DE File\uFF09",
      onClick: onClose
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        overflow: "auto",
        padding: "14px 14px 30px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14.5,
        fontWeight: 700,
        color: "var(--heading)",
        lineHeight: 1.35,
        marginBottom: 12
      }
    }, doc.title), doc.authors && /*#__PURE__*/React.createElement(MetaRow, {
      k: "Authors",
      v: doc.authors
    }), /*#__PURE__*/React.createElement(MetaRow, {
      k: "Year",
      v: doc.year
    }), doc.venue && /*#__PURE__*/React.createElement(MetaRow, {
      k: "Journal",
      v: doc.venue
    }), doc.doi && /*#__PURE__*/React.createElement(MetaRow, {
      k: "DOI",
      v: doc.doi,
      link: true,
      mono: true
    }), /*#__PURE__*/React.createElement(MetaRow, {
      k: "Type",
      v: doc.type
    }), /*#__PURE__*/React.createElement(MetaRow, {
      k: "Added",
      v: doc.added,
      mono: true
    }), /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        margin: "18px 0 8px"
      }
    }, "Tags"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexWrap: "wrap",
        gap: 5
      }
    }, doc.tags.map(t => /*#__PURE__*/React.createElement(Tag, {
      key: t,
      label: t
    }))), /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        margin: "20px 0 8px"
      }
    }, "Annotations \xB7 ", data.annotations.length), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 8
      }
    }, data.annotations.map(a => {
      const c = ANN[a.color] || ANN.yellow;
      return /*#__PURE__*/React.createElement("div", {
        key: a.id,
        style: {
          borderRadius: "var(--radius-md)",
          border: `1px solid ${c.bd}`,
          background: c.bg,
          overflow: "hidden",
          display: "flex"
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 3,
          flexShrink: 0,
          background: c.bar
        }
      }), /*#__PURE__*/React.createElement("div", {
        style: {
          padding: "8px 10px",
          flex: 1,
          minWidth: 0
        }
      }, /*#__PURE__*/React.createElement("p", {
        style: {
          margin: 0,
          fontSize: 12,
          lineHeight: 1.55,
          color: "var(--fg)"
        }
      }, a.text), a.comment && /*#__PURE__*/React.createElement("p", {
        style: {
          margin: "6px 0 0",
          fontSize: 11,
          fontStyle: "italic",
          fontWeight: 600,
          color: c.bar,
          lineHeight: 1.45
        }
      }, a.comment), /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginTop: 6
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 10,
          color: "var(--fg-subtle)",
          fontFamily: "var(--font-mono)"
        }
      }, "p.", a.page, " \xB7 highlight"))));
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        margin: "20px 0 8px"
      }
    }, /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        flex: 1
      }
    }, "Notes \xB7 ", localNotes.length), /*#__PURE__*/React.createElement(IconBtn, {
      name: "plus",
      label: "\u65B0\u5EFA\u7B14\u8BB0\uFF08\u672C\u5730\uFF09",
      onClick: onAddNote
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        gap: 7
      }
    }, localNotes.map(n => /*#__PURE__*/React.createElement("div", {
      key: n.id,
      style: {
        padding: "9px 11px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border)",
        background: "var(--surface)"
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 12,
        lineHeight: 1.6,
        color: "var(--fg)"
      }
    }, n.body), n.linked && /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 4,
        marginTop: 6,
        fontSize: 10.5,
        color: "var(--accent)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "link",
      size: 11
    }), " \u6765\u81EA Chat \u56DE\u7B54"))), localNotes.length === 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        color: "var(--fg-subtle)"
      }
    }, "\u6682\u65E0\u7B14\u8BB0\uFF0C\u70B9 + \u65B0\u5EFA\u3002")), /*#__PURE__*/React.createElement(Eyebrow, {
      style: {
        margin: "20px 0 8px"
      }
    }, "Abstract"), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 12,
        lineHeight: 1.7,
        color: "var(--fg-muted)"
      }
    }, doc.abstract)));
  }
  window.KRNotePanel = NotePanel;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/NotePanel.jsx", error: String((e && e.message) || e) }); }

// web/SettingModal.jsx
try { (() => {
/* Knowledge Repository · Setting modal — merges Appearance + Backend config + Sync/Backup + Terminal. */
(function () {
  const {
    Modal,
    Button,
    Toggle,
    Select,
    Tag,
    Badge,
    Eyebrow,
    IconBtn
  } = window.KRUI;
  const Icon = window.KRIcon;
  function Field({
    label,
    children,
    hint
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 500,
        color: "var(--fg)"
      }
    }, label), hint && /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: "var(--fg-subtle)",
        marginTop: 2,
        lineHeight: 1.45
      }
    }, hint)), /*#__PURE__*/React.createElement("div", {
      style: {
        flexShrink: 0
      }
    }, children));
  }
  function Card({
    title,
    icon,
    children,
    badge
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: "4px 16px 12px",
        marginBottom: 14
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "12px 0 4px"
      }
    }, icon && /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 16,
      style: {
        color: "var(--accent)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 650,
        color: "var(--heading)",
        flex: 1
      }
    }, title), badge), children);
  }
  function ConfigKV({
    k,
    v,
    masked
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid var(--border)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 170,
        flexShrink: 0,
        fontSize: 12,
        color: "var(--fg-muted)"
      }
    }, k), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 12,
        fontFamily: "var(--font-mono)",
        color: masked ? "var(--fg-subtle)" : "var(--fg)",
        wordBreak: "break-all"
      }
    }, v));
  }
  function Swatch({
    h,
    active,
    onClick,
    label
  }) {
    return /*#__PURE__*/React.createElement("button", {
      onClick: onClick,
      title: label,
      style: {
        width: 30,
        height: 30,
        borderRadius: "var(--radius-md)",
        border: active ? "2px solid var(--fg)" : "2px solid transparent",
        boxShadow: active ? "0 0 0 1px var(--surface) inset" : "none",
        background: `hsl(${h} 70% 56%)`,
        cursor: "pointer",
        padding: 0
      }
    });
  }
  function SettingModal({
    onClose,
    accent,
    setAccent,
    onTheme,
    theme
  }) {
    const [tab, setTab] = React.useState("appearance");
    const tabs = [{
      id: "appearance",
      label: "外观",
      icon: "sun"
    }, {
      id: "sync",
      label: "同步 / 备份",
      icon: "sync"
    }, {
      id: "config",
      label: "后端配置",
      icon: "db"
    }, {
      id: "terminal",
      label: "终端日志",
      icon: "terminal"
    }];
    return /*#__PURE__*/React.createElement(Modal, {
      title: "Setting",
      icon: "settings",
      onClose: onClose,
      width: 920,
      footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
        variant: "ghost",
        onClick: onClose
      }, "\u53D6\u6D88"), /*#__PURE__*/React.createElement(Button, {
        variant: "primary"
      }, "\u4FDD\u5B58\u914D\u7F6E"))
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        height: "100%"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 168,
        flexShrink: 0,
        borderRight: "1px solid var(--border)",
        background: "var(--surface)",
        padding: 10
      }
    }, tabs.map(t => /*#__PURE__*/React.createElement("button", {
      key: t.id,
      onClick: () => setTab(t.id),
      style: {
        display: "flex",
        alignItems: "center",
        gap: 9,
        width: "100%",
        padding: "8px 10px",
        borderRadius: "var(--radius-md)",
        border: "none",
        background: tab === t.id ? "var(--accent-soft)" : "transparent",
        color: tab === t.id ? "var(--accent)" : "var(--fg-muted)",
        cursor: "pointer",
        fontSize: 13,
        fontWeight: tab === t.id ? 600 : 450,
        fontFamily: "var(--font-sans)",
        marginBottom: 2,
        textAlign: "left"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: t.icon,
      size: 15
    }), " ", t.label))), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        overflow: "auto",
        padding: "18px 22px"
      }
    }, tab === "appearance" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
      title: "\u4E3B\u9898\u4E0E\u5916\u89C2",
      icon: "sun"
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u4E3B\u9898\u6A21\u5F0F",
      hint: "\u6DF1\u6D45\u914D\u8272\uFF08\u4F60\u5DF2\u6709\u591A\u5957\u65B9\u6848\uFF0C\u6B64\u5904\u5207\u6362\uFF09"
    }, /*#__PURE__*/React.createElement(Select, {
      value: theme,
      onChange: onTheme,
      options: [{
        value: "light",
        label: "浅色"
      }, {
        value: "dark",
        label: "深色"
      }, {
        value: "system",
        label: "跟随系统"
      }]
    })), /*#__PURE__*/React.createElement(Field, {
      label: "\u754C\u9762\u8BED\u8A00",
      hint: "\u672F\u8BED\uFF08collection / chunk / RRF\uFF09\u4FDD\u7559\u82F1\u6587"
    }, /*#__PURE__*/React.createElement(Select, {
      value: "zh",
      options: [{
        value: "zh",
        label: "中文"
      }, {
        value: "en",
        label: "English"
      }]
    }))), /*#__PURE__*/React.createElement(Card, {
      title: "\u5168\u5C40\u5F3A\u8C03\u8272",
      icon: "sparkle",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: "accent"
      }, "\u4E00\u5904\u751F\u6548")
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--fg-muted)",
        lineHeight: 1.55,
        marginBottom: 12
      }
    }, "\u6240\u6709\u63A7\u4EF6\u7684\u4E3B\u9898\u8272 / \u5F3A\u8C03\u8272\u7EDF\u4E00\u7531\u6B64\u9A71\u52A8\uFF1B\u8C03\u8282\u540E\u5168\u7AD9\u5B9E\u65F6\u7EA7\u8054\u6E32\u67D3\u5E76\u672C\u5730\u6301\u4E45\u5316\u3002"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 8,
        marginBottom: 16
      }
    }, [225, 200, 265, 160, 32, 12, 340].map(h => /*#__PURE__*/React.createElement(Swatch, {
      key: h,
      h: h,
      active: Math.abs(accent.h - h) < 6,
      onClick: () => setAccent({
        ...accent,
        h
      })
    }))), [["色相 H", "h", 0, 360], ["饱和度 S", "s", 0, 100], ["明度 L", "l", 20, 80]].map(([lbl, key, min, max]) => /*#__PURE__*/React.createElement("div", {
      key: key,
      style: {
        display: "flex",
        alignItems: "center",
        gap: 12,
        marginBottom: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 60,
        fontSize: 12,
        color: "var(--fg-muted)"
      }
    }, lbl), /*#__PURE__*/React.createElement("input", {
      type: "range",
      min: min,
      max: max,
      value: accent[key],
      onChange: e => setAccent({
        ...accent,
        [key]: +e.target.value
      }),
      style: {
        flex: 1,
        accentColor: "var(--accent)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        width: 36,
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        color: "var(--fg)",
        textAlign: "right"
      }
    }, accent[key], key === "h" ? "°" : "%"))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 8,
        marginTop: 14
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "primary"
    }, "\u4E3B\u6309\u94AE"), /*#__PURE__*/React.createElement(Button, {
      variant: "outline"
    }, "\u6B21\u6309\u94AE"), /*#__PURE__*/React.createElement(Tag, {
      label: "\u6807\u7B7E",
      accent: true
    }), /*#__PURE__*/React.createElement(Badge, {
      tone: "accent"
    }, "\u5FBD\u7AE0")))), tab === "sync" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
      title: "Zotero \u540C\u6B65",
      icon: "book",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: "ok"
      }, "\u5DF2\u8FDE\u63A5")
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u5355\u5411 Pull \u955C\u50CF",
      hint: "\u53EA\u8BFB\u955C\u50CF Zotero \u6761\u76EE / \u96C6\u5408 / \u6807\u7B7E / PDF\uFF0C\u6E05\u6D17\u4E3A Markdown"
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "outline",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "sync",
      size: 13
    }), " \u7ACB\u5373\u540C\u6B65")), /*#__PURE__*/React.createElement(Field, {
      label: "\u81EA\u52A8\u540C\u6B65",
      hint: "\u95F4\u9694 3600 \u79D2"
    }, /*#__PURE__*/React.createElement(Toggle, {
      checked: true,
      onChange: () => {}
    }))), /*#__PURE__*/React.createElement(Card, {
      title: "Cloudflare R2 \u5907\u4EFD",
      icon: "cloud",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: "ok"
      }, "\u5DF2\u542F\u7528")
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u5BF9\u8C61\u5B58\u50A8\u5907\u4EFD",
      hint: "3.2 GB / 10 GB \u5DF2\u7528"
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "outline",
      size: "sm"
    }, "\u7ACB\u5373\u5907\u4EFD")), /*#__PURE__*/React.createElement(Field, {
      label: "\u5907\u4EFD\u95F4\u9694",
      hint: "86400 \u79D2\uFF08\u6BCF\u65E5\uFF09"
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, "daily"))), /*#__PURE__*/React.createElement(Card, {
      title: "Notion \u955C\u50CF",
      icon: "layers",
      badge: /*#__PURE__*/React.createElement(Badge, {
        tone: "warn"
      }, "\u5373\u5C06\u4E0A\u7EBF v0.8.0")
    }, /*#__PURE__*/React.createElement(Field, {
      label: "\u4ECE Notion \u62C9\u53D6\u5143\u6570\u636E",
      hint: "\u7AEF\u53E3\u9884\u7559\u4E2D\uFF0CUI \u4F18\u96C5\u964D\u7EA7"
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      disabled: true
    }, "\u62C9\u53D6")))), tab === "config" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: "var(--fg-muted)",
        marginBottom: 14
      }
    }, "\u53EA\u8BFB\u6838\u5BF9\u540E\u7AEF\u6709\u6548\u914D\u7F6E\uFF08", /*#__PURE__*/React.createElement("code", {
      style: {
        fontFamily: "var(--font-mono)",
        color: "var(--accent)"
      }
    }, "GET /api/config/effective"), "\uFF09\uFF0C\u654F\u611F\u5B57\u6BB5\u5DF2\u6253\u7801\u3002"), /*#__PURE__*/React.createElement(Card, {
      title: "\u6E90\u5E93 Source Store",
      icon: "db"
    }, /*#__PURE__*/React.createElement(ConfigKV, {
      k: "db_filename",
      v: "knowledge_repository.db"
    }), /*#__PURE__*/React.createElement(ConfigKV, {
      k: "default_collection",
      v: "default"
    }), /*#__PURE__*/React.createElement(ConfigKV, {
      k: "ocr_enabled",
      v: "false"
    })), /*#__PURE__*/React.createElement(Card, {
      title: "Web \u63A7\u5236\u53F0",
      icon: "globe"
    }, /*#__PURE__*/React.createElement(ConfigKV, {
      k: "host",
      v: "0.0.0.0"
    }), /*#__PURE__*/React.createElement(ConfigKV, {
      k: "port",
      v: "6520"
    }), /*#__PURE__*/React.createElement(ConfigKV, {
      k: "password",
      v: "****",
      masked: true
    }))), tab === "terminal" && /*#__PURE__*/React.createElement("div", {
      style: {
        background: "#16171a",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-lg)",
        padding: 14,
        fontFamily: "var(--font-mono)",
        fontSize: 11.5,
        lineHeight: 1.7,
        color: "#cfd2c8",
        minHeight: 320
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        color: "#7c89b8"
      }
    }, "[12:04:11] ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#6abf75"
      }
    }, "INFO"), " aiohttp server on 0.0.0.0:6520"), /*#__PURE__*/React.createElement("div", null, "[12:04:11] ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#6abf75"
      }
    }, "INFO"), " migrations 001\u2013012 applied"), /*#__PURE__*/React.createElement("div", null, "[12:04:13] ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#6abf75"
      }
    }, "INFO"), " Milvus Lite index loaded \xB7 6 docs / 188 chunks"), /*#__PURE__*/React.createElement("div", null, "[12:05:02] ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#e0a23b"
      }
    }, "WARN"), " LightRAG workspace \"Foundations\" not built"), /*#__PURE__*/React.createElement("div", null, "[12:06:44] ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: "#6abf75"
      }
    }, "INFO"), " /api/ask conv=demo-1 mode=milvus_lightrag k=5 \u2192 200 (812ms)"), /*#__PURE__*/React.createElement("div", {
      style: {
        color: "#6b6759"
      }
    }, "\u2014 \u7EC8\u7AEF\u65E5\u5FD7\u6682\u7F6E\u4E8E Setting\uFF0C\u540E\u7EED\u53EF\u72EC\u7ACB \u2014")))));
  }
  window.KRSettingModal = SettingModal;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/SettingModal.jsx", error: String((e && e.message) || e) }); }

// web/WorkflowModal.jsx
try { (() => {
/* Knowledge Repository · WorkFlow modal — data-flow pipeline (redesigned nodes, Heptabase style).
   Reuses the existing Flow logic (stages / status / switchable backends) with new node art. */
(function () {
  const {
    Modal,
    Badge,
    StatusChipUnused
  } = window.KRUI;
  const Icon = window.KRIcon;
  const STAGES = [{
    id: "zotero",
    icon: "book",
    title: "Zotero 文献库",
    role: "可选来源",
    status: "ready",
    field: ["来源", "managed_copy"],
    desc: "只读镜像条目/PDF，清洗为 Markdown"
  }, {
    id: "ingest",
    icon: "upload",
    title: "上传 / 分块",
    role: "只读 · 默认",
    status: "ready",
    field: ["STORE", "SQLite"],
    desc: "原件留存，切分文本片段"
  }, {
    id: "embedding",
    icon: "layers",
    title: "向量化",
    role: "可切换",
    status: "ready",
    field: ["PROVIDER", "local · e5-small"],
    desc: "文本片段 → 向量"
  }, {
    id: "vector",
    icon: "db",
    title: "向量库",
    role: "可切换",
    status: "ready",
    field: ["BACKEND", "Milvus Lite"],
    desc: "稠密检索，AstrBot KB 回退"
  }, {
    id: "retrieval",
    icon: "search",
    title: "检索编排",
    role: "只读 · 默认",
    status: "ready",
    field: ["STRATEGY", "向量 + 词汇 · RRF"],
    desc: "多路召回，RRF 融合"
  }, {
    id: "ask",
    icon: "sparkle",
    title: "问答 Ask",
    role: "界面 · 可切换",
    status: "ready",
    field: ["MODE", "inject"],
    desc: "注入上下文生成回答"
  }];
  function Node({
    s,
    dest
  }) {
    const sc = {
      ready: "var(--ok)",
      degraded: "var(--warn)",
      off: "var(--fg-subtle)",
      info: "var(--info)"
    }[s.status];
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: "relative",
        width: 188,
        flexShrink: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: dest ? "var(--shadow-raised)" : "var(--shadow-card)",
        padding: "12px 13px",
        display: "flex",
        flexDirection: "column",
        gap: 9,
        overflow: "hidden"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        left: 0,
        top: 0,
        bottom: 0,
        width: 3,
        background: `linear-gradient(${sc}, color-mix(in srgb, ${sc} 40%, transparent))`
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 28,
        height: 28,
        borderRadius: "var(--radius-md)",
        background: `color-mix(in srgb, ${sc} 10%, var(--bg-inset))`,
        border: `1px solid color-mix(in srgb, ${sc} 22%, var(--border))`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: sc,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: s.icon,
      size: 15
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        fontWeight: 650,
        color: "var(--heading)",
        letterSpacing: "-.01em"
      }
    }, s.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 9.5,
        fontWeight: 600,
        color: "var(--fg-muted)"
      }
    }, s.role))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "inline-flex",
        alignSelf: "flex-start",
        alignItems: "center",
        gap: 5,
        fontSize: 10.5,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 999,
        border: `1px solid color-mix(in srgb, ${sc} 30%, transparent)`,
        color: sc,
        background: `color-mix(in srgb, ${sc} 9%, transparent)`
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: sc
      }
    }), " \u5C31\u7EEA"), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: ".09em",
        color: "var(--fg-subtle)",
        fontFamily: "var(--font-mono)"
      }
    }, s.field[0]), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        fontWeight: 600,
        color: "var(--fg)",
        marginTop: 3,
        fontFamily: "var(--font-mono)"
      }
    }, s.field[1])), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10.5,
        color: "var(--fg-muted)",
        lineHeight: 1.5
      }
    }, s.desc));
  }
  function Connector() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        color: "var(--border-strong)",
        width: 30,
        justifyContent: "center"
      }
    }, /*#__PURE__*/React.createElement("svg", {
      width: "30",
      height: "14",
      viewBox: "0 0 30 14"
    }, /*#__PURE__*/React.createElement("line", {
      x1: "0",
      y1: "7",
      x2: "22",
      y2: "7",
      stroke: "var(--border-strong)",
      strokeWidth: "2",
      strokeDasharray: "3 4"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: "18,3 24,7 18,11",
      fill: "none",
      stroke: "var(--border-strong)",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    })));
  }
  function WorkflowModal({
    onClose
  }) {
    return /*#__PURE__*/React.createElement(Modal, {
      title: "WorkFlow \xB7 \u6570\u636E\u6D41",
      icon: "flow",
      onClose: onClose,
      width: 1040,
      height: "86vh"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: "18px 22px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 14,
        marginBottom: 6
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 12.5,
        color: "var(--fg-muted)",
        lineHeight: 1.55,
        flex: 1
      }
    }, "\u67E5\u770B\u77E5\u8BC6\u5E93\u5404\u73AF\u8282\u5F53\u524D\u7528\u54EA\u4E2A\u540E\u7AEF\u3001\u662F\u5426\u5C31\u7EEA\u3002\u68C0\u7D22\u7F16\u6392\u4E0E LightRAG \u56FE\u8C31", /*#__PURE__*/React.createElement("b", {
      style: {
        color: "var(--fg)"
      }
    }, "\u5E76\u8054"), "\uFF0C\u56FE\u8C31\u4E3A\u9AD8\u7CBE\u5EA6\u53EF\u9009\u8DEF\u5F84\uFF0C\u4E0D\u963B\u585E\u9ED8\u8BA4\u68C0\u7D22\u3002"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 12,
        fontSize: 11,
        color: "var(--fg-muted)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: "var(--ok)"
      }
    }), " \u5C31\u7EEA"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: "var(--warn)"
      }
    }), " \u5F85\u5904\u7406"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 5
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: "var(--fg-subtle)"
      }
    }), " \u672A\u542F\u7528"))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        overflowX: "auto",
        padding: "22px 4px 10px"
      }
    }, STAGES.map((s, i) => /*#__PURE__*/React.createElement(React.Fragment, {
      key: s.id
    }, /*#__PURE__*/React.createElement(Node, {
      s: s
    }), i < STAGES.length - 1 && /*#__PURE__*/React.createElement(Connector, null)))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 30,
        marginTop: 18,
        flexWrap: "wrap"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 280,
        background: "var(--accent-soft)",
        border: "1px solid var(--accent-border)",
        borderRadius: "var(--radius-xl)",
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "graph",
      size: 16,
      style: {
        color: "var(--accent)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        fontWeight: 650,
        color: "var(--heading)",
        flex: 1
      }
    }, "LightRAG \u56FE\u8C31 \xB7 \u5E76\u8054\u9AD8\u7CBE\u5EA6\u8DEF\u5F84"), /*#__PURE__*/React.createElement(Badge, {
      tone: "violet"
    }, "\u53EF\u9009 \xB7 \u9694\u79BB\u6784\u5EFA")), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 11.5,
        color: "var(--fg-muted)",
        lineHeight: 1.55
      }
    }, "\u4E0E\u68C0\u7D22\u7F16\u6392\u5E76\u8054\uFF0C\u57FA\u4E8E\u77E5\u8BC6\u56FE\u8C31\u53EC\u56DE\u3002\u624B\u52A8\u89E6\u53D1\u6784\u5EFA\u4EE5\u63A7\u5236\u6210\u672C\uFF0C\u4E0E Sync \u9694\u79BB\u2014\u2014Sync \u53D8\u5316\u4E0D\u4F1A\u89E6\u53D1\u6216\u5F71\u54CD\u56FE\u8C31\u7D22\u5F15\u3002"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 6,
        marginTop: 10
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, "RAG & Retrieval \xB7 142e"), /*#__PURE__*/React.createElement(Badge, {
      tone: "neutral"
    }, "Agents \xB7 86e"))), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 280,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "cloud",
      size: 16,
      style: {
        color: "var(--fg-muted)"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        fontWeight: 650,
        color: "var(--heading)",
        flex: 1
      }
    }, "\u540C\u6B65 / \u5907\u4EFD \xB7 \u65C1\u8DEF"), /*#__PURE__*/React.createElement(Badge, {
      tone: "ok"
    }, "R2 \u5C31\u7EEA")), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 11.5,
        color: "var(--fg-muted)",
        lineHeight: 1.55
      }
    }, "\u955C\u50CF\u5907\u4EFD\u5230 Cloudflare R2 / Notion\uFF0C\u4E0E\u68C0\u7D22\u4E92\u4E0D\u5F71\u54CD\u3002\u5BC6\u94A5\u7ECF\u73AF\u5883\u53D8\u91CF\u914D\u7F6E\u3002"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 6,
        marginTop: 10
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "ok"
    }, "R2 \xB7 3.2/10 GB"), /*#__PURE__*/React.createElement(Badge, {
      tone: "warn"
    }, "Notion \xB7 v0.8.0"))))));
  }
  window.KRWorkflowModal = WorkflowModal;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/WorkflowModal.jsx", error: String((e && e.message) || e) }); }

// web/icons.jsx
try { (() => {
/* Knowledge Repository · Icon set (Lucide-style strokes, 1.7–2 weight, round caps).
   Usage: <Icon name="search" size={16} />  — all share one frame. */
(function () {
  const P = {
    sparkle: /*#__PURE__*/React.createElement("path", {
      d: "M12 3l1.9 5.7L19.6 10.6 13.9 12.5 12 18.2 10.1 12.5 4.4 10.6 10.1 8.7z"
    }),
    doc: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M14 3v5h5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 13h6M9 17h4"
    })),
    file: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M14 3v5h5"
    })),
    folder: /*#__PURE__*/React.createElement("path", {
      d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"
    }),
    search: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "11",
      cy: "11",
      r: "7.5"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "21",
      y1: "21",
      x2: "16.65",
      y2: "16.65"
    })),
    chat: /*#__PURE__*/React.createElement("path", {
      d: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-5A8 8 0 1 1 21 12z"
    }),
    note: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M5 4.5A1.5 1.5 0 0 1 6.5 3H18a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6.5A1.5 1.5 0 0 1 5 18.5z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 7h6M9 10h4"
    })),
    graph: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "6",
      cy: "6",
      r: "2.4"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "18",
      cy: "9",
      r: "2.4"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "9",
      cy: "18",
      r: "2.4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M8 7.2l8 0.6M7.6 16l1.2-7.4M16.4 11l-6 5.4"
    })),
    settings: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "3"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
    })),
    flow: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "3",
      width: "6",
      height: "6",
      rx: "1.4"
    }), /*#__PURE__*/React.createElement("rect", {
      x: "15",
      y: "15",
      width: "6",
      height: "6",
      rx: "1.4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 6h5a2 2 0 0 1 2 2v7"
    })),
    chevR: /*#__PURE__*/React.createElement("polyline", {
      points: "9 6 15 12 9 18"
    }),
    chevD: /*#__PURE__*/React.createElement("polyline", {
      points: "6 9 12 15 18 9"
    }),
    chevL: /*#__PURE__*/React.createElement("polyline", {
      points: "15 6 9 12 15 18"
    }),
    plus: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
      x1: "12",
      y1: "5",
      x2: "12",
      y2: "19"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "5",
      y1: "12",
      x2: "19",
      y2: "12"
    })),
    x: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
      x1: "18",
      y1: "6",
      x2: "6",
      y2: "18"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "6",
      y1: "6",
      x2: "18",
      y2: "18"
    })),
    trash: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("polyline", {
      points: "3 6 5 6 21 6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 11v6M14 11v6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
    })),
    sync: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("polyline", {
      points: "23 4 23 10 17 10"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: "1 20 1 14 7 14"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"
    })),
    upload: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: "17 8 12 3 7 8"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "12",
      y1: "3",
      x2: "12",
      y2: "15"
    })),
    download: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: "7 10 12 15 17 10"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "12",
      y1: "3",
      x2: "12",
      y2: "15"
    })),
    edit: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"
    })),
    cloud: /*#__PURE__*/React.createElement("path", {
      d: "M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"
    }),
    book: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
    })),
    pin: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M12 17v5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 10.76V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v5.76l1.5 3.24H7.5z"
    })),
    bookmark: /*#__PURE__*/React.createElement("path", {
      d: "M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"
    }),
    link: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"
    })),
    quote: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M3 21c3 0 7-1 7-8V5H4v7h3"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M14 21c3 0 7-1 7-8V5h-6v7h3"
    })),
    filePdf: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M14 3v5h5"
    })),
    tag: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "7",
      y1: "7",
      x2: "7.01",
      y2: "7"
    })),
    dots: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "5",
      cy: "12",
      r: "1.4"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "1.4"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "19",
      cy: "12",
      r: "1.4"
    })),
    check: /*#__PURE__*/React.createElement("polyline", {
      points: "20 6 9 17 4 12"
    }),
    spark2: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M12 3v4M12 17v4M3 12h4M17 12h4"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "3.2"
    })),
    layers: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
      d: "M12 3 3 8l9 5 9-5-9-5z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 13l9 5 9-5"
    })),
    db: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("ellipse", {
      cx: "12",
      cy: "5.5",
      rx: "7",
      ry: "2.6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M5 5.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M5 11.5v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6"
    })),
    terminal: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("polyline", {
      points: "4 17 10 11 4 5"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "12",
      y1: "19",
      x2: "20",
      y2: "19"
    })),
    globe: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "9"
    }), /*#__PURE__*/React.createElement("line", {
      x1: "3",
      y1: "12",
      x2: "21",
      y2: "12"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"
    })),
    arrowUp: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
      x1: "12",
      y1: "19",
      x2: "12",
      y2: "5"
    }), /*#__PURE__*/React.createElement("polyline", {
      points: "5 12 12 5 19 12"
    })),
    send: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
      x1: "22",
      y1: "2",
      x2: "11",
      y2: "13"
    }), /*#__PURE__*/React.createElement("polygon", {
      points: "22 2 15 22 11 13 2 9 22 2"
    })),
    sun: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
      cx: "12",
      cy: "12",
      r: "4.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"
    }))
  };
  function Icon({
    name,
    size = 16,
    strokeWidth = 1.8,
    style,
    className
  }) {
    return /*#__PURE__*/React.createElement("svg", {
      className: className,
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: strokeWidth,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      style: {
        flexShrink: 0,
        display: "block",
        ...style
      },
      "aria-hidden": "true"
    }, P[name] || P.doc);
  }
  window.KRIcon = Icon;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/icons.jsx", error: String((e && e.message) || e) }); }

// web/mock.jsx
try { (() => {
/* Knowledge Repository · Mock data for the prototype (offline, ?mock-equivalent). */
(function () {
  const COLLECTIONS = {
    zotero: [{
      name: "RAG & Retrieval",
      key: "z-rag",
      count: 4
    }, {
      name: "Agents",
      key: "z-agent",
      count: 3
    }, {
      name: "Foundations",
      key: "z-found",
      count: 2
    }],
    local: [{
      name: "papers",
      count: 5
    }, {
      name: "manuals",
      count: 2
    }, {
      name: "default",
      count: 1
    }],
    lightrag: [{
      name: "RAG & Retrieval",
      built: true,
      entities: 142,
      relations: 318
    }, {
      name: "Agents",
      built: true,
      entities: 86,
      relations: 173
    }]
  };
  const DOCS = [{
    doc_id: "d-react",
    title: "ReAct: Synergizing Reasoning and Acting in Language Models",
    authors: "Yao, S.; Zhao, J.; Yu, D.; Du, N.; Shafran, I.; Narasimhan, K.; Cao, Y.",
    year: 2023,
    venue: "ICLR 2023",
    type: "Conference paper",
    doi: "10.48550/arXiv.2210.03629",
    added: "2024-11-03",
    collection: "Agents",
    origin: "zotero",
    lightrag: true,
    tags: ["agent", "reasoning", "tool use", "LLM", "read"],
    ext: "pdf",
    size: 2_456_789,
    chunks: 48,
    abstract: "While large language models (LLMs) have demonstrated impressive capabilities across tasks in language understanding and interactive decision making, their abilities for reasoning and acting have largely been studied as separate topics. In this paper we explore the use of LLMs to generate both reasoning traces and task-specific actions in an interleaved manner."
  }, {
    doc_id: "d-lightrag",
    title: "LightRAG: Simple and Fast Retrieval-Augmented Generation",
    authors: "Guo, Z.; Xia, L.; Yu, Y.; Ao, T.; Huang, C.",
    year: 2024,
    venue: "arXiv:2410.05779",
    type: "Preprint",
    doi: "10.48550/arXiv.2410.05779",
    added: "2024-10-21",
    collection: "RAG & Retrieval",
    origin: "zotero",
    lightrag: true,
    tags: ["rag", "lightrag", "knowledge-graph", "retrieval"],
    ext: "pdf",
    size: 1_234_567,
    chunks: 28,
    abstract: "Retrieval-Augmented Generation (RAG) systems enhance large language models by integrating external knowledge sources. We propose LightRAG, which incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system that improves comprehensive information retrieval from both low-level and high-level knowledge."
  }, {
    doc_id: "d-attn",
    title: "Attention Is All You Need",
    authors: "Vaswani, A.; Shazeer, N.; Parmar, N.; Uszkoreit, J.; Jones, L.; Gomez, A.; Kaiser, Ł.; Polosukhin, I.",
    year: 2017,
    venue: "NeurIPS 2017",
    type: "Conference paper",
    doi: "10.48550/arXiv.1706.03762",
    added: "2024-09-15",
    collection: "Foundations",
    origin: "zotero",
    lightrag: false,
    tags: ["transformer", "attention", "nlp"],
    ext: "pdf",
    size: 2_956_120,
    chunks: 42,
    abstract: "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely."
  }, {
    doc_id: "d-graphrag",
    title: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
    authors: "Edge, D.; Trinh, H.; Cheng, N.; Bradley, J.; Chao, A.; Mody, A.; Truitt, S.; Larson, J.",
    year: 2024,
    venue: "arXiv:2404.16130",
    type: "Preprint",
    doi: "10.48550/arXiv.2404.16130",
    added: "2024-10-02",
    collection: "RAG & Retrieval",
    origin: "zotero",
    lightrag: true,
    tags: ["graphrag", "knowledge-graph", "summarization"],
    ext: "pdf",
    size: 3_120_000,
    chunks: 56,
    abstract: "We present a Graph RAG approach to question answering over private text corpora that scales with both the generality of user questions and the quantity of source text to be indexed."
  }, {
    doc_id: "d-rrf",
    title: "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods",
    authors: "Cormack, G. V.; Clarke, C. L. A.; Buettcher, S.",
    year: 2009,
    venue: "SIGIR 2009",
    type: "Conference paper",
    doi: "10.1145/1571941.1572114",
    added: "2024-10-22",
    collection: "RAG & Retrieval",
    origin: "zotero",
    lightrag: true,
    tags: ["rrf", "ranking", "fusion"],
    ext: "pdf",
    size: 412_000,
    chunks: 9,
    abstract: "We demonstrate that Reciprocal Rank Fusion (RRF), a simple method for combining the document rankings from multiple IR systems, consistently yields better results than any individual system."
  }, {
    doc_id: "d-manual",
    title: "AstrBot 知识库插件使用手册.md",
    authors: "",
    year: 2025,
    venue: "",
    type: "Manual",
    doi: "",
    added: "2025-05-01",
    collection: "manuals",
    origin: "local",
    lightrag: false,
    tags: ["astrbot", "manual"],
    ext: "md",
    size: 98_432,
    chunks: 15,
    abstract: "本手册介绍 AstrBot 知识库插件的安装、配置与日常使用：文档上传、集合管理、检索编排、LightRAG 图谱构建与 Research Agent 问答。"
  }];

  // chunks per doc, with ordinal + text + page
  const CHUNKS = {
    "d-react": [{
      chunk_id: "react-0",
      ordinal: 0,
      page: 1,
      text: "While large language models (LLMs) have demonstrated impressive capabilities across tasks in language understanding and interactive decision making, their abilities for reasoning (e.g., chain-of-thought prompting) and acting (e.g., action plan generation) have largely been studied as separate topics."
    }, {
      chunk_id: "react-3",
      ordinal: 3,
      page: 1,
      text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions pertaining to a task in an interleaved manner, which allows the model to perform dynamic reasoning to create, maintain, and adjust high-level plans for acting (reason to act), while also interacting with external environments to incorporate additional information into reasoning (act to reason)."
    }, {
      chunk_id: "react-9",
      ordinal: 9,
      page: 6,
      text: "On two interactive decision making benchmarks (ALFWorld and WebShop), ReAct outperforms imitation and reinforcement learning methods by an absolute success rate of 34% and 10% respectively, while being prompted with only one or two in-context examples."
    }, {
      chunk_id: "react-12",
      ordinal: 12,
      page: 3,
      text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions, making it more robust than acting-only baselines that lack a reasoning trace."
    }],
    "d-lightrag": [{
      chunk_id: "lr-1",
      ordinal: 1,
      page: 2,
      text: "LightRAG incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system that improves comprehensive information retrieval from both low-level (entity neighborhood) and high-level (cross-document themes) knowledge."
    }, {
      chunk_id: "lr-4",
      ordinal: 4,
      page: 4,
      text: "The dual-level retrieval paradigm couples a keying step that extracts both local and global keys with an incremental update algorithm that ensures the timely integration of new data without rebuilding the entire index."
    }, {
      chunk_id: "lr-7",
      ordinal: 7,
      page: 5,
      text: "By integrating graph-based knowledge structures with vector representations, LightRAG facilitates efficient retrieval of related entities and their relationships, significantly enhancing response coherence."
    }],
    "d-rrf": [{
      chunk_id: "rrf-2",
      ordinal: 2,
      page: 2,
      text: "Reciprocal Rank Fusion (RRF) sorts the documents according to a naive scoring formula: RRFscore(d) = Σ 1/(k + rank_i(d)), where k is a constant (typically 60) that mitigates the impact of high rankings by outlier systems."
    }, {
      chunk_id: "rrf-5",
      ordinal: 5,
      page: 3,
      text: "Despite its simplicity and the absence of any tuning parameters beyond k, RRF consistently outperforms more complex fusion methods such as CombMNZ and Condorcet across a range of TREC collections."
    }],
    "d-attn": [{
      chunk_id: "attn-1",
      ordinal: 1,
      page: 2,
      text: "The Transformer relies entirely on self-attention to compute representations of its input and output without using sequence-aligned RNNs or convolution, enabling significantly more parallelization."
    }]
  };

  // Zotero-style notes / annotations per doc
  const NOTES = {
    "d-react": {
      collection: "Zotero Sync",
      annotations: [{
        id: "a1",
        color: "purple",
        page: 1,
        text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions pertaining to a task in an interleaved manner.",
        comment: ""
      }, {
        id: "a2",
        color: "yellow",
        page: 6,
        text: "ReAct outperforms imitation and reinforcement learning methods by an absolute success rate of 34% and 10% respectively.",
        comment: "key result — compare with CoT baseline"
      }, {
        id: "a3",
        color: "green",
        page: 3,
        text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions.",
        comment: ""
      }],
      notes: [{
        id: "n1",
        body: "核心贡献：交替生成 reasoning trace 和 action，比纯 CoT 或纯 action 都强。",
        linked: false
      }, {
        id: "n2",
        body: "与 ToolFormer 的区别在于 ReAct 不需要 finetune，zero-shot 即可。",
        linked: false
      }]
    }
  };
  const GRAPH = {
    nodes: [{
      id: "n1",
      name: "ReAct",
      type: "Method",
      degree: 5,
      x: 0.5,
      y: 0.32
    }, {
      id: "n2",
      name: "Chain-of-Thought",
      type: "Method",
      degree: 3,
      x: 0.24,
      y: 0.2
    }, {
      id: "n3",
      name: "ALFWorld",
      type: "Dataset",
      degree: 2,
      x: 0.78,
      y: 0.22
    }, {
      id: "n4",
      name: "WebShop",
      type: "Dataset",
      degree: 2,
      x: 0.82,
      y: 0.5
    }, {
      id: "n5",
      name: "Tool Use",
      type: "Concept",
      degree: 4,
      x: 0.3,
      y: 0.62
    }, {
      id: "n6",
      name: "LLM",
      type: "Concept",
      degree: 6,
      x: 0.52,
      y: 0.66
    }],
    edges: [{
      source: "n1",
      target: "n2",
      relation: "extends"
    }, {
      source: "n1",
      target: "n3",
      relation: "evaluated on"
    }, {
      source: "n1",
      target: "n4",
      relation: "evaluated on"
    }, {
      source: "n1",
      target: "n5",
      relation: "uses"
    }, {
      source: "n1",
      target: "n6",
      relation: "built on"
    }, {
      source: "n5",
      target: "n6",
      relation: "augments"
    }, {
      source: "n2",
      target: "n6",
      relation: "prompts"
    }]
  };
  window.KRMock = {
    COLLECTIONS,
    DOCS,
    CHUNKS,
    NOTES,
    GRAPH
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/mock.jsx", error: String((e && e.message) || e) }); }

// web/ui.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Knowledge Repository · Shared UI primitives (Heptabase-style, light-first).
   All visual values come from web/tokens.css custom properties. */
(function () {
  const Icon = window.KRIcon;

  /* ── Tooltip wrapper: shows label on hover (used by frameless icon buttons) ── */
  function Tip({
    label,
    side = "bottom",
    children
  }) {
    const [show, setShow] = React.useState(false);
    const pos = side === "bottom" ? {
      top: "calc(100% + 7px)",
      left: "50%",
      transform: "translateX(-50%)"
    } : side === "left" ? {
      right: "calc(100% + 7px)",
      top: "50%",
      transform: "translateY(-50%)"
    } : {
      bottom: "calc(100% + 7px)",
      left: "50%",
      transform: "translateX(-50%)"
    };
    return /*#__PURE__*/React.createElement("span", {
      style: {
        position: "relative",
        display: "inline-flex"
      },
      onMouseEnter: () => setShow(true),
      onMouseLeave: () => setShow(false)
    }, children, show && label && /*#__PURE__*/React.createElement("span", {
      style: {
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
        letterSpacing: ".01em"
      }
    }, label));
  }

  /* ── Framed button (primary actions, top-right tabs) ── */
  function Button({
    variant = "primary",
    size = "md",
    active = false,
    loading = false,
    disabled = false,
    children,
    style,
    ...rest
  }) {
    const sizes = {
      sm: {
        fontSize: 12,
        padding: "5px 10px",
        height: 28
      },
      md: {
        fontSize: 13,
        padding: "7px 13px",
        height: 32
      }
    };
    const variants = {
      primary: {
        background: "var(--accent)",
        color: "var(--accent-fg)",
        border: "1px solid transparent",
        boxShadow: "0 1px 2px rgba(22,23,26,.12)"
      },
      outline: {
        background: "var(--surface)",
        color: "var(--fg)",
        border: "1px solid var(--border-strong)"
      },
      ghost: {
        background: "transparent",
        color: "var(--fg-muted)",
        border: "1px solid transparent"
      },
      danger: {
        background: "var(--danger)",
        color: "#fff",
        border: "1px solid transparent"
      },
      tab: {
        background: active ? "var(--surface)" : "var(--surface)",
        color: active ? "var(--accent)" : "var(--fg)",
        border: `1px solid ${active ? "var(--accent-border)" : "var(--border-strong)"}`,
        boxShadow: active ? "0 0 0 3px var(--ring)" : "var(--shadow-card)"
      }
    };
    const dis = disabled || loading;
    return /*#__PURE__*/React.createElement("button", _extends({
      disabled: dis,
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        fontFamily: "var(--font-sans)",
        fontWeight: 500,
        lineHeight: 1,
        borderRadius: "var(--radius-md)",
        cursor: dis ? "not-allowed" : "pointer",
        opacity: dis ? 0.55 : 1,
        userSelect: "none",
        transition: "background .14s, border-color .14s, box-shadow .14s, transform .08s",
        ...sizes[size],
        ...variants[variant],
        ...style
      },
      onMouseDown: e => {
        if (!dis) e.currentTarget.style.transform = "scale(0.975)";
      },
      onMouseUp: e => {
        e.currentTarget.style.transform = "scale(1)";
      },
      onMouseLeave: e => {
        e.currentTarget.style.transform = "scale(1)";
      }
    }, rest), loading && /*#__PURE__*/React.createElement("span", {
      style: {
        width: 12,
        height: 12,
        border: "2px solid currentColor",
        borderTopColor: "transparent",
        borderRadius: "50%",
        animation: "spin .6s linear infinite"
      }
    }), children);
  }

  /* ── Frameless icon button with hover tooltip (panel header controls) ── */
  function IconBtn({
    name,
    label,
    size = 16,
    active = false,
    side = "bottom",
    onClick,
    style,
    children
  }) {
    const [hover, setHover] = React.useState(false);
    return /*#__PURE__*/React.createElement(Tip, {
      label: label,
      side: side
    }, /*#__PURE__*/React.createElement("button", {
      onClick: onClick,
      "aria-label": label,
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      style: {
        width: 26,
        height: 26,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        border: "none",
        borderRadius: "var(--radius-sm)",
        cursor: "pointer",
        background: active ? "var(--accent-soft)" : hover ? "var(--bg-inset)" : "transparent",
        color: active ? "var(--accent)" : hover ? "var(--fg)" : "var(--fg-subtle)",
        transition: "background .12s, color .12s",
        ...style
      }
    }, children || /*#__PURE__*/React.createElement(Icon, {
      name: name,
      size: size
    })));
  }

  /* ── Tag pill ── */
  function Tag({
    label,
    accent = false,
    onRemove,
    onClick,
    style
  }) {
    return /*#__PURE__*/React.createElement("span", {
      onClick: onClick,
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: accent ? "var(--accent-soft)" : "var(--bg-inset)",
        border: `1px solid ${accent ? "var(--accent-border)" : "transparent"}`,
        color: accent ? "var(--accent)" : "var(--fg-muted)",
        borderRadius: "var(--radius-pill)",
        padding: "1px 9px",
        fontSize: 11,
        fontWeight: 500,
        lineHeight: "19px",
        whiteSpace: "nowrap",
        cursor: onClick ? "pointer" : "default",
        ...style
      }
    }, label, onRemove && /*#__PURE__*/React.createElement("button", {
      onClick: e => {
        e.stopPropagation();
        onRemove();
      },
      style: {
        background: "none",
        border: "none",
        padding: 0,
        cursor: "pointer",
        color: "inherit",
        opacity: .55,
        fontSize: 13,
        lineHeight: 1
      }
    }, "\xD7"));
  }

  /* ── Badge ── */
  function Badge({
    tone = "neutral",
    children,
    style
  }) {
    const t = {
      neutral: {
        bg: "var(--bg-inset)",
        fg: "var(--fg-muted)"
      },
      accent: {
        bg: "var(--accent-soft)",
        fg: "var(--accent)"
      },
      info: {
        bg: "var(--info-soft)",
        fg: "var(--info)"
      },
      ok: {
        bg: "var(--ok-soft)",
        fg: "var(--ok)"
      },
      warn: {
        bg: "var(--warn-soft)",
        fg: "var(--warn)"
      },
      danger: {
        bg: "var(--danger-soft)",
        fg: "var(--danger)"
      },
      violet: {
        bg: "var(--ann-purple-bg)",
        fg: "var(--ann-purple)"
      }
    }[tone];
    return /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10.5,
        fontWeight: 600,
        padding: "1.5px 7px",
        borderRadius: "var(--radius-sm)",
        background: t.bg,
        color: t.fg,
        whiteSpace: "nowrap",
        ...style
      }
    }, children);
  }

  /* ── Toggle ── */
  function Toggle({
    checked,
    onChange,
    disabled,
    label,
    style
  }) {
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      role: "switch",
      "aria-checked": checked,
      disabled: disabled,
      onClick: () => !disabled && onChange && onChange(!checked),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        background: "none",
        border: "none",
        padding: 0,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? .5 : 1,
        fontFamily: "var(--font-sans)",
        fontSize: 13,
        color: "var(--fg)",
        ...style
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: "relative",
        width: 32,
        height: 18,
        borderRadius: 999,
        background: checked ? "var(--accent)" : "var(--bg-inset)",
        border: `1.5px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
        transition: "background .15s, border-color .15s",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        top: 2,
        left: checked ? 14 : 2,
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: checked ? "#fff" : "var(--fg-subtle)",
        transition: "left .15s"
      }
    })), label && /*#__PURE__*/React.createElement("span", null, label));
  }

  /* ── Select (custom dropdown) ── */
  function Select({
    value,
    onChange,
    options,
    size = "sm",
    style
  }) {
    const [open, setOpen] = React.useState(false);
    const ref = React.useRef(null);
    const h = size === "sm" ? 30 : 34,
      fs = size === "sm" ? 12 : 13;
    const sel = options.find(o => o.value === value);
    React.useEffect(() => {
      if (!open) return;
      const f = e => {
        if (ref.current && !ref.current.contains(e.target)) setOpen(false);
      };
      document.addEventListener("mousedown", f);
      return () => document.removeEventListener("mousedown", f);
    }, [open]);
    return /*#__PURE__*/React.createElement("div", {
      ref: ref,
      style: {
        position: "relative",
        display: "inline-block",
        ...style
      }
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      onClick: () => setOpen(v => !v),
      style: {
        height: h,
        paddingLeft: 11,
        paddingRight: 28,
        width: "100%",
        textAlign: "left",
        background: "var(--surface)",
        border: `1px solid ${open ? "var(--accent)" : "var(--border-strong)"}`,
        borderRadius: "var(--radius-md)",
        color: "var(--fg)",
        fontSize: fs,
        fontWeight: 500,
        fontFamily: "var(--font-sans)",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        position: "relative",
        boxShadow: open ? "0 0 0 3px var(--ring)" : "none",
        transition: "border-color .14s, box-shadow .14s"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, sel ? sel.label : value), /*#__PURE__*/React.createElement(Icon, {
      name: "chevD",
      size: 13,
      style: {
        position: "absolute",
        right: 9,
        color: "var(--fg-subtle)",
        transform: open ? "rotate(180deg)" : "none",
        transition: "transform .18s"
      }
    })), open && /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        top: "calc(100% + 5px)",
        left: 0,
        minWidth: "100%",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-pop)",
        padding: 4,
        zIndex: 700
      }
    }, options.map(o => {
      const a = o.value === value;
      return /*#__PURE__*/React.createElement("button", {
        key: o.value,
        onClick: () => {
          onChange && onChange(o.value);
          setOpen(false);
        },
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "6px 9px",
          borderRadius: "var(--radius-sm)",
          background: a ? "var(--accent-soft)" : "transparent",
          color: a ? "var(--accent)" : "var(--fg)",
          border: "none",
          cursor: "pointer",
          fontSize: fs,
          fontWeight: a ? 600 : 400,
          fontFamily: "var(--font-sans)",
          textAlign: "left",
          whiteSpace: "nowrap"
        },
        onMouseEnter: e => {
          if (!a) e.currentTarget.style.background = "var(--bg-inset)";
        },
        onMouseLeave: e => {
          if (!a) e.currentTarget.style.background = "transparent";
        }
      }, a ? /*#__PURE__*/React.createElement(Icon, {
        name: "check",
        size: 12
      }) : /*#__PURE__*/React.createElement("span", {
        style: {
          width: 12
        }
      }), o.label);
    })));
  }

  /* ── Panel shell: a Heptabase card with sticky header ── */
  function Panel({
    title,
    crumbs,
    right,
    children,
    style,
    bodyStyle,
    flush = false
  }) {
    return /*#__PURE__*/React.createElement("section", {
      style: {
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-card)",
        overflow: "hidden",
        ...style
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        height: 38,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "0 8px 0 13px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0,
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12.5
      }
    }, title && /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 650,
        color: "var(--heading)",
        letterSpacing: "-.01em"
      }
    }, title), crumbs && crumbs.map((c, i) => /*#__PURE__*/React.createElement(React.Fragment, {
      key: i
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--fg-subtle)"
      }
    }, "/"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: i === crumbs.length - 1 ? "var(--fg)" : "var(--fg-muted)",
        fontWeight: i === crumbs.length - 1 ? 600 : 400,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        maxWidth: 220,
        cursor: c.onClick ? "pointer" : "default"
      },
      onClick: c.onClick
    }, c.label || c)))), right && /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 2,
        flexShrink: 0
      }
    }, right)), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minHeight: 0,
        overflow: "auto",
        padding: flush ? 0 : 14,
        ...bodyStyle
      }
    }, children));
  }

  /* ── Modal overlay (large pop panels) ── */
  function Modal({
    title,
    icon,
    onClose,
    footer,
    children,
    width = 880,
    height = "84vh"
  }) {
    React.useEffect(() => {
      const f = e => {
        if (e.key === "Escape") onClose();
      };
      document.addEventListener("keydown", f);
      return () => document.removeEventListener("keydown", f);
    }, []);
    return /*#__PURE__*/React.createElement("div", {
      onClick: e => e.target === e.currentTarget && onClose(),
      style: {
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(22,23,26,.38)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        animation: "overlayIn .16s ease",
        padding: 24
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width,
        maxWidth: "94vw",
        height,
        maxHeight: "92vh",
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-pop)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        animation: "modalIn .2s cubic-bezier(.2,.7,.2,1)"
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        height: 52,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "0 14px 0 18px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)"
      }
    }, icon && /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        color: "var(--accent)"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 18
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontSize: 15,
        fontWeight: 650,
        color: "var(--heading)",
        letterSpacing: "-.01em"
      }
    }, title), /*#__PURE__*/React.createElement(IconBtn, {
      name: "x",
      label: "\u5173\u95ED",
      onClick: onClose
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minHeight: 0,
        overflow: "auto"
      }
    }, children), footer && /*#__PURE__*/React.createElement("footer", {
      style: {
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: 8,
        padding: "12px 18px",
        borderTop: "1px solid var(--border)",
        background: "var(--surface)"
      }
    }, footer)));
  }

  /* ── Section label ── */
  function Eyebrow({
    children,
    style
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: ".08em",
        textTransform: "uppercase",
        color: "var(--fg-subtle)",
        ...style
      }
    }, children);
  }
  function fmtSize(b) {
    if (!b) return "—";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    return (b / 1048576).toFixed(1) + " MB";
  }
  window.KRUI = {
    Tip,
    Button,
    IconBtn,
    Tag,
    Badge,
    Toggle,
    Select,
    Panel,
    Modal,
    Eyebrow,
    fmtSize
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "web/ui.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.QuotaBar = __ds_scope.QuotaBar;

__ds_ns.StatusChip = __ds_scope.StatusChip;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Tag = __ds_scope.Tag;

__ds_ns.Toggle = __ds_scope.Toggle;

})();
