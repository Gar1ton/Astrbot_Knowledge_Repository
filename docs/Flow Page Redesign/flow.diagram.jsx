/* flow.diagram.jsx — 横向分支拓扑图 + 可拖拽/缩放画布。
   主干 ingest→embedding→vector_store→ask 横向；retrieval/graph 上下并联汇入 ask；
   ingest 纵向旁路→sync。连线按真实位置测量，保留流动动效。导出 window.FlowApp。 */
const { useState, useRef, useEffect, useLayoutEffect, useCallback } = React;
const FI = window.FLOW.i18n;
const SVAR = { ready: "var(--st-ready)", degraded: "var(--st-warn)", off: "var(--st-off)", info: "var(--st-info)" };

// 横向网格：col 左→右(主干推进)，row 1 上 / 2 中(主干) / 3 下
const GRID = {
  sync:         { col: 1, row: 1 },
  ingest:       { col: 1, row: 2 },
  embedding:    { col: 2, row: 2 },
  vector_store: { col: 3, row: 2 },
  retrieval:    { col: 4, row: 1 },
  graph:        { col: 4, row: 3 },
  ask:          { col: 5, row: 2 },
};

function recomputeStatus(stage, depMap) {
  const missing = stage.required_deps.some((k) => { const d = depMap.get(k); return d && !d.installed; });
  if (stage.candidates.length === 2 && stage.candidates.includes("on")) {
    if (stage.current === "off") return "off";
    return missing ? "degraded" : "ready";
  }
  if (missing) return "degraded";
  return "ready";
}

function Connectors({ conns, w, h }) {
  return (
    <svg className="conn-svg" width={w} height={h} aria-hidden style={{ overflow: "visible" }}>
      {conns.map((c, i) => {
        const col = SVAR[c.status] || SVAR.off;
        const base = c.dashed ? "var(--conn)" : `color-mix(in srgb, ${col} 52%, var(--conn))`;
        return (
          <g key={i}>
            <path d={c.d} className={"conn-base" + (c.dashed ? " conn-dashed" : "")} style={{ stroke: base }} />
            {c.live && <path d={c.d} className="conn-flow" style={{ stroke: col }} />}
          </g>
        );
      })}
    </svg>
  );
}

