import * as React from "react";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Semantic color. @default "neutral" */
  tone?: "neutral" | "accent" | "info" | "ok" | "warn" | "danger" | "violet";
}

/** Soft status / origin pill (本地上传, 只读, 即将上线, …). */
export function Badge(props: BadgeProps): JSX.Element;
