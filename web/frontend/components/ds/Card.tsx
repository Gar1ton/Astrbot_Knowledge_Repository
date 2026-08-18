"use client";
import React from "react";
import { Icon } from "./Icon";

/**
 * 面板内的分区容器与设置行（DS 层）。
 *
 * 为何在这里：AstrBotModal 与 SettingModal 各自逐字拷了一份同样的实现，第三个面板
 * （显存与本地模型）需要同一套样式时，正确做法是收敛而不是再拷第三份。样式一字未改，
 * 抽取本身对既有两个面板必须是**零视觉变化**的。
 *
 * 用法约定：`Modal` 的 body 自身没有 padding，调用方须自行包一层 `padding: "18px 22px"`，
 * Card 之间的间距由 Card 自带的 marginBottom 负责。
 */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{label}</div>
        {hint && (
          <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2, lineHeight: 1.45 }}>
            {hint}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

export function Card({
  title,
  icon,
  badge,
  children,
}: {
  title: string;
  icon?: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: "4px 16px 12px",
        marginBottom: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 4px" }}>
        {icon && <Icon name={icon} size={16} style={{ color: "var(--accent)" }} />}
        <span style={{ fontSize: 13.5, fontWeight: 650, color: "var(--heading)", flex: 1 }}>
          {title}
        </span>
        {badge}
      </div>
      {children}
    </div>
  );
}
