"use client";

/**
 * 终端日志工具栏：标题行（动作按钮）+ 过滤行（级别 chips / 分类下拉 / 搜索 / 错误徽章）。
 *
 * 纯受控组件：所有状态由 TerminalPanel 经 useTerminalLogs 提供。
 */
import React from "react";
import { Select } from "@/components/ds";
import { useI18n } from "@/lib/i18n";
import { LEVELS, levelColor, levelShort, type LevelKey } from "./format";

export interface TerminalToolbarProps {
  title: string;
  levels: Record<LevelKey, boolean>;
  onToggleLevel: (level: LevelKey) => void;
  category: string;
  categories: string[];
  onCategoryChange: (category: string) => void;
  query: string;
  onQueryChange: (query: string) => void;
  paused: boolean;
  onTogglePause: () => void;
  autoScroll: boolean;
  onToggleAutoScroll: () => void;
  errorCount: number;
  onJumpError: () => void;
  copied: boolean;
  onCopy: () => void;
  onDownload: () => void;
  onClear: () => void;
  loading: boolean;
  onRefresh: () => void;
  onClose?: () => void;
}

const actionButtonStyle: React.CSSProperties = {
  height: 26,
  padding: "0 8px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--fg-muted)",
  cursor: "pointer",
  fontSize: 11,
  fontFamily: "var(--font-sans)",
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  whiteSpace: "nowrap",
};

function activeButtonStyle(active: boolean): React.CSSProperties {
  return {
    ...actionButtonStyle,
    color: active ? "var(--accent)" : "var(--fg-muted)",
    borderColor: active ? "var(--accent-border)" : "var(--border)",
    background: active ? "var(--accent-soft)" : "var(--surface)",
  };
}

export function TerminalToolbar(props: TerminalToolbarProps) {
  const { t } = useI18n();

  return (
    <div style={{ borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
      {/* 标题 + 动作行 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px 8px 16px" }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--fg-muted)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {props.title}
        </span>
        <button
          onClick={props.onTogglePause}
          title={props.paused ? t("terminal_resume") : t("terminal_pause")}
          style={activeButtonStyle(props.paused)}
        >
          {props.paused ? t("terminal_resume") : t("terminal_pause")}
        </button>
        <button
          onClick={props.onToggleAutoScroll}
          title={t("terminal_auto_scroll")}
          style={activeButtonStyle(props.autoScroll)}
        >
          {t("terminal_auto_scroll_short")}
        </button>
        <button onClick={props.onCopy} title={t("terminal_copy")} style={actionButtonStyle}>
          {props.copied ? t("terminal_copied") : t("terminal_copy")}
        </button>
        <button onClick={props.onDownload} title={t("terminal_download")} style={actionButtonStyle}>
          {t("terminal_download")}
        </button>
        <button onClick={props.onClear} title={t("terminal_clear")} style={actionButtonStyle}>
          {t("terminal_clear")}
        </button>
        <button onClick={props.onRefresh} title={t("terminal_refresh")} style={actionButtonStyle}>
          {props.loading ? "..." : t("terminal_refresh")}
        </button>
        {props.onClose && (
          <button
            onClick={props.onClose}
            title={t("btn_close")}
            style={{
              background: "none",
              border: "none",
              color: "var(--fg-subtle)",
              cursor: "pointer",
              padding: 4,
              display: "flex",
              alignItems: "center",
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      {/* 过滤行 */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "0 12px 10px 16px", flexWrap: "wrap" }}>
        <div style={{ display: "inline-flex", gap: 4 }}>
          {LEVELS.map((level) => {
            const active = props.levels[level];
            return (
              <button
                key={level}
                onClick={() => props.onToggleLevel(level)}
                title={level}
                style={{
                  ...actionButtonStyle,
                  height: 24,
                  padding: "0 7px",
                  fontFamily: "var(--font-mono)",
                  fontWeight: 700,
                  fontSize: 10,
                  color: active ? levelColor(level) : "var(--fg-subtle)",
                  borderColor: active
                    ? "color-mix(in srgb, currentColor 45%, transparent)"
                    : "var(--border)",
                  background: active
                    ? "color-mix(in srgb, currentColor 9%, transparent)"
                    : "var(--surface)",
                  opacity: active ? 1 : 0.6,
                }}
              >
                {levelShort(level)}
              </button>
            );
          })}
        </div>
        <Select
          value={props.category}
          onChange={props.onCategoryChange}
          size="sm"
          style={{ minWidth: 118 }}
          options={[
            { value: "all", label: t("terminal_category_all") },
            ...props.categories.map((c) => ({ value: c, label: c })),
          ]}
        />
        <input
          value={props.query}
          onChange={(e) => props.onQueryChange(e.target.value)}
          placeholder={t("terminal_search_placeholder")}
          spellCheck={false}
          style={{
            flex: 1,
            minWidth: 120,
            height: 26,
            padding: "0 9px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--fg)",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            outline: "none",
          }}
        />
        {props.errorCount > 0 && (
          <button
            onClick={props.onJumpError}
            title={t("terminal_jump_error")}
            style={{
              ...actionButtonStyle,
              height: 24,
              color: "var(--danger)",
              borderColor: "color-mix(in srgb, var(--danger) 45%, transparent)",
              background: "color-mix(in srgb, var(--danger) 9%, transparent)",
              fontWeight: 700,
            }}
          >
            {props.errorCount} ERR ↓
          </button>
        )}
      </div>
    </div>
  );
}
