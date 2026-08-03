"use client";
import React from "react";
import { Button } from "@/components/ds/Button";
import { Modal } from "@/components/ds/Modal";
import { ModelRuntimePanel, useModelRuntime } from "@/components/panels/ModelRuntimePanel";
import { useI18n } from "@/lib/i18n";

interface ModelsModalProps {
  onClose: () => void;
}

export function ModelsModal({ onClose }: ModelsModalProps) {
  const { t } = useI18n();
  const { runtime, busy, error, doUnload } = useModelRuntime();

  return (
    <Modal
      title={t("models_modal_title")}
      icon="chip"
      onClose={onClose}
      width={580}
      height="auto"
      footer={
        <>
          <span
            style={{
              flex: 1,
              minWidth: 0,
              fontSize: 11,
              lineHeight: 1.5,
              color: "var(--fg-subtle)",
            }}
          >
            {t("models_unload_hint")}
          </span>
          <Button
            variant="primary"
            disabled={busy || (runtime?.resident_count ?? 0) === 0}
            onClick={() => void doUnload()}
          >
            {t("models_unload_all")}
          </Button>
        </>
      }
    >
      <ModelRuntimePanel
        runtime={runtime}
        busy={busy}
        error={error}
        onUnload={(kinds) => void doUnload(kinds)}
      />
    </Modal>
  );
}
