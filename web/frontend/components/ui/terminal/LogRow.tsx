"use client";

/**
 * 终端日志单行渲染：毫秒时间戳、级别徽章、分类 chip、代码位置、
 * 可折叠 traceback 与 metadata 内联展示。
 *
 * React.memo：轮询每 2.5s 触发列表重建，未变更的行对象引用不变，避免整表重渲染。
 */
import React, { useState } from "react";
import type { LogLine } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  formatTime,
  levelColor,
  levelShort,
  metadataPairs,
  normalizeLevel,
  rowBackground,
} from "./format";

export const ROW_GRID = "86px 42px 76px 110px minmax(0, 1fr)";

function LogRowInner({ line }: { line: LogLine }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const level = normalizeLevel(line.level);
  const pairs = metadataPairs(line);
  const excLineCount = line.exc ? line.exc.split("\n").length : 0;

  return (
    <div
      data-loglevel={level}
      style={{
        display: "grid",
        gridTemplateColumns: ROW_GRID,
        gap: 10,
        alignItems: "start",
        padding: "4px 16px",
        borderBottom: "1px solid color-mix(in srgb, var(--border) 42%, transparent)",
        fontSize: 11,
        lineHeight: 1.5,
        background: rowBackground(level),
      }}
    >
      <span style={{ color: "var(--fg-subtle)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
        {formatTime(line.ts)}
      </span>
      <span style={{ color: levelColor(level), fontWeight: 700, whiteSpace: "nowrap" }}>
        {levelShort(level)}
      </span>
      <span
        title={line.category || line.source || ""}
        style={{
          color: "var(--fg-muted)",
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {line.category || line.source || "-"}
      </span>
      <span
        title={line.location ? `${line.name} · ${line.location}` : line.name}
        style={{
          color: "var(--fg-subtle)",
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {line.location || line.name}
      </span>
      <span style={{ color: "var(--fg)", minWidth: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {line.msg}
        {typeof line.elapsed_ms === "number" && (
          <span style={{ color: "var(--fg-subtle)", marginLeft: 8 }}>
            {Math.round(line.elapsed_ms)}ms
          </span>
        )}
        {pairs.length > 0 && (
          <span style={{ color: "var(--fg-subtle)", marginLeft: 8, fontSize: 10 }}>
            {pairs.map(([k, v]) => `${k}=${v}`).join(" ")}
          </span>
        )}
        {line.exc && (
          <>
            <button
              onClick={() => setExpanded((v) => !v)}
              style={{
                display: "block",
                marginTop: 2,
                padding: 0,
                border: "none",
                background: "none",
                color: "var(--danger)",
                cursor: "pointer",
                fontSize: 10,
                fontFamily: "inherit",
              }}
            >
              {expanded
                ? t("terminal_collapse_trace")
                : t("terminal_expand_trace", { n: excLineCount })}
            </button>
            {expanded && (
              <span
                style={{
                  display: "block",
                  marginTop: 4,
                  padding: "6px 8px",
                  borderRadius: "var(--radius-sm)",
                  background: "color-mix(in srgb, var(--danger) 6%, transparent)",
                  color: "var(--fg-muted)",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: 10,
                }}
              >
                {line.exc}
              </span>
            )}
          </>
        )}
      </span>
    </div>
  );
}

export const LogRow = React.memo(LogRowInner);
