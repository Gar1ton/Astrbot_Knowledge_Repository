import * as React from "react";

export interface TagProps {
  /** Tag text. */
  label: string;
  /** Highlight as active/selected (accent-soft fill). */
  accent?: boolean;
  /** When provided, renders a × button and calls this on click. */
  onRemove?: () => void;
  style?: React.CSSProperties;
}

/** Small pill for document tags, filters, and retrieval-mode labels. */
export function Tag(props: TagProps): JSX.Element;
