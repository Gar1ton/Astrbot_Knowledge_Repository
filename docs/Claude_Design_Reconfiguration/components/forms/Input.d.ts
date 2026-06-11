import * as React from "react";

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  /** Control height. sm = 32px, md = 36px. @default "md" */
  size?: "sm" | "md";
  /** Paint a danger border + ring. */
  invalid?: boolean;
  /** Use the monospace family (IDs, model/collection names). */
  mono?: boolean;
}

/** Single-line text field with warm surface and accent focus ring. */
export function Input(props: InputProps): JSX.Element;
