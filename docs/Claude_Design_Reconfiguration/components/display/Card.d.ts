import * as React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Add a gradient hairline + accent glow (featured / Research Agent surfaces). */
  featured?: boolean;
  /** Apply default 16px padding. @default true */
  pad?: boolean;
}

/** Base surface container with warm border, radius, and shadow. */
export function Card(props: CardProps): JSX.Element;
