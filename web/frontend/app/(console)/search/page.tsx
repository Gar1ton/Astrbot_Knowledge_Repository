"use client";

import React, { useEffect, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  KbChunk, KbChunkContext, ApiError, listCollections, listDocuments, searchKb,
} from "@/lib/api";
import { Select } from "@/components/ui/Select";

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function highlight(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    new RegExp(`^${escaped}$`, "i").test(part) ? (
      <mark key={i} style={{ background: "var(--accent-soft)", color: "var(--accent)", borderRadius: 2, padding: "0 1px" }}>
        {part}
      </mark>
    ) : (
      part
    )
  );
}

// ─── 上下文段落 ───────────────────────────────────────────────

function ContextLine({ chunk, query, isBefore }: { chunk: KbChunkContext; query: string; isBefore: boolean }) {
  return (
    <p
      style={{
        margin: 0,
        fontSize: 12,
        lineHeight: 1.65,
        color: "var(--fg-muted)",
        padding: isBefore ? "0 0 8px 0" : "8px 0 0 0",
        borderBottom: isBefore ? "1px solid var(--border)" : undefined,
        borderTop: !isBefore ? "1px solid var(--border)" : undefined,
      }}
    >
      {highlight(chunk.text, query)}
    </p>
  );
}

// ─── 结果卡片 ─────────────────────────────────────────────────

function ChunkCard({
  chunk,
  query,
  docTitle,
  idx,
}: {
  chunk: KbChunk;
  query: string;
  docTitle: string;
  idx: number;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
        animation: `fadeUp .2s ${idx * 0.03}s both`,
      }}
    >
      {/* 标题行 */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "10px 14px 8px",
        borderBottom: "1px solid var(--border)",
        background: "var(--bg-inset)",
      }}>
        <span style={{
          background: "var(--accent-soft)", color: "var(--accent)",
          borderRadius: 999, fontSize: 11, fontWeight: 700, padding: "1px 8px", flexShrink: 0,
        }}>
          #{chunk.ordinal + 1}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {docTitle}
        </span>
      </div>

      {/* 上下文 */}
      <div style={{ padding: "10px 14px" }}>
        {/* 前文 */}
        {chunk.context_before && chunk.context_before.map((ctx) => (
          <ContextLine key={ctx.chunk_id} chunk={ctx} query={query} isBefore />
        ))}

        {/* 命中段落 */}
        <p style={{
          margin: 0,
          fontSize: 13,
          lineHeight: 1.75,
          color: "var(--fg)",
          padding: (chunk.context_before?.length || chunk.context_after?.length) ? "8px 0" : 0,
        }}>
          {highlight(chunk.text, query)}
        </p>

        {/* 后文 */}
        {chunk.context_after && chunk.context_after.map((ctx) => (
          <ContextLine key={ctx.chunk_id} chunk={ctx} query={query} isBefore={false} />
        ))}
      </div>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────

export default function SearchPage() {
  const { t } = useI18n();
  const { toast } = useToast();

  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<KbChunk[] | null>(null);
  const [loading, setLoading] = useState(false);
  // doc_id → title map for display
  const [docTitles, setDocTitles] = useState<Record<string, string>>({});

  useEffect(() => {
    listCollections()
      .then((cols) => {
        const names = cols.map((c) => c.name);
        setCollections(names);
        if (names.length) setCollection(names[0]);
      })
      .catch(() => {});
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      const [chunks, docs] = await Promise.all([
        searchKb(collection, query, topK),
        listDocuments(collection ? { collection } : undefined).catch(() => []),
      ]);
      setResults(chunks);
      const titles: Record<string, string> = {};
      docs.forEach((d) => { titles[d.doc_id] = d.title || d.filename || d.doc_id; });
      // fallback for any doc_id not in list
      chunks.forEach((c) => { if (!titles[c.doc_id]) titles[c.doc_id] = c.doc_id.slice(0, 8) + "…"; });
      setDocTitles(titles);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", position: "relative" }}>
      <div style={{ position: "relative", zIndex: 1, width: "100%", maxWidth: 820, margin: "0 auto", padding: "32px 24px 0" }}>
        <div style={{ color: "var(--fg-subtle)", fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
          知识库
        </div>
        <h1 style={{ margin: "0 0 2px", fontSize: 24, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.04em" }}>
          {t("nav_search")}
        </h1>
        <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--fg-muted)" }}>
          <span style={{ color: "var(--accent-2)", marginRight: 6 }}>●</span>
          Milvus 向量检索 · 关键词高亮 · 完整上下文
        </p>

        {/* 搜索表单 */}
        <form
          onSubmit={handleSearch}
          style={{
            display: "flex", gap: 8, alignItems: "center",
            padding: 10, border: "1px solid var(--accent-border)",
            borderRadius: 14, background: "var(--surface)", boxShadow: "var(--shadow-pop)",
          }}
        >
          <SearchIcon />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search_placeholder")}
            style={{ flex: 1, minWidth: 180, height: 34, border: "none", background: "transparent", padding: "0 4px", boxShadow: "none" }}
          />
          {collections.length > 0 && (
            <Select
              value={collection}
              onChange={setCollection}
              options={collections.map((c) => ({ value: c, label: c }))}
            />
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>{t("search_top_k")}</span>
            <input
              type="number"
              value={topK}
              min={1}
              max={20}
              onChange={(e) => setTopK(Number(e.target.value))}
              style={{ width: 56, height: 36, textAlign: "center" }}
            />
          </div>
          <Btn type="submit" loading={loading} disabled={!query.trim()}>{t("search_btn")}</Btn>
        </form>
      </div>

      {/* 结果区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 24px 20px", position: "relative", zIndex: 1 }}>
        <div style={{ maxWidth: 820, margin: "0 auto" }}>
          {results === null ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              输入关键词开始检索
            </div>
          ) : results.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              {t("search_no_results")}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {results.map((chunk, idx) => (
                <ChunkCard
                  key={chunk.chunk_id}
                  chunk={chunk}
                  query={query}
                  docTitle={docTitles[chunk.doc_id] ?? chunk.doc_id}
                  idx={idx}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
