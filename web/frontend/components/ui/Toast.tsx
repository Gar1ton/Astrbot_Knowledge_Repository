"use client";

import React, { createContext, useCallback, useContext, useState, useEffect } from "react";

interface ToastItem {
  id: number;
  message: string;
  type: "info" | "error" | "ok";
}

interface ToastContextValue {
  toast: (msg: string, type?: ToastItem["type"]) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  let nextId = 0;

  const toast = useCallback((message: string, type: ToastItem["type"] = "info") => {
    const id = ++nextId;
    setItems((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        style={{
          position: "fixed",
          bottom: 24,
          right: 24,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          zIndex: 9999,
          pointerEvents: "none",
        }}
      >
        {items.map((item) => (
          <ToastBubble key={item.id} item={item} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastBubble({ item }: { item: ToastItem }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 10);
    return () => clearTimeout(t);
  }, []);

  const bg =
    item.type === "error"
      ? "var(--danger-soft)"
      : item.type === "ok"
      ? "var(--ok-soft)"
      : "var(--surface)";

  const border =
    item.type === "error"
      ? "var(--danger)"
      : item.type === "ok"
      ? "var(--ok)"
      : "var(--border)";

  return (
    <div
      style={{
        background: bg,
        border: `1px solid ${border}`,
        color: "var(--fg)",
        borderRadius: 10,
        padding: "10px 16px",
        fontSize: 13,
        boxShadow: "var(--shadow)",
        pointerEvents: "auto",
        transform: visible ? "translateY(0)" : "translateY(8px)",
        transition: "transform 0.2s ease",
        maxWidth: 320,
      }}
    >
      {item.message}
    </div>
  );
}
