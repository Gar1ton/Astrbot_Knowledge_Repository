import * as React from "react";

export interface StatusChipProps {
  /** Pipeline / connection state. @default "off" */
  status?: "ready" | "degraded" | "off" | "info";
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

/** Dot + label capsule for stage/connection status (Data-Flow style). */
export function StatusChip(props: StatusChipProps): JSX.Element;
