/* Knowledge Repository · AstrBot modal — AstrBot-related config (embedding / vector DB / LightRAG core / Ask). */
(function () {
  const { Modal, Button, Toggle, Select, Badge, Tag, Eyebrow } = window.KRUI;
  const Icon = window.KRIcon;

  function Field({ label, children, hint }) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: "1px solid var(--border)" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{label}</div>
          {hint && <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 2, lineHeight: 1.45 }}>{hint}</div>}
        </div>
        <div style={{ flexShrink: 0 }}>{children}</div>
      </div>
    );
  }
  function Card({ title, icon, children, badge }) {
    return (
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-xl)", boxShadow: "var(--shadow-card)", padding: "4px 16px 12px", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 4px" }}>
          {icon && <Icon name={icon} size={16} style={{ color: "var(--accent)" }} />}
          <span style={{ fontSize: 13.5, fontWeight: 650, color: "var(--heading)", flex: 1 }}>{title}</span>
          {badge}
        </div>
        {children}
      </div>
    );
  }
  const inputStyle = { height: 30, padding: "0 10px", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-md)", background: "var(--surface)", color: "var(--fg)", fontSize: 12, fontFamily: "var(--font-mono)", width: 230, outline: "none" };

  function AstrBotModal({ onClose }) {
    const [graphOn, setGraphOn] = React.useState(true);
    const [autoIdx, setAutoIdx] = React.useState(true);
    return (
      <Modal title="AstrBot 配置" icon="spark2" onClose={onClose} width={760}
        footer={<React.Fragment><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary">保存配置</Button></React.Fragment>}>
        <div style={{ padding: "18px 22px" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "11px 13px", background: "var(--warn-soft)", border: "1px solid color-mix(in srgb, var(--warn) 28%, transparent)", borderRadius: "var(--radius-lg)", marginBottom: 16 }}>
            <Icon name="spark2" size={16} style={{ color: "var(--warn)", marginTop: 1 }} />
            <div style={{ fontSize: 12, color: "var(--fg)", lineHeight: 1.55 }}>修改 Embedding 提供商 / 模型 / 接口后，Milvus 与各 collection 的 LightRAG 索引均需手动重建。部分项需重启插件生效。</div>
          </div>

          <Card title="Embedding 运行时" icon="layers" badge={<Badge tone="ok">本地</Badge>}>
            <Field label="提供商" hint="本地离线 (sentence-transformers) 或云端 API"><Select value="local" options={[{ value: "local", label: "本地 Embedding" }, { value: "api", label: "API Embedding" }]} /></Field>
            <Field label="模型名称"><input style={inputStyle} defaultValue="intfloat/multilingual-e5-small" /></Field>
            <Field label="向量维度" hint="由模型决定，只读"><Badge tone="neutral">384</Badge></Field>
            <Field label="API Key" hint="仅从环境变量 KR_EMBEDDING_API_KEY 读取"><span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>env-only</span></Field>
          </Card>

          <Card title="向量数据库与检索后端" icon="db">
            <Field label="向量后端"><Select value="milvus" options={[{ value: "milvus", label: "Milvus Lite" }, { value: "astrbot", label: "AstrBot KB（回退）" }]} /></Field>
            <Field label="自动索引" hint="上传后自动建立 Milvus 索引"><Toggle checked={autoIdx} onChange={setAutoIdx} /></Field>
          </Card>

          <Card title="LightRAG Core" icon="graph" badge={<Badge tone={graphOn ? "violet" : "neutral"}>{graphOn ? "已启用" : "关闭"}</Badge>}>
            <Field label="启用图谱索引" hint="手动触发构建，不随上传自动构建（成本隔离）"><Toggle checked={graphOn} onChange={setGraphOn} /></Field>
            <Field label="检索模式" hint="mix 向量+图谱（推荐）"><Select value="mix" options={[{ value: "mix", label: "mix — 混合（推荐）" }, { value: "local", label: "local — 本地图谱" }, { value: "global", label: "global — 全局" }, { value: "naive", label: "naive — 纯向量" }]} /></Field>
            <Field label="LLM 并发上限" hint="默认 4，调高更快但易限流"><input style={{ ...inputStyle, width: 80, textAlign: "center" }} defaultValue="4" /></Field>
            <Field label="工作目录" hint="只读，需改配置文件并重启"><span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>lightrag_workspaces</span></Field>
          </Card>

          <Card title="Research Agent (Ask)" icon="sparkle">
            <Field label="对话增强模式"><Select value="inject" options={[{ value: "inject", label: "注入增强" }, { value: "agent", label: "代理增强" }]} /></Field>
            <Field label="默认 Top-K"><input style={{ ...inputStyle, width: 80, textAlign: "center" }} defaultValue="5" /></Field>
            <Field label="展示引用来源" hint="cite_sources"><Toggle checked onChange={() => {}} /></Field>
          </Card>
        </div>
      </Modal>
    );
  }

  window.KRAstrBotModal = AstrBotModal;
})();
