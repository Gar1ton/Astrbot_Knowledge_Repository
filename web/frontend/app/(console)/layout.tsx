"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { ToastProvider } from "@/components/ui/Toast";
import { I18nContext, Lang, makeT } from "@/lib/i18n";
import { initPalette } from "@/lib/theme";
import { getAuth } from "@/lib/api";
import { ConsoleProvider, useConsole } from "@/lib/ConsoleContext";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { ProgressDock } from "@/components/progress/ProgressDock";
import { TopBar } from "@/components/layout/TopBar";
import { FilePanel } from "@/components/panels/FilePanel";
import { DocumentsPanel } from "@/components/panels/DocumentsPanel";
import { ChatPanel } from "@/components/panels/ChatPanel";
import { NotePanel } from "@/components/panels/NotePanel";
import { WorkflowModal } from "@/components/modals/WorkflowModal";
import { SettingModal } from "@/components/modals/SettingModal";
import { AstrBotModal } from "@/components/modals/AstrBotModal";

// ─── I18n Provider ────────────────────────────────────────────

function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    if (typeof localStorage === "undefined") return "zh";
    const saved = localStorage.getItem("kr-lang");
    return saved === "en" ? "en" : "zh";
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    if (typeof localStorage !== "undefined") localStorage.setItem("kr-lang", l);
    if (typeof document !== "undefined") document.documentElement.lang = l;
  }, []);

  useEffect(() => {
    initPalette();
  }, []);

  return (
    <I18nContext.Provider value={{ lang, setLang, t: makeT(lang) }}>
      {children}
    </I18nContext.Provider>
  );
}

// ─── Three-panel canvas ───────────────────────────────────────

const DEFAULT_CHAT_W = 360;
const MIN_CHAT_W = 280;
const DEFAULT_FILE_W = 264;
const MIN_FILE_W = 200;
const MAX_FILE_W = 528;

type DragTarget = "file" | "chat" | null;

function ConsoleCanvas({ onLogout }: { onLogout: () => void }) {
  const { noteDocId, selectedDocId, selectedCollection, settingOpen, setSettingOpen, astrBotOpen, setAstrBotOpen, workflowOpen, setWorkflowOpen } = useConsole();

  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_W);
  const [fileWidth, setFileWidth] = useState(DEFAULT_FILE_W);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragTarget = useRef<DragTarget>(null);
  const startX = useRef(0);
  const startChatWidth = useRef(DEFAULT_CHAT_W);
  const startFileWidth = useRef(DEFAULT_FILE_W);
  const [fileDividerHover, setFileDividerHover] = useState(false);
  const [chatDividerHover, setChatDividerHover] = useState(false);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragTarget.current || !containerRef.current) return;
      if (dragTarget.current === "file") {
        const delta = e.clientX - startX.current;
        const next = Math.max(MIN_FILE_W, Math.min(MAX_FILE_W, startFileWidth.current + delta));
        setFileWidth(next);
      } else {
        // chat: dragging left increases chat width
        const totalPadGap = 40;
        const availableWidth = containerRef.current.clientWidth - fileWidth - totalPadGap;
        const maxChatWidth = availableWidth / 2;
        const delta = startX.current - e.clientX;
        const next = Math.max(MIN_CHAT_W, Math.min(maxChatWidth, startChatWidth.current + delta));
        setChatWidth(next);
      }
    };
    const onMouseUp = () => { dragTarget.current = null; };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, [fileWidth]);

  const handleFileDragStart = useCallback((e: React.MouseEvent) => {
    dragTarget.current = "file";
    startX.current = e.clientX;
    startFileWidth.current = fileWidth;
    e.preventDefault();
  }, [fileWidth]);

  const handleChatDragStart = useCallback((e: React.MouseEvent) => {
    dragTarget.current = "chat";
    startX.current = e.clientX;
    startChatWidth.current = chatWidth;
    e.preventDefault();
  }, [chatWidth]);

  useEffect(() => {
    const isLightRAG = selectedCollection?.startsWith("lr:") ?? false;
    document.documentElement.dataset.mode = isLightRAG ? "lightrag" : "";
  }, [selectedCollection]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <TopBar />

      {/* Three-panel stage */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          padding: "0 var(--panel-gap) var(--panel-gap)",
          overflow: "hidden",
        }}
      >
        {/* Left: File OR Note */}
        <div
          style={{
            width: fileWidth,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          {(selectedDocId || noteDocId) ? (
            <NotePanel docId={selectedDocId ?? noteDocId!} />
          ) : (
            <FilePanel />
          )}
        </div>

        {/* File drag handle */}
        <div
          onMouseDown={handleFileDragStart}
          onMouseEnter={() => setFileDividerHover(true)}
          onMouseLeave={() => setFileDividerHover(false)}
          style={{
            width: "var(--panel-gap)",
            flexShrink: 0,
            cursor: "col-resize",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            userSelect: "none",
          }}
        >
          <div
            style={{
              width: 2,
              height: 40,
              borderRadius: 1,
              background: fileDividerHover ? "var(--border-strong)" : "var(--border)",
              transition: "background .15s",
            }}
          />
        </div>

        {/* Middle: Documents */}
        <DocumentsPanel />

        {/* Chat drag handle */}
        <div
          onMouseDown={handleChatDragStart}
          onMouseEnter={() => setChatDividerHover(true)}
          onMouseLeave={() => setChatDividerHover(false)}
          style={{
            width: "var(--panel-gap)",
            flexShrink: 0,
            cursor: "col-resize",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            userSelect: "none",
          }}
        >
          <div
            style={{
              width: 2,
              height: 40,
              borderRadius: 1,
              background: chatDividerHover ? "var(--border-strong)" : "var(--border)",
              transition: "background .15s",
            }}
          />
        </div>

        {/* Right: Chat */}
        <ChatPanel width={chatWidth} />
      </div>

      {/* Full-screen modals */}
      {settingOpen && <SettingModal onClose={() => setSettingOpen(false)} onLogout={onLogout} />}
      {astrBotOpen && <AstrBotModal onClose={() => setAstrBotOpen(false)} />}
      {workflowOpen && <WorkflowModal onClose={() => setWorkflowOpen(false)} />}
    </div>
  );
}

// ─── Console Shell (auth gate) ────────────────────────────────

function ConsoleShell() {
  const [authChecked, setAuthChecked] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    getAuth()
      .then(({ logged_in }) => {
        setLoggedIn(logged_in);
        setAuthChecked(true);
      })
      .catch(() => {
        setLoggedIn(false);
        setAuthChecked(true);
      });
  }, []);

  const handleLogout = useCallback(() => {
    setLoggedIn(false);
  }, []);

  if (!authChecked) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: "var(--bg)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--fg-muted)",
          fontSize: 13,
        }}
      >
        加载中...
      </div>
    );
  }

  if (!loggedIn) {
    return <LoginScreen onLogin={() => setLoggedIn(true)} />;
  }

  return (
    <ConsoleProvider>
      <ConsoleCanvas onLogout={handleLogout} />
      <ProgressDock />
    </ConsoleProvider>
  );
}

// ─── Layout Export ────────────────────────────────────────────

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  void children;
  return (
    <ToastProvider>
      <I18nProvider>
        <ConsoleShell />
      </I18nProvider>
    </ToastProvider>
  );
}
