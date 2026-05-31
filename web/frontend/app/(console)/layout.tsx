"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Rail } from "@/components/rail/Rail";
import { GrainOverlay } from "@/components/fx/GrainOverlay";
import { ToastProvider, useToast } from "@/components/ui/Toast";
import { I18nContext, Lang, makeT } from "@/lib/i18n";
import { initPalette } from "@/lib/theme";
import { getAuth, login, logout } from "@/lib/api";

// ─── 登录页面 ─────────────────────────────────────────────────

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { toast } = useToast();

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(username, password);
      onLogin();
    } catch {
      setError("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "var(--bg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      {/* Aurora 背景 */}
      <div
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          pointerEvents: "none",
          background:
            "radial-gradient(ellipse at 20% 20%, var(--accent-soft) 0%, transparent 50%), radial-gradient(ellipse at 80% 80%, var(--accent-2-soft) 0%, transparent 50%)",
          opacity: 0.7,
        }}
      />

      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 16,
          padding: 32,
          width: 320,
          boxShadow: "var(--shadow-pop)",
          position: "relative",
          zIndex: 1,
        }}
      >
        <h1
          style={{
            margin: "0 0 4px",
            fontSize: 16,
            fontWeight: 700,
            color: "var(--heading)",
            letterSpacing: "-0.02em",
          }}
        >
          Knowledge Repository
        </h1>
        <p style={{ margin: "0 0 20px", fontSize: 13, color: "var(--fg-muted)" }}>
          控制台登录
        </p>

        <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoFocus
            required
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码"
            required
          />
          <button
            type="submit"
            disabled={loading}
            style={{
              background: "var(--accent)",
              color: "var(--accent-fg)",
              border: "none",
              borderRadius: 999,
              padding: "9px 0",
              fontSize: 14,
              fontWeight: 600,
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.7 : 1,
              transition: "opacity 0.15s",
              fontFamily: "inherit",
            }}
          >
            {loading ? "登录中..." : "登录"}
          </button>
          {error && (
            <p style={{ margin: 0, fontSize: 12, color: "var(--danger)", textAlign: "center" }}>
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

// ─── I18n Provider ────────────────────────────────────────────

function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("zh");

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("kr-lang", l);
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = l;
    }
  }, []);

  useEffect(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem("kr-lang")) as Lang | null;
    if (saved === "zh" || saved === "en") setLangState(saved);
    initPalette();
  }, []);

  const t = makeT(lang);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

// ─── Console Shell ────────────────────────────────────────────

function ConsoleShell({ children }: { children: React.ReactNode }) {
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

  const handleLogout = useCallback(async () => {
    await logout();
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
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Rail onLogout={handleLogout} />
      <main
        style={{
          flex: 1,
          minWidth: 0,
          overflowX: "hidden",
          position: "relative",
        }}
      >
        {children}
      </main>
    </div>
  );
}

// ─── Layout Export ────────────────────────────────────────────

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <I18nProvider>
        <GrainOverlay />
        <ConsoleShell>{children}</ConsoleShell>
      </I18nProvider>
    </ToastProvider>
  );
}
