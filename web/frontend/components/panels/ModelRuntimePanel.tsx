"use client";
import React, { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Card, Field } from "@/components/ds/Card";
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

/**
 * 显存与模型驻留状态的拉取与卸载动作。
 *
 * 单列成 hook 是因为「全部卸载」按钮按 DS 惯例属于 Modal 的 footer，而正文在 body——
 * 两处需要同一份 runtime/busy 状态，状态因此必须由 ModelsModal 持有。
 */
export function useModelRuntime() {
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

  return { runtime, busy, error, doUnload };
}

function ModelRow({
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
  const label = t(entry.kind === "embedding" ? "models_kind_embedding" : "models_kind_rerank");
  const hint = `${entry.model || "—"}${entry.device ? ` · ${entry.device}` : ""}`;
  return (
    <Field
      label={label}
      hint={entry.last_error ? `${hint} · ${entry.last_error}` : hint}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Badge tone={STATE_TONE[entry.state] ?? "neutral"}>
          {t(`models_state_${entry.state}` as never)}
        </Badge>
        <Button size="sm" variant="tab" disabled={busy || !resident} onClick={onUnload}>
          {t("models_unload_one")}
        </Button>
      </div>
    </Field>
  );
}

export function ModelRuntimePanel({
  runtime,
  busy,
  error,
  onUnload,
}: {
  runtime: ModelRuntime | null;
  busy: boolean;
  error: string;
  onUnload: (kinds?: string[]) => void;
}) {
  const { t } = useI18n();
  const accelerator = runtime?.accelerator ?? null;
  const models = runtime?.models ?? [];

  return (
    <div style={{ padding: "18px 22px" }}>
      {error && (
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            background: "color-mix(in srgb, var(--danger) 10%, transparent)",
            border: "1px solid color-mix(in srgb, var(--danger) 28%, transparent)",
            borderRadius: "var(--radius-lg)",
            marginBottom: 16,
            padding: "11px 13px",
          }}
        >
          <Icon name="spark2" size={16} style={{ color: "var(--danger)", flexShrink: 0 }} />
          <span style={{ fontSize: 12, lineHeight: 1.55, color: "var(--fg)" }}>{error}</span>
        </div>
      )}

      {/* 显存概览：读不到加速器时整块降级为「CPU 模式」，而不是报错。 */}
      <Card
        title={t("models_vram_section")}
        icon="chip"
        badge={
          <Badge tone={accelerator ? "accent" : "neutral"}>
            {accelerator ? t("models_vram_badge_gpu") : t("models_vram_badge_cpu")}
          </Badge>
        }
      >
        {accelerator ? (
          <>
            <Field label={t("models_vram_device")}>
              <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg)" }}>
                {accelerator.device}
              </span>
            </Field>
            <Field label={t("models_vram_used")} hint={t("models_vram_used_hint")}>
              <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg)" }}>
                {formatBytes(accelerator.used_bytes)} / {formatBytes(accelerator.total_bytes)}
              </span>
            </Field>
            <Field label={t("models_vram_process")} hint={t("models_vram_process_hint")}>
              <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg)" }}>
                {formatBytes(accelerator.reserved_bytes)}
              </span>
            </Field>
          </>
        ) : (
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.55,
              color: "var(--fg-muted)",
              padding: "4px 0 8px",
            }}
          >
            {t("models_cpu_mode")}
          </div>
        )}
      </Card>

      <Card title={t("models_list_section")} icon="layers">
        {models.length > 0 ? (
          models.map((entry) => (
            <ModelRow
              key={entry.kind}
              entry={entry}
              busy={busy}
              onUnload={() => onUnload([entry.kind])}
            />
          ))
        ) : (
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.55,
              color: "var(--fg-subtle)",
              padding: "4px 0 8px",
            }}
          >
            {runtime ? t("models_none") : t("models_loading")}
          </div>
        )}
      </Card>
    </div>
  );
}
