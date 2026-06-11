import * as React from "react";

export interface QuotaBarProps {
  /** Usage fraction 0–1. */
  ratio: number;
  /** Title above the track. */
  label?: string;
  /** Right-aligned mono detail (e.g. "3.2 GB / 10 GB"). */
  detail?: string;
  /** Ratio at which the fill turns warn. @default 0.8 */
  warnThreshold?: number;
  style?: React.CSSProperties;
}

/** Labelled storage usage meter with warn/danger thresholds (R2 / Notion). */
export function QuotaBar(props: QuotaBarProps): JSX.Element;
