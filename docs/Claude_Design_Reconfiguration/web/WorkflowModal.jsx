/* Knowledge Repository · WorkFlow modal — data-flow pipeline (redesigned nodes, Heptabase style).
   Reuses the existing Flow logic (stages / status / switchable backends) with new node art. */
(function () {
  const { Modal, Badge, StatusChipUnused } = window.KRUI;
  const Icon = window.KRIcon;

  const STAGES = [
    { id: "zotero", icon: "book", title: "Zotero 文献库", role: "可选来源", status: "ready", field: ["来源", "managed_copy"], desc: "只读镜像条目/PDF，清洗为 Markdown" },
    { id: "ingest", icon: "upload", title: "上传 / 分块", role: "只读 · 默认", status: "ready", field: ["STORE", "SQLite"], desc: "原件留存，切分文本片段" },
    { id: "embedding", icon: "layers", title: "向量化", role: "可切换", status: "ready", field: ["PROVIDER", "local · e5-small"], desc: "文本片段 → 向量" },
    { id: "vector", icon: "db", title: "向量库", role: "可切换", status: "ready", field: ["BACKEND", "Milvus Lite"], desc: "稠密检索，AstrBot KB 回退" },
    { id: "retrieval", icon: "search", title: "检索编排", role: "只读 · 默认", status: "ready", field: ["STRATEGY", "向量 + 词汇 · RRF"], desc: "多路召回，RRF 融合" },
    { id: "ask", icon: "sparkle", title: "问答 Ask", role: "界面 · 可切换", status: "ready", field: ["MODE", "inject"], desc: "注入上下文生成回答" },
  ];

  function Node({ s, dest }) {
    const sc = { ready: "var(--ok)", degraded: "var(--warn)", off: "var(--fg-subtle)", info: "var(--info)" }[s.status];
    return (
      <div style={{
        position: "relative", width: 188, flexShrink: 0, background: "var(--surface)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-xl)", boxShadow: dest ? "var(--shadow-raised)" : "var(--shadow-card)",
        padding: "12px 13px", display: "flex", flexDirection: "column", gap: 9, overflow: "hidden",
      }}>
        <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: `linear-gradient(${sc}, color-mix(in srgb, ${sc} 40%, transparent))` }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 28, height: 28, borderRadius: "var(--radius-md)", background: `color-mix(in srgb, ${sc} 10%, var(--bg-inset))`, border: `1px solid color-mix(in srgb, ${sc} 22%, var(--border))`, display: "flex", alignItems: "center", justifyContent: "center", color: sc, flexShrink: 0 }}>
            <Icon name={s.icon} size={15} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 650, color: "var(--heading)", letterSpacing: "-.01em" }}>{s.title}</div>
            <div style={{ fontSize: 9.5, fontWeight: 600, color: "var(--fg-muted)" }}>{s.role}</div>
          </div>
        </div>
        <div style={{ display: "inline-flex", alignSelf: "flex-start", alignItems: "center", gap: 5, fontSize: 10.5, fontWeight: 600, padding: "2px 8px", borderRadius: 999, border: `1px solid color-mix(in srgb, ${sc} 30%, transparent)`, color: sc, background: `color-mix(in srgb, ${sc} 9%, transparent)` }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: sc }} /> 就绪
        </div>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".09em", color: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}>{s.field[0]}</div>
          <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--fg)", marginTop: 3, fontFamily: "var(--font-mono)" }}>{s.field[1]}</div>
        </div>
        <div style={{ fontSize: 10.5, color: "var(--fg-muted)", lineHeight: 1.5 }}>{s.desc}</div>
      </div>
    );
  }

  function Connector() {
    return (
      <div style={{ flexShrink: 0, display: "flex", alignItems: "center", color: "var(--border-strong)", width: 30, justifyContent: "center" }}>
        <svg width="30" height="14" viewBox="0 0 30 14"><line x1="0" y1="7" x2="22" y2="7" stroke="var(--border-strong)" strokeWidth="2" strokeDasharray="3 4" /><polyline points="18,3 24,7 18,11" fill="none" stroke="var(--border-strong)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </div>
    );
  }

  function WorkflowModal({ onClose }) {
    return (
      <Modal title="WorkFlow · 数据流" icon="flow" onClose={onClose} width={1040} height="86vh">
        <div style={{ padding: "18px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 6 }}>
            <p style={{ margin: 0, fontSize: 12.5, color: "var(--fg-muted)", lineHeight: 1.55, flex: 1 }}>查看知识库各环节当前用哪个后端、是否就绪。检索编排与 LightRAG 图谱<b style={{ color: "var(--fg)" }}>并联</b>，图谱为高精度可选路径，不阻塞默认检索。</p>
            <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--fg-muted)" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ok)" }} /> 就绪</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--warn)" }} /> 待处理</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--fg-subtle)" }} /> 未启用</span>
            </div>
          </div>

          {/* main pipeline rail */}
          <div style={{ display: "flex", alignItems: "center", overflowX: "auto", padding: "22px 4px 10px" }}>
            {STAGES.map((s, i) => (
              <React.Fragment key={s.id}>
                <Node s={s} />
                {i < STAGES.length - 1 && <Connector />}
              </React.Fragment>
            ))}
          </div>

          {/* parallel LightRAG branch + sync */}
          <div style={{ display: "flex", gap: 30, marginTop: 18, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 280, background: "var(--accent-soft)", border: "1px solid var(--accent-border)", borderRadius: "var(--radius-xl)", padding: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <Icon name="graph" size={16} style={{ color: "var(--accent)" }} />
                <span style={{ fontSize: 13, fontWeight: 650, color: "var(--heading)", flex: 1 }}>LightRAG 图谱 · 并联高精度路径</span>
                <Badge tone="violet">可选 · 隔离构建</Badge>
              </div>
              <p style={{ margin: 0, fontSize: 11.5, color: "var(--fg-muted)", lineHeight: 1.55 }}>与检索编排并联，基于知识图谱召回。手动触发构建以控制成本，与 Sync 隔离——Sync 变化不会触发或影响图谱索引。</p>
              <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                <Badge tone="neutral">RAG &amp; Retrieval · 142e</Badge><Badge tone="neutral">Agents · 86e</Badge>
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 280, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-xl)", boxShadow: "var(--shadow-card)", padding: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <Icon name="cloud" size={16} style={{ color: "var(--fg-muted)" }} />
                <span style={{ fontSize: 13, fontWeight: 650, color: "var(--heading)", flex: 1 }}>同步 / 备份 · 旁路</span>
                <Badge tone="ok">R2 就绪</Badge>
              </div>
              <p style={{ margin: 0, fontSize: 11.5, color: "var(--fg-muted)", lineHeight: 1.55 }}>镜像备份到 Cloudflare R2 / Notion，与检索互不影响。密钥经环境变量配置。</p>
              <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                <Badge tone="ok">R2 · 3.2/10 GB</Badge><Badge tone="warn">Notion · v0.8.0</Badge>
              </div>
            </div>
          </div>
        </div>
      </Modal>
    );
  }

  window.KRWorkflowModal = WorkflowModal;
})();
