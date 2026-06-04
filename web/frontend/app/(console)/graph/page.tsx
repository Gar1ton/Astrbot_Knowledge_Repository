"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  GraphData, GraphNode, GraphEdge, KbChunk, ApiError, GraphBuildJob,
  getGraph, queryGraph, buildGraph, estimateGraphBuild, getGraphBuildJob, isReserved, listCollections,
} from "@/lib/api";
import { Select } from "@/components/ui/Select";

// ─── 类型配色 ─────────────────────────────────────────────────

function getNodeTypeColor(type?: string): string {
  if (type === "Method/Algorithm") return "var(--accent)";
  if (type === "Dataset") return "var(--accent-2)";
  if (type === "Concept") return "#3b82f6"; // Blue
  if (type === "Person") return "#8b5cf6";  // Purple
  return "var(--accent)";
}

interface HybridGraphProps {
  data: GraphData;
  onSelectNode: (n: GraphNode) => void;
  onSelectEdge: (e: GraphEdge) => void;
  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;
  onClearSelection: () => void;
}

// ─── 力导向布局 Hook ──────────────────────────────────────────

interface Vec2 { x: number; y: number; }

function useForceLayout(data: GraphData, W: number, H: number): Record<string, Vec2> {
  const [positions, setPositions] = useState<Record<string, Vec2>>(() =>
    initPositions(data.nodes, W, H)
  );
  const simRef = useRef<{ nodes: string[]; pos: Record<string, Vec2>; vel: Record<string, Vec2> } | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const initPos = initPositions(data.nodes, W, H);
    const vel: Record<string, Vec2> = {};
    data.nodes.forEach((n) => { vel[n.id] = { x: 0, y: 0 }; });
    simRef.current = { nodes: data.nodes.map((n) => n.id), pos: { ...initPos }, vel };
    setPositions({ ...initPos });

    let frame = 0;
    const MAX_FRAMES = 120;

    function tick() {
      const sim = simRef.current!;
      const REPEL = 3500;
      const ATTRACT = 0.04;
      const DAMP = 0.78;
      const ids = sim.nodes;

      // 计算力
      const force: Record<string, Vec2> = {};
      ids.forEach((id) => { force[id] = { x: 0, y: 0 }; });

      // 斥力（节点间）
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = sim.pos[ids[i]];
          const b = sim.pos[ids[j]];
          const dx = b.x - a.x || 0.01;
          const dy = b.y - a.y || 0.01;
          const dist2 = Math.max(dx * dx + dy * dy, 1);
          const f = REPEL / dist2;
          const fx = f * dx / Math.sqrt(dist2);
          const fy = f * dy / Math.sqrt(dist2);
          force[ids[i]].x -= fx; force[ids[i]].y -= fy;
          force[ids[j]].x += fx; force[ids[j]].y += fy;
        }
      }

      // 引力（有边的节点对）
      data.edges.forEach((e) => {
        const a = sim.pos[e.source];
        const b = sim.pos[e.target];
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        force[e.source].x += dx * ATTRACT;
        force[e.source].y += dy * ATTRACT;
        force[e.target].x -= dx * ATTRACT;
        force[e.target].y -= dy * ATTRACT;
      });

      // 向中心的弱引力（防止节点飘出边界）
      ids.forEach((id) => {
        force[id].x += (W / 2 - sim.pos[id].x) * 0.005;
        force[id].y += (H / 2 - sim.pos[id].y) * 0.005;
      });

      // 更新速度 + 位置
      ids.forEach((id) => {
        sim.vel[id].x = (sim.vel[id].x + force[id].x) * DAMP;
        sim.vel[id].y = (sim.vel[id].y + force[id].y) * DAMP;
        sim.pos[id] = {
          x: Math.max(30, Math.min(W - 30, sim.pos[id].x + sim.vel[id].x)),
          y: Math.max(30, Math.min(H - 30, sim.pos[id].y + sim.vel[id].y)),
        };
      });

      setPositions({ ...sim.pos });
      frame++;
      if (frame < MAX_FRAMES) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  return positions;
}

