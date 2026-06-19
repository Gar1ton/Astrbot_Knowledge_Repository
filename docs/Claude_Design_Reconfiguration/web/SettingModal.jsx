/* Knowledge Repository · Setting modal — merges Appearance + Backend config + Sync/Backup + Terminal. */
(function () {
  const { Modal, Button, Toggle, Select, Tag, Badge, Eyebrow, IconBtn } = window.KRUI;
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

  function ConfigKV({ k, v, masked }) {
    return (
      <div style={{ display: "flex", gap: 12, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
        <span style={{ width: 170, flexShrink: 0, fontSize: 12, color: "var(--fg-muted)" }}>{k}</span>
        <span style={{ flex: 1, fontSize: 12, fontFamily: "var(--font-mono)", color: masked ? "var(--fg-subtle)" : "var(--fg)", wordBreak: "break-all" }}>{v}</span>
      </div>
    );
  }

  function Swatch({ h, active, onClick, label }) {
    return (
      <button onClick={onClick} title={label} style={{ width: 30, height: 30, borderRadius: "var(--radius-md)", border: active ? "2px solid var(--fg)" : "2px solid transparent", boxShadow: active ? "0 0 0 1px var(--surface) inset" : "none", background: `hsl(${h} 70% 56%)`, cursor: "pointer", padding: 0 }} />
    );
  }

  function SettingModal({ onClose, accent, setAccent, onTheme, theme }) {
    const [tab, setTab] = React.useState("appearance");
    const tabs = [
      { id: "appearance", label: "外观", icon: "sun" },
      { id: "sync", label: "同步 / 备份", icon: "sync" },
      { id: "config", label: "后端配置", icon: "db" },
      { id: "terminal", label: "终端日志", icon: "terminal" },
    ];
    return (
      <Modal title="Setting" icon="settings" onClose={onClose} width={920}
        footer={<React.Fragment><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary">保存配置</Button></React.Fragment>}>
        <div style={{ display: "flex", height: "100%" }}>
          {/* left tabs */}
          <div style={{ width: 168, flexShrink: 0, borderRight: "1px solid var(--border)", background: "var(--surface)", padding: 10 }}>
            {tabs.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)} style={{
                display: "flex", alignItems: "center", gap: 9, width: "100%", padding: "8px 10px", borderRadius: "var(--radius-md)", border: "none",
                background: tab === t.id ? "var(--accent-soft)" : "transparent", color: tab === t.id ? "var(--accent)" : "var(--fg-muted)",
                cursor: "pointer", fontSize: 13, fontWeight: tab === t.id ? 600 : 450, fontFamily: "var(--font-sans)", marginBottom: 2, textAlign: "left",
              }}><Icon name={t.icon} size={15} /> {t.label}</button>
            ))}
          </div>
          {/* content */}
          <div style={{ flex: 1, overflow: "auto", padding: "18px 22px" }}>
            {tab === "appearance" && (
              <React.Fragment>
                <Card title="主题与外观" icon="sun">
                  <Field label="主题模式" hint="深浅配色（你已有多套方案，此处切换）">
                    <Select value={theme} onChange={onTheme} options={[{ value: "light", label: "浅色" }, { value: "dark", label: "深色" }, { value: "system", label: "跟随系统" }]} />
                  </Field>
                  <Field label="界面语言" hint="术语（collection / chunk / RRF）保留英文">
                    <Select value="zh" options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]} />
                  </Field>
                </Card>
                <Card title="全局强调色" icon="sparkle" badge={<Badge tone="accent">一处生效</Badge>}>
                  <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.55, marginBottom: 12 }}>所有控件的主题色 / 强调色统一由此驱动；调节后全站实时级联渲染并本地持久化。</div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                    {[225, 200, 265, 160, 32, 12, 340].map((h) => <Swatch key={h} h={h} active={Math.abs(accent.h - h) < 6} onClick={() => setAccent({ ...accent, h })} />)}
                  </div>
                  {[["色相 H", "h", 0, 360], ["饱和度 S", "s", 0, 100], ["明度 L", "l", 20, 80]].map(([lbl, key, min, max]) => (
                    <div key={key} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                      <span style={{ width: 60, fontSize: 12, color: "var(--fg-muted)" }}>{lbl}</span>
                      <input type="range" min={min} max={max} value={accent[key]} onChange={(e) => setAccent({ ...accent, [key]: +e.target.value })} style={{ flex: 1, accentColor: "var(--accent)" }} />
                      <span style={{ width: 36, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg)", textAlign: "right" }}>{accent[key]}{key === "h" ? "°" : "%"}</span>
                    </div>
                  ))}
                  <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                    <Button variant="primary">主按钮</Button><Button variant="outline">次按钮</Button><Tag label="标签" accent /><Badge tone="accent">徽章</Badge>
                  </div>
                </Card>
              </React.Fragment>
            )}

            {tab === "sync" && (
              <React.Fragment>
                <Card title="Zotero 同步" icon="book" badge={<Badge tone="ok">已连接</Badge>}>
                  <Field label="单向 Pull 镜像" hint="只读镜像 Zotero 条目 / 集合 / 标签 / PDF，清洗为 Markdown"><Button variant="outline" size="sm"><Icon name="sync" size={13} /> 立即同步</Button></Field>
                  <Field label="自动同步" hint="间隔 3600 秒"><Toggle checked onChange={() => {}} /></Field>
                </Card>
                <Card title="Cloudflare R2 备份" icon="cloud" badge={<Badge tone="ok">已启用</Badge>}>
                  <Field label="对象存储备份" hint="3.2 GB / 10 GB 已用"><Button variant="outline" size="sm">立即备份</Button></Field>
                  <Field label="备份间隔" hint="86400 秒（每日）"><Badge tone="neutral">daily</Badge></Field>
                </Card>
                <Card title="Notion 镜像" icon="layers" badge={<Badge tone="warn">即将上线 v0.8.0</Badge>}>
                  <Field label="从 Notion 拉取元数据" hint="端口预留中，UI 优雅降级"><Button variant="ghost" size="sm" disabled>拉取</Button></Field>
                </Card>
              </React.Fragment>
            )}

            {tab === "config" && (
              <React.Fragment>
                <div style={{ fontSize: 12, color: "var(--fg-muted)", marginBottom: 14 }}>只读核对后端有效配置（<code style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>GET /api/config/effective</code>），敏感字段已打码。</div>
                <Card title="源库 Source Store" icon="db"><ConfigKV k="db_filename" v="knowledge_repository.db" /><ConfigKV k="default_collection" v="default" /><ConfigKV k="ocr_enabled" v="false" /></Card>
                <Card title="Web 控制台" icon="globe"><ConfigKV k="host" v="0.0.0.0" /><ConfigKV k="port" v="26618" /><ConfigKV k="password" v="****" masked /></Card>
              </React.Fragment>
            )}

            {tab === "terminal" && (
              <div style={{ background: "#16171a", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-lg)", padding: 14, fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.7, color: "#cfd2c8", minHeight: 320 }}>
                <div style={{ color: "#7c89b8" }}>[12:04:11] <span style={{ color: "#6abf75" }}>INFO</span> aiohttp server on 0.0.0.0:26618</div>
                <div>[12:04:11] <span style={{ color: "#6abf75" }}>INFO</span> migrations 001–012 applied</div>
                <div>[12:04:13] <span style={{ color: "#6abf75" }}>INFO</span> Milvus Lite index loaded · 6 docs / 188 chunks</div>
                <div>[12:05:02] <span style={{ color: "#e0a23b" }}>WARN</span> LightRAG workspace "Foundations" not built</div>
                <div>[12:06:44] <span style={{ color: "#6abf75" }}>INFO</span> /api/ask conv=demo-1 mode=milvus_lightrag k=5 → 200 (812ms)</div>
                <div style={{ color: "#6b6759" }}>— 终端日志暂置于 Setting，后续可独立 —</div>
              </div>
            )}
          </div>
        </div>
      </Modal>
    );
  }

  window.KRSettingModal = SettingModal;
})();
