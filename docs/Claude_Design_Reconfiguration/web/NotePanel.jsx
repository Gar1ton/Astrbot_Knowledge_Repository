/* Knowledge Repository · Note panel — Zotero-style metadata + annotations + notes.
   Replaces the File panel when a document is opened (Fig4 behavior).
   Data: Zotero-synced annotations (read-only) + local notes (new backend — see report). */
(function () {
  const { IconBtn, Tag, Eyebrow, Button } = window.KRUI;
  const Icon = window.KRIcon;
  const { NOTES, CHUNKS } = window.KRMock;

  const ANN = {
    purple: { bar: "var(--ann-purple)", bg: "var(--ann-purple-bg)", bd: "var(--ann-purple-border)" },
    yellow: { bar: "var(--ann-yellow)", bg: "var(--ann-yellow-bg)", bd: "var(--ann-yellow-border)" },
    green: { bar: "var(--ann-green)", bg: "var(--ann-green-bg)", bd: "var(--ann-green-border)" },
    red: { bar: "var(--ann-red)", bg: "var(--ann-red-bg)", bd: "var(--ann-red-border)" },
    blue: { bar: "var(--ann-blue)", bg: "var(--ann-blue-bg)", bd: "var(--ann-blue-border)" },
  };

  function MetaRow({ k, v, mono, link }) {
    return (
      <div style={{ display: "flex", gap: 10, padding: "3px 0" }}>
        <span style={{ width: 58, flexShrink: 0, fontSize: 11, color: "var(--fg-subtle)" }}>{k}</span>
        <span style={{ flex: 1, fontSize: 11.5, color: link ? "var(--accent)" : "var(--fg)", fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", wordBreak: "break-word", lineHeight: 1.45 }}>{v}</span>
      </div>
    );
  }

  function NotePanel({ doc, notes, onClose, onJumpChunk, onAddNote }) {
    const data = NOTES[doc.doc_id] || { annotations: [], notes: [] };
    const localNotes = notes && notes[doc.doc_id] ? notes[doc.doc_id] : data.notes;

    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        {/* sticky header */}
        <header style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", gap: 6, padding: "0 8px 0 13px", borderBottom: "1px solid var(--border)" }}>
          <span style={{ fontSize: 12.5, fontWeight: 650, color: "var(--heading)" }}>Note</span>
          <span style={{ color: "var(--fg-subtle)" }}>/</span>
          <span style={{ flex: 1, fontSize: 12, color: "var(--fg-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.origin === "zotero" ? "Zotero Sync" : "Local"}</span>
          <IconBtn name="x" label="关闭面板（返回 File）" onClick={onClose} />
        </header>

        <div style={{ flex: 1, overflow: "auto", padding: "14px 14px 30px" }}>
          {/* title */}
          <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--heading)", lineHeight: 1.35, marginBottom: 12 }}>{doc.title}</div>

          {/* metadata table */}
          {doc.authors && <MetaRow k="Authors" v={doc.authors} />}
          <MetaRow k="Year" v={doc.year} />
          {doc.venue && <MetaRow k="Journal" v={doc.venue} />}
          {doc.doi && <MetaRow k="DOI" v={doc.doi} link mono />}
          <MetaRow k="Type" v={doc.type} />
          <MetaRow k="Added" v={doc.added} mono />

          {/* tags */}
          <Eyebrow style={{ margin: "18px 0 8px" }}>Tags</Eyebrow>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {doc.tags.map((t) => <Tag key={t} label={t} />)}
          </div>

          {/* annotations */}
          <Eyebrow style={{ margin: "20px 0 8px" }}>Annotations · {data.annotations.length}</Eyebrow>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.annotations.map((a) => {
              const c = ANN[a.color] || ANN.yellow;
              return (
                <div key={a.id} style={{ borderRadius: "var(--radius-md)", border: `1px solid ${c.bd}`, background: c.bg, overflow: "hidden", display: "flex" }}>
                  <span style={{ width: 3, flexShrink: 0, background: c.bar }} />
                  <div style={{ padding: "8px 10px", flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 12, lineHeight: 1.55, color: "var(--fg)" }}>{a.text}</p>
                    {a.comment && <p style={{ margin: "6px 0 0", fontSize: 11, fontStyle: "italic", fontWeight: 600, color: c.bar, lineHeight: 1.45 }}>{a.comment}</p>}
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
                      <span style={{ fontSize: 10, color: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}>p.{a.page} · highlight</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* notes */}
          <div style={{ display: "flex", alignItems: "center", margin: "20px 0 8px" }}>
            <Eyebrow style={{ flex: 1 }}>Notes · {localNotes.length}</Eyebrow>
            <IconBtn name="plus" label="新建笔记（本地）" onClick={onAddNote} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {localNotes.map((n) => (
              <div key={n.id} style={{ padding: "9px 11px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--surface)" }}>
                <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: "var(--fg)" }}>{n.body}</p>
                {n.linked && <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 10.5, color: "var(--accent)" }}><Icon name="link" size={11} /> 来自 Chat 回答</div>}
              </div>
            ))}
            {localNotes.length === 0 && <div style={{ fontSize: 11.5, color: "var(--fg-subtle)" }}>暂无笔记，点 + 新建。</div>}
          </div>

          {/* abstract */}
          <Eyebrow style={{ margin: "20px 0 8px" }}>Abstract</Eyebrow>
          <p style={{ margin: 0, fontSize: 12, lineHeight: 1.7, color: "var(--fg-muted)" }}>{doc.abstract}</p>
        </div>
      </div>
    );
  }

  window.KRNotePanel = NotePanel;
})();
