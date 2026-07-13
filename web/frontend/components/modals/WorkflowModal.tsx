"use client";
import React from "react";
import { Modal } from "@/components/ds/Modal";
import { FlowPageContent } from "@/components/panels/FlowPageContent";
import { useI18n } from "@/lib/i18n";

interface WorkflowModalProps {
  onClose: () => void;
}

export function WorkflowModal({ onClose }: WorkflowModalProps) {
  const { t } = useI18n();

  return (
    <Modal
      title={t("workflow_modal_title")}
      icon="flow"
      onClose={onClose}
      fullscreen
      style={{ width: "100vw", height: "100vh" }}
      contentStyle={{
        flex: "1 1 auto",
        minHeight: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <FlowPageContent onClose={onClose} />
    </Modal>
  );
}
