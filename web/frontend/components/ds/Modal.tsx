"use client";
import React, { useEffect } from "react";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { useI18n } from "@/lib/i18n";

interface ModalProps {
  title: string;
  icon?: string;
  onClose: () => void;
  footer?: React.ReactNode;
  children: React.ReactNode;
  width?: number | string;
  height?: number | string;
  style?: React.CSSProperties;
  contentStyle?: React.CSSProperties;
}

export function Modal({ title, icon, onClose, footer, children, width = 880, height = "84vh", style, contentStyle }: ModalProps) {
  const { t } = useI18n();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(22,23,26,.38)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        animation: "overlayIn .16s ease",
        padding: 24,
      }}
    >
      <div
        style={{
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
          animation: "modalIn .2s cubic-bezier(.2,.7,.2,1)",
          ...style,
        }}
      >
        <header
          style={{
            height: 52,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "0 14px 0 18px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          {icon && (
            <span style={{ display: "inline-flex", color: "var(--accent)" }}>
              <Icon name={icon} size={18} />
            </span>
          )}
          <span
            style={{
              flex: 1,
              fontSize: 15,
              fontWeight: 650,
              color: "var(--heading)",
              letterSpacing: "-.01em",
            }}
          >
            {title}
          </span>
          <IconButton name="x" label={t("modal_close")} onClick={onClose} />
        </header>
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", ...contentStyle }}>{children}</div>
        {footer && (
          <footer
            style={{
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              gap: 8,
              padding: "12px 18px",
              borderTop: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
