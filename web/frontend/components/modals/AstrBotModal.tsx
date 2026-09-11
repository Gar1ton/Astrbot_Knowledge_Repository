"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/components/ds/Modal";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Card, Field } from "@/components/ds/Card";
import { Icon } from "@/components/ds/Icon";
import { Select } from "@/components/ds/Select";
import { Toggle } from "@/components/ds/Toggle";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import { getEffectiveConfig, updateConfigValue, EffectiveConfig } from "@/lib/api";

interface AstrBotModalProps {
  onClose: () => void;
}

// ─── Shared primitives ────────────────────────────────────────

const INPUT_STYLE: React.CSSProperties = {
  height: 30,
  padding: "0 10px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface)",
  color: "var(--fg)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
  width: 230,
  outline: "none",
};

// ─── AstrBotModal ─────────────────────────────────────────────

export function AstrBotModal({ onClose }: AstrBotModalProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // Derived values from config
  const embCfg = config?.embedding ?? {};
  const graphCfg = config?.graph ?? {};

  const [graphOn, setGraphOn] = useState(true);
  const [autoIdx, setAutoIdx] = useState(true);
  const [citeSources, setCiteSources] = useState(true);
  const [embProvider, setEmbProvider] = useState("local");
  const [embModel, setEmbModel] = useState("intfloat/multilingual-e5-small");
  const [vecBackend, setVecBackend] = useState("milvus");
  const [lrMode, setLrMode] = useState("mix");
  const [lrParallel, setLrParallel] = useState("4");
  const [topK, setTopK] = useState("5");
  const [agentMode, setAgentMode] = useState("inject");

  useEffect(() => {
    getEffectiveConfig()
      .then((cfg) => {
        setConfig(cfg);
        const emb = cfg.embedding ?? {};
        const vdb = cfg.vector_db ?? {};
        const grp = cfg.graph ?? {};
        const ask = cfg.ask ?? {};

        if (emb.provider) setEmbProvider(String(emb.provider));
        if (emb.model) setEmbModel(String(emb.model));
        if (vdb.backend) setVecBackend(String(vdb.backend));
        if (vdb.auto_index !== undefined) setAutoIdx(Boolean(vdb.auto_index));
        if (grp.enabled !== undefined) setGraphOn(Boolean(grp.enabled));
        if (grp.lightrag_mode) setLrMode(String(grp.lightrag_mode));
        if (grp.llm_parallel) setLrParallel(String(grp.llm_parallel));
        if (ask.top_k) setTopK(String(ask.top_k));
        if (ask.ask_mode) setAgentMode(String(ask.ask_mode));
        if (ask.cite_sources !== undefined) setCiteSources(Boolean(ask.cite_sources));
      })
      .catch(() => {});
  }, []);

  async function save(section: string, key: string, value: string | boolean) {
    const id = `${section}.${key}`;
    setSaving(id);
    try {
      const r = await updateConfigValue(section, key, value);
      if (r.rebuild_required) toast(t("astrbot_saved_rebuild"), "info");
      else if (r.restart_required) toast(t("astrbot_saved_restart"), "info");
      else toast(t("astrbot_saved"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : t("astrbot_save_failed"), "error");
    } finally {
      setSaving(null);
    }
  }

  const embDim =
    embCfg.dims ??
    embCfg.dimension ??
    embCfg.vector_dim ??
    embCfg.dim ??
    "—";

  return (
    <Modal
      title={t("astrbot_modal_title")}
      icon="spark2"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("btn_cancel")}
          </Button>
          <Button
            variant="primary"
            loading={saving !== null}
            onClick={onClose}
          >
            {t("astrbot_btn_done")}
          </Button>
        </>
      }
    >
      <div style={{ padding: "18px 22px" }}>
        {/* Warning banner */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "11px 13px",
            background: "color-mix(in srgb, var(--warn) 10%, transparent)",
            border: "1px solid color-mix(in srgb, var(--warn) 28%, transparent)",
            borderRadius: "var(--radius-lg)",
            marginBottom: 16,
          }}
        >
          <Icon name="spark2" size={16} style={{ color: "var(--warn)", marginTop: 1 }} />
          <div style={{ fontSize: 12, color: "var(--fg)", lineHeight: 1.55 }}>
            {t("astrbot_warning")}
          </div>
        </div>

        {/* Embedding */}
        <Card
          title={t("astrbot_card_embedding")}
          icon="layers"
          badge={
            <Badge tone={embProvider === "local" ? "ok" : "accent"}>
              {embProvider === "local" ? t("astrbot_badge_local") : t("astrbot_badge_api")}
            </Badge>
          }
        >
          <Field label={t("astrbot_field_provider")} hint={t("astrbot_field_provider_hint")}>
            <Select
              value={embProvider}
              onChange={(v) => { setEmbProvider(v); save("embedding", "provider", v); }}
              options={[
                { value: "local", label: t("astrbot_opt_local_embedding") },
                { value: "api", label: t("astrbot_opt_api_embedding") },
              ]}
            />
          </Field>
          <Field label={t("astrbot_field_model")}>
            <input
              style={INPUT_STYLE}
              value={embModel}
              onChange={(e) => setEmbModel(e.target.value)}
              onBlur={() => save("embedding", "model", embModel)}
            />
          </Field>
          <Field label={t("astrbot_field_dim")} hint={t("astrbot_field_dim_hint")}>
            <Badge tone="neutral">{String(embDim)}</Badge>
          </Field>
          <Field label={t("astrbot_field_api_key")} hint={t("astrbot_field_api_key_hint")}>
            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>
              env-only
            </span>
          </Field>
        </Card>

        {/* Vector DB */}
        <Card title={t("astrbot_card_vector")} icon="db">
          <Field label={t("astrbot_field_backend")} hint={t("astrbot_field_backend_hint")}>
            <Select
              value={vecBackend === "astr" || vecBackend === "astrbot" ? "milvus" : vecBackend}
              onChange={(v) => { setVecBackend(v); save("vector_db", "backend", v); }}
              options={[
                { value: "milvus", label: "Milvus Lite" },
              ]}
            />
          </Field>
          <Field label={t("astrbot_field_auto_index")} hint={t("astrbot_field_auto_index_hint")}>
            <Toggle
              checked={autoIdx}
              onChange={(v) => { setAutoIdx(v); save("vector_db", "auto_index", v); }}
            />
          </Field>
        </Card>

        {/* LightRAG Core */}
        <Card
          title="LightRAG Core"
          icon="graph"
          badge={
            <Badge tone={graphOn ? "violet" : "neutral"}>
              {graphOn ? t("astrbot_badge_graph_on") : t("astrbot_badge_graph_off")}
            </Badge>
          }
        >
          <Field label={t("astrbot_field_graph_enabled")} hint={t("astrbot_field_graph_enabled_hint")}>
            <Toggle
              checked={graphOn}
              onChange={(v) => { setGraphOn(v); save("graph", "enabled", v); }}
            />
          </Field>
          <Field label={t("astrbot_field_lr_mode")} hint={t("astrbot_field_lr_mode_hint")}>
            <Select
              value={lrMode}
              onChange={(v) => { setLrMode(v); save("graph", "lightrag_mode", v); }}
              options={[
                { value: "mix", label: t("astrbot_opt_lr_mix") },
                { value: "local", label: t("astrbot_opt_lr_local") },
                { value: "global", label: t("astrbot_opt_lr_global") },
                { value: "naive", label: t("astrbot_opt_lr_naive") },
              ]}
            />
          </Field>
          <Field label={t("astrbot_field_llm_parallel")} hint={t("astrbot_field_llm_parallel_hint")}>
            <input
              style={{ ...INPUT_STYLE, width: 80, textAlign: "center" }}
              value={lrParallel}
              onChange={(e) => setLrParallel(e.target.value)}
              onBlur={() => save("graph", "llm_parallel", lrParallel)}
            />
          </Field>
          <Field label={t("astrbot_field_workspace")} hint={t("astrbot_field_workspace_hint")}>
            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>
              {(graphCfg.workspace as string) ?? "lightrag_workspaces"}
            </span>
          </Field>
        </Card>

        {/* Research Agent */}
        <Card title="Research Agent (Ask)" icon="sparkle">
          <Field label={t("astrbot_field_ask_mode")}>
            <Select
              value={agentMode}
              onChange={(v) => { setAgentMode(v); save("ask", "ask_mode", v); }}
              options={[
                { value: "inject", label: t("astrbot_opt_ask_inject") },
                { value: "agent", label: t("astrbot_opt_ask_agent") },
              ]}
            />
          </Field>
          <Field label={t("astrbot_field_topk")}>
            <input
              style={{ ...INPUT_STYLE, width: 80, textAlign: "center" }}
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              onBlur={() => save("ask", "top_k", topK)}
            />
          </Field>
          <Field label={t("astrbot_field_cite")} hint="cite_sources">
            <Toggle
              checked={citeSources}
              onChange={(v) => { setCiteSources(v); save("ask", "cite_sources", v); }}
            />
          </Field>
        </Card>
      </div>
    </Modal>
  );
}
