"use client";
import React, { useContext } from "react";
import Image from "next/image";
import { useConsole } from "@/lib/ConsoleContext";
import { Button } from "@/components/ds/Button";
import { IconButton } from "@/components/ds/IconButton";
import { Icon } from "@/components/ds/Icon";
import { I18nContext } from "@/lib/i18n";
import { logout } from "@/lib/api";

interface TopBarProps {
  onLogout: () => void;
}

export function TopBar({ onLogout }: TopBarProps) {
  const { setSettingOpen, setAstrBotOpen, setWorkflowOpen } = useConsole();
  const { lang, setLang, t } = useContext(I18nContext);

  async function handleLogout() {
    await logout();
    onLogout();
  }

  return (
    <div
      className="fx-glass"
      style={{
        height: "var(--topbar-h)",
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "0 14px",
        position: "relative",
        zIndex: 10,
      }}
    >
      {/* Brand */}
      <span
        style={{
          width: 24,
          height: 24,
          borderRadius: 6,
          background: "var(--accent)",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          overflow: "hidden",
        }}
      >
        <Image
          src="/mark-sparkle.svg"
          alt=""
          width={16}
          height={16}
          style={{ filter: "brightness(0) invert(1)" }}
          onError={() => {}}
        />
      </span>
      <span
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: "var(--heading)",
          letterSpacing: "-.01em",
          flexShrink: 0,
        }}
      >
        Knowledge Repository
      </span>

      <span style={{ flex: 1 }} />

      {/* Modal trigger buttons */}
      <Button
        variant="tab"
        size="sm"
        style={{ height: 30, gap: 6 }}
        onClick={() => setSettingOpen(true)}
      >
        <Icon name="settings" size={14} /> {t("topbar_settings")}
      </Button>
      <Button
        variant="tab"
        size="sm"
        style={{ height: 30, gap: 6 }}
        onClick={() => setAstrBotOpen(true)}
      >
        <Icon name="spark2" size={14} /> AstrBot
      </Button>
      <Button
        variant="tab"
        size="sm"
        style={{ height: 30, gap: 6 }}
        onClick={() => setWorkflowOpen(true)}
      >
        <Icon name="flow" size={14} /> {t("topbar_workflow")}
      </Button>

      <span style={{ width: 6 }} />

      {/* Theme & logout */}
      <IconButton
        name={lang === "zh" ? "globe" : "globe"}
        label={lang === "zh" ? t("topbar_switch_to_en") : t("topbar_switch_to_zh")}
        onClick={() => setLang(lang === "zh" ? "en" : "zh")}
      />
      <IconButton name="arrowUp" label={t("nav_logout")} side="left" onClick={handleLogout} />
    </div>
  );
}
