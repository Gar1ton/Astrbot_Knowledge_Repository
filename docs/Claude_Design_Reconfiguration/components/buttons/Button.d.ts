import * as React from "react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style. @default "primary" */
  variant?: "primary" | "outline" | "ghost" | "danger";
  /** Control size. @default "md" */
  size?: "sm" | "md";
  /** Show an inline spinner and disable interaction. */
  loading?: boolean;
}

/**
 * Pill-shaped action button — the console's primary call to action.
 *
 * @startingPoint section="Buttons" subtitle="Pill action button · 4 variants" viewport="700x150"
 */
export function Button(props: ButtonProps): JSX.Element;
