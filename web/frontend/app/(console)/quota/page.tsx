"use client";

import React, { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ui/Toast";
import { Btn } from "@/components/ui/Btn";
import { DotField } from "@/components/fx/DotField";
import { QuotaItem, ApiError, getQuota } from "@/lib/api";

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

function QuotaCard({ item }: { item: QuotaItem }) {
  const { t } = useI18n();
  const ratio = Math.min(item.ratio, 1);
  const pct = (ratio * 100).toFixed(1);
  const isWarn = item.ratio >= 0.8;
  const isDanger = item.ratio >= 0.95;

  const barColor = isDanger
    ? "var(--danger)"
    : isWarn
    ? "var(--warn)"
    : "var(--ok)";

  const labelMap: Record<string, string> = {
    r2: t("quota_r2"),
    notion: t("quota_notion"),
  };

  return (
    <div
      style={{
        background: "var(--surface)",
        border: `1px solid ${isDanger ? "var(--danger)" : isWarn ? "var(--warn)" : "var(--border)"}`,
        borderRadius: 14,
        padding: "18px 20px",
        transition: "border-color .2s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--heading)" }}>
          {labelMap[item.target] ?? item.target}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: isDanger ? "var(--danger)" : isWarn ? "var(--warn)" : "var(--fg-muted)",
          }}
        >
          {pct}%
        </span>
      </div>

      {/* 进度条 */}
      <div
        style={{
          height: 8,
          background: "var(--bg-inset)",
          borderRadius: 999,
          overflow: "hidden",
          border: "1px solid var(--border)",
          marginBottom: 10,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: barColor,
            borderRadius: 999,
            transition: "width .4s ease",
          }}
        />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--fg-muted)" }}>
        <span>{t("quota_used")}: {fmtBytes(item.used_bytes)}</span>
        <span>{t("quota_limit")}: {fmtBytes(item.limit_bytes)}</span>
      </div>

      {item.detail && (
        <div style={{ marginTop: 6, fontSize: 11, color: "var(--fg-subtle)", fontFamily: "var(--font-geist-mono)" }}>
          {item.detail}
        </div>
      )}

      {isWarn && (
        <div
          style={{
            marginTop: 10,
            padding: "6px 10px",
            background: isDanger ? "var(--danger-soft)" : "var(--warn-soft)",
            borderRadius: 8,
            fontSize: 12,
            color: isDanger ? "var(--danger)" : "var(--warn)",
          }}
        >
          {isDanger ? "⚠ 存储空间即将耗尽，请立即清理或扩容" : "⚠ 存储用量超过 80%，请注意"}
        </div>
      )}
    </div>
  );
}

export default function QuotaPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [items, setItems] = useState<QuotaItem[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await getQuota();
      setItems(data);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      <DotField />
      <div style={{ padding: "24px", maxWidth: 720, position: "relative", zIndex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.02em" }}>
            {t("nav_quota")}
          </h1>
          <Btn variant="ghost" size="sm" loading={loading} onClick={load}>
            刷新
          </Btn>
        </div>

        {loading ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 13 }}>{t("loading")}</div>
        ) : items.length === 0 ? (
          <div style={{ color: "var(--fg-muted)", fontSize: 13 }}>暂无配额数据</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {items.map((item, i) => (
              <div key={item.target} style={{ animation: `fadeUp .2s ${i * 0.06}s both` }}>
                <QuotaCard item={item} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
