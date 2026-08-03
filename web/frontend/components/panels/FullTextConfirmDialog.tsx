"use client";
import React from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ds/Button";
import { useI18n } from "@/lib/i18n";
import { Z } from "@/lib/zLayers";
import type { FullTextConfirmation } from "@/lib/api";

/**
 * 全文检索的「超阈值」确认框。
 *
 * 触发条件由**后端**判定（`/api/ask` 返回 409 `fulltext_confirmation_required`），本组件
 * 只负责把 409 体里的数字如实展示出来——阈值与字符数都来自服务端，前端不复制这些规则。
 *
 * 视觉与 ChatPanel 的 GraphBuildDialog 对齐（同一面板里的两个确认框应当同款）。
 */
export function FullTextConfirmDialog({
  info,
  running,
  onConfirm,
  onCancel,
}: {
  info: FullTextConfirmation;
  running?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const nf = new Intl.NumberFormat();
  const rows: [string, string][] = [
    [t("chat_fulltext_doc"), info.title],
    [t("chat_fulltext_chars"), nf.format(info.total_chars)],
    [t("chat_fulltext_est_tokens"), `≈ ${nf.format(info.estimated_tokens)}`],
    [t("chat_fulltext_threshold"), nf.format(info.threshold_chars)],
  ];

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: Z.dialog,
      }}
      onClick={(e) => e.target === e.currentTarget && !running && onCancel()}
    >
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-3xl)",
          padding: 24,
          width: 410,
          boxShadow: "var(--shadow-pop)",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div>
          <h3 style={{ margin: "0 0 5px", fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
            {t("chat_fulltext_confirm_title")}
          </h3>
          <p style={{ margin: 0, fontSize: 11, lineHeight: 1.6, color: "var(--fg-muted)" }}>
            {t("chat_fulltext_confirm_body")}
          </p>
        </div>
        <div
          style={{
            background: "var(--bg-inset)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          {rows.map(([label, value], i) => (
            <div
              key={label}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                padding: "8px 14px",
                borderTop: i > 0 ? "1px solid var(--border)" : undefined,
              }}
            >
              <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>{label}</span>
              <span
                style={{
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                  color: "var(--fg)",
                  fontWeight: 600,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {value}
              </span>
            </div>
          ))}
        </div>
        {/* 诚实披露：超窗时这次生成会失败，不会悄悄截断成半篇答案。 */}
        <div
          style={{
            fontSize: 11,
            lineHeight: 1.6,
            color: "var(--warn)",
            background: "color-mix(in srgb, var(--warn) 10%, transparent)",
            border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
            borderRadius: 8,
            padding: "8px 12px",
          }}
        >
          {t("chat_fulltext_context_warning")}
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <Button variant="ghost" size="sm" disabled={running} onClick={onCancel}>
            {t("btn_cancel")}
          </Button>
          <Button size="sm" loading={running} onClick={onConfirm}>
            {t("chat_fulltext_confirm_btn")}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
