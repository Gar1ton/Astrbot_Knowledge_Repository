"use client";

import React, { useEffect, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  GraphData, GraphNode, GraphEdge, KbChunk, ApiError,
  getGraph, queryGraph, buildGraph, isReserved, listCollections,
} from "@/lib/api";

// ─── 类型配色 ─────────────────────────────────────────────────

function getNodeTypeColor(type?: string): string {
  if (type === "Method/Algorithm") return "var(--accent)";
  if (type === "Dataset") return "var(--accent-2)";
  if (type === "Concept") return "#3b82f6"; // Blue
  if (type === "Person") return "#8b5cf6";  // Purple
  return "var(--accent)";
}

// ─── 混合式扁平毛玻璃图谱（HTML + SVG Hybrid） ────────────────────

interface HybridGraphProps {
  data: GraphData;
  onSelectNode: (n: GraphNode) => void;
  onSelectEdge: (e: GraphEdge) => void;
  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;
  onClearSelection: () => void;
}

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

  // Ellipse positioning on a 560x440 canvas
  const W = 560;
  const H = 440;
  const positions = React.useMemo(() => {
    const pos: Record<string, { x: number; y: number }> = {};
    data.nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / data.nodes.length - Math.PI / 2;
      const rx = W * 0.36;
      const ry = H * 0.34;
      pos[n.id] = {
        x: W / 2 + rx * Math.cos(angle),
        y: H / 2 + ry * Math.sin(angle),
      };
    });
    return pos;
  }, [data]);

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
    chunks: KbChunk[];
    entities: GraphNode[];
    relations: GraphEdge[];
    debug?: unknown;
  } | null>(null);
  const [querying, setQuerying] = useState(false);
  const [buildReserved, setBuildReserved] = useState<string | null>(null);
  const [graphReserved, setGraphReserved] = useState<string | null>(null);
  const [collections, setCollections] = useState<string[]>([]);
  const [collection, setCollection] = useState("");

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
    } catch {
      toast(t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleBuild() {
    setBuilding(true);
    try {
      const res = await buildGraph(collection || undefined);
      if (isReserved(res)) {
        setBuildReserved(res.available_in);
      } else {
        toast("图谱构建已启动", "ok");
        setTimeout(() => loadGraph(collection), 2000);
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setBuilding(false);
    }
  }

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
        setQueryResult({ chunks: res.chunks, entities: res.entities, relations: res.relations, debug: res.debug });
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
      {/* 主视图 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* 工具条 */}
        <div
          className="fx-glass"
          style={{ position: "sticky", top: 0, zIndex: 3, padding: "10px 16px", display: "flex", alignItems: "center", gap: 8 }}
        >
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--heading)", flex: 1 }}>
            {t("nav_graph")}
            {graphData && (
              <span style={{ marginLeft: 8, fontSize: 11, color: "var(--fg-muted)", fontWeight: 500 }}>
                {graphData.nodes.length} 实体 · {graphData.edges.length} 关系
              </span>
            )}
          </h1>
          <select
            value={collection}
            onChange={(event) => {
              const next = event.target.value;
              setCollection(next);
              loadGraph(next);
            }}
            style={{ height: 30, fontSize: 12, padding: "0 8px", borderRadius: 8 }}
          >
            {collections.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          {buildReserved ? (
            <ReservedBanner availableIn={buildReserved} />
          ) : (
            <Btn variant="outline" size="sm" loading={building} onClick={handleBuild}>
              {t("graph_build")}
            </Btn>
          )}
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
                onSelectNode={(n) => { setSelectedNode(n); setSelectedEdge(null); }}
                onSelectEdge={(e) => { setSelectedEdge(e); setSelectedNode(null); }}
                selectedNode={selectedNode}
                selectedEdge={selectedEdge}
                onClearSelection={handleClearSelection}
              />
            </div>
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              暂无图谱数据，点击「{t("graph_build")}」开始构建
            </div>
          )}
        </div>

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

      {/* 右侧详情面板 */}
      <div
        style={{
          width: 280, flexShrink: 0, borderLeft: "1px solid var(--border)",
          overflowY: "auto", padding: "12px 14px",
        }}
        className="fx-glass-edge"
      >
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
  );
}
