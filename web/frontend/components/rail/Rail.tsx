"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useI18n } from "@/lib/i18n";
import { getQuota, logout } from "@/lib/api";

// ─── 图标（内联 SVG，避免额外依赖） ──────────────────────────

function SparkleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2l2.4 7.2H22l-6.2 4.5 2.4 7.3L12 17l-6.2 4-0.1-.1 2.5-7.2L2 9.2h7.6z" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function GraphIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

function SyncIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  );
}

function QuotaIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

// ─── 导航项 ───────────────────────────────────────────────────

interface NavItemProps {
  href: string;
  icon: React.ReactNode;
  label: string;
  badge?: number;
  featured?: boolean;
}

function NavItem({ href, icon, label, badge, featured }: NavItemProps) {
  const pathname = usePathname();
  const isActive = pathname === href || pathname.startsWith(href + "/");

  return (
    <Link
      href={href}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 10px",
        borderRadius: 10,
        fontSize: 13,
        fontWeight: isActive ? 600 : 450,
        color: isActive
          ? "var(--accent)"
          : featured
          ? "var(--fg)"
          : "var(--fg-muted)",
        background: isActive
          ? "var(--accent-soft)"
          : featured && !isActive
          ? "transparent"
          : "transparent",
        border: featured && !isActive
          ? "1px solid var(--accent-border)"
          : isActive
          ? "1px solid var(--accent-border)"
          : "1px solid transparent",
        boxShadow: featured && !isActive
          ? "0 0 0 1px var(--accent-border), 0 0 16px var(--accent-soft)"
          : "none",
        transition: "all 0.15s",
        textDecoration: "none",
        position: "relative",
        animation: featured ? "sparkleFloat 4.5s ease-in-out infinite" : "none",
      }}
    >
      <span style={{ opacity: isActive ? 1 : 0.7 }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
      {badge !== undefined && badge > 0 && (
        <span
          style={{
            background: "var(--warn)",
            color: "#fff",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 700,
            padding: "0 5px",
            lineHeight: "16px",
            minWidth: 16,
            textAlign: "center",
          }}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--fg-subtle)",
        padding: "8px 10px 4px",
        marginTop: 4,
      }}
    >
      {label}
    </div>
  );
}

// ─── Rail ─────────────────────────────────────────────────────

interface RailProps {
  onLogout?: () => void;
}

export function Rail({ onLogout }: RailProps) {
  const { t } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const [quotaRatio, setQuotaRatio] = useState<number | null>(null);

  useEffect(() => {
    getQuota()
      .then((items) => {
        const r2 = items.find((q) => q.target === "r2");
        if (r2) setQuotaRatio(r2.ratio);
      })
      .catch(() => {});
  }, []);

  const quotaWarning =
    quotaRatio !== null && quotaRatio >= 0.8 ? Math.round(quotaRatio * 100) : undefined;

  return (
    <nav
      style={{
        width: "var(--rail-w, 220px)",
        minHeight: "100vh",
        background: "var(--surface)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        padding: "0 10px",
        flexShrink: 0,
        position: "sticky",
        top: 0,
        overflowY: "auto",
        overflowX: "hidden",
      }}
      className="fx-glass-edge"
    >
      {/* 品牌区 */}
      <div
        style={{
          padding: "16px 10px 12px",
          borderBottom: "1px solid var(--border)",
          marginBottom: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              color: "var(--accent)",
              animation: "sparkleFloat 4.5s ease-in-out infinite",
            }}
          >
            <SparkleIcon />
          </span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: "var(--heading)",
              letterSpacing: "-0.02em",
              lineHeight: 1.2,
            }}
          >
            Knowledge Repo
          </span>
        </div>
      </div>

      {/* Ask Agent（featured） */}
      <div style={{ padding: "6px 0" }}>
        <NavItem
          href="/ask"
          icon={<SparkleIcon />}
          label={t("nav_ask")}
          featured
        />
      </div>

      {/* 知识库分组 */}
      <SectionLabel label={t("nav_knowledge")} />
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <NavItem href="/documents" icon={<DocIcon />} label={t("nav_documents")} />
        <NavItem href="/search" icon={<SearchIcon />} label={t("nav_search")} />
        <NavItem href="/graph" icon={<GraphIcon />} label={t("nav_graph")} />
      </div>

      {/* 运维分组 */}
      <SectionLabel label={t("nav_ops")} />
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <NavItem href="/sync" icon={<SyncIcon />} label={t("nav_sync")} />
        <NavItem
          href="/quota"
          icon={<QuotaIcon />}
          label={t("nav_quota")}
          badge={quotaWarning}
        />
      </div>

      {/* 弹性间隔 */}
      <div style={{ flex: 1 }} />

      {/* 底部：设置 + 主题切换 + 用户区 */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          paddingTop: 8,
          paddingBottom: 12,
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        <NavItem href="/settings" icon={<SettingsIcon />} label={t("nav_settings")} />

        {/* 主题切换 */}
        <button
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          title={resolvedTheme === "dark" ? t("settings_theme_light") : t("settings_theme_dark")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            padding: "7px 10px",
            borderRadius: 10,
            fontSize: 13,
            color: "var(--fg-muted)",
            background: "none",
            border: "1px solid transparent",
            cursor: "pointer",
            transition: "all 0.15s",
            textAlign: "left",
            fontFamily: "inherit",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--surface-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "none";
          }}
        >
          <span style={{ opacity: 0.7 }}>
            {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
          </span>
          <span>
            {resolvedTheme === "dark" ? t("settings_theme_light") : t("settings_theme_dark")}
          </span>
        </button>

        {/* 用户区 + 登出 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "6px 10px",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--fg-muted)", fontWeight: 500 }}>
            admin
          </span>
          <button
            onClick={onLogout}
            title={t("nav_logout")}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--fg-subtle)",
              padding: 4,
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--danger)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--fg-subtle)";
            }}
          >
            <LogoutIcon />
          </button>
        </div>
      </div>
    </nav>
  );
}
