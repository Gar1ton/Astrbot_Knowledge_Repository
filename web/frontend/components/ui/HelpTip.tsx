"use client";

import React, { useState } from "react";

/**
 * 设置项标签旁的「?」问号角标。
 *
 * 为什么存在：LightRAG Core 等参数对非专家用户不够自解释，需就地给出简短说明，
 * 又不希望长描述常驻占用表单垂直空间。鼠标悬停 / 键盘聚焦 / 点击（触屏）即弹出解释气泡。
 * 复用 Select 的绝对定位浮层范式（var(--shadow-pop) + 高 z-index），随主题与强调色级联渲染。
 */
export function HelpTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <span
      style={{ position: "relative", display: "inline-flex", verticalAlign: "middle", marginLeft: 5 }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={text}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}
        style={{
          width: 15,
          height: 15,
          flexShrink: 0,
          borderRadius: "50%",
          border: "1px solid var(--border-strong)",
          background: open ? "var(--accent-soft)" : "var(--bg-inset)",
          color: open ? "var(--accent)" : "var(--fg-subtle)",
          fontSize: 10,
          fontWeight: 700,
          lineHeight: 1,
          cursor: "help",
          padding: 0,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "inherit",
          transition: "color .15s, background .15s, border-color .15s",
        }}
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            top: "calc(100% + 7px)",
            left: "50%",
            transform: "translateX(-50%)",
            width: "max-content",
            maxWidth: 230,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 9,
            boxShadow: "var(--shadow-pop)",
            padding: "9px 11px",
            fontSize: 11,
            lineHeight: 1.6,
            fontWeight: 400,
            color: "var(--fg-muted)",
            textAlign: "left",
            whiteSpace: "normal",
            zIndex: 700,
            pointerEvents: "none",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
