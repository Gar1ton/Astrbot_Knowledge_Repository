import * as React from "react";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  /** Currently selected value. */
  value: string;
  /** Called with the new value on selection. */
  onChange?: (value: string) => void;
  /** Option list. */
  options: SelectOption[];
  /** Shown when no option matches `value`. */
  placeholder?: string;
  /** Trigger size. @default "sm" */
  size?: "sm" | "md";
  disabled?: boolean;
  style?: React.CSSProperties;
}

/** Custom dropdown select matching the warm surface system. */
export function Select(props: SelectProps): JSX.Element;
