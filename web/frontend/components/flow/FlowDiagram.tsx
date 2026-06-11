import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { DependencyStatus, PipelineStage } from "@/lib/api";
import type { FlowConfigSnapshot, QuickConfigUpdate } from "./QuickConfigPanel";
import type { I18nKey, Lang } from "@/lib/i18n";
import { FitIcon, MinusIcon, PlusIcon } from "./Icons";
import { EDGES, GRID, isFlowStageId, STAGE_META, type FlowStageId, type FlowStageStatus } from "./model";
import { FlowNode } from "./FlowNode";

type Rect = { x: number; y: number; w: number; h: number };
type Geo = { rects: Partial<Record<FlowStageId, Rect>> | null; w: number; h: number };
type View = { s: number; x: number; y: number };
type PanState = { sx: number; sy: number; ox: number; oy: number } | null;

type Connector = {
  d: string;
  status: FlowStageStatus;
  dashed: boolean;
  live: boolean;
  label?: string;
  mid: { x: number; y: number };
};

type Handle = { x: number; y: number; status: FlowStageStatus };

function connectorStatus(from: PipelineStage, to: PipelineStage): FlowStageStatus {
  if (from.status === "off" || to.status === "off") return "off";
  if (from.status === "ready" && to.status === "ready") return "ready";
  return "degraded";
}

function sameGeo(a: Geo, b: Geo): boolean {
  return a.w === b.w && a.h === b.h && JSON.stringify(a.rects) === JSON.stringify(b.rects);
}

function clampScale(scale: number): number {
  return Math.min(1.5, Math.max(0.4, scale));
}

function snapScale(scale: number): number {
  return Math.round(scale * 100) / 100;
}

function snapCoord(value: number): number {
  return Math.round(value);
}

function Connectors({ conns, width, height }: { conns: Connector[]; width: number; height: number }) {
  return (
    <svg className="flow-connectors" width={width} height={height} aria-hidden="true">
      {conns.map((conn, index) => (
        <g key={`${conn.d}-${index}`} className={`flow-conn-group ${conn.status} ${conn.dashed ? "is-dashed" : ""}`}>
          <path d={conn.d} className="flow-conn-base" />
          {conn.live && <path d={conn.d} className="flow-conn-live" />}
        </g>
      ))}
    </svg>
  );
}

