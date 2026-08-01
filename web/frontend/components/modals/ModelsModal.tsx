"use client";
import React from "react";
import { Modal } from "@/components/ds/Modal";
import { ModelRuntimePanel } from "@/components/panels/ModelRuntimePanel";
import { useI18n } from "@/lib/i18n";

interface ModelsModalProps {
  onClose: () => void;
}

export function ModelsModal({ onClose }: ModelsModalProps) {
  const { t } = useI18n();

  return (
    <Modal title={t("models_modal_title")} icon="chip" onClose={onClose} width={520} height="auto">
      <ModelRuntimePanel />
    </Modal>
  );
}
