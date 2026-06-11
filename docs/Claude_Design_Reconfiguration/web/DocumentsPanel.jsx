/* Knowledge Repository · Documents panel.
   List view (Zotero-style rows) ⇄ reading view (breadcrumb + md/PDF toggle).
   Citation jump: scrolls to a chunk anchor and flashes it. */
(function () {
  const { Panel, IconBtn, Tag, Badge, Button, fmtSize, Eyebrow } = window.KRUI;
  const Icon = window.KRIcon;
  const { DOCS, CHUNKS } = window.KRMock;

  function DocRow({ d, onOpen }) {
    const [hover, setHover] = React.useState(false);
    return (
      <div onClick={() => onOpen(d)} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
        style={{
          display: "flex", gap: 12, padding: "13px 14px", borderRadius: "var(--radius-lg)", cursor: "pointer",
          background: hover ? "var(--surface-hover)" : "transparent",
          border: "1px solid " + (hover ? "var(--border)" : "transparent"), transition: "background .12s, border-color .12s",
        }}>
        <span style={{ width: 30, height: 38, flexShrink: 0, borderRadius: 4, background: d.ext === "md" ? "var(--info-soft)" : "var(--danger-soft)", color: d.ext === "md" ? "var(--info)" : "var(--danger)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8.5, fontWeight: 700, fontFamily: "var(--font-mono)", textTransform: "uppercase", border: "1px solid color-mix(in srgb, currentColor 22%, transparent)" }}>
          {d.ext}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--heading)", lineHeight: 1.35, marginBottom: 3 }}>{d.title}</div>
          {d.authors && <div style={{ fontSize: 11.5, color: "var(--fg-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.authors}</div>}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            {d.venue && <span style={{ fontSize: 11, fontStyle: "italic", color: "var(--fg)" }}>{d.venue}</span>}
            <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>· {d.year} · {d.type}</span>
            {d.lightrag && <Badge tone="violet"><Icon name="graph" size={10} /> LightRAG</Badge>}
            <span style={{ flex: 1 }} />
            {d.tags.slice(0, 3).map((t) => <Tag key={t} label={t} />)}
          </div>
        </div>
        <span style={{ display: "flex", alignItems: "center", color: "var(--fg-subtle)", opacity: hover ? 1 : 0 }}><Icon name="chevR" size={16} /></span>
      </div>
    );
  }

  function ListView({ docs, title }) {
    return (
      <div style={{ maxWidth: 760, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, padding: "4px 14px 10px" }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: "var(--heading)", letterSpacing: "-.02em" }}>{title}</span>
          <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>· {docs.length} 篇文献</span>
        </div>
        {docs.length === 0
          ? <div style={{ padding: 40, textAlign: "center", color: "var(--fg-subtle)", fontSize: 13 }}>该集合暂无文档</div>
          : docs.map((d) => <DocRow key={d.doc_id} d={d} onOpen={(doc) => window.__krOpenDoc(doc)} />)}
      </div>
    );
  }

  function ReadingView({ doc, mode, setMode, highlight, onClearHighlight }) {
    const refs = React.useRef({});
    const chunks = CHUNKS[doc.doc_id] || [];

    React.useEffect(() => {
      if (highlight && refs.current[highlight]) {
        const el = refs.current[highlight];
        el.scrollIntoView ? el.scrollIntoView({ block: "center" }) : null;
        el.style.animation = "none";
        // force reflow then flash
        void el.offsetWidth;
        el.style.animation = "citeFlash 1.6s ease-out forwards";
        const t = setTimeout(() => onClearHighlight && onClearHighlight(), 1800);
        return () => clearTimeout(t);
      }
    }, [highlight]);

    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "6px 20px 60px" }}>
        {/* meta header */}
        <h1 style={{ fontSize: 21, fontWeight: 700, color: "var(--heading)", letterSpacing: "-.02em", lineHeight: 1.3, margin: "8px 0 10px" }}>{doc.title}</h1>
        {doc.authors && <div style={{ fontSize: 12.5, color: "var(--fg-muted)", marginBottom: 12 }}>{doc.authors}</div>}
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 18, paddingBottom: 18, borderBottom: "1px solid var(--border)" }}>
          {doc.venue && <Badge tone="neutral">{doc.venue}</Badge>}
          <Badge tone="neutral">{doc.year}</Badge>
          <Badge tone="neutral">{doc.type}</Badge>
          {doc.doi && <Badge tone="accent">DOI {doc.doi}</Badge>}
          {doc.lightrag && <Badge tone="violet"><Icon name="graph" size={10} /> 已建图谱</Badge>}
        </div>

        {mode === "pdf" ? (
          <div style={{ background: "var(--bg-inset)", border: "1px dashed var(--border-strong)", borderRadius: "var(--radius-lg)", padding: "60px 20px", textAlign: "center", color: "var(--fg-subtle)" }}>
            <Icon name="file" size={30} style={{ margin: "0 auto 10px" }} />
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg-muted)" }}>PDF 原件预览</div>
            <div style={{ fontSize: 11.5, marginTop: 4 }}>{doc.title} · {fmtSize(doc.size)}</div>
            <div style={{ fontSize: 11, marginTop: 10, fontFamily: "var(--font-mono)" }}>需新端口 GET /api/documents/&#123;id&#125;/raw（见报告）</div>
          </div>
        ) : (
          <React.Fragment>
            <Eyebrow style={{ marginBottom: 8 }}>Abstract</Eyebrow>
            <p style={{ fontSize: 13.5, lineHeight: 1.75, color: "var(--fg)", margin: "0 0 24px" }}>{doc.abstract}</p>
            <Eyebrow style={{ marginBottom: 8 }}>分块原文 · {chunks.length} chunks</Eyebrow>
            {chunks.map((c) => (
              <div key={c.chunk_id} ref={(el) => (refs.current[c.chunk_id] = el)}
                style={{ padding: "11px 13px", borderRadius: "var(--radius-md)", marginBottom: 8, border: "1px solid var(--border)", background: "var(--surface)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                  <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--accent)" }}>#{c.ordinal}</span>
                  <span style={{ fontSize: 10, color: "var(--fg-subtle)" }}>p.{c.page} · {c.chunk_id}</span>
                </div>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: "var(--fg)" }}>{c.text}</p>
              </div>
            ))}
            {chunks.length === 0 && <div style={{ fontSize: 12.5, color: "var(--fg-subtle)", padding: "16px 0" }}>该文档分块原文未加载（演示数据）。</div>}
          </React.Fragment>
        )}
      </div>
    );
  }

  function DocumentsPanel({ selection, view, doc, mode, setMode, highlight, onClearHighlight, onBack }) {
    const Icon = window.KRIcon;
    let crumbs, right, body;

    if (view === "reading" && doc) {
      crumbs = [{ label: "Documents", onClick: onBack }, { label: doc.collection || "—", onClick: onBack }, { label: doc.title }];
      right = (
        <div style={{ display: "flex", gap: 2, background: "var(--bg-inset)", borderRadius: "var(--radius-md)", padding: 2 }}>
          {["md", "pdf"].map((m) => (
            <button key={m} onClick={() => setMode(m)} style={{
              fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: "var(--radius-sm)", border: "none", cursor: "pointer",
              fontFamily: "var(--font-sans)", textTransform: "uppercase", letterSpacing: ".04em",
              background: mode === m ? "var(--surface)" : "transparent", color: mode === m ? "var(--accent)" : "var(--fg-muted)",
              boxShadow: mode === m ? "var(--shadow-card)" : "none",
            }}>{m}</button>
          ))}
        </div>
      );
      body = <ReadingView doc={doc} mode={mode} setMode={setMode} highlight={highlight} onClearHighlight={onClearHighlight} />;
    } else {
      // list view
      let docs = DOCS, title = "全部文档";
      if (selection.type === "collection") { docs = DOCS.filter((d) => d.collection === selection.name); title = selection.name; }
      else if (selection.type === "lightrag") { docs = DOCS.filter((d) => d.collection === selection.name && d.lightrag); title = selection.name; }
      crumbs = [{ label: "Documents" }, { label: selection.name || "全部" }];
      right = <IconBtn name="search" label="在集合内查找 (Find)" />;
      body = <ListView docs={docs} title={title} />;
    }

    return <Panel title={view === "reading" ? null : "Documents"} crumbs={crumbs} right={right} flush style={{ flex: 1, minWidth: 0 }} bodyStyle={{ padding: "14px 0" }}>{body}</Panel>;
  }

  window.KRDocumentsPanel = DocumentsPanel;
})();
