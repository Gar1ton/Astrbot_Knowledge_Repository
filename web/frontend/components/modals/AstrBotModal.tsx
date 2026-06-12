"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/components/ds/Modal";
import { Badge } from "@/components/ds/Badge";
import { Button } from "@/components/ds/Button";
import { Icon } from "@/components/ds/Icon";
import { Select } from "@/components/ds/Select";
import { Toggle } from "@/components/ds/Toggle";
import { useToast } from "@/components/ui/Toast";
import { getEffectiveConfig, updateConfigValue, EffectiveConfig } from "@/lib/api";

interface AstrBotModalProps {
  onClose: () => void;
}

// ─── Shared primitives ────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{label}</div>
        {hint && (
          <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2, lineHeight: 1.45 }}>
            {hint}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

function Card({
  title,
  icon,
  badge,
  children,
}: {
  title: string;
  icon?: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-xl)",
        boxShadow: "var(--shadow-card)",
        padding: "4px 16px 12px",
        marginBottom: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 4px" }}>
        {icon && <Icon name={icon} size={16} style={{ color: "var(--accent)" }} />}
        <span style={{ fontSize: 13.5, fontWeight: 650, color: "var(--heading)", flex: 1 }}>
          {title}
        </span>
        {badge}
      </div>
      {children}
    </div>
  );
}

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
  const { toast } = useToast();
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // Derived values from config
  const embCfg = config?.embedding ?? {};
  const vecCfg = config?.vector_db ?? {};
  const graphCfg = config?.graph ?? {};
  const askCfg = config?.ask ?? {};

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
      if (r.rebuild_required) toast("配置已保存，Milvus 索引需重建", "info");
      else if (r.restart_required) toast("配置已保存，需重启插件生效", "info");
      else toast("已保存", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : "保存失败", "error");
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
      title="AstrBot 配置"
      icon="spark2"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            loading={saving !== null}
            onClick={onClose}
          >
            完成
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
            修改 Embedding 提供商 / 模型 / 接口后，Milvus 与各集合的 LightRAG 索引均需手动重建。部分项需重启插件生效。
          </div>
        </div>

        {/* Embedding */}
        <Card
          title="Embedding 运行时"
          icon="layers"
          badge={
            <Badge tone={embProvider === "local" ? "ok" : "accent"}>
              {embProvider === "local" ? "本地" : "API"}
            </Badge>
          }
        >
          <Field label="提供商" hint="本地离线 (sentence-transformers) 或云端 API">
            <Select
              value={embProvider}
              onChange={(v) => { setEmbProvider(v); save("embedding", "provider", v); }}
              options={[
                { value: "local", label: "本地 Embedding" },
                { value: "api", label: "API Embedding" },
              ]}
            />
          </Field>
          <Field label="模型名称">
            <input
              style={INPUT_STYLE}
              value={embModel}
              onChange={(e) => setEmbModel(e.target.value)}
              onBlur={() => save("embedding", "model", embModel)}
            />
          </Field>
          <Field label="向量维度" hint="由模型决定，只读">
            <Badge tone="neutral">{String(embDim)}</Badge>
          </Field>
          <Field label="API Key" hint="仅从环境变量 KR_EMBEDDING_API_KEY 读取">
            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>
              env-only
            </span>
          </Field>
        </Card>

        {/* Vector DB */}
        <Card title="向量数据库与检索后端" icon="db">
          <Field label="向量后端" hint="Milvus Lite 为默认必装向量库；AstrBot KB 仅保留为后端兜底，前端暂不可选择。">
            <Select
              value={vecBackend === "astr" || vecBackend === "astrbot" ? "milvus" : vecBackend}
              onChange={(v) => { setVecBackend(v); save("vector_db", "backend", v); }}
              options={[
                { value: "milvus", label: "Milvus Lite" },
              ]}
            />
          </Field>
          <Field label="自动索引" hint="上传后自动建立 Milvus 索引">
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
              {graphOn ? "已启用" : "关闭"}
            </Badge>
          }
        >
          <Field label="启用图谱索引" hint="手动触发构建，不随上传自动构建（成本隔离）">
            <Toggle
              checked={graphOn}
              onChange={(v) => { setGraphOn(v); save("graph", "enabled", v); }}
            />
          </Field>
          <Field label="检索模式" hint="mix 向量+图谱（推荐）">
            <Select
              value={lrMode}
              onChange={(v) => { setLrMode(v); save("graph", "lightrag_mode", v); }}
              options={[
                { value: "mix", label: "mix — 混合（推荐）" },
                { value: "local", label: "local — 本地图谱" },
                { value: "global", label: "global — 全局" },
                { value: "naive", label: "naive — 纯向量" },
              ]}
            />
          </Field>
          <Field label="LLM 并发上限" hint="默认 4，调高更快但易限流">
            <input
              style={{ ...INPUT_STYLE, width: 80, textAlign: "center" }}
              value={lrParallel}
              onChange={(e) => setLrParallel(e.target.value)}
              onBlur={() => save("graph", "llm_parallel", lrParallel)}
            />
          </Field>
          <Field label="工作目录" hint="只读，需改配置文件并重启">
            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>
              {(graphCfg.workspace as string) ?? "lightrag_workspaces"}
            </span>
          </Field>
        </Card>

        {/* Research Agent */}
        <Card title="Research Agent (Ask)" icon="sparkle">
          <Field label="对话增强模式">
            <Select
              value={agentMode}
              onChange={(v) => { setAgentMode(v); save("ask", "ask_mode", v); }}
              options={[
                { value: "inject", label: "注入增强" },
                { value: "agent", label: "代理增强" },
              ]}
            />
          </Field>
          <Field label="默认 Top-K">
            <input
              style={{ ...INPUT_STYLE, width: 80, textAlign: "center" }}
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              onBlur={() => save("ask", "top_k", topK)}
            />
          </Field>
          <Field label="展示引用来源" hint="cite_sources">
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
