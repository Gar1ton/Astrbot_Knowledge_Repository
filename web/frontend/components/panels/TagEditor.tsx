"use client";

import React, { useState } from "react";
import { Eyebrow } from "@/components/ds/Eyebrow";
import { Icon } from "@/components/ds/Icon";
import { Tag } from "@/components/ds/Tag";
import { useI18n } from "@/lib/i18n";

function normalizeTags(tags: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of tags) {
    const tag = raw.trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
  }
  return out;
}

interface TagEditorProps {
  tags: string[];
  readOnly: boolean;
  editing: boolean;
  saving: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (tags: string[]) => void;
}

export function TagEditor({
  tags,
  readOnly,
  editing,
  saving,
  onEdit,
  onCancel,
  onSave,
}: TagEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<string[]>(tags);
  const [input, setInput] = useState("");

  function resetDraft() {
    setDraft(tags);
    setInput("");
  }

  function addInputTags() {
    const additions = input.split(",").map((s) => s.trim()).filter(Boolean);
    if (additions.length === 0) return;
    setDraft((current) => normalizeTags([...current, ...additions]));
    setInput("");
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addInputTags();
    } else if (e.key === "Escape") {
      onCancel();
    } else if (e.key === "Backspace" && !input) {
      setDraft((current) => current.slice(0, -1));
    }
  }

  const titleRow = (
    <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "18px 0 8px" }}>
      <Eyebrow style={{ margin: 0, flex: 1 }}>{t("note_tags")}</Eyebrow>
      {readOnly ? (
        <span
          style={{
            fontSize: 10,
            color: "var(--fg-subtle)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-pill)",
            padding: "1px 7px",
            background: "var(--bg-inset)",
            lineHeight: "17px",
          }}
        >
          {t("note_tags_readonly_zotero")}
        </span>
      ) : !editing ? (
        <button
          type="button"
          onClick={() => {
            resetDraft();
            onEdit();
          }}
          style={{
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--fg-muted)",
            borderRadius: "var(--radius-pill)",
            padding: "1px 8px",
            fontSize: 10.5,
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "var(--font-sans)",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            height: 22,
          }}
        >
          <Icon name="edit" size={11} />
          {tags.length > 0 ? t("note_tags_edit") : t("note_tags_add")}
        </button>
      ) : null}
    </div>
  );

  if (!editing) {
    return (
      <>
        {titleRow}
        {tags.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {tags.map((tag) => <Tag key={tag} label={tag} />)}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "var(--fg-subtle)", lineHeight: 1.5 }}>
            {readOnly ? t("note_tags_empty_readonly") : t("note_tags_empty")}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      {titleRow}
      <div
        style={{
          background: "var(--bg-inset)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--radius-md)",
          padding: "8px 9px",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 7 }}>
          {draft.map((tag) => (
            <Tag
              key={tag}
              label={tag}
              accent
              onRemove={() => setDraft((current) => current.filter((item) => item !== tag))}
            />
          ))}
          {draft.length === 0 && (
            <span style={{ fontSize: 11, color: "var(--fg-subtle)", lineHeight: "21px" }}>
              {t("note_tags_empty")}
            </span>
          )}
        </div>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onBlur={addInputTags}
          onKeyDown={handleInputKeyDown}
          placeholder={t("note_tags_input_placeholder")}
          disabled={saving}
          style={{
            width: "100%",
            height: 28,
            boxSizing: "border-box",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            background: "var(--surface)",
            color: "var(--fg)",
            padding: "0 8px",
            fontSize: 11.5,
            fontFamily: "var(--font-sans)",
            outline: "none",
          }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 8 }}>
          <button
            type="button"
            onClick={() => {
              resetDraft();
              onCancel();
            }}
            disabled={saving}
            style={{
              fontSize: 11, padding: "4px 10px", borderRadius: "var(--radius-pill)",
              border: "1px solid var(--border)", background: "transparent",
              color: "var(--fg-muted)", cursor: saving ? "wait" : "pointer",
              fontFamily: "var(--font-sans)",
            }}
          >
            {t("btn_cancel")}
          </button>
          <button
            type="button"
            onClick={() => onSave(normalizeTags([...draft, input]))}
            disabled={saving}
            style={{
              fontSize: 11, padding: "4px 10px", borderRadius: "var(--radius-pill)",
              border: "none", background: "var(--accent)", color: "var(--accent-fg)",
              cursor: saving ? "wait" : "pointer", fontWeight: 600,
              fontFamily: "var(--font-sans)", opacity: saving ? 0.7 : 1,
            }}
          >
            {t("note_tags_save")}
          </button>
        </div>
      </div>
    </>
  );
}
