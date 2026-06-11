/* Knowledge Repository · File panel — tri-section collection tree.
   Sections: Zotero Sync (expandable) · Local Collection · LightRAG Collection.
   Active row: inverse highlight + a theme-color pulse traveling the branch line.
   LightRAG build progress lives inside the LightRAG section. */
(function () {
  const { IconBtn, Eyebrow, Tip } = window.KRUI;
  const Icon = window.KRIcon;
  const { COLLECTIONS, DOCS } = window.KRMock;

  function Caret({ open }) {
    return <Icon name="chevR" size={13} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s", color: "var(--fg-subtle)" }} />;
  }

  // a single row in the tree (collection or document leaf)
  function Row({ depth, active, leaf, label, count, icon, onClick, lightragBuilt, badge }) {
    const [hover, setHover] = React.useState(false);
    return (
      <div onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
        style={{
          position: "relative", display: "flex", alignItems: "center", gap: 7,
          padding: "5px 8px 5px " + (10 + depth * 16) + "px", borderRadius: "var(--radius-md)",
          cursor: "pointer", userSelect: "none",
          backgroundColor: active ? "var(--select-bg)" : hover ? "var(--bg-inset)" : "rgba(0,0,0,0)",
          color: active ? "var(--select-fg)" : leaf ? "var(--fg-muted)" : "var(--fg)",
          transition: "background-color .12s, color .12s", margin: "1px 0",
        }}>
        {/* branch pulse on active leaf */}
        {active && depth > 0 && (
          <span aria-hidden style={{ position: "absolute", left: 10 + (depth - 1) * 16 + 3, top: "50%", width: 13, height: 2, transform: "translateY(-50%)", overflow: "hidden" }}>
            <span style={{ position: "absolute", top: 0, left: 0, width: 8, height: 2, borderRadius: 2, background: "var(--accent)", boxShadow: "0 0 6px 1px var(--accent)", animation: "branchPulse 1.6s ease-in-out infinite" }} />
          </span>
        )}
        <span style={{ display: "inline-flex", color: active ? (leaf ? "var(--select-muted)" : "var(--select-fg)") : leaf ? "var(--fg-subtle)" : "var(--accent)", flexShrink: 0 }}>
          {icon}
        </span>
        <span style={{ flex: 1, fontSize: 12.5, fontWeight: active && !leaf ? 600 : leaf ? 400 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        {badge}
        {count != null && <span style={{ fontSize: 10.5, fontWeight: 600, color: active ? "var(--select-muted)" : "var(--fg-subtle)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{count}</span>}
        {lightragBuilt && <span title="已构建图谱" style={{ width: 5, height: 5, borderRadius: "50%", background: active ? "var(--accent)" : "var(--ann-purple)", flexShrink: 0 }} />}
      </div>
    );
  }

  function SectionHead({ icon, label, actions }) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px 4px 8px", marginTop: 2 }}>
        <span style={{ display: "inline-flex", color: "var(--fg-subtle)" }}><Icon name={icon} size={14} /></span>
        <span style={{ flex: 1, fontSize: 10.5, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", color: "var(--fg-subtle)" }}>{label}</span>
        <div style={{ display: "flex", gap: 1 }}>{actions}</div>
      </div>
    );
  }

  function docsOf(colName, origin) {
    return DOCS.filter((d) => d.collection === colName && d.origin === origin);
  }
  function lightragDocsOf(colName) {
    return DOCS.filter((d) => d.collection === colName && d.lightrag);
  }

  function FilePanel({ selection, onSelect, onZoteroSync, build, onToggleBuild }) {
    const [open, setOpen] = React.useState({ "z:RAG & Retrieval": true, "z:Agents": false });
    const [secOpen, setSecOpen] = React.useState({ zotero: true, local: true, lightrag: true });
    const isSel = (type, id) => selection.type === type && selection.id === id;
    const tog = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }));

    return (
      <div style={{ padding: "6px 8px 14px" }}>
        {/* ZOTERO SYNC */}
        <SectionHead icon="sync" label="Zotero Sync" actions={
          <React.Fragment>
            <IconBtn name="sync" label="Zotero 同步 (Push / Pull)" size={14} onClick={onZoteroSync} />
            <IconBtn name="plus" label="新建集合" size={14} />
          </React.Fragment>
        } />
        {secOpen.zotero && COLLECTIONS.zotero.map((c) => {
          const k = "z:" + c.name;
          return (
            <div key={k}>
              <Row depth={0} icon={<Caret open={open[k]} />} label={c.name} count={c.count}
                active={isSel("collection", k)}
                onClick={() => { tog(k); onSelect({ type: "collection", id: k, name: c.name, section: "zotero" }); }} />
              {open[k] && docsOf(c.name, "zotero").map((d) => (
                <Row key={d.doc_id} depth={1} leaf icon={<Icon name="file" size={13} />} label={d.title}
                  active={isSel("doc", d.doc_id)} lightragBuilt={d.lightrag}
                  onClick={() => onSelect({ type: "doc", id: d.doc_id, name: d.title, section: "zotero", collection: c.name })} />
              ))}
            </div>
          );
        })}

        <div style={{ height: 1, background: "var(--border)", margin: "10px 6px" }} />

        {/* LOCAL COLLECTION */}
        <SectionHead icon="folder" label="Local Collection" actions={
          <React.Fragment>
            <IconBtn name="upload" label="上传文档" size={14} />
            <IconBtn name="plus" label="新建集合" size={14} />
          </React.Fragment>
        } />
        {secOpen.local && COLLECTIONS.local.map((c) => {
          const k = "l:" + c.name;
          return (
            <div key={k}>
              <Row depth={0} icon={<Caret open={open[k]} />} label={c.name} count={c.count}
                active={isSel("collection", k)}
                onClick={() => { tog(k); onSelect({ type: "collection", id: k, name: c.name, section: "local" }); }} />
              {open[k] && docsOf(c.name, "local").map((d) => (
                <Row key={d.doc_id} depth={1} leaf icon={<Icon name={d.ext === "md" ? "doc" : "file"} size={13} />} label={d.title}
                  active={isSel("doc", d.doc_id)}
                  onClick={() => onSelect({ type: "doc", id: d.doc_id, name: d.title, section: "local", collection: c.name })} />
              ))}
            </div>
          );
        })}

        <div style={{ height: 1, background: "var(--border)", margin: "10px 6px" }} />

        {/* LIGHTRAG COLLECTION */}
        <SectionHead icon="graph" label="LightRAG Collection" actions={
          <IconBtn name="spark2" label="构建 / 增量索引 (隔离于 Sync)" size={14} onClick={onToggleBuild} />
        } />
        {secOpen.lightrag && COLLECTIONS.lightrag.map((c) => {
          const k = "lr:" + c.name;
          const building = build && build.collection === c.name;
          return (
            <div key={k}>
              <Row depth={0} icon={<Icon name="layers" size={13} />} label={c.name}
                active={isSel("lightrag", k)} lightragBuilt
                badge={<span style={{ fontSize: 9.5, fontFamily: "var(--font-mono)", color: isSel("lightrag", k) ? "var(--select-muted)" : "var(--ann-purple)", marginRight: 2 }}>{c.entities}e·{c.relations}r</span>}
                onClick={() => onSelect({ type: "lightrag", id: k, name: c.name, section: "lightrag" })} />
              {building && (
                <div style={{ margin: "3px 6px 8px 24px", padding: "8px 10px", background: "var(--accent-soft)", border: "1px solid var(--accent-border)", borderRadius: "var(--radius-md)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
                    <span style={{ width: 9, height: 9, borderRadius: "50%", border: "2px solid var(--accent)", borderTopColor: "transparent", animation: "spin .7s linear infinite" }} />
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", flex: 1 }}>图谱构建中 · {build.stage}</span>
                    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>{Math.round(build.pct)}%</span>
                  </div>
                  <div style={{ height: 5, borderRadius: 999, background: "color-mix(in srgb, var(--accent) 18%, transparent)", overflow: "hidden" }}>
                    <div style={{ width: build.pct + "%", height: "100%", borderRadius: 999, background: "linear-gradient(90deg, var(--accent), var(--accent-strong))", transition: "width .4s" }} />
                  </div>
                  <div style={{ fontSize: 10, color: "var(--fg-muted)", marginTop: 6, fontFamily: "var(--font-mono)" }}>{build.processed}/{build.total} chunks · 隔离构建，不受 Sync 影响</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  window.KRFilePanel = FilePanel;
})();
