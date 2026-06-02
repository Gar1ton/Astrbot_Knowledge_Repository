"use client";

import React, { useEffect, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { KbChunk, ApiError, listKbCollections, searchKb } from "@/lib/api";
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

export default function SearchPage() {
  const { t } = useI18n();
  const { toast } = useToast();

  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<KbChunk[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listKbCollections()
      .then((cols) => {
        setCollections(cols);
        if (cols.length) setCollection(cols[0]);
      })
      .catch(() => {});
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !collection) return;
    setLoading(true);
    try {
      const chunks = await searchKb(collection, query, topK);
      setResults(chunks);
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
        <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--fg-muted)" }}>
          <span style={{ color: "var(--accent-2)", marginRight: 6 }}>●</span>
          复用 AstrBot embedding + RRF
        </p>
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
          <Select
            value={collection}
            onChange={setCollection}
            options={collections.map((c) => ({ value: c, label: c }))}
          />

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

          <Btn type="submit" loading={loading}>{t("search_btn")}</Btn>
        </form>
      </div>

      {/* 结果区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "72px 24px 20px", position: "relative", zIndex: 1 }}>
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
              <div
                key={chunk.chunk_id}
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 12,
                  padding: "14px 16px",
                  animation: `fadeUp .2s ${idx * 0.03}s both`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span
                    style={{
                      background: "var(--accent-soft)",
                      color: "var(--accent)",
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 700,
                      padding: "1px 8px",
                    }}
                  >
                    #{chunk.ordinal + 1}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)" }}>
                    {chunk.chunk_id}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: "var(--fg)" }}>
                  {highlight(chunk.text, query)}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
