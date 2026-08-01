"use client";
import React, { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { getModelRuntime, unloadModels, type ModelRuntime, type ModelRuntimeEntry } from "@/lib/api";
import { formatBytes } from "@/lib/modelHealth";

const STATE_TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = {
  ready: "ok",
  loading: "warn",
  failed: "danger",
  idle: "neutral",
  external: "neutral",
};

function ModelCard({
  entry,
  busy,
  onUnload,
}: {
  entry: ModelRuntimeEntry;
  busy: boolean;
  onUnload: () => void;
}) {
  const { t } = useI18n();
  const resident = entry.state === "ready" || entry.state === "loading";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 12px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border)",
        background: "var(--surface)",
        marginBottom: 8,
      }}
    >
      <Icon name="chip" size={16} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--heading)" }}>
            {t(entry.kind === "embedding" ? "models_kind_embedding" : "models_kind_rerank")}
          </span>
          <Badge tone={STATE_TONE[entry.state] ?? "neutral"}>
            {t(`models_state_${entry.state}` as never)}
          </Badge>
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--fg-muted)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {entry.model || "—"}
          {entry.device ? ` · ${entry.device}` : ""}
        </div>
        {entry.last_error && (
          <div style={{ fontSize: 10.5, color: "var(--danger)", marginTop: 2 }}>
            {entry.last_error}
          </div>
        )}
      </div>
      <Button size="sm" variant="tab" disabled={busy || !resident} onClick={onUnload}>
        {t("models_unload_one")}
      </Button>
    </div>
  );
}

export function ModelRuntimePanel() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [runtime, setRuntime] = useState<ModelRuntime | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setRuntime(await getModelRuntime());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const doUnload = useCallback(
    async (kinds?: string[]) => {
      setBusy(true);
      try {
        const next = await unloadModels(kinds);
        setRuntime(next);
        const failed = Object.keys(next.errors ?? {});
        if (failed.length > 0) toast(t("models_unload_partial"), "error");
        else toast(t("models_unload_done"), "ok");
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "error");
      } finally {
        setBusy(false);
      }
    },
    [t, toast],
  );

  const accelerator = runtime?.accelerator ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* 显存概览：读不到加速器时整块降级为「CPU 模式」，而不是报错。 */}
      <div
        style={{
          padding: "12px 14px",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border-strong)",
          background: "var(--bg-inset)",
        }}
      >
        {accelerator ? (
          <>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--heading)", marginBottom: 6 }}>
              {accelerator.device}
            </div>
            <div style={{ display: "flex", gap: 18, fontSize: 11.5, color: "var(--fg-muted)" }}>
              <span>
                {t("models_vram_used")}{" "}
                <strong style={{ color: "var(--fg)" }}>
                  {formatBytes(accelerator.used_bytes)} / {formatBytes(accelerator.total_bytes)}
                </strong>
              </span>
              <span>
                {t("models_vram_process")}{" "}
                <strong style={{ color: "var(--fg)" }}>
                  {formatBytes(accelerator.reserved_bytes)}
                </strong>
              </span>
            </div>
          </>
        ) : (
          <div style={{ fontSize: 11.5, color: "var(--fg-muted)" }}>{t("models_cpu_mode")}</div>
        )}
      </div>

      {error && <div style={{ fontSize: 11.5, color: "var(--danger)" }}>{error}</div>}

      <div>
        {(runtime?.models ?? []).map((entry) => (
          <ModelCard
            key={entry.kind}
            entry={entry}
            busy={busy}
            onUnload={() => void doUnload([entry.kind])}
          />
        ))}
        {runtime && runtime.models.length === 0 && (
          <div style={{ fontSize: 11.5, color: "var(--fg-subtle)" }}>{t("models_none")}</div>
        )}
      </div>

      <Button
        variant="primary"
        disabled={busy || (runtime?.resident_count ?? 0) === 0}
        onClick={() => void doUnload()}
      >
        {t("models_unload_all")}
      </Button>
      <div style={{ fontSize: 10.5, lineHeight: 1.6, color: "var(--fg-subtle)" }}>
        {t("models_unload_hint")}
      </div>
    </div>
  );
}
