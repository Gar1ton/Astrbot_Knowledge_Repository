/* Knowledge Repository · Chat panel (Research Agent).
   Citations [n] jump to the cited chunk in Documents (open + scroll + flash).
   Context = selected single doc OR collection. Pin keeps an answer across clears;
   "Add to Linked Notes" saves an answer into the doc's Notes. */
(function () {
  const { IconBtn, Tag, Badge, Button, Tip } = window.KRUI;
  const Icon = window.KRIcon;

  const SEED = [
    { role: "user", content: "ReAct 的核心思想是什么？它和纯 Chain-of-Thought 有何不同？" },
    {
      role: "assistant",
      content: "ReAct 的核心是让大模型以**交替（interleaved）**的方式同时生成「推理轨迹（reasoning trace）」与「具体动作（action）」[1]。这样模型既能用推理来创建、维护和调整高层计划（reason to act），又能通过与外部环境交互把新信息纳入推理（act to reason）。\n\n与纯 Chain-of-Thought 不同，CoT 只在内部推理、不与环境交互，容易产生事实漂移；ReAct 通过动作获取外部观测来纠偏，因此更鲁棒、能处理异常 [3]。在 ALFWorld 与 WebShop 上，ReAct 相对模仿学习/强化学习基线分别有 34% 和 10% 的绝对成功率提升 [2]。",
      mode: "联合检索 · Milvus + 图谱",
      sources: [
        { n: 1, doc_id: "d-react", chunk_id: "react-3", title: "ReAct", text: "ReAct prompts LLMs to generate both verbal reasoning traces and actions in an interleaved manner.", rrf: 0.0331 },
        { n: 2, doc_id: "d-react", chunk_id: "react-9", title: "ReAct", text: "ReAct outperforms imitation and RL methods by an absolute success rate of 34% and 10% respectively.", rrf: 0.0297 },
        { n: 3, doc_id: "d-react", chunk_id: "react-12", title: "ReAct", text: "The synergy of reasoning and acting allows the model to dynamically adjust its plans and handle exceptions.", rrf: 0.0212 },
      ],
      pinned: false,
    },
  ];

  function renderAnswer(text, onCite) {
    return text.split("\n").map((line, li) => {
      const parts = line.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
      return (
        <React.Fragment key={li}>
          {parts.map((p, pi) => {
            if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={pi} style={{ fontWeight: 700, color: "var(--heading)" }}>{p.slice(2, -2)}</strong>;
            const m = p.match(/^\[(\d+)\]$/);
            if (m) {
              const n = +m[1];
              return <sup key={pi} onClick={() => onCite(n)} style={{ cursor: "pointer", color: "var(--accent)", background: "var(--accent-soft)", borderRadius: 3, padding: "0 3px", fontWeight: 700, fontSize: ".72em", margin: "0 1px" }}>[{n}]</sup>;
            }
            return p;
          })}
          {li < text.split("\n").length - 1 && <br />}
        </React.Fragment>
      );
    });
  }

  function SourceMini({ s, onClick }) {
    return (
      <div onClick={onClick} style={{ display: "flex", gap: 7, padding: "7px 9px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", marginTop: 6 }}>
        <span style={{ width: 16, height: 16, flexShrink: 0, borderRadius: "50%", background: "var(--accent)", color: "#fff", fontSize: 9.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{s.n}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--heading)" }}>{s.title}</span>
            <span style={{ fontSize: 9.5, fontFamily: "var(--font-mono)", color: "var(--fg-subtle)" }}>{s.chunk_id}</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 9.5, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>RRF {s.rrf}</span>
          </div>
          <p style={{ margin: "3px 0 0", fontSize: 10.5, lineHeight: 1.5, color: "var(--fg-muted)", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{s.text}</p>
        </div>
      </div>
    );
  }

  function Bubble({ msg, onCite, onPin, onSaveNote }) {
    const isUser = msg.role === "user";
    const [hover, setHover] = React.useState(false);
    if (isUser) {
      return (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
          <div style={{ maxWidth: "86%", background: "var(--accent)", color: "var(--accent-fg)", borderRadius: "10px 10px 3px 10px", padding: "9px 12px", fontSize: 12.5, lineHeight: 1.6 }}>{msg.content}</div>
        </div>
      );
    }
    return (
      <div style={{ marginBottom: 16 }} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <div style={{ maxWidth: "94%", background: "var(--surface)", border: "1px solid " + (msg.pinned ? "var(--accent-border)" : "var(--border)"), borderRadius: "10px 10px 10px 3px", padding: "10px 13px", boxShadow: msg.pinned ? "0 0 0 3px var(--ring)" : "var(--shadow-card)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
            <Badge tone="accent">{msg.mode}</Badge>
            {msg.pinned && <Badge tone="warn"><Icon name="pin" size={9} /> 已锁定</Badge>}
          </div>
          <div style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--fg)" }}>{renderAnswer(msg.content, onCite)}</div>
          {msg.sources && msg.sources.length > 0 && (
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 2 }}>引用来源 · 点击在文档中打开</div>
              {msg.sources.map((s) => <SourceMini key={s.n} s={s} onClick={() => onCite(s.n)} />)}
            </div>
          )}
        </div>
        {/* action row */}
        <div style={{ display: "flex", gap: 4, marginTop: 6, opacity: hover || msg.pinned ? 1 : 0.4, transition: "opacity .15s" }}>
          <Tip label="存为该文献的关联笔记"><button onClick={onSaveNote} style={actionBtn}><Icon name="link" size={12} /> Add to Linked Notes</button></Tip>
          <Tip label={msg.pinned ? "取消锁定" : "锁定回答：持续保留，清空对话也不消失"}><button onClick={onPin} style={{ ...actionBtn, color: msg.pinned ? "var(--accent)" : "var(--fg-muted)" }}><Icon name="pin" size={12} /> {msg.pinned ? "已锁定" : "锁定回答"}</button></Tip>
        </div>
      </div>
    );
  }
  const actionBtn = { display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500, color: "var(--fg-muted)", background: "transparent", border: "1px solid var(--border)", borderRadius: "var(--radius-pill)", padding: "3px 9px", cursor: "pointer", fontFamily: "var(--font-sans)" };

  function ChatPanel({ contextLabel, contextKind, onCite, onSaveNote }) {
    const [messages, setMessages] = React.useState(SEED);
    const [input, setInput] = React.useState("");
    const scrollRef = React.useRef(null);

    React.useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages]);

    function handleCite(msg, n) {
      const s = (msg.sources || []).find((x) => x.n === n);
      if (s) onCite(s);
    }
    function send() {
      if (!input.trim()) return;
      const q = input.trim();
      setInput("");
      setMessages((m) => [...m, { role: "user", content: q }]);
      setTimeout(() => {
        setMessages((m) => [...m, {
          role: "assistant", mode: contextKind === "lightrag" ? "图谱检索 · LightRAG" : "语义检索 · Milvus",
          content: "基于当前知识库范围检索到的内容，这里是对「" + q + "」的回答示例。引用来源见下方 [1]，点击可在中间面板定位原文。",
          sources: [{ n: 1, doc_id: "d-lightrag", chunk_id: "lr-1", title: "LightRAG", text: "LightRAG incorporates graph structures into text indexing and retrieval, employing a dual-level retrieval system.", rrf: 0.0309 }],
          pinned: false,
        }]);
      }, 280);
    }
    function clearChat() { setMessages((m) => m.filter((x) => x.pinned)); }
    function pin(i) { setMessages((m) => m.map((x, idx) => idx === i ? { ...x, pinned: !x.pinned } : x)); }

    return (
      <section style={{ width: "var(--chat-w)", flexShrink: 0, display: "flex", flexDirection: "column", minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-2xl)", boxShadow: "var(--shadow-card)", overflow: "hidden" }}>
        <header style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", gap: 6, padding: "0 8px 0 13px", borderBottom: "1px solid var(--border)" }}>
          <Icon name="sparkle" size={15} style={{ color: "var(--accent)" }} />
          <span style={{ flex: 1, fontSize: 12.5, fontWeight: 650, color: "var(--heading)" }}>Chat</span>
          <IconBtn name="trash" label="清空记录（保留锁定回答）" onClick={clearChat} />
        </header>

        {/* messages */}
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "14px 12px" }}>
          {messages.map((m, i) => (
            <Bubble key={i} msg={m} onCite={(n) => handleCite(m, n)} onPin={() => pin(i)} onSaveNote={() => onSaveNote(m)} />
          ))}
        </div>

        {/* context chip + composer */}
        <div style={{ flexShrink: 0, padding: "8px 12px 12px", borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
            <span style={{ fontSize: 10.5, color: "var(--fg-subtle)" }}>知识库范围</span>
            <Badge tone={contextKind === "lightrag" ? "violet" : contextKind === "doc" ? "info" : "accent"}>
              <Icon name={contextKind === "doc" ? "file" : contextKind === "lightrag" ? "graph" : "folder"} size={10} /> {contextLabel}
            </Badge>
          </div>
          <div style={{ border: "1px solid var(--border-strong)", borderRadius: "var(--radius-lg)", background: "var(--surface)", padding: 8, boxShadow: "var(--shadow-card)" }}>
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="向知识库提问…" rows={2}
              style={{ width: "100%", resize: "none", border: "none", outline: "none", background: "transparent", fontSize: 12.5, lineHeight: 1.55, fontFamily: "var(--font-sans)", color: "var(--fg)", padding: "2px 4px" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
              <IconBtn name="settings" label="查询设置（检索方式 / TopK / 语言）" />
              <span style={{ flex: 1 }} />
              <Button size="sm" onClick={send} style={{ height: 28 }}><Icon name="send" size={13} /> 发送</Button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  window.KRChatPanel = ChatPanel;
})();
