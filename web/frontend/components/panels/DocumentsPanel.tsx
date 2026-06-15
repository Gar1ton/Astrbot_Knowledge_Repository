"use client";
import React, { useEffect, useRef, useState } from "react";
import { Panel } from "@/components/ds/Panel";
import { Badge } from "@/components/ds/Badge";
import { Tag } from "@/components/ds/Tag";
import { Eyebrow } from "@/components/ds/Eyebrow";
import { IconButton } from "@/components/ds/IconButton";
import { Icon } from "@/components/ds/Icon";
import { useConsole } from "@/lib/ConsoleContext";
import {
  getDocumentAnnotations,
  KrDocument,
  listDocumentChunks,
  listDocuments,
  reextractDocument,
  ZoteroAnnotation,
} from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { PdfViewer } from "@/components/panels/PdfViewer";
import { useI18n } from "@/lib/i18n";
import { parseChunkText, ChunkTextPart } from "@/lib/chunkText";

// ─── Doc type badge ───────────────────────────────────────────

function ExtBadge({ ext }: { ext?: string }) {
  const e = ext?.toLowerCase() ?? "?";
  const isPdf = e === "pdf";
  return (
    <span
      style={{
        width: 30,
        height: 38,
        flexShrink: 0,
        borderRadius: 4,
        background: isPdf ? "var(--danger-soft)" : "var(--info-soft)",
        color: isPdf ? "var(--danger)" : "var(--info)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 8.5,
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        border: "1px solid color-mix(in srgb, currentColor 22%, transparent)",
      }}
    >
      {e}
    </span>
  );
}

// ─── DocRow ───────────────────────────────────────────────────

function DocRow({ doc, onOpen, onNote }: { doc: KrDocument; onOpen: () => void; onNote: () => void }) {
  const [hover, setHover] = useState(false);
  const { t } = useI18n();
  const meta = doc.zotero_meta;

  return (
    <div
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        gap: 12,
        padding: "13px 14px",
        borderRadius: "var(--radius-lg)",
        cursor: "pointer",
        background: hover ? "var(--surface-hover)" : "transparent",
        border: `1px solid ${hover ? "var(--border)" : "transparent"}`,
        transition: "background .12s, border-color .12s",
      }}
    >
      <ExtBadge ext={doc.ext} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13.5,
            fontWeight: 600,
            color: "var(--heading)",
            lineHeight: 1.35,
            marginBottom: 3,
          }}
        >
          {doc.title ?? doc.filename ?? t("panel_untitled")}
        </div>
        {meta?.creators && meta.creators.length > 0 && (
          <div
            style={{
              fontSize: 11.5,
              color: "var(--fg-muted)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {meta.creators.join(", ")}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
          {meta?.venue && (
            <span style={{ fontSize: 11, fontStyle: "italic", color: "var(--fg)" }}>
              {meta.venue}
            </span>
          )}
          {(meta?.year || doc.origin) && (
            <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
              {[meta?.year, meta?.item_type].filter(Boolean).join(" · ")}
            </span>
          )}
          {doc.lightrag_index_status?.status === "built" && (
            <Badge tone="violet">
              <Icon name="graph" size={10} /> LightRAG
            </Badge>
          )}
          <span style={{ flex: 1 }} />
          {doc.tags.slice(0, 3).map((t) => <Tag key={t} label={t} />)}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {hover && (
          <span
            onClick={(e) => { e.stopPropagation(); onNote(); }}
            title={t("documents_open_note")}
            style={{ cursor: "pointer", color: "var(--fg-subtle)", opacity: 0.7 }}
          >
            <Icon name="note" size={14} />
          </span>
        )}
        <span style={{ color: "var(--fg-subtle)", opacity: hover ? 1 : 0 }}>
          <Icon name="chevR" size={16} />
        </span>
      </div>
    </div>
  );
}

// ─── ListView ─────────────────────────────────────────────────

function ListView({
  docs,
  title,
  loading,
  onOpen,
  onNote,
}: {
  docs: KrDocument[];
  title: string;
  loading: boolean;
  onOpen: (doc: KrDocument) => void;
  onNote: (docId: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, padding: "4px 14px 10px" }}>
        <span
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: "var(--heading)",
            letterSpacing: "-.02em",
          }}
        >
          {title}
        </span>
        {!loading && (
          <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>· {t("documents_count", { n: docs.length })}</span>
        )}
      </div>
      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--fg-subtle)", fontSize: 13 }}>
          {t("panel_loading")}
        </div>
      ) : docs.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--fg-subtle)", fontSize: 13 }}>
          {t("documents_empty_collection")}
        </div>
      ) : (
        docs.map((d) => (
          <DocRow key={d.doc_id} doc={d} onOpen={() => onOpen(d)} onNote={() => onNote(d.doc_id)} />
        ))
      )}
    </div>
  );
}

