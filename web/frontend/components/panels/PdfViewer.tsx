"use client";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/ds/Icon";
import { IconButton } from "@/components/ds/IconButton";
import { ZoteroAnnotation } from "@/lib/api";

interface PdfViewerProps {
  docId: string;
  title?: string;
  annotations: ZoteroAnnotation[];
}

type PdfDocument = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPage>;
  destroy?: () => Promise<void>;
};

type PdfPage = {
  getViewport: (options: { scale: number }) => { width: number; height: number };
  render: (context: {
    canvasContext: CanvasRenderingContext2D;
    viewport: { width: number; height: number };
  }) => { promise: Promise<void>; cancel: () => void };
};

type PdfJsModule = {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument: (source: { url: string }) => { promise: Promise<PdfDocument>; destroy?: () => void };
};

const MIN_SCALE = 0.5;
const MAX_SCALE = 2.4;
const SCALE_STEP = 0.15;

export function PdfViewer({ docId, title, annotations }: PdfViewerProps) {
  const [pdf, setPdf] = useState<PdfDocument | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pagesRef = useRef<Record<number, HTMLDivElement | null>>({});
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const pdfUrl = useMemo(
    () => `/api/documents/${encodeURIComponent(docId)}/raw?disposition=inline`,
    [docId],
  );

  useEffect(() => {
    let cancelled = false;
    let loadingTask: { promise: Promise<PdfDocument>; destroy?: () => void } | null = null;
    setPdf(null);
    setPageCount(0);
    setCurrentPage(1);
    setLoading(true);
    setError("");

    async function loadPdf() {
      try {
        const pdfjs = (await import("pdfjs-dist")) as unknown as PdfJsModule;
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.mjs",
          import.meta.url,
        ).toString();
        loadingTask = pdfjs.getDocument({ url: pdfUrl });
        const doc = await loadingTask.promise;
        if (cancelled) {
          await doc.destroy?.();
          return;
        }
        setPdf(doc);
        setPageCount(doc.numPages);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "PDF load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadPdf();
    return () => {
      cancelled = true;
      loadingTask?.destroy?.();
    };
  }, [pdfUrl]);

  const scrollToPage = useCallback((page: number) => {
    const clamped = Math.max(1, Math.min(pageCount || page, page));
    setCurrentPage(clamped);
    pagesRef.current[clamped]?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [pageCount]);

  const fitWidth = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport || !pdf) return;
    void pdf.getPage(1).then((page) => {
      const natural = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(320, viewport.clientWidth - 46);
      const nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, availableWidth / natural.width));
      setScale(Number(nextScale.toFixed(2)));
    });
  }, [pdf]);

  useEffect(() => {
    if (pdf) fitWidth();
  }, [pdf, fitWidth]);

  const annotatedPages = useMemo(() => {
    const pages = new Set<number>();
    annotations.forEach((ann) => {
      const page = annotationPage(ann);
      if (page != null) pages.add(page);
    });
    return pages;
  }, [annotations]);

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          height: 38,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 10px",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-inset)",
        }}
      >
        <Icon name="filePdf" size={15} />
        <span
          style={{
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontSize: 12,
            fontWeight: 650,
            color: "var(--heading)",
          }}
        >
          {title ?? "PDF"}
        </span>
        <IconButton
          name="chevL"
          label="上一页"
          onClick={() => scrollToPage(currentPage - 1)}
          style={{ opacity: currentPage <= 1 ? 0.45 : 1 }}
        />
        <span style={{ fontSize: 11, color: "var(--fg-muted)", fontFamily: "var(--font-mono)" }}>
          {currentPage}/{pageCount || "-"}
        </span>
        <IconButton
          name="chevR"
          label="下一页"
          onClick={() => scrollToPage(currentPage + 1)}
          style={{ opacity: pageCount && currentPage >= pageCount ? 0.45 : 1 }}
        />
        <IconButton
          name="zoomOut"
          label="缩小"
          onClick={() => setScale((value) => Math.max(MIN_SCALE, Number((value - SCALE_STEP).toFixed(2))))}
        />
        <span style={{ minWidth: 38, textAlign: "center", fontSize: 11, color: "var(--fg-muted)" }}>
          {Math.round(scale * 100)}%
        </span>
        <IconButton
          name="zoomIn"
          label="放大"
          onClick={() => setScale((value) => Math.min(MAX_SCALE, Number((value + SCALE_STEP).toFixed(2))))}
        />
        <IconButton name="maximize" label="适合宽度" onClick={fitWidth} />
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        <div
          ref={viewportRef}
          onScroll={() => {
            const entries = Object.entries(pagesRef.current);
            const top = viewportRef.current?.getBoundingClientRect().top ?? 0;
            let closest = currentPage;
            let distance = Number.POSITIVE_INFINITY;
            entries.forEach(([page, el]) => {
              if (!el) return;
              const nextDistance = Math.abs(el.getBoundingClientRect().top - top);
              if (nextDistance < distance) {
                distance = nextDistance;
                closest = Number(page);
              }
            });
            if (closest !== currentPage) setCurrentPage(closest);
          }}
          style={{
            flex: 1,
            minHeight: 0,
            overflow: "auto",
            background: "var(--bg)",
            padding: "10px 14px",
          }}
        >
          {loading && <PdfState label="Loading PDF" />}
          {error && <PdfState label={error} tone="error" />}
          {!loading && !error && pdf && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
              {Array.from({ length: pageCount }, (_, index) => {
                const pageNumber = index + 1;
                return (
                  <div
                    key={pageNumber}
                    ref={(el) => { pagesRef.current[pageNumber] = el; }}
                    style={{
                      position: "relative",
                      border: annotatedPages.has(pageNumber)
                        ? "2px solid var(--accent)"
                        : "1px solid var(--border)",
                      boxShadow: "var(--shadow-card)",
                      background: "white",
                    }}
                  >
                    <PdfPageCanvas pdf={pdf} pageNumber={pageNumber} scale={scale} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {annotations.length > 0 && (
          <aside
            style={{
              width: 260,
              flexShrink: 0,
              borderLeft: "1px solid var(--border)",
              background: "var(--surface)",
              overflow: "auto",
              padding: 12,
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--fg-muted)", marginBottom: 9 }}>
              Annotations · {annotations.length}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {annotations.map((ann) => {
                const page = annotationPage(ann);
                return (
                  <button
                    key={ann.id}
                    type="button"
                    onClick={() => page != null && scrollToPage(page)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      border: "1px solid var(--border)",
                      borderLeft: `3px solid ${ann.color || "var(--accent)"}`,
                      borderRadius: "var(--radius-sm)",
                      background: "var(--bg-inset)",
                      padding: "8px 9px",
                      cursor: page != null ? "pointer" : "default",
                      fontFamily: "var(--font-sans)",
                    }}
                  >
                    <div style={{ fontSize: 10.5, color: "var(--fg-subtle)", marginBottom: 4 }}>
                      {page != null ? `p.${page}` : "PDF"} · {ann.type || "annotation"}
                    </div>
                    <div style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--fg)" }}>
                      {ann.text || ann.comment || "Annotation"}
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

function PdfPageCanvas({ pdf, pageNumber, scale }: { pdf: PdfDocument; pageNumber: number; scale: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [rendering, setRendering] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let renderTask: { promise: Promise<void>; cancel: () => void } | null = null;

    async function renderPage() {
      setRendering(true);
      const page = await pdf.getPage(pageNumber);
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      renderTask = page.render({ canvasContext: context, viewport });
      try {
        await renderTask.promise;
      } catch {
        // Render cancellation during zoom/doc switches is expected.
      } finally {
        if (!cancelled) setRendering(false);
      }
    }

    void renderPage();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [pdf, pageNumber, scale]);

  return (
    <>
      <canvas ref={canvasRef} style={{ display: "block" }} />
      {rendering && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "grid",
            placeItems: "center",
            background: "rgba(255,255,255,.62)",
            fontSize: 11,
            color: "var(--fg-subtle)",
          }}
        >
          Rendering
        </div>
      )}
    </>
  );
}

function PdfState({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "error" }) {
  return (
    <div
      style={{
        minHeight: 260,
        display: "grid",
        placeItems: "center",
        color: tone === "error" ? "var(--danger)" : "var(--fg-subtle)",
        fontSize: 12,
      }}
    >
      {label}
    </div>
  );
}

function annotationPage(annotation: ZoteroAnnotation): number | null {
  if (typeof annotation.page === "number") return annotation.page;
  if (typeof annotation.position?.pageIndex === "number") return annotation.position.pageIndex + 1;
  return null;
}