window.FlowApp = function FlowApp() {
  const [caps, setCaps] = useState(() => window.FLOW.initialCaps());
  const [selectedId, setSelectedId] = useState(null);
  const [savingId, setSavingId] = useState(null);
  const [installingKey, setInstallingKey] = useState(null);
  const [rechecking, setRechecking] = useState(false);
  const [banner, setBanner] = useState(null);
  const [justActivated, setJustActivated] = useState(null);
  const [toast, setToast] = useState(null);
  const flashT = useRef(null), toastT = useRef(null);

  const depMap = new Map(caps.dependencies.map((d) => [d.key, d]));
  const stageById = new Map(caps.pipeline.map((s) => [s.id, s]));

  const showToast = (msg) => {
    setToast(msg);
    if (toastT.current) clearTimeout(toastT.current);
    toastT.current = setTimeout(() => setToast(null), 2200);
  };

  const handleSwitch = useCallback((stage, value) => {
    const map = window.FLOW.SWITCH_MAP[stage.id];
    if (!map || value === stage.current) return;
    setSavingId(stage.id);
    setTimeout(() => {
      setCaps((prev) => {
        const dm = new Map(prev.dependencies.map((d) => [d.key, d]));
        const pipeline = prev.pipeline.map((s) => {
          if (s.id !== stage.id) return s;
          const ns = { ...s, current: value };
          ns.status = recomputeStatus(ns, dm);
          return ns;
        });
        return { ...prev, pipeline };
      });
      if (stage.consequence === "rebuild") setBanner({ kind: "rebuild", msg: FI.rebuild_banner });
      else if (stage.consequence === "restart") setBanner({ kind: "restart", msg: FI.restart_banner });
      else showToast(FI.saved);
      setJustActivated({ stageId: stage.id, value });
      if (flashT.current) clearTimeout(flashT.current);
      flashT.current = setTimeout(() => setJustActivated(null), 720);
      setSavingId(null);
    }, 280);
  }, []);

  const handleInstall = useCallback((dep) => {
    setInstallingKey(dep.key);
    showToast(FI.installing);
    setTimeout(() => {
      setCaps((prev) => {
        const dependencies = prev.dependencies.map((d) => d.key === dep.key ? { ...d, installed: true, version: "1.0.0" } : d);
        const dm = new Map(dependencies.map((d) => [d.key, d]));
        const pipeline = prev.pipeline.map((s) => ({ ...s, status: recomputeStatus(s, dm) }));
        return { ...prev, dependencies, pipeline };
      });
      setBanner({ kind: "install", msg: FI.install_banner });
      setInstallingKey(null);
    }, 950);
  }, []);

  const handleRecheck = useCallback(() => {
    setRechecking(true);
    setTimeout(() => { setRechecking(false); showToast(FI.saved); }, 650);
  }, []);

  const handleOpen = useCallback((link) => {
    showToast(`→ 跳转 ${link.href}`);  // 真实代码：next/link 跳转 link.href
  }, []);

  // ── 测量节点矩形 → 计算连线 / 端口 ───────────────────────────
  const gridRef = useRef(null);
  const nodeRefs = useRef({});
  const [geo, setGeo] = useState({ rects: null, w: 0, h: 0 });

  const measure = useCallback(() => {
    const grid = gridRef.current; if (!grid) return;
    const rects = {};
    for (const id of Object.keys(GRID)) {
      const el = nodeRefs.current[id]; if (!el) return;
      rects[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    }
    setGeo((prev) => {
      const next = { rects, w: grid.offsetWidth, h: grid.offsetHeight };
      if (prev.rects && prev.w === next.w && prev.h === next.h &&
          JSON.stringify(prev.rects) === JSON.stringify(rects)) return prev;
      return next;
    });
  }, []);

  useLayoutEffect(() => { measure(); }, [caps, measure]);
  useEffect(() => {
    const grid = gridRef.current; if (!grid) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(grid);
    const t = setTimeout(measure, 220);
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [measure]);

  // 连线 + 端口
  const conns = [];
  const handleSet = {};
  if (geo.rects) {
    const R = geo.rects;
    for (const e of window.FLOW.EDGES) {
      const A = R[e.from], B = R[e.to];
      const from = stageById.get(e.from), to = stageById.get(e.to);
      let st;
      if (from.status === "off" || to.status === "off") st = "off";
      else if (from.status === "ready" && to.status === "ready") st = "ready";
      else st = "degraded";
      let d, mid;
      if (e.vertical) {
        // 纵向旁路：sync 在 ingest 上方 → 从 A 顶 出，到 B 底 入
        const x1 = A.x + A.w / 2, y1 = A.y, x2 = B.x + B.w / 2, y2 = B.y + B.h;
        const dy = Math.min(70, Math.max(24, Math.abs(y1 - y2) * 0.5));
        d = `M ${x1} ${y1} C ${x1} ${y1 - dy}, ${x2} ${y2 + dy}, ${x2} ${y2}`;
        mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
        handleSet[`${e.from}:t`] = { x: x1, y: y1, st: from.status };
        handleSet[`${e.to}:b`] = { x: x2, y: y2, st: to.status };
      } else {
        // 横向主干：从 A 右 出，到 B 左 入
        const x1 = A.x + A.w, y1 = A.y + A.h / 2, x2 = B.x, y2 = B.y + B.h / 2;
        const dx = Math.min(90, Math.max(30, (x2 - x1) * 0.5));
        d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
        mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
        handleSet[`${e.from}:r`] = { x: x1, y: y1, st: from.status };
        handleSet[`${e.to}:l`] = { x: x2, y: y2, st: to.status };
      }
      conns.push({ d, status: st, dashed: !!e.dashed || st === "off", live: st === "ready" && !e.dashed, label: e.label, mid });
    }
  }
  const handles = Object.entries(handleSet);

  // ── 画布平移 / 缩放 ───────────────────────────────────────────
  const vpRef = useRef(null);
  const [view, setView] = useState({ s: 1, x: 0, y: 0 });
  const pan = useRef(null);
  const fitted = useRef(false);
  const clampS = (s) => Math.min(1.5, Math.max(0.4, s));

  const fit = useCallback(() => {
    const vp = vpRef.current; if (!vp || !geo.w) return;
    const vw = vp.clientWidth, vh = vp.clientHeight;
    const s = clampS(Math.min((vw - 72) / geo.w, (vh - 64) / geo.h, 1));
    setView({ s, x: (vw - geo.w * s) / 2, y: Math.max(24, (vh - geo.h * s) / 2) });
  }, [geo.w, geo.h]);

  useEffect(() => { if (geo.w && !fitted.current) { fitted.current = true; fit(); } }, [geo.w, fit]);

  const onWheel = (e) => {
    e.preventDefault();
    const r = vpRef.current.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    setView((v) => {
      const ns = clampS(v.s * (e.deltaY < 0 ? 1.08 : 0.926));
      const k = ns / v.s;
      return { s: ns, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
    });
  };
  const onPointerDown = (e) => {
    if (e.target.closest(".node")) return;
    pan.current = { sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y };
    vpRef.current.setPointerCapture(e.pointerId);
    vpRef.current.style.cursor = "grabbing";
    setSelectedId(null);
  };
  const onPointerMove = (e) => {
    const p = pan.current; if (!p) return;
    const nx = p.ox + (e.clientX - p.sx), ny = p.oy + (e.clientY - p.sy);
    setView((v) => ({ ...v, x: nx, y: ny }));
  };
  const onPointerUp = (e) => {
    pan.current = null;
    if (vpRef.current) { vpRef.current.releasePointerCapture?.(e.pointerId); vpRef.current.style.cursor = "grab"; }
  };
  const zoomBtn = (factor) => setView((v) => {
    const ns = clampS(v.s * factor); const k = ns / v.s;
    const r = vpRef.current.getBoundingClientRect(); const px = r.width / 2, py = r.height / 2;
    return { s: ns, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
  });

  const bannerWarn = banner && banner.kind === "rebuild";

  return (
    <div className="flow-page">
      <header className="flow-header" onClick={() => setSelectedId(null)}>
        <div className="fh-row">
          <div className="fh-title-wrap">
            <h1 className="fh-title">{FI.title}</h1>
            <p className="fh-sub">{FI.subtitle}</p>
          </div>
          <button className="recheck-btn" disabled={rechecking} onClick={(e) => { e.stopPropagation(); handleRecheck(); }}>
            <span className={rechecking ? "spin" : ""}>{window.UIIcon.refresh}</span>
            {rechecking ? FI.rechecking : FI.recheck}
          </button>
        </div>
        <div className="fh-legend">
          {["ready", "degraded", "off"].map((s) => (
            <span key={s} className="lg-item"><span className="lg-dot" style={{ background: SVAR[s] }} />{FI.legend[s]}</span>
          ))}
          <span className="lg-sep" />
          <span className="lg-item lg-item--branch"><span className="lg-branch" />检索编排 ∥ LightRAG 并联</span>
          <span className="lg-hint">滚轮缩放 · 拖拽空白处平移</span>
        </div>
        {banner && (
          <div className={"banner" + (bannerWarn ? " banner--warn" : "")}>
            <span className="banner-ico">{bannerWarn ? window.UIIcon.alert : window.UIIcon.check}</span>
            <span>{banner.msg}</span>
            <button className="banner-x" onClick={(e) => { e.stopPropagation(); setBanner(null); }} aria-label="dismiss">{window.UIIcon.x}</button>
          </div>
        )}
      </header>

      <div ref={vpRef} className="viewport"
        onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
        <div className="grid-bg" style={{ backgroundSize: `${26 * view.s}px ${26 * view.s}px`, backgroundPosition: `${view.x}px ${view.y}px` }} />
        <div className="world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }}>
          <div ref={gridRef} className="diagram-grid">
            <Connectors conns={conns} w={geo.w} h={geo.h} />
            {handles.map(([k, hd]) => (
              <span key={k} className={"handle" + (hd.st !== "off" ? " is-active" : "")}
                style={{ left: hd.x, top: hd.y, "--st": SVAR[hd.st] }} />
            ))}
            {conns.filter((c) => c.label).map((c, i) => (
              <span key={i} className={"edge-label" + (c.dashed ? " edge-label--muted" : "")}
                style={{ left: c.mid.x, top: c.mid.y }}>{c.label}</span>
            ))}
            {caps.pipeline.map((stage) => {
              const g = GRID[stage.id];
              return (
                <div key={stage.id} className="node-cell"
                  ref={(el) => { nodeRefs.current[stage.id] = el; }}
                  style={{ gridColumn: g.col, gridRow: g.row }}>
                  <window.FlowNode
                    stage={stage}
                    depMap={depMap}
                    installing={installingKey}
                    saving={savingId === stage.id}
                    justActivatedValue={justActivated && justActivated.stageId === stage.id ? justActivated.value : null}
                    selected={selectedId === stage.id}
                    onSelect={(e) => { e.stopPropagation(); setSelectedId(stage.id); }}
                    onSwitch={handleSwitch}
                    onInstall={handleInstall}
                    onOpen={handleOpen}
                  />
                </div>
              );
            })}
          </div>
        </div>

        <div className="zoom-ctl">
          <button onClick={() => zoomBtn(1.12)} aria-label="zoom in">{window.UIIcon.plus}</button>
          <span className="zoom-val">{Math.round(view.s * 100)}%</span>
          <button onClick={() => zoomBtn(0.89)} aria-label="zoom out">{window.UIIcon.minus}</button>
          <button onClick={() => { fitted.current = true; fit(); }} aria-label="fit">{window.UIIcon.fit}</button>
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
};