// ─── ReadingView ──────────────────────────────────────────────

interface ChunkItem {
  chunk_id: string;
  ordinal: number;
  page?: number;
  text: string;
}

function ChunkHeading({ part }: { part: Extract<ChunkTextPart, { type: "heading" }> }) {
  const isThesis = part.kind === "thesis";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        flexWrap: "wrap",
        margin: "2px 0 7px",
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          minHeight: 20,
          padding: isThesis ? "2px 8px" : "1px 7px",
          borderRadius: "var(--radius-sm)",
          border: "1px solid var(--accent-border)",
          background: "var(--accent-soft)",
          color: "var(--accent)",
          fontFamily: "var(--font-mono)",
          fontSize: isThesis ? 12 : 10.5,
          fontWeight: 800,
          lineHeight: 1,
        }}
      >
        {part.label}
      </span>
      {part.title && (
        <span
          style={{
            color: "var(--heading)",
            fontSize: part.kind === "section" ? 14 : 13.5,
            fontWeight: part.kind === "subsection" ? 650 : 700,
            lineHeight: 1.35,
          }}
        >
          {part.title}
        </span>
      )}
    </div>
  );
}

function ChunkText({ text }: { text: string }) {
  const parts = parseChunkText(text);
  if (parts.length === 0) return null;

  return (
    <div style={{ fontSize: 13, lineHeight: 1.7, color: "var(--fg)" }}>
      {parts.map((part, index) => {
        if (part.type === "heading") {
          return (
            <div key={`${part.type}-${index}`} style={{ marginTop: index === 0 ? 0 : 12 }}>
              <ChunkHeading part={part} />
            </div>
          );
        }

        return (
          <p
            key={`${part.type}-${index}`}
            style={{
              margin: index === 0 ? 0 : "7px 0 0",
              color: "var(--fg)",
              whiteSpace: "pre-wrap",
            }}
          >
            {part.text}
          </p>
        );
      })}
    </div>
  );
}