export function FlowDiagram({
  stages,
  dependencies,
  lang,
  t,
  savingId,
  installingKey,
  justActivatedId,
  rebuildingIndex,
  config,
  onSwitch,
  onQuickConfigSave,
  onInstall,
  onRebuildIndex,
  onClose,
}: {
  stages: PipelineStage[];
  dependencies: DependencyStatus[];
  lang: Lang;
  t: (k: I18nKey) => string;
  savingId: string | null;
  installingKey: string | null;
  justActivatedId: string | null;
  rebuildingIndex: boolean;
  config: FlowConfigSnapshot;
  onSwitch: (stage: PipelineStage, value: string) => void;
  onQuickConfigSave: (stageId: FlowStageId, updates: QuickConfigUpdate[]) => void;
  onInstall: (dep: DependencyStatus) => void;
  onRebuildIndex: () => void;
  onClose?: () => void;
}) {
  const knownStages = useMemo(() => {
    const base = stages
      .filter((stage) => isFlowStageId(stage.id))
      .sort((a, b) => STAGE_META[a.id as FlowStageId].idx - STAGE_META[b.id as FlowStageId].idx);
    // 电路级联：沿实线(非 dashed)边把上游的 degraded 向下游传播——一个错误配置的环节会让其后
    // 的环节也变黄(degraded/受损)而非保持绿色(ready)。base 已按 idx 左→右拓扑排序，上游先计算。
    const incoming = new Map<FlowStageId, FlowStageId[]>();
    for (const edge of EDGES) {
      if (edge.dashed) continue; // 旁路/可选来源(dashed)不传播。
      const arr = incoming.get(edge.to) ?? [];
      arr.push(edge.from);
      incoming.set(edge.to, arr);
    }
    const eff = new Map<FlowStageId, FlowStageStatus>();
    return base.map((stage) => {
      const id = stage.id as FlowStageId;
      let status = stage.status;
      if (status === "ready") {
        for (const up of incoming.get(id) ?? []) {
          if (eff.get(up) === "degraded") { status = "degraded"; break; }
        }
      }
      eff.set(id, status);
      return status === stage.status ? stage : { ...stage, status };
    });
  }, [stages]);
  const depMap = useMemo(() => new Map(dependencies.map((dep) => [dep.key, dep])), [dependencies]);
  const stageById = useMemo(() => new Map(knownStages.map((stage) => [stage.id as FlowStageId, stage])), [knownStages]);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef<Partial<Record<FlowStageId, HTMLDivElement | null>>>({});
  const pan = useRef<PanState>(null);
  const fitted = useRef(false);

  const [geo, setGeo] = useState<Geo>({ rects: null, w: 0, h: 0 });
  const [view, setView] = useState<View>({ s: 1, x: 0, y: 0 });
  const [viewReady, setViewReady] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const measure = useCallback(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const rects: Partial<Record<FlowStageId, Rect>> = {};
    for (const stage of knownStages) {
      const id = stage.id as FlowStageId;
      const el = nodeRefs.current[id];
      if (!el) return;
      rects[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    }
    const next: Geo = { rects, w: grid.offsetWidth, h: grid.offsetHeight };
    setGeo((prev) => (sameGeo(prev, next) ? prev : next));
  }, [knownStages]);

  useLayoutEffect(() => {
    measure();
  }, [measure]);

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const timer = window.setTimeout(measure, 220);
    const cleanupFns: Array<() => void> = [() => window.clearTimeout(timer)];

    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(() => measure());
      observer.observe(grid);
      cleanupFns.push(() => observer.disconnect());
    }

    const fonts = document.fonts;
    if (fonts) {
      fonts.ready.then(measure).catch(() => undefined);
    }

    return () => cleanupFns.forEach((cleanup) => cleanup());
  }, [measure]);

  const buildFitView = useCallback((preferCrisp: boolean): View | null => {
    const viewport = viewportRef.current;
    if (!viewport || !geo.w || !geo.h) return null;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    let scale = Math.min((vw - 72) / geo.w, (vh - 64) / geo.h, 1);
    if (preferCrisp && scale >= 0.92) scale = 1;
    scale = snapScale(clampScale(scale));
    return {
      s: scale,
      x: snapCoord((vw - geo.w * scale) / 2),
      y: snapCoord(Math.max(24, (vh - geo.h * scale) / 2)),
    };
  }, [geo.h, geo.w]);

  const fit = useCallback(() => {
    const nextView = buildFitView(false);
    if (!nextView) return;
    setView(nextView);
    setViewReady(true);
  }, [buildFitView]);

  const applyEntryView = useCallback(() => {
    const nextView = buildFitView(true);
    if (!nextView) return;
    setView(nextView);
    setViewReady(true);
  }, [buildFitView]);

  useLayoutEffect(() => {
    if (geo.w && !fitted.current) {
      fitted.current = true;
      applyEntryView();
    }
  }, [applyEntryView, geo.w]);

  const { conns, handles } = useMemo(() => {
    const nextConns: Connector[] = [];
    const handleMap: Record<string, Handle> = {};
    const rects = geo.rects;
    if (!rects) return { conns: nextConns, handles: [] as Array<[string, Handle]> };

    for (const edge of EDGES) {
      const fromStage = stageById.get(edge.from);
      const toStage = stageById.get(edge.to);
      const fromRect = rects[edge.from];
      const toRect = rects[edge.to];
      if (!fromStage || !toStage || !fromRect || !toRect) continue;

      const status = connectorStatus(fromStage, toStage);
      let d = "";
      let mid = { x: 0, y: 0 };

      if (edge.vertical) {
        const x1 = fromRect.x + fromRect.w / 2;
        const y1 = fromRect.y;
        const x2 = toRect.x + toRect.w / 2;
        const y2 = toRect.y + toRect.h;
        const dy = Math.min(70, Math.max(24, Math.abs(y1 - y2) * 0.5));
        d = `M ${x1} ${y1} C ${x1} ${y1 - dy}, ${x2} ${y2 + dy}, ${x2} ${y2}`;
        mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
        handleMap[`${edge.from}:t`] = { x: x1, y: y1, status: fromStage.status };
        handleMap[`${edge.to}:b`] = { x: x2, y: y2, status: toStage.status };
      } else {
        const x1 = fromRect.x + fromRect.w;
        const y1 = fromRect.y + fromRect.h / 2;
        const x2 = toRect.x;
        const y2 = toRect.y + toRect.h / 2;
        const dx = Math.min(90, Math.max(30, (x2 - x1) * 0.5));
        d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
        mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
        handleMap[`${edge.from}:r`] = { x: x1, y: y1, status: fromStage.status };
        handleMap[`${edge.to}:l`] = { x: x2, y: y2, status: toStage.status };
      }

      nextConns.push({
        d,
        status,
        dashed: Boolean(edge.dashed) || status === "off",
        live: status === "ready" && !edge.dashed,
        label: edge.labelKey ? t(edge.labelKey) : undefined,
        mid,
      });
    }

    return { conns: nextConns, handles: Object.entries(handleMap) as Array<[string, Handle]> };
  }, [geo.rects, stageById, t]);

  const zoomFromPoint = useCallback((clientX: number, clientY: number, factor: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    setView((current) => {
      const nextScale = snapScale(clampScale(current.s * factor));
      const ratio = nextScale / current.s;
      return {
        s: nextScale,
        x: snapCoord(px - (px - current.x) * ratio),
        y: snapCoord(py - (py - current.y) * ratio),
      };
    });
  }, []);

  const handleWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    zoomFromPoint(event.clientX, event.clientY, event.deltaY < 0 ? 1.08 : 0.926);
  }, [zoomFromPoint]);

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.target instanceof Element && event.target.closest(".flow-node")) return;
    event.preventDefault();
    pan.current = { sx: event.clientX, sy: event.clientY, ox: view.x, oy: view.y };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add("is-panning");
    setSelectedId(null);
  }, [view.x, view.y]);

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const currentPan = pan.current;
    if (!currentPan) return;
    const x = snapCoord(currentPan.ox + event.clientX - currentPan.sx);
    const y = snapCoord(currentPan.oy + event.clientY - currentPan.sy);
    setView((current) => ({ ...current, x, y }));
  }, []);

  const endPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    pan.current = null;
    event.currentTarget.classList.remove("is-panning");
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer capture may already be released when leaving the viewport.
    }
  }, []);

  const zoomFromCenter = useCallback((factor: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    zoomFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
  }, [zoomFromPoint]);

  return (
    <div
      ref={viewportRef}
      className="flow-viewport"
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endPan}
      onPointerLeave={endPan}
    >
      <div
        className="flow-grid-bg"
        style={{ backgroundSize: `${26 * view.s}px ${26 * view.s}px`, backgroundPosition: `${view.x}px ${view.y}px` }}
      />
      <div
        className={`flow-world ${viewReady ? "is-ready" : ""}`}
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0)`, zoom: view.s }}
      >
        <div ref={gridRef} className="flow-diagram-grid">
          <Connectors conns={conns} width={geo.w} height={geo.h} />

          {handles.map(([key, handle]) => (
            <span
              key={key}
              className={`flow-handle ${handle.status !== "off" ? "is-active" : ""} ${handle.status}`}
              style={{ left: handle.x, top: handle.y }}
            />
          ))}

          {conns.filter((conn) => conn.label).map((conn, index) => (
            <span
              key={`${conn.label}-${index}`}
              className={`flow-edge-label ${conn.dashed ? "flow-edge-label--muted" : ""}`}
              style={{ left: conn.mid.x, top: conn.mid.y }}
            >
              {conn.label}
            </span>
          ))}

          {knownStages.map((stage) => {
            const id = stage.id as FlowStageId;
            const grid = GRID[id];
            const justActivatedValue = justActivatedId?.startsWith(`${stage.id}-`)
              ? justActivatedId.slice(stage.id.length + 1)
              : null;
            return (
              <div
                key={stage.id}
                className={`flow-node-cell ${id === "retrieval" || id === "graph" ? "flow-node-cell--branch" : ""}`}
                ref={(node) => { nodeRefs.current[id] = node; }}
                style={{ gridColumn: grid.col, gridRow: grid.row }}
              >
                <FlowNode
                  stage={stage}
                  depMap={depMap}
                  lang={lang}
                  t={t}
                  saving={savingId === stage.id}
                  installing={installingKey}
                  justActivatedValue={justActivatedValue}
                  rebuildingIndex={rebuildingIndex}
                  selected={selectedId === stage.id}
                  config={config}
                  onSelect={() => setSelectedId(stage.id)}
                  onSwitch={onSwitch}
                  onQuickConfigSave={onQuickConfigSave}
                  onInstall={onInstall}
                  onRebuildIndex={onRebuildIndex}
                  onClose={onClose}
                />
              </div>
            );
          })}
        </div>
      </div>

      <div className="flow-zoom-control" onPointerDown={(event) => event.stopPropagation()}>
        <button type="button" onClick={() => zoomFromCenter(1.12)} aria-label="zoom in"><PlusIcon /></button>
        <span className="flow-zoom-value">{Math.round(view.s * 100)}%</span>
        <button type="button" onClick={() => zoomFromCenter(0.89)} aria-label="zoom out"><MinusIcon /></button>
        <button type="button" onClick={fit} aria-label="fit"><FitIcon /></button>
      </div>
    </div>
  );
}
