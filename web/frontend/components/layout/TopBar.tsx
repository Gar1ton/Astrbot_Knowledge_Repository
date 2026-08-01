"use client";
import React, { useEffect, useState } from "react";
import Image from "next/image";
import { useConsole } from "@/lib/ConsoleContext";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { useI18n } from "@/lib/i18n";
import { getCapabilities, getModelRuntime } from "@/lib/api";
import { deriveWorkflowStatus, type WorkflowStatus } from "@/lib/flowHealth";
import { deriveModelStatus, type ModelStatus } from "@/lib/modelHealth";
import { Z } from "@/lib/zLayers";

export function TopBar() {
  const { setSettingOpen, setAstrBotOpen, setWorkflowOpen, setModelsOpen } = useConsole();
  const { t } = useI18n();
  const [wfStatus, setWfStatus] = useState<WorkflowStatus>("red");
  const [modelStatus, setModelStatus] = useState<ModelStatus>("green");

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

  // 模型驻留态单独轮询：节奏比能力探测慢一档，且这个端点绝不触发模型加载。
  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const runtime = await getModelRuntime();
        if (alive) setModelStatus(deriveModelStatus(runtime));
      } catch {
        if (alive) setModelStatus("red");
      } finally {
        inFlight = false;
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 8000);
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
        zIndex: Z.raised,
      }}
    >
      {/* Brand */}
      <Image
        src="/knowledge-arch-icon.svg"
        alt="Knowledge Arch"
        width={28}
        height={28}
        style={{ borderRadius: "var(--radius-md)", flexShrink: 0 }}
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
      {/* 显存/模型驻留：与数据流共用 wf-pulse-* 呼吸光效，语义为「绿=已让出显存」。 */}
      <span className={`wf-pulse-${modelStatus}`}>
        <Button
          variant="tab"
          size="sm"
          style={{ height: 30, gap: 6 }}
          onClick={() => setModelsOpen(true)}
        >
          <Icon name="chip" size={14} /> {t("topbar_models")}
        </Button>
      </span>
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
