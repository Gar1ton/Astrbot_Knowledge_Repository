"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  GraphData, GraphNode, GraphEdge, ApiError, GraphBuildJob, GraphNotReady, BuildJobRecord,
  getGraph, buildGraph, estimateGraphBuild, getGraphBuildJob, isReserved, isGraphNotReady, listCollections, getBuildJobHistory,
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

function formatDuration(seconds?: number | null): string {
  const total = Math.max(0, Math.round(seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function BuildEstimateModal({ estimate, onConfirm, onCancel }: BuildEstimateModalProps) {
  const { t } = useI18n();

  const rows: [string, string][] = [
    [t("graph_build_modal_docs"),         String(estimate.docs_count)],
    [t("graph_build_modal_chunks"),       String(estimate.chunks_count)],
    ["LRAG chunks",                       String(estimate.estimated_lrag_chunks ?? estimate.chunks_count)],
    [t("graph_build_modal_chars"),        estimate.chars_count.toLocaleString()],
    [t("graph_build_modal_llm_calls"),    `${estimate.estimated_llm_calls_min} – ${estimate.estimated_llm_calls_max}`],
    [t("graph_build_modal_embed_batches"),String(estimate.estimated_embedding_batches)],
    [t("graph_build_modal_duration"),     `${formatDuration(estimate.estimated_duration_seconds_min)} – ${formatDuration(estimate.estimated_duration_seconds_max)}`],
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

// ─── 未就绪状态 ───────────────────────────────────────────────

function GraphReadinessPanel({
  state,
  onBuild,
  building,
  interruptedJob,
}: {
  state: GraphNotReady;
  onBuild: () => void;
  building: boolean;
  interruptedJob: BuildJobRecord | null;
}) {
  const reason = state.reason || state.message || "LightRAG 图谱尚未就绪。";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 14, textAlign: "center" }}>
      <div style={{ width: 56, height: 56, borderRadius: "50%", background: "var(--warn-soft)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--warn)", fontWeight: 800 }}>
        LR
      </div>
      <div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--heading)", marginBottom: 6 }}>LightRAG 图谱未就绪</div>
        <div style={{ fontSize: 13, color: "var(--fg-muted)", lineHeight: 1.6, maxWidth: 420 }}>
          当前集合：<strong style={{ color: "var(--fg)" }}>{state.collection || "（未选择）"}</strong><br />
          {reason}
        </div>
      </div>
      {interruptedJob && (
        <div style={{
          padding: "10px 16px",
          borderRadius: 10,
          background: "color-mix(in srgb, var(--warning, #f59e0b) 12%, transparent)",
          border: "1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent)",
          fontSize: 12, color: "var(--fg-muted)", maxWidth: 360, lineHeight: 1.6,
        }}>
          ⚠️ 上次构建因进程重启被中断（已处理 {interruptedJob.processed_docs}/{interruptedJob.total_docs} 篇）。<br />
          重新发起构建将自动从断点续建，仅处理未完成文档。
        </div>
      )}
      {state.build_available ? (
        <Btn onClick={onBuild} loading={building}>
          {interruptedJob ? "续建知识图谱" : "预估并构建知识图谱"}
        </Btn>
      ) : (
        <div style={{ fontSize: 12, color: "var(--warn)", lineHeight: 1.6, maxWidth: 420 }}>
          请先在数据流或设置中启用 LightRAG，安装可选依赖并重启插件；集合为空时请先上传文档。
        </div>
      )}
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
  const [buildJob, setBuildJob] = useState<GraphBuildJob | null>(null);
  const [graphNotReady, setGraphNotReady] = useState<GraphNotReady | null>(null);
  const [showEstimateModal, setShowEstimateModal] = useState(false);
  const [pendingEstimate, setPendingEstimate] = useState<import("@/lib/api").GraphBuildEstimate | null>(null);
  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState("");
  const [entitySearch, setEntitySearch] = useState("");
  const [interruptedJob, setInterruptedJob] = useState<BuildJobRecord | null>(null);

  const matchingNodes = React.useMemo(() => {
    if (!graphData || !entitySearch.trim()) return [];
    const q = entitySearch.toLowerCase();
    return graphData.nodes.filter((n) => n.name.toLowerCase().includes(q)).slice(0, 8);
  }, [graphData, entitySearch]);

  // Ego network: only the selected node + its direct neighbors
  const focusedGraphData = React.useMemo((): GraphData => {
    if (!selectedNode || !graphData) return { nodes: [], edges: [] };
    const neighborIds = new Set<string>([selectedNode.id]);
    const relevantEdges: GraphEdge[] = [];
    graphData.edges.forEach((e) => {
      if (e.source === selectedNode.id || e.target === selectedNode.id) {
        neighborIds.add(e.source);
        neighborIds.add(e.target);
        relevantEdges.push(e);
      }
    });
    return {
      nodes: graphData.nodes.filter((n) => neighborIds.has(n.id)),
      edges: relevantEdges,
    };
  }, [selectedNode, graphData]);

  // Edges involving the selected node, sorted: outgoing first
  const relatedEdges = React.useMemo(() => {
    if (!selectedNode || !graphData) return [];
    return graphData.edges.filter(
      (e) => e.source === selectedNode.id || e.target === selectedNode.id
    );
  }, [selectedNode, graphData]);

  useEffect(() => {
    const timeoutGuard = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timeout")), 5000)
    );
    Promise.race([listCollections(), timeoutGuard])
      .then((items) => {
        const names = items.map((item: { name: string }) => item.name);
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
      const [res, history] = await Promise.all([
        getGraph(selectedCollection || undefined),
        getBuildJobHistory(selectedCollection || undefined).catch(() => [] as BuildJobRecord[]),
      ]);
      const lastInterrupted = history.find(j => j.status === "interrupted") ?? null;
      setInterruptedJob(lastInterrupted);
      if (isReserved(res)) {
        setGraphData(null);
        setGraphNotReady({
          status: "not_ready",
          ready: false,
          collection: selectedCollection || collection || undefined,
          engine: "lightrag_core",
          reason: `旧服务端返回 reserved：${res.available_in}`,
          build_available: false,
        });
      } else if (isGraphNotReady(res)) {
        setGraphData(null);
        setGraphNotReady(res);
      } else {
        setGraphData(res);
        setGraphNotReady(null);
      }
      setSelectedNode(null);
      setSelectedEdge(null);
    } catch (err) {
      setGraphData(null);
      setGraphNotReady(null);
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
          <Btn
            variant={graphData ? "outline" : "primary"}
            size="sm"
            loading={building}
            disabled={Boolean(graphNotReady && !graphNotReady.build_available)}
            onClick={handleBuild}
          >
            {graphData ? "重建图谱" : t("graph_build")}
          </Btn>
        </div>

        {/* 图谱画布 */}
        <div style={{ flex: 1, padding: "12px 16px", overflow: "hidden" }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>{t("loading")}</div>
          ) : graphNotReady ? (
            <GraphReadinessPanel state={graphNotReady} onBuild={handleBuild} building={building} interruptedJob={interruptedJob} />
          ) : graphData && graphData.nodes.length > 0 ? (
            <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {selectedNode ? (
                <div style={{ width: "100%", height: "100%", borderRadius: 14, overflow: "hidden", border: "1px solid var(--border)", boxShadow: "inset 0 0 26px color-mix(in srgb, var(--border) 70%, transparent), var(--shadow)" }}>
                  <HybridGraph
                    data={focusedGraphData}
                    onSelectNode={(n) => { setSelectedNode(n); setSelectedEdge(null); }}
                    onSelectEdge={(e) => { setSelectedEdge(e); setSelectedNode(null); }}
                    selectedNode={selectedNode}
                    selectedEdge={selectedEdge}
                    onClearSelection={handleClearSelection}
                  />
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, textAlign: "center" }}>
                  <div style={{ width: 52, height: 52, borderRadius: "50%", background: "var(--accent-soft)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "var(--heading)", marginBottom: 4 }}>搜索实体以探索关系网络</div>
                    <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.6 }}>在右侧搜索框中输入实体名称<br/>选中后将显示其直接关联网络</div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 16, textAlign: "center" }}>
              <div style={{ width: 56, height: 56, borderRadius: "50%", background: "var(--accent-soft)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/>
                  <line x1="7.5" y1="12" x2="16.5" y2="6"/><line x1="7.5" y1="12" x2="16.5" y2="18"/>
                </svg>
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--heading)", marginBottom: 6 }}>知识图谱尚未构建</div>
                <div style={{ fontSize: 13, color: "var(--fg-muted)", lineHeight: 1.6, marginBottom: 20 }}>
                  当前集合：<strong style={{ color: "var(--fg)" }}>{collection || "（未选择）"}</strong><br/>
                  LightRAG 将从文档中提取实体与关系
                </div>
                <Btn onClick={handleBuild} loading={building}>预估并构建知识图谱</Btn>
              </div>
            </div>
          )}
        </div>

        {/* 构建进度条 */}
        {buildJob && !["success", "partial_failure", "error"].includes(buildJob.status) && (() => {
          const done = buildJob.total_chunks !== undefined ? (buildJob.processed_chunks ?? 0) : (buildJob.processed_docs ?? 0);
          const total = buildJob.total_chunks !== undefined ? (buildJob.total_chunks ?? 0) : (buildJob.total_docs ?? 0);
          const unit = buildJob.total_chunks !== undefined ? "LRAG chunk" : "文档";
          const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
          return (
          <div style={{ borderTop: "1px solid var(--border)", padding: "10px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block", animation: "spin 0.6s linear infinite", flexShrink: 0 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>
                ⚙ 正在构建图谱：{buildJob.stage ?? "queued"}
              </span>
              <span style={{ fontSize: 11, color: "var(--fg-muted)", marginLeft: "auto" }}>
                {unit} {done} / {total} · 已运行 {formatDuration(buildJob.elapsed_seconds)}
                {buildJob.estimated_remaining_seconds ? ` · 剩余约 ${formatDuration(buildJob.estimated_remaining_seconds)}` : ""}
              </span>
            </div>
            {total > 0 && (
              <div style={{ height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden" }}>
                <div style={{
                  height: "100%", borderRadius: 2, background: "var(--accent)",
                  width: `${pct}%`,
                  transition: "width 0.4s ease",
                }} />
              </div>
            )}
            {buildJob.recent_error && (
              <div style={{ fontSize: 11, color: "var(--danger)", marginTop: 4 }}>{buildJob.recent_error}</div>
            )}
          </div>
          );
        })()}
        {buildJob?.status === "success" && graphData && (
          <div style={{ borderTop: "1px solid var(--border)", padding: "8px 16px", fontSize: 11, color: "var(--fg-muted)", display: "flex", alignItems: "center", gap: 6 }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            <span style={{ color: "var(--ok)", fontWeight: 600 }}>构建完成</span>
            <span>已提取 {graphData.nodes.length} 个实体，{graphData.edges.length} 条关系</span>
          </div>
        )}
      </div>

      {/* 右侧详情面板（常驻） */}
      <div
        style={{
          width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
        className="fx-glass-edge"
      >
        {/* 搜索框（始终置顶） */}
        <div
          style={{
            padding: "10px 12px 8px",
            borderBottom: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            background: "var(--bg-inset)", border: "1px solid var(--border)",
            borderRadius: 8, padding: "6px 10px",
          }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--fg-muted)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input
              value={entitySearch}
              onChange={(e) => setEntitySearch(e.target.value)}
              placeholder="搜索实体…"
              style={{
                flex: 1, background: "transparent", border: "none", outline: "none",
                fontSize: 12, color: "var(--fg)", minWidth: 0,
              }}
            />
            {entitySearch && (
              <button
                onClick={() => setEntitySearch("")}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--fg-muted)", padding: 0, lineHeight: 1, fontSize: 14 }}
              >×</button>
            )}
          </div>
          {/* 搜索结果下拉 */}
          {entitySearch.trim() && matchingNodes.length > 0 && (
            <div style={{
              marginTop: 4, background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, boxShadow: "var(--shadow-pop)", overflow: "hidden",
            }}>
              {matchingNodes.map((node) => (
                <div
                  key={node.id}
                  onClick={() => { setSelectedNode(node); setSelectedEdge(null); setEntitySearch(""); }}
                  style={{ padding: "7px 10px", fontSize: 12, color: "var(--fg)", cursor: "pointer", transition: "background .1s", display: "flex", alignItems: "center", gap: 6 }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "var(--accent-soft)"; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
                >
                  <span style={{ fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{node.name}</span>
                  {node.type && <span style={{ fontSize: 10, color: "var(--fg-muted)", flexShrink: 0 }}>{node.type}</span>}
                </div>
              ))}
            </div>
          )}
          {entitySearch.trim() && matchingNodes.length === 0 && (
            <div style={{ marginTop: 4, fontSize: 11, color: "var(--fg-muted)", padding: "6px 2px" }}>无匹配实体</div>
          )}
        </div>

        {/* 详情区域 */}
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px" }}>
          {selectedNode ? (
            <>
              {/* 实体标题 */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 15, color: "var(--heading)", marginBottom: 4, lineHeight: 1.3 }}>
                  {selectedNode.name}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  {selectedNode.type && (
                    <span style={{
                      fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 999,
                      background: "var(--accent-soft)", color: "var(--accent)", border: "1px solid var(--accent-border)",
                    }}>{selectedNode.type}</span>
                  )}
                  {selectedNode.degree !== undefined && (
                    <span style={{ fontSize: 10, color: "var(--fg-subtle)" }}>{selectedNode.degree} 个关联</span>
                  )}
                </div>
              </div>

              {/* 关联实体列表 */}
              {relatedEdges.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "var(--fg-subtle)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                    关联实体 ({relatedEdges.length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {relatedEdges.map((edge) => {
                      const isOutgoing = edge.source === selectedNode.id;
                      const neighborId = isOutgoing ? edge.target : edge.source;
                      const neighbor = graphData?.nodes.find((n) => n.id === neighborId);
                      if (!neighbor) return null;
                      return (
                        <button
                          key={edge.id}
                          onClick={() => { setSelectedNode(neighbor); setSelectedEdge(null); }}
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)",
                            background: "var(--bg-inset)", cursor: "pointer", textAlign: "left",
                            transition: "all .12s", width: "100%",
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-soft)"; e.currentTarget.style.borderColor = "var(--accent-border)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; e.currentTarget.style.borderColor = "var(--border)"; }}
                        >
                          <span style={{ fontSize: 10, color: "var(--fg-subtle)", flexShrink: 0, width: 14, textAlign: "center" }}>
                            {isOutgoing ? "→" : "←"}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {neighbor.name}
                            </div>
                            <div style={{ fontSize: 10, color: "var(--accent)", fontWeight: 500, marginTop: 1 }}>
                              {edge.relation}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{ color: "var(--fg-muted)", fontSize: 12, minHeight: 120, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", lineHeight: 1.7 }}>
              搜索实体名称<br/>或点击画布中的节点
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
