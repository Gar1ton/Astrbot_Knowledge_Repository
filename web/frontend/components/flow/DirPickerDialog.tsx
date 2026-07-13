"use client";

import React, { useCallback, useEffect, useState } from "react";
import { browseDir, type FsBrowseResult } from "@/lib/api";
import type { I18nKey } from "@/lib/i18n";

interface DirPickerDialogProps {
  initialPath?: string;
  t: (k: I18nKey) => string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export function DirPickerDialog({ initialPath, t, onSelect, onClose }: DirPickerDialogProps) {
  const [path, setPath] = useState(initialPath || undefined);
  const [result, setResult] = useState<FsBrowseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const navigate = useCallback((nextPath?: string) => {
    setLoading(true);
    setError(null);
    setPath(nextPath);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadPath() {
      try {
        const data = await browseDir(path);
        if (cancelled) return;
        setResult(data);
        setError(null);
      } catch {
        if (!cancelled) setError(t("dir_picker_error"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadPath();
    return () => {
      cancelled = true;
    };
  }, [path, t]);

  const selectDir = useCallback((nextPath?: string) => {
    navigate(nextPath);
  }, [navigate]);

  const selectChild = useCallback((basePath: string, name: string) => {
    navigate(`${basePath}/${name}`);
  }, [navigate]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="dir-picker-overlay" onPointerDown={onClose}>
      <div
        className="dir-picker-dialog"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dir-picker-header">
          <span className="dir-picker-title">{t("dir_picker_title")}</span>
          <button type="button" className="dir-picker-close" onClick={onClose} aria-label="close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="dir-picker-path">
          {result?.path ?? (loading ? "…" : "")}
        </div>

        <div className="dir-picker-list">
          {loading && (
            <div className="dir-picker-status">{t("dir_picker_loading")}</div>
          )}
          {!loading && error && (
            <div className="dir-picker-status dir-picker-status--error">{error}</div>
          )}
          {!loading && result && (
            <>
              {result.parent !== null && (
                <button
                  type="button"
                  className="dir-picker-item dir-picker-item--up"
                  onClick={() => selectDir(result.parent!)}
                >
                  <FolderUpIcon />
                  <span>{t("dir_picker_up")}</span>
                </button>
              )}
              {result.dirs.length === 0 && !result.parent && (
                <div className="dir-picker-status">—</div>
              )}
              {result.dirs.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="dir-picker-item"
                  onClick={() => selectChild(result.path, name)}
                >
                  <FolderIcon />
                  <span>{name}</span>
                </button>
              ))}
            </>
          )}
        </div>

        <div className="dir-picker-footer">
          <button type="button" className="dir-picker-btn dir-picker-btn--ghost" onClick={onClose}>
            {t("dir_picker_cancel")}
          </button>
          <button
            type="button"
            className="dir-picker-btn dir-picker-btn--primary"
            disabled={!result}
            onClick={() => result && onSelect(result.path)}
          >
            {t("dir_picker_select")}
          </button>
        </div>
      </div>
    </div>
  );
}

function FolderIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function FolderUpIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      <polyline points="12 12 12 8" />
      <polyline points="10 10 12 8 14 10" />
    </svg>
  );
}
