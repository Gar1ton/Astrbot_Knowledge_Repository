"use client";

import React from "react";
import { useI18n } from "@/lib/i18n";
import type { ZoteroMeta } from "@/lib/api";

export type MetaDraft = Partial<ZoteroMeta> & { title?: string };

export function MetaRow({
  k,
  v,
  mono,
  link,
}: {
  k: string;
  v?: string | null;
  mono?: boolean;
  link?: boolean;
}) {
  if (!v) return null;
  return (
    <div style={{ display: "flex", gap: 10, padding: "3px 0" }}>
      <span style={{ width: 58, flexShrink: 0, fontSize: 11, color: "var(--fg-subtle)" }}>{k}</span>
      <span
        style={{
          flex: 1,
          fontSize: 11.5,
          color: link ? "var(--accent)" : "var(--fg)",
          fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          wordBreak: "break-word",
          lineHeight: 1.45,
        }}
      >
        {v}
      </span>
    </div>
  );
}

export function MetaEditForm({
  draft,
  saving,
  onChange,
  onSave,
  onCancel,
}: {
  draft: MetaDraft;
  saving: boolean;
  onChange: (d: MetaDraft) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const fieldStyle: React.CSSProperties = {
    width: "100%",
    fontSize: 12,
    fontFamily: "var(--font-sans)",
    color: "var(--fg)",
    background: "var(--bg-inset)",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-sm)",
    padding: "4px 7px",
    outline: "none",
    boxSizing: "border-box",
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 10.5,
    color: "var(--fg-subtle)",
    marginBottom: 3,
    display: "block",
  };
  const rowStyle: React.CSSProperties = { marginBottom: 8 };
  const creatorsValue = Array.isArray(draft.creators)
    ? draft.creators.join("\n")
    : (draft.creators as string | undefined) ?? "";

  return (
    <div
      style={{
        background: "var(--bg-inset)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-md)",
        padding: "10px 12px",
        marginBottom: 12,
      }}
    >
      <div style={rowStyle}>
        <label style={labelStyle}>{t("note_meta_title")}</label>
        <input
          style={fieldStyle}
          value={draft.title ?? ""}
          onChange={(e) => onChange({ ...draft, title: e.target.value })}
        />
      </div>
      <div style={rowStyle}>
        <label style={labelStyle}>{t("note_meta_authors")} ({t("note_meta_authors_hint")})</label>
        <textarea
          style={{ ...fieldStyle, resize: "none", lineHeight: 1.5 }}
          rows={3}
          value={creatorsValue}
          onChange={(e) => onChange({ ...draft, creators: e.target.value as unknown as string[] })}
        />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        <div>
          <label style={labelStyle}>{t("note_meta_year")}</label>
          <input style={fieldStyle} value={draft.year ?? ""} onChange={(e) => onChange({ ...draft, year: e.target.value })} />
        </div>
        <div>
          <label style={labelStyle}>{t("note_meta_journal")}</label>
          <input style={fieldStyle} value={draft.venue ?? ""} onChange={(e) => onChange({ ...draft, venue: e.target.value })} />
        </div>
      </div>
      <div style={rowStyle}>
        <label style={labelStyle}>DOI</label>
        <input style={{ ...fieldStyle, fontFamily: "var(--font-mono)" }} value={draft.doi ?? ""} onChange={(e) => onChange({ ...draft, doi: e.target.value })} />
      </div>
      <div style={rowStyle}>
        <label style={labelStyle}>{t("documents_abstract")}</label>
        <textarea
          style={{ ...fieldStyle, resize: "none", lineHeight: 1.55 }}
          rows={4}
          value={draft.abstract ?? ""}
          onChange={(e) => onChange({ ...draft, abstract: e.target.value })}
        />
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
        <button
          onClick={onCancel}
          style={{
            fontSize: 11, padding: "4px 10px", borderRadius: "var(--radius-pill)",
            border: "1px solid var(--border)", background: "transparent",
            color: "var(--fg-muted)", cursor: "pointer", fontFamily: "var(--font-sans)",
          }}
        >
          {t("btn_cancel")}
        </button>
        <button
          onClick={onSave}
          disabled={saving}
          style={{
            fontSize: 11, padding: "4px 10px", borderRadius: "var(--radius-pill)",
            border: "none", background: "var(--accent)", color: "var(--accent-fg)",
            cursor: saving ? "wait" : "pointer", fontWeight: 600, fontFamily: "var(--font-sans)",
            opacity: saving ? 0.7 : 1,
          }}
        >
          {t("btn_save")}
        </button>
      </div>
    </div>
  );
}
