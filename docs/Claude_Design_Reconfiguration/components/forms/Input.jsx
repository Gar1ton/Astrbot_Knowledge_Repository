import React from "react";

/**
 * Input — single-line text field with warm surface and accent focus ring.
 * Sizes: sm (32px) | md (36px). Set `invalid` to paint a danger ring.
 * Pass `mono` for monospace content (IDs, model names, collection names).
 */
export function Input({
  size = "md",
  invalid = false,
  mono = false,
  style,
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  const heights = { sm: 32, md: 36 };
  const ringColor = invalid ? "var(--danger)" : "var(--accent)";

  return (
    <input
      onFocus={(e) => { setFocused(true); rest.onFocus && rest.onFocus(e); }}
      onBlur={(e) => { setFocused(false); rest.onBlur && rest.onBlur(e); }}
      style={{
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
        boxShadow: focused
          ? `0 0 0 3px ${invalid ? "color-mix(in srgb, var(--danger) 22%, transparent)" : "var(--ring)"}`
          : "none",
        transition: "border-color .15s, box-shadow .15s",
        ...style,
      }}
      {...rest}
    />
  );
}
