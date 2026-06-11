import * as React from "react";

export interface ToggleProps {
  /** On/off state. */
  checked: boolean;
  /** Called with the next boolean when toggled. */
  onChange?: (checked: boolean) => void;
  /** Optional trailing label. */
  label?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
}

/** Compact accent switch for binary settings. */
export function Toggle(props: ToggleProps): JSX.Element;
