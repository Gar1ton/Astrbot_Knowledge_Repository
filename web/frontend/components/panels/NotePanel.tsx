"use client";
import React, { useEffect, useState } from "react";
import { Eyebrow } from "@/components/ds/Eyebrow";
import { Icon } from "@/components/ds/Icon";
import { IconButton } from "@/components/ds/IconButton";
import { MetaEditForm, MetaRow, type MetaDraft } from "@/components/panels/DocumentMeta";
import { TagEditor } from "@/components/panels/TagEditor";
import { useToast } from "@/components/ui/Toast";
import { useConsole } from "@/lib/ConsoleContext";
import {
  createDocumentNote,
  getDocumentAnnotations,
  getDocumentNotes,
  listDocuments,
  patchDocument,
  syncZoteroPull,
  updateDocumentMeta,
  type DocumentNote,
  type KrDocument,
  type ZoteroAnnotation,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// ─── Annotation color map ─────────────────────────────────────

const ANN_COLORS = {
  purple: { bar: "var(--ann-purple)", bg: "var(--ann-purple-bg)", bd: "var(--ann-purple-border)" },
  yellow: { bar: "var(--ann-yellow)", bg: "var(--ann-yellow-bg)", bd: "var(--ann-yellow-border)" },
  green:  { bar: "var(--ann-green)",  bg: "var(--ann-green-bg)",  bd: "var(--ann-green-border)"  },
  red:    { bar: "var(--ann-red)",    bg: "var(--ann-red-bg)",    bd: "var(--ann-red-border)"    },
  blue:   { bar: "var(--ann-blue)",   bg: "var(--ann-blue-bg)",   bd: "var(--ann-blue-border)"   },
} as const;

type AnnColor = keyof typeof ANN_COLORS;

interface Annotation {
  id: string;
  text: string;
  comment?: string;
  color: AnnColor;
  page?: number;
}

interface LocalStoredNote {
  id: string;
  body?: string;
  content?: string;
  linked?: boolean;
  created_at: string;
  updated_at?: string;
}

const ZOTERO_COLOR_MAP: Record<string, AnnColor> = {
  "#a28ae5": "purple",
  "#ffd400": "yellow",
  "#5fb236": "green",
  "#ff6666": "red",
  "#2ea8e5": "blue",
};

function annotationColor(raw?: string): AnnColor {
  if (!raw) return "yellow";
  const normalized = raw.toLowerCase();
  return ZOTERO_COLOR_MAP[normalized] ?? "yellow";
}

function toAnnotation(a: ZoteroAnnotation): Annotation {
  return {
    id: a.id,
    text: a.text,
    comment: a.comment,
    color: annotationColor(a.color),
    page: a.page,
  };
}

function toDocumentNote(n: LocalStoredNote, docId: string): DocumentNote {
  const now = new Date().toISOString();
  const content = n.content ?? n.body ?? "";
  return {
    id: n.id,
    scope_type: "document",
    scope_key: docId,
    doc_id: docId,
    content,
    body: content,
    linked: n.linked,
    created_at: n.created_at ?? now,
    updated_at: n.updated_at ?? n.created_at ?? now,
  };
}

// ─── NotePanel ────────────────────────────────────────────────

export function NotePanel({ docId }: { docId: string }) {
  const { setNoteDocId, setSelectedDocId, selectedCollection } = useConsole();
  const { toast } = useToast();
  const { t, lang } = useI18n();
  const [doc, setDoc] = useState<KrDocument | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [notes, setNotes] = useState<DocumentNote[]>([]);
  const [newNote, setNewNote] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [editingMeta, setEditingMeta] = useState(false);
  const [metaDraft, setMetaDraft] = useState<MetaDraft>({});
  const [savingMeta, setSavingMeta] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [savingTags, setSavingTags] = useState(false);

  async function handleZoteroSync() {
    if (syncing) return;
    setSyncing(true);
    try { await syncZoteroPull(true); } catch { /* ignore */ } finally { setSyncing(false); }
  }

  function handleBack() {
    setSelectedDocId(null);
    setNoteDocId(null);
  }

  function openMetaEdit() {
    const m = doc?.zotero_meta;
    setMetaDraft({
      title: doc?.title ?? "",
      creators: m?.creators ?? [],
      year: m?.year ?? "",
      venue: m?.venue ?? "",
      doi: m?.doi ?? "",
      abstract: m?.abstract ?? "",
    });
    setEditingMeta(true);
  }

  async function handleSaveMeta() {
    if (!doc) return;
    setSavingMeta(true);
    try {
      const payload: MetaDraft = {
        ...metaDraft,
        creators: typeof metaDraft.creators === "string"
          ? (metaDraft.creators as string).split("\n").map((s) => s.trim()).filter(Boolean)
          : (metaDraft.creators ?? []),
      };
      const updated = await updateDocumentMeta(docId, payload);
      setDoc(updated);
      setEditingMeta(false);
    } catch { /* ignore */ } finally {
      setSavingMeta(false);
    }
  }

  async function handleSaveTags(tags: string[]) {
    if (!doc) return;
    setSavingTags(true);
    try {
      const updated = await patchDocument(doc.doc_id, { tags });
      setDoc(updated);
      setEditingTags(false);
      toast(t("note_tags_saved"), "ok");
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : t("error_generic"), "error");
    } finally {
      setSavingTags(false);
    }
  }

  const colName = selectedCollection?.replace(/^(z:|l:|lr:)/, "");

  useEffect(() => {
    if (!colName) return;
    listDocuments({ collection: colName })
      .then((docs) => {
        const found = docs.find((d) => d.doc_id === docId);
        setDoc(found ?? null);
      })
      .catch(() => {});
  }, [docId, colName]);

  useEffect(() => {
    getDocumentAnnotations(docId)
      .then((data) => setAnnotations(data.map(toAnnotation)))
      .catch(() => {});
  }, [docId]);

  // Try notes endpoint, fallback to localStorage
  useEffect(() => {
    const lsKey = `kr_notes_doc_${docId}`;
    (async () => {
      try {
        setNotes(await getDocumentNotes(docId));
        return;
      } catch { /* ignore */ }
      const stored = JSON.parse(localStorage.getItem(lsKey) ?? "[]") as LocalStoredNote[];
      setNotes(stored.map((n) => toDocumentNote(n, docId)));
    })();
  }, [docId]);

  async function handleAddNote() {
    const body = newNote.trim();
    if (!body) return;
    const now = new Date().toISOString();
    const note: DocumentNote = {
      id: crypto.randomUUID(),
      scope_type: "document",
      scope_key: docId,
      doc_id: docId,
      content: body,
      body,
      created_at: now,
      updated_at: now,
    };
    try {
      const data = await createDocumentNote(docId, body);
      setNotes((prev) => [data, ...prev]);
      setNewNote(""); setAddingNote(false);
      return;
    } catch { /* ignore */ }
    // localStorage fallback
    const updated = [note, ...notes];
    setNotes(updated);
    const lsKey = `kr_notes_doc_${docId}`;
    localStorage.setItem(lsKey, JSON.stringify(updated));
    setNewNote(""); setAddingNote(false);
  }

  const meta = doc?.zotero_meta;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-card)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <header
        style={{
          height: 38,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "0 8px 0 13px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span style={{ fontSize: 12.5, fontWeight: 650, color: "var(--heading)" }}>{t("panel_note")}</span>
        <span style={{ color: "var(--fg-subtle)" }}>/</span>
        <span
          style={{
            flex: 1,
            fontSize: 12,
            color: "var(--fg-muted)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {doc ? (doc.origin === "zotero" ? t("file_zotero_sync") : t("note_source_local")) : t("panel_loading")}
        </span>
        {doc?.origin === "local" && !editingMeta && (
          <IconButton name="edit" label={t("note_edit_meta")} onClick={openMetaEdit} />
        )}
        <IconButton name="sync" label={t("file_action_zotero_sync")} onClick={handleZoteroSync} active={syncing} />
        <button
          onClick={handleBack}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
            height: 24,
            padding: "0 8px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border-strong)",
            background: "var(--surface)",
            boxShadow: "var(--shadow-card)",
            cursor: "pointer",
            fontSize: 11,
            fontWeight: 600,
            color: "var(--fg)",
            fontFamily: "var(--font-sans)",
          }}
        >
          <Icon name="chevL" size={11} />
          {t("note_back_to_list")}
        </button>
      </header>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "14px 14px 30px" }}>
        {!doc ? (
          <div style={{ padding: 24, textAlign: "center", fontSize: 12, color: "var(--fg-subtle)" }}>
            {t("panel_loading")}
          </div>
        ) : (
          <>
            <div
              style={{
                fontSize: 14.5,
                fontWeight: 700,
                color: "var(--heading)",
                lineHeight: 1.35,
                marginBottom: 12,
              }}
            >
              {doc.title ?? doc.filename ?? t("panel_untitled")}
            </div>

            {editingMeta ? (
              <MetaEditForm
                draft={metaDraft}
                saving={savingMeta}
                onChange={setMetaDraft}
                onSave={handleSaveMeta}
                onCancel={() => setEditingMeta(false)}
              />
            ) : (
              <>
                {meta?.creators && meta.creators.length > 0 && (
                  <MetaRow k={t("note_meta_authors")} v={meta.creators.join(", ")} />
                )}
                <MetaRow k={t("note_meta_year")} v={meta?.year ? String(meta.year) : undefined} />
                <MetaRow k={t("note_meta_journal")} v={meta?.venue} />
                <MetaRow k="DOI" v={meta?.doi} link mono />
                <MetaRow k={t("note_meta_type")} v={meta?.item_type} />
                <MetaRow k="Doc ID" v={doc.doc_id} mono />
              </>
            )}

            <TagEditor
              tags={doc.tags}
              readOnly={doc.origin === "zotero" || Boolean(doc.read_only)}
              editing={editingTags}
              saving={savingTags}
              onEdit={() => setEditingTags(true)}
              onCancel={() => setEditingTags(false)}
              onSave={handleSaveTags}
            />

            {/* Annotations */}
            <Eyebrow style={{ margin: "20px 0 8px" }}>
              {t("note_annotations", { n: annotations.length })}
            </Eyebrow>
            {annotations.length === 0 ? (
              <div
                style={{
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  background: "var(--bg-inset)",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginBottom: 8 }}>
                  {t("note_annotation_empty")}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(Object.entries(ANN_COLORS) as [AnnColor, (typeof ANN_COLORS)[AnnColor]][]).map(
                    ([color, s]) => (
                      <span
                        key={color}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 10.5,
                          color: "var(--fg-muted)",
                          padding: "2px 7px",
                          borderRadius: "var(--radius-pill)",
                          background: s.bg,
                          border: `1px solid ${s.bd}`,
                        }}
                      >
                        <span
                          style={{
                            width: 7,
                            height: 7,
                            borderRadius: "50%",
                            background: s.bar,
                            flexShrink: 0,
                          }}
                        />
                        {color}
                      </span>
                    ),
                  )}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {annotations.map((a) => {
                  const c = ANN_COLORS[a.color] ?? ANN_COLORS.yellow;
                  return (
                    <div
                      key={a.id}
                      style={{
                        borderRadius: "var(--radius-md)",
                        border: `1px solid ${c.bd}`,
                        background: c.bg,
                        overflow: "hidden",
                        display: "flex",
                      }}
                    >
                      <span style={{ width: 3, flexShrink: 0, background: c.bar }} />
                      <div style={{ padding: "8px 10px", flex: 1, minWidth: 0 }}>
                        <p style={{ margin: 0, fontSize: 12, lineHeight: 1.55, color: "var(--fg)" }}>
                          {a.text}
                        </p>
                        {a.comment && (
                          <p
                            style={{
                              margin: "6px 0 0",
                              fontSize: 11,
                              fontStyle: "italic",
                              fontWeight: 600,
                              color: c.bar,
                              lineHeight: 1.45,
                            }}
                          >
                            {a.comment}
                          </p>
                        )}
                        {a.page != null && (
                          <div
                            style={{
                              marginTop: 6,
                              fontSize: 10,
                              color: "var(--fg-subtle)",
                              fontFamily: "var(--font-mono)",
                            }}
                          >
                            {t("note_page_highlight", { page: a.page })}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Notes */}
            <div style={{ display: "flex", alignItems: "center", margin: "20px 0 8px" }}>
              <Eyebrow style={{ flex: 1 }}>{t("note_notes", { n: notes.length })}</Eyebrow>
              <IconButton name="plus" label={t("note_new")} onClick={() => setAddingNote(true)} />
            </div>

            {addingNote && (
              <div
                style={{
                  marginBottom: 8,
                  background: "var(--bg-inset)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: "var(--radius-md)",
                  padding: 10,
                }}
              >
                <textarea
                  autoFocus
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  placeholder={t("note_placeholder")}
                  rows={3}
                  style={{
                    width: "100%",
                    resize: "none",
                    border: "none",
                    outline: "none",
                    background: "transparent",
                    fontSize: 12,
                    lineHeight: 1.55,
                    fontFamily: "var(--font-sans)",
                    color: "var(--fg)",
                    boxShadow: "none",
                  }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 7 }}>
                  <button
                    onClick={() => { setAddingNote(false); setNewNote(""); }}
                    style={{
                      fontSize: 11,
                      padding: "4px 10px",
                      borderRadius: "var(--radius-pill)",
                      border: "1px solid var(--border)",
                      background: "transparent",
                      color: "var(--fg-muted)",
                      cursor: "pointer",
                      fontFamily: "var(--font-sans)",
                    }}
                  >
                    {t("btn_cancel")}
                  </button>
                  <button
                    onClick={handleAddNote}
                    style={{
                      fontSize: 11,
                      padding: "4px 10px",
                      borderRadius: "var(--radius-pill)",
                      border: "none",
                      background: "var(--accent)",
                      color: "var(--accent-fg)",
                      cursor: "pointer",
                      fontWeight: 600,
                      fontFamily: "var(--font-sans)",
                    }}
                  >
                    {t("btn_save")}
                  </button>
                </div>
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {notes.map((n) => (
                <div
                  key={n.id}
                  style={{
                    padding: "9px 11px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--border)",
                    background: "var(--surface)",
                  }}
                >
                  <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: "var(--fg)" }}>
                    {n.content || n.body}
                  </p>
                  {n.linked && (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        marginTop: 6,
                        fontSize: 10.5,
                        color: "var(--accent)",
                      }}
                    >
                      <Icon name="link" size={11} /> {t("note_from_chat")}
                    </div>
                  )}
                  {n.created_at && (
                    <div
                      style={{
                        marginTop: 4,
                        fontSize: 10,
                        color: "var(--fg-subtle)",
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {new Date(n.created_at).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US")}
                    </div>
                  )}
                </div>
              ))}
              {notes.length === 0 && !addingNote && (
                <div style={{ fontSize: 11.5, color: "var(--fg-subtle)" }}>
                  {t("note_empty")}
                </div>
              )}
            </div>

            {meta?.abstract && (
              <>
                <Eyebrow style={{ margin: "20px 0 8px" }}>{t("documents_abstract")}</Eyebrow>
                <p style={{ margin: 0, fontSize: 12, lineHeight: 1.7, color: "var(--fg-muted)" }}>
                  {meta.abstract}
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