function ReadingView({
  doc,
  mode,
  setMode,
}: {
  doc: KrDocument;
  mode: "md" | "pdf";
  setMode: (m: "md" | "pdf") => void;
}) {
  const { highlightedChunk, setHighlightedChunk } = useConsole();
  const { t } = useI18n();
  const { toast } = useToast();
  const chunkRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [annotations, setAnnotations] = useState<ZoteroAnnotation[]>([]);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [reextracting, setReextracting] = useState(false);
  const meta = doc.zotero_meta;

  async function handleReextract() {
    setReextracting(true);
    try {
      const result = await reextractDocument(doc.doc_id);
      toast(`重新提取完成：${result.chunk_count} 个 chunk`, "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : "重新提取失败", "error");
    } finally {
      setReextracting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setChunks([]);
    setAnnotations([]);
    setChunkLoading(true);
    Promise.allSettled([
      listDocumentChunks(doc.doc_id),
      getDocumentAnnotations(doc.doc_id),
    ]).then(([chunkResult, annotationResult]) => {
      if (cancelled) return;
      if (chunkResult.status === "fulfilled") setChunks(chunkResult.value);
      if (annotationResult.status === "fulfilled") setAnnotations(annotationResult.value);
    }).finally(() => {
      if (!cancelled) setChunkLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [doc.doc_id]);

  useEffect(() => {
    if (!highlightedChunk || highlightedChunk.docId !== doc.doc_id) return;
    const el = chunkRefs.current[highlightedChunk.chunkId];
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.style.animation = "none";
    void el.offsetWidth; // force reflow
    el.style.animation = "citeFlash 1.6s ease-out forwards";
    const timer = setTimeout(() => setHighlightedChunk(null), 1800);
    return () => clearTimeout(timer);
  }, [highlightedChunk, doc.doc_id, setHighlightedChunk]);

  const docHeader = (
    <>
      <h1
        style={{
          fontSize: 21,
          fontWeight: 700,
          color: "var(--heading)",
          letterSpacing: "-.02em",
          lineHeight: 1.3,
          margin: "8px 0 10px",
        }}
      >
        {doc.title ?? doc.filename}
      </h1>
      {meta?.creators && meta.creators.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--fg-muted)", marginBottom: 12 }}>
          {meta.creators.join(", ")}
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: 7,
          flexWrap: "wrap",
          marginBottom: 18,
          paddingBottom: 18,
          borderBottom: "1px solid var(--border)",
        }}
      >
        {meta?.venue && <Badge tone="neutral">{meta.venue}</Badge>}
        {meta?.year && <Badge tone="neutral">{meta.year}</Badge>}
        {meta?.item_type && <Badge tone="neutral">{meta.item_type}</Badge>}
        {meta?.doi && <Badge tone="accent">DOI {meta.doi}</Badge>}
        {doc.lightrag_index_status?.status === "built" && (
          <Badge tone="violet">
            <Icon name="graph" size={10} /> {t("documents_graph_built")}
          </Badge>
        )}
        {doc.ext?.toLowerCase() === "pdf" && !doc.read_only && (
          <button
            type="button"
            disabled={reextracting}
            onClick={handleReextract}
            style={{
              fontSize: 10.5,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "transparent",
              color: reextracting ? "var(--fg-subtle)" : "var(--fg-muted)",
              cursor: reextracting ? "not-allowed" : "pointer",
              letterSpacing: ".03em",
            }}
          >
            {reextracting ? t("documents_reextracting") : t("documents_reextract")}
          </button>
        )}
      </div>
    </>
  );

  if (mode === "pdf") {
    return (
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "6px 12px 12px", flexShrink: 0 }}>
          {docHeader}
        </div>
        <div style={{ flex: 1, minHeight: 0, padding: "0 12px 12px", overflow: "hidden" }}>
          <PdfViewer
            docId={doc.doc_id}
            title={doc.title ?? doc.filename}
            annotations={annotations}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "6px 12px 60px" }}>
      {docHeader}
      {meta?.abstract && (
        <>
          <Eyebrow style={{ marginBottom: 8 }}>{t("documents_abstract")}</Eyebrow>
          <p style={{ fontSize: 13.5, lineHeight: 1.75, color: "var(--fg)", margin: "0 0 24px" }}>
            {meta.abstract}
          </p>
        </>
      )}
      <Eyebrow style={{ marginBottom: 8 }}>
        {t("documents_source_chunks", { n: chunks.length })}
      </Eyebrow>
      {chunkLoading ? (
        <div style={{ fontSize: 12.5, color: "var(--fg-subtle)", padding: "16px 0" }}>
          {t("documents_detail_loading")}
        </div>
      ) : chunks.length === 0 ? (
        <div style={{ fontSize: 12.5, color: "var(--fg-subtle)", padding: "16px 0" }}>
          {t("documents_no_chunks")}
        </div>
      ) : (
        chunks.map((c) => (
          <div
            key={c.chunk_id}
            ref={(el) => { chunkRefs.current[c.chunk_id] = el; }}
            style={{
              padding: "11px 13px",
              borderRadius: "var(--radius-md)",
              marginBottom: 8,
              border: "1px solid var(--border)",
              background: "var(--surface)",
              transition: "background-color .2s",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span
                style={{ fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--accent)" }}
              >
                #{c.ordinal}
              </span>
              {c.page != null && (
                <span style={{ fontSize: 10, color: "var(--fg-subtle)" }}>
                  {t("documents_page_label", { page: c.page })} · {c.chunk_id}
                </span>
              )}
            </div>
            <ChunkText text={c.text} />
          </div>
        ))
      )}
    </div>
  );
}

// ─── DocumentsPanel ───────────────────────────────────────────

export function DocumentsPanel() {
  const { t } = useI18n();
  const {
    selectedCollection,
    selectedDocId,
    setSelectedDocId,
    highlightedChunk,
    setNoteDocId,
  } = useConsole();

  const [docs, setDocs] = useState<KrDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeDoc, setActiveDoc] = useState<KrDocument | null>(null);
  const [mode, setMode] = useState<"md" | "pdf">("md");

  // Derive collection name from key (strip prefix)
  const colName = selectedCollection
    ? selectedCollection.replace(/^(z:|l:|lr:)/, "")
    : undefined;

  // Load documents when collection changes
  useEffect(() => {
    if (!colName) { setDocs([]); return; }
    setLoading(true);
    listDocuments({ collection: colName })
      .then(setDocs)
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, [colName]);

  // Open doc when selectedDocId changes externally (e.g. from citation click)
  useEffect(() => {
    if (!selectedDocId) { setActiveDoc(null); return; }
    const found = docs.find((d) => d.doc_id === selectedDocId);
    if (found) {
      setActiveDoc(found);
      setMode("md");
    }
  }, [selectedDocId, docs]);

  // When highlightedChunk fires for a doc not yet open, open it
  useEffect(() => {
    if (!highlightedChunk) return;
    const found = docs.find((d) => d.doc_id === highlightedChunk.docId);
    if (found && activeDoc?.doc_id !== found.doc_id) {
      setActiveDoc(found);
      setSelectedDocId(found.doc_id);
      setMode("md");
    }
  }, [highlightedChunk]); // eslint-disable-line react-hooks/exhaustive-deps

  function openDoc(doc: KrDocument) {
    setActiveDoc(doc);
    setSelectedDocId(doc.doc_id);
    setMode("md");
  }

  function backToList() {
    setActiveDoc(null);
    setSelectedDocId(null);
  }

  const isReading = !!activeDoc;
  const title = colName ?? t("docs_all");

  const crumbs = isReading
    ? [
        { label: t("panel_documents"), onClick: backToList },
        { label: activeDoc!.collection, onClick: backToList, separator: "  " },
        { label: activeDoc!.title ?? activeDoc!.filename ?? "" },
      ]
    : [{ label: title }];

  const right = isReading ? (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: "var(--bg-inset)",
        borderRadius: "var(--radius-md)",
        padding: 2,
      }}
    >
      {(["md", "pdf"] as const).map((m) => (
        <button
          key={m}
          onClick={() => setMode(m)}
          style={{
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
            boxShadow: mode === m ? "var(--shadow-card)" : "none",
          }}
        >
          {m}
        </button>
      ))}
    </div>
  ) : (
    <IconButton name="search" label={t("documents_search_in_collection")} />
  );

  return (
    <Panel
      title={isReading ? undefined : t("panel_documents")}
      crumbs={crumbs}
      right={right}
      flush
      style={{ flex: 1, minWidth: 0 }}
      bodyStyle={
        isReading && mode === "pdf"
          ? { padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }
          : { padding: "14px 0" }
      }
    >
      {isReading ? (
        <ReadingView doc={activeDoc!} mode={mode} setMode={setMode} />
      ) : (
        <ListView
          docs={docs}
          title={title}
          loading={loading}
          onOpen={openDoc}
          onNote={(docId) => setNoteDocId(docId)}
        />
      )}
    </Panel>
  );
}
