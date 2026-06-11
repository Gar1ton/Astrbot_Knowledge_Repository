import * as React from "react";

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Square edge length in px. @default 28 */
  size?: number;
  /** Paint with the accent-soft surface (toggled / selected state). */
  active?: boolean;
}

/** Square, quiet button holding a single inline-SVG icon. */
export function IconButton(props: IconButtonProps): JSX.Element;
