"use client";

import React, { useEffect, useState } from "react";
import { DotField } from "@/components/fx/DotField";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { KbChunk, ApiError, listKbCollections, searchKb } from "@/lib/api";

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
      <DotField />

      {/* 搜索栏 */}
      <div
        className="fx-glass"
        style={{ position: "sticky", top: 0, zIndex: 3, padding: "16px 24px" }}
      >
        <h1 style={{ margin: "0 0 12px", fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
          {t("nav_search")}
        </h1>
        <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
            style={{ height: 36, fontSize: 13, padding: "0 10px", borderRadius: 10 }}
          >
            {collections.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search_placeholder")}
            style={{ flex: 1, minWidth: 200, height: 36 }}
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
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
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
