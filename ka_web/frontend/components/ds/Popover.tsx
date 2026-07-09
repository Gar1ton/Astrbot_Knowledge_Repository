"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Z } from "@/lib/zLayers";

// SSR 下 useLayoutEffect 会告警；这里退回 useEffect。
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

type Side = "top" | "bottom" | "left" | "right";
type Align = "start" | "center" | "end";

interface PopoverProps {
  /** 是否展开 */
  open: boolean;
  /** 锚点元素（触发器）的 ref */
  anchorRef: React.RefObject<HTMLElement | null>;
  /** 请求关闭（outside-click / Escape 时触发） */
  onClose?: () => void;
  /** 相对锚点的方位 */
  side?: Side;
  /** 沿副轴的对齐 */
  align?: Align;
  /** 与锚点的间距（px） */
  gap?: number;
  /** 层级，默认 dropdown */
  zIndex?: number;
  /** 浮层 minWidth 跟随锚点宽度（Select 下拉用） */
  matchAnchorWidth?: boolean;
  /** 浮层容器附加样式 */
  style?: React.CSSProperties;
  children: React.ReactNode;
}

interface Pos {
  top: number;
  left: number;
  transform: string;
  width: number;
}

// 用 transform 百分比偏移浮层自身尺寸，无需在 JS 里测量浮层大小。
function computePos(rect: DOMRect, side: Side, align: Align, gap: number): Pos {
  let top = 0;
  let left = 0;
  let tx = "0";
  let ty = "0";

  if (side === "bottom" || side === "top") {
    if (side === "bottom") { top = rect.bottom + gap; ty = "0"; }
    else { top = rect.top - gap; ty = "-100%"; }
    if (align === "start") { left = rect.left; tx = "0"; }
    else if (align === "end") { left = rect.right; tx = "-100%"; }
    else { left = rect.left + rect.width / 2; tx = "-50%"; }
  } else {
    if (side === "right") { left = rect.right + gap; tx = "0"; }
    else { left = rect.left - gap; tx = "-100%"; }
    if (align === "start") { top = rect.top; ty = "0"; }
    else if (align === "end") { top = rect.bottom; ty = "-100%"; }
    else { top = rect.top + rect.height / 2; ty = "-50%"; }
  }

  return { top, left, transform: `translate(${tx}, ${ty})`, width: rect.width };
}

/**
 * 锚定浮层原语：portal 到 document.body 渲染，绕开祖先的 stacking context
 * 与 overflow 裁切；用锚点的 getBoundingClientRect 以 position:fixed 定位，
 * 监听 scroll/resize 重算，并处理 outside-click 与 Escape。
 */
export function Popover({
  open,
  anchorRef,
  onClose,
  side = "bottom",
  align = "start",
  gap = 6,
  zIndex = Z.dropdown,
  matchAnchorWidth = false,
  style,
  children,
}: PopoverProps) {
  const [pos, setPos] = useState<Pos | null>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const measure = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    setPos(computePos(el.getBoundingClientRect(), side, align, gap));
  }, [anchorRef, side, align, gap]);

  // 展开时先量一次，并订阅 scroll（capture，含内层滚动容器）/resize 重算。
  useIsoLayoutEffect(() => {
    if (!open) return;
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, measure]);

  // outside-click + Escape 关闭。
  useEffect(() => {
    if (!open || !onClose) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (anchorRef.current?.contains(t) || popRef.current?.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, anchorRef]);

  if (!open || pos === null || typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={popRef}
      style={{
        position: "fixed",
        top: pos.top,
        left: pos.left,
        transform: pos.transform,
        zIndex,
        ...(matchAnchorWidth ? { minWidth: pos.width } : null),
        ...style,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
