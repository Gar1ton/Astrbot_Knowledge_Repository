"use client";
import React, { useEffect, useState } from "react";
import Image from "next/image";
import { useConsole } from "@/lib/ConsoleContext";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { useI18n } from "@/lib/i18n";
import { getCapabilities } from "@/lib/api";
import { deriveWorkflowStatus, type WorkflowStatus } from "@/lib/flowHealth";

export function TopBar() {
  const { setSettingOpen, setAstrBotOpen, setWorkflowOpen } = useConsole();
  const { t } = useI18n();
  const [wfStatus, setWfStatus] = useState<WorkflowStatus>("red");

  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const caps = await getCapabilities();
        if (alive) setWfStatus(deriveWorkflowStatus(caps));
      } catch {
        if (alive) setWfStatus("red");
      } finally {
        inFlight = false;
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

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
      <Image
        src="/knowledge-arch-icon.svg"
        alt="Knowledge Arch"
        width={28}
        height={28}
        style={{ borderRadius: 7, flexShrink: 0 }}
      />
      <span
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: "var(--heading)",
          letterSpacing: "-.01em",
          flexShrink: 0,
        }}
      >
        Knowledge Arch
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
      <span className={`wf-pulse-${wfStatus}`}>
        <Button
          variant="tab"
          size="sm"
          style={{ height: 30, gap: 6 }}
          onClick={() => setWorkflowOpen(true)}
        >
          <Icon name="flow" size={14} /> {t("topbar_workflow")}
        </Button>
      </span>
    </div>
  );
}
