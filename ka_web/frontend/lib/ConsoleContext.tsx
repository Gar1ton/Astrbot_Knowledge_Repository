"use client";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getConsoleScopeState, upsertConsoleScopeState } from "@/lib/api";

interface HighlightedChunk {
  docId: string;
  chunkId: string;
}

interface ConsoleContextValue {
  selectedCollection: string | null;
  setSelectedCollection: (c: string | null) => void;

  selectedDocId: string | null;
  setSelectedDocId: (id: string | null) => void;

  highlightedChunk: HighlightedChunk | null;
  setHighlightedChunk: (h: HighlightedChunk | null) => void;

  noteDocId: string | null;
  setNoteDocId: (id: string | null) => void;

  settingOpen: boolean;
  setSettingOpen: (v: boolean) => void;

  astrBotOpen: boolean;
  setAstrBotOpen: (v: boolean) => void;

  workflowOpen: boolean;
  setWorkflowOpen: (v: boolean) => void;
}

const ConsoleContext = createContext<ConsoleContextValue>({
  selectedCollection: null,
  setSelectedCollection: () => {},
  selectedDocId: null,
  setSelectedDocId: () => {},
  highlightedChunk: null,
  setHighlightedChunk: () => {},
  noteDocId: null,
  setNoteDocId: () => {},
  settingOpen: false,
  setSettingOpen: () => {},
  astrBotOpen: false,
  setAstrBotOpen: () => {},
  workflowOpen: false,
  setWorkflowOpen: () => {},
});

export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [highlightedChunk, setHighlightedChunk] = useState<HighlightedChunk | null>(null);
  const [noteDocId, setNoteDocId] = useState<string | null>(null);
  const [settingOpen, setSettingOpen] = useState(false);
  const [astrBotOpen, setAstrBotOpen] = useState(false);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const hydratedRef = useRef(false);

  useEffect(() => {
    let alive = true;
    getConsoleScopeState("global", "console")
      .then((state) => {
        if (!alive) return;
        if (state) {
          setSelectedCollection(state.selected_collection || null);
          setSelectedDocId(state.selected_doc_id || null);
          setNoteDocId(state.note_doc_id || null);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (alive) hydratedRef.current = true;
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!hydratedRef.current || !selectedCollection) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      getConsoleScopeState("collection", selectedCollection)
        .then((state) => {
          if (!alive || !state) return;
          if (state.selected_doc_id) setSelectedDocId(state.selected_doc_id);
          if (state.note_doc_id) setNoteDocId(state.note_doc_id);
        })
        .catch(() => {});
    }, 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [selectedCollection]);

  useEffect(() => {
    if (!hydratedRef.current || !selectedDocId) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      getConsoleScopeState("document", selectedDocId)
        .then((state) => {
          if (!alive || !state) return;
          if (state.note_doc_id) setNoteDocId(state.note_doc_id);
        })
        .catch(() => {});
    }, 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [selectedDocId]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    const timer = window.setTimeout(() => {
      const baseState = {
        selected_collection: selectedCollection ?? "",
        selected_doc_id: selectedDocId ?? "",
        note_doc_id: noteDocId ?? "",
        right_panel: noteDocId ? "notes" : selectedDocId ? "document" : selectedCollection ? "collection" : "",
        reading_mode: "",
        payload: highlightedChunk ? { highlighted_chunk: highlightedChunk } : {},
      };
      const writes = [
        upsertConsoleScopeState({ scope_type: "global", scope_key: "console", ...baseState }),
      ];
      if (selectedCollection) {
        writes.push(
          upsertConsoleScopeState({
            scope_type: "collection",
            scope_key: selectedCollection,
            ...baseState,
          }),
        );
      }
      if (selectedDocId) {
        writes.push(
          upsertConsoleScopeState({
            scope_type: "document",
            scope_key: selectedDocId,
            ...baseState,
          }),
        );
      }
      Promise.all(writes).catch(() => {});
    }, 450);
    return () => window.clearTimeout(timer);
  }, [selectedCollection, selectedDocId, noteDocId, highlightedChunk]);

  return (
    <ConsoleContext.Provider
      value={{
        selectedCollection, setSelectedCollection,
        selectedDocId, setSelectedDocId,
        highlightedChunk, setHighlightedChunk,
        noteDocId, setNoteDocId,
        settingOpen, setSettingOpen,
        astrBotOpen, setAstrBotOpen,
        workflowOpen, setWorkflowOpen,
      }}
    >
      {children}
    </ConsoleContext.Provider>
  );
}

export function useConsole() {
  return useContext(ConsoleContext);
}