function initPositions(nodes: GraphNode[], W: number, H: number): Record<string, Vec2> {
  const pos: Record<string, Vec2> = {};
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    const rx = W * 0.32;
    const ry = H * 0.30;
    // 加入少量随机抖动，避免节点完全重叠
    pos[n.id] = {
      x: W / 2 + rx * Math.cos(angle) + (Math.random() - 0.5) * 20,
      y: H / 2 + ry * Math.sin(angle) + (Math.random() - 0.5) * 20,
    };
  });
  return pos;
}

// ─── 混合式扁平毛玻璃图谱（HTML + SVG Hybrid，力导向布局） ──────

function HybridGraph({
  data,
  onSelectNode,
  onSelectEdge,
  selectedNode,
  selectedEdge,
  onClearSelection,
}: HybridGraphProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Calculate focused node
  const focusedNodeId = hoveredNodeId || selectedNode?.id || null;

  // Build connection map to quickly find neighbors
  const adjacencyMap = React.useMemo(() => {
    const map = new Map<string, Set<string>>();
    data.nodes.forEach((n) => map.set(n.id, new Set()));
    data.edges.forEach((e) => {
      map.get(e.source)?.add(e.target);
      map.get(e.target)?.add(e.source);
    });
    return map;
  }, [data]);

  // 力导向布局
  const W = 560;
  const H = 440;
  const positions = useForceLayout(data, W, H);

  // Neighborhood helper
  const isNodeHighlighted = (nodeId: string) => {
    if (focusedNodeId === null) return true;
    if (nodeId === focusedNodeId) return true;
    return adjacencyMap.get(focusedNodeId)?.has(nodeId) ?? false;
  };

  const isEdgeHighlighted = (edge: GraphEdge) => {
    if (focusedNodeId === null) return true;
    return edge.source === focusedNodeId || edge.target === focusedNodeId;
  };

  return (
    <div
      onClick={onClearSelection}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        aspectRatio: "560/440",
        background: "var(--bg)",
        borderRadius: 12,
        overflow: "hidden",
        cursor: "default",
        userSelect: "none",
      }}
    >
      {/* 1. SVG 连线层 */}
      <svg
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          zIndex: 1,
        }}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
      >
        {data.edges.map((edge) => {
          const src = positions[edge.source];
          const tgt = positions[edge.target];
          if (!src || !tgt) return null;

          const isSelected = selectedEdge?.id === edge.id;
          const isHighlighted = isEdgeHighlighted(edge);
          const opacity = isHighlighted ? 1 : 0.16;

          return (
            <g key={edge.id} style={{ transition: "opacity 0.25s ease" }}>
              {/* Visible connecting line */}
              <line
                x1={src.x}
                y1={src.y}
                x2={tgt.x}
                y2={tgt.y}
                stroke={isSelected ? "var(--accent)" : "var(--border-strong)"}
                strokeWidth={isSelected ? 2.5 : 1.2}
                opacity={opacity}
                style={{
                  transition: "all 0.25s ease",
                }}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>

      {/* 2. SVG 点击热区层（置于最底层，方便交互） */}
      <svg
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          zIndex: 2,
        }}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
      >
        {data.edges.map((edge) => {
          const src = positions[edge.source];
          const tgt = positions[edge.target];
          if (!src || !tgt) return null;

          return (
            <line
              key={`hotspot-${edge.id}`}
              x1={src.x}
              y1={src.y}
              x2={tgt.x}
              y2={tgt.y}
              stroke="transparent"
              strokeWidth={8}
              style={{ cursor: "pointer", pointerEvents: "auto" }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectEdge(edge);
              }}
            />
          );
        })}
      </svg>

      {/* 3. HTML 关系标签小药丸 */}
      {data.edges.map((edge) => {
        const src = positions[edge.source];
        const tgt = positions[edge.target];
        if (!src || !tgt) return null;

        const isHighlighted = isEdgeHighlighted(edge);
        const isSelected = selectedEdge?.id === edge.id;
        
        // Show only if the edge is in the focused set or explicitly selected
        const showLabel = isHighlighted && focusedNodeId !== null || isSelected;
        if (!showLabel) return null;

        const midX = (src.x + tgt.x) / 2;
        const midY = (src.y + tgt.y) / 2;

        return (
          <div
            key={`pill-${edge.id}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelectEdge(edge);
            }}
            style={{
              position: "absolute",
              left: `${(midX / W) * 100}%`,
              top: `${(midY / H) * 100}%`,
              transform: "translate(-50%, -50%)",
              zIndex: 4,
              background: "color-mix(in srgb, var(--surface) 70%, transparent)",
              backdropFilter: "blur(6px)",
              WebkitBackdropFilter: "blur(6px)",
              border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
              borderRadius: 999,
              padding: "2px 8px",
              fontSize: 10,
              fontWeight: 600,
              color: isSelected ? "var(--accent)" : "var(--fg-muted)",
              boxShadow: "var(--shadow)",
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "all 0.2s ease",
            }}
          >
            {edge.relation}
          </div>
        );
      })}

      {/* 4. HTML 节点圆盘 (扁平淡毛玻璃) */}
      {data.nodes.map((node) => {
        const pos = positions[node.id];
        if (!pos) return null;

        const typeColor = getNodeTypeColor(node.type);
        const isSelected = selectedNode?.id === node.id;
        const isHighlighted = isNodeHighlighted(node.id);

        const diameter = 34 + (node.degree ?? 1) * 8;
        const opacity = isHighlighted ? 1 : 0.34;

        return (
          <div
            key={node.id}
            onMouseEnter={() => setHoveredNodeId(node.id)}
            onMouseLeave={() => setHoveredNodeId(null)}
            onClick={(e) => {
              e.stopPropagation();
              onSelectNode(node);
            }}
            style={{
              position: "absolute",
              left: `${(pos.x / W) * 100}%`,
              top: `${(pos.y / H) * 100}%`,
              width: diameter,
              height: diameter,
              transform: `translate(-50%, -50%) ${isSelected ? "scale(1.08)" : "scale(1)"}`,
              borderRadius: "50%",
              background: `color-mix(in srgb, ${typeColor} ${isSelected ? 34 : 20}%, color-mix(in srgb, var(--surface) 52%, transparent))`,
              backdropFilter: "blur(7px)",
              WebkitBackdropFilter: "blur(7px)",
              border: `1px solid color-mix(in srgb, ${typeColor} ${isSelected ? 72 : 40}%, transparent)`,
              boxShadow: isSelected ? `0 0 0 3px color-mix(in srgb, ${typeColor} 20%, transparent)` : "none",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              zIndex: isSelected ? 5 : 3,
              opacity: opacity,
              transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          >
            {/* 下方标签 */}
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: "50%",
                transform: "translateX(-50%)",
                marginTop: 6,
                fontSize: 11,
                fontWeight: 600,
                color: isSelected ? "var(--accent)" : "var(--fg)",
                whiteSpace: "nowrap",
                padding: "2px 0",
                pointerEvents: "none",
              }}
            >
              {node.name}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 构建预估弹窗 ─────────────────────────────────────────────

interface BuildEstimateModalProps {
  estimate: import("@/lib/api").GraphBuildEstimate;
  onConfirm: () => void;
  onCancel: () => void;
}

function BuildEstimateModal({ estimate, onConfirm, onCancel }: BuildEstimateModalProps) {
  const { t } = useI18n();

  const rows: [string, string][] = [
    [t("graph_build_modal_docs"),         String(estimate.docs_count)],
    [t("graph_build_modal_chunks"),       String(estimate.chunks_count)],
    [t("graph_build_modal_chars"),        estimate.chars_count.toLocaleString()],
    [t("graph_build_modal_llm_calls"),    `${estimate.estimated_llm_calls_min} – ${estimate.estimated_llm_calls_max}`],
    [t("graph_build_modal_embed_batches"),String(estimate.estimated_embedding_batches)],
    [t("graph_build_modal_duration"),     `${estimate.estimated_duration_seconds_min} – ${estimate.estimated_duration_seconds_max}`],
  ];

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300,
      }}
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 14, padding: 24, width: 380, boxShadow: "var(--shadow-pop)",
        display: "flex", flexDirection: "column", gap: 16,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
          {t("graph_build_modal_title")}
        </h3>

        <div style={{
          background: "var(--bg-inset)", border: "1px solid var(--border)",
          borderRadius: 10, overflow: "hidden",
        }}>
          {rows.map(([label, value], i) => (
            <div key={label} style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "8px 14px",
              borderTop: i > 0 ? "1px solid var(--border)" : undefined,
            }}>
              <span style={{ fontSize: 12, color: "var(--fg-muted)" }}>{label}</span>
              <span style={{ fontSize: 12, fontFamily: "var(--font-geist-mono)", color: "var(--fg)", fontWeight: 600 }}>{value}</span>
            </div>
          ))}
        </div>

        <div style={{
          fontSize: 11, lineHeight: 1.6,
          color: "var(--warn)",
          background: "color-mix(in srgb, var(--warn, #d97706) 10%, transparent)",
          border: "1px solid color-mix(in srgb, var(--warn, #d97706) 30%, transparent)",
          borderRadius: 8, padding: "8px 12px",
        }}>
          ⚠ {estimate.estimate_notice}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Btn variant="ghost" size="sm" onClick={onCancel}>{t("btn_cancel")}</Btn>
          <Btn size="sm" onClick={onConfirm}>{t("graph_build_modal_confirm")}</Btn>
        </div>
      </div>
    </div>
  );
}

// ─── 预留横幅 ─────────────────────────────────────────────────

function ReservedBanner({ availableIn }: { availableIn: string }) {
  return (
    <div
      style={{
        background: "var(--warn-soft)",
        border: "1px solid var(--warn)",
        borderRadius: 10,
        padding: "10px 14px",
        fontSize: 12,
        color: "var(--warn)",
        fontWeight: 600,
      }}
    >
      ⏳ 即将上线（{availableIn}）
    </div>
  );
}

// ─── 图谱页 ───────────────────────────────────────────────────

export default function GraphPage() {
  const { t } = useI18n();
  const { toast } = useToast();

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [queryInput, setQueryInput] = useState("");
  const [queryResult, setQueryResult] = useState<{
    answer?: string;
    context?: string;
    chunks: KbChunk[];
    entities: GraphNode[];
    relations: GraphEdge[];
    debug?: unknown;
  } | null>(null);
  const [querying, setQuerying] = useState(false);
  const [buildJob, setBuildJob] = useState<GraphBuildJob | null>(null);
  const [graphReserved, setGraphReserved] = useState<string | null>(null);
  const [showEstimateModal, setShowEstimateModal] = useState(false);
  const [pendingEstimate, setPendingEstimate] = useState<import("@/lib/api").GraphBuildEstimate | null>(null);
  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState("");
  const [showDetailPanel, setShowDetailPanel] = useState(true);

  useEffect(() => {
    listCollections()
      .then((items) => {
        const names = items.map((item) => item.name);
        setCollections(names);
        const initial = names[0] ?? "";
        setCollection(initial);
        loadGraph(initial);
      })
      .catch(() => loadGraph());
  }, []);

  async function loadGraph(selectedCollection: string = collection) {
    setLoading(true);
    try {
      const res = await getGraph(selectedCollection || undefined);
      if (isReserved(res)) {
        setGraphReserved(res.available_in);
      } else {
        setGraphData(res);
      }
    } catch (err) {
      setGraphData(null);
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleBuild() {
    setBuilding(true);
    try {
      const estimate = await estimateGraphBuild(collection || undefined);
      setPendingEstimate(estimate);
      setShowEstimateModal(true);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setBuilding(false);
    }
  }

  const handleEstimateConfirm = useCallback(async () => {
    setShowEstimateModal(false);
    setPendingEstimate(null);
    try {
      const job = await buildGraph(collection || undefined);
      setBuildJob(job);
      toast(t("graph_build_modal_confirm"), "ok");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }, [collection, t, toast]);

  const handleEstimateCancel = useCallback(() => {
    setShowEstimateModal(false);
    setPendingEstimate(null);
  }, []);

  useEffect(() => {
    if (!buildJob || ["success", "partial_failure", "error"].includes(buildJob.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getGraphBuildJob(buildJob.job_id);
        setBuildJob(next);
        if (next.status === "success" || next.status === "partial_failure") loadGraph(next.collection);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
      }
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [buildJob, t, toast]);

  async function handleQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!queryInput.trim()) return;
    setQuerying(true);
    setQueryResult(null);
    try {
      const res = await queryGraph(queryInput, collection || undefined);
      if (isReserved(res)) {
        toast(`图谱查询即将上线（${res.available_in}）`, "info");
      } else {
        setQueryResult({
          answer: res.answer, context: res.context, chunks: res.chunks ?? [],
          entities: res.entities ?? [], relations: res.relations ?? [], debug: res.debug,
        });
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setQuerying(false);
    }
  }

  function handleClearSelection() {
    setSelectedNode(null);
    setSelectedEdge(null);
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>
      {showEstimateModal && pendingEstimate && (
        <BuildEstimateModal
          estimate={pendingEstimate}
          onConfirm={handleEstimateConfirm}
          onCancel={handleEstimateCancel}
        />
      )}
      {/* 主视图 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* 工具条 */}
        <div
          className="fx-glass"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 3,
            height: "var(--topbar-h)",
            boxSizing: "border-box",
            padding: "0 22px",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--heading)", flex: 1, lineHeight: 1 }}>
            {t("nav_graph")}
            {graphData && (
              <span style={{ marginLeft: 8, fontSize: 11, color: "var(--fg-muted)", fontWeight: 500, lineHeight: 1 }}>
                {graphData.nodes.length} 实体 · {graphData.edges.length} 关系
              </span>
            )}
          </h1>
          <Select
            value={collection}
            onChange={(next) => { setCollection(next); loadGraph(next); }}
            options={collections.map((name) => ({ value: name, label: name }))}
          />
          <Btn variant="outline" size="sm" loading={building} onClick={handleBuild}>
            {t("graph_build")}
          </Btn>
          <button
            onClick={() => setShowDetailPanel(v => !v)}
            title={showDetailPanel ? "收起详情面板" : "展开详情面板"}
            style={{
              width: 28, height: 28, borderRadius: 7, border: "1px solid var(--border)",
              background: showDetailPanel ? "var(--accent-soft)" : "var(--bg-inset)",
              color: showDetailPanel ? "var(--accent)" : "var(--fg-subtle)",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", transition: "all .15s", flexShrink: 0,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="15" y1="3" x2="15" y2="21"/>
            </svg>
          </button>
        </div>

        {/* 图谱画布 */}
        <div style={{ flex: 1, padding: "12px 16px", overflow: "hidden" }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>{t("loading")}</div>
          ) : graphReserved ? (
            <div style={{ padding: 40 }}>
              <ReservedBanner availableIn={graphReserved} />
            </div>
          ) : graphData ? (
            <div style={{ width: "100%", height: "100%", borderRadius: 14, overflow: "hidden", border: "1px solid var(--border)", boxShadow: "inset 0 0 26px color-mix(in srgb, var(--border) 70%, transparent), var(--shadow)" }}>
              <HybridGraph
                data={graphData}
                onSelectNode={(n) => { setSelectedNode(n); setSelectedEdge(null); setShowDetailPanel(true); }}
                onSelectEdge={(e) => { setSelectedEdge(e); setSelectedNode(null); setShowDetailPanel(true); }}
                selectedNode={selectedNode}
                selectedEdge={selectedEdge}
                onClearSelection={handleClearSelection}
              />
            </div>
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13, lineHeight: 1.7 }}>
              知识图谱为空
              <br />
              <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                请先上传文档，再点击顶部「{t("graph_build")}」按钮构建实体关系图
              </span>
            </div>
          )}
        </div>

        {buildJob && (
          <div style={{ borderTop: "1px solid var(--border)", padding: "8px 16px", fontSize: 11, color: "var(--fg-muted)", display: "flex", gap: 12, flexWrap: "wrap" }}>
            <strong style={{ color: "var(--fg)" }}>LightRAG 索引：{buildJob.status}</strong>
            <span>阶段：{buildJob.stage ?? "queued"}</span>
            <span>文档：{buildJob.processed_docs ?? 0}/{buildJob.total_docs ?? 0}</span>
            <span>失败：{buildJob.failed_docs ?? 0}</span>
            <span>耗时：{buildJob.elapsed_seconds ?? 0}s</span>
            {buildJob.recent_error && <span style={{ color: "var(--danger)" }}>{buildJob.recent_error}</span>}
          </div>
        )}

        {/* 图谱增强查询 */}
        <div style={{ borderTop: "1px solid var(--border)", padding: "10px 16px" }}>
          <form onSubmit={handleQuery} style={{ display: "flex", gap: 8 }}>
            <input
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder={t("graph_query_placeholder")}
              style={{ flex: 1, height: 36 }}
            />
            <Btn size="sm" type="submit" loading={querying}>{t("graph_query")}</Btn>
          </form>
        </div>
      </div>

      {/* 右侧详情面板（可折叠） */}
      {showDetailPanel && (
      <div
        style={{
          width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
        className="fx-glass-edge"
      >
        {/* 面板标题 + 关闭 */}
        <div
          className="fx-glass"
          style={{
            position: "sticky", top: 0, zIndex: 2,
            height: "var(--topbar-h)", boxSizing: "border-box",
            padding: "0 10px 0 14px",
            display: "flex", alignItems: "center", gap: 8,
            borderBottom: "1px solid var(--border)", flexShrink: 0,
          }}
        >
          <span style={{ flex: 1, fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)" }}>
            详情
          </span>
          <button
            onClick={() => setShowDetailPanel(false)}
            title="收起详情面板"
            style={{ width: 24, height: 24, borderRadius: 6, border: "none", background: "transparent", color: "var(--fg-subtle)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", transition: "all .15s" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; e.currentTarget.style.color = "var(--fg)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--fg-subtle)"; }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px" }}>
        {/* 节点/边详情 */}
        {selectedNode && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--fg-subtle)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
              {t("graph_nodes")}
            </div>
            <div style={{ background: "var(--accent-soft)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: "var(--accent)", marginBottom: 4 }}>{selectedNode.name}</div>
              <div style={{ fontSize: 12, color: "var(--fg-muted)" }}>{selectedNode.type ?? "—"}</div>
              {selectedNode.degree !== undefined && (
                <div style={{ fontSize: 11, color: "var(--fg-subtle)", marginTop: 4 }}>连接度: {selectedNode.degree}</div>
              )}
            </div>
          </div>
        )}

        {selectedEdge && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--fg-subtle)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
              {t("graph_edges")}
            </div>
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 12, color: "var(--fg)", marginBottom: 4 }}>
                <strong>{selectedEdge.source}</strong> → <strong>{selectedEdge.target}</strong>
              </div>
              <div style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>{selectedEdge.relation}</div>
              {selectedEdge.description && (
                <div style={{ fontSize: 11, color: "var(--fg-muted)", marginTop: 6 }}>{selectedEdge.description}</div>
              )}
            </div>
          </div>
        )}

        {/* 查询结果 */}
        {queryResult && (
          <>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--fg-subtle)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
              查询结果
            </div>
            {(queryResult.answer || queryResult.context) && (
              <div style={{ background: "var(--accent-soft)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, marginBottom: 8, whiteSpace: "pre-wrap", fontSize: 11, lineHeight: 1.55 }}>
                {queryResult.answer || queryResult.context}
              </div>
            )}
            {queryResult.chunks.map((chunk) => (
              <div
                key={chunk.chunk_id}
                style={{ background: "var(--bg-inset)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, marginBottom: 8 }}
              >
                <div style={{ fontSize: 10, color: "var(--fg-subtle)", marginBottom: 4, fontFamily: "var(--font-geist-mono)" }}>#{chunk.ordinal + 1}</div>
                <p style={{ margin: 0, fontSize: 11, color: "var(--fg)", lineHeight: 1.5 }}>{chunk.text}</p>
              </div>
            ))}

            {queryResult.debug && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ fontSize: 11, color: "var(--fg-muted)", cursor: "pointer" }}>{t("graph_debug")}</summary>
                <pre style={{ fontSize: 10, color: "var(--fg-subtle)", marginTop: 6, overflow: "auto", fontFamily: "var(--font-geist-mono)", background: "var(--bg-inset)", borderRadius: 8, padding: 8 }}>
                  {JSON.stringify(queryResult.debug, null, 2)}
                </pre>
              </details>
            )}
          </>
        )}

        {!selectedNode && !selectedEdge && !queryResult && (
          <div style={{ color: "var(--fg-muted)", fontSize: 12, minHeight: 180, padding: 8, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", lineHeight: 1.7 }}>
            点击节点或关系查看来源
            <br />
            或在下方做图谱增强查询
          </div>
        )}
        </div>
      </div>
      )}
    </div>
  );
}
