"use client";

import React, { useEffect, useRef, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  GraphData, GraphNode, GraphEdge, KbChunk, ApiError,
  getGraph, queryGraph, buildGraph, isReserved,
} from "@/lib/api";
import { DotField } from "@/components/fx/DotField";
import { SunBloom } from "@/components/fx/SunBloom";

// ─── 简单力导向图（纯 SVG） ───────────────────────────────────

const W = 600, H = 420;
const TYPE_COLORS: Record<string, string> = {
  "Method/Algorithm": "#df7a18",
  "Dataset": "#4f8a3d",
  "default": "#6b7adb",
};

function nodeColor(type?: string): string {
  return TYPE_COLORS[type ?? "default"] ?? TYPE_COLORS.default;
}

interface SVGGraphProps {
  data: GraphData;
  onSelectNode: (n: GraphNode) => void;
  onSelectEdge: (e: GraphEdge) => void;
  selectedId: string | null;
}

function SVGGraph({ data, onSelectNode, onSelectEdge, selectedId }: SVGGraphProps) {
  const nodeMap = new Map(data.nodes.map((n) => [n.id, n]));
  const RADIUS = 18;

  const positions: Record<string, { x: number; y: number }> = {};
  data.nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / data.nodes.length - Math.PI / 2;
    const r = Math.min(W, H) * 0.35;
    positions[n.id] = {
      x: W / 2 + r * Math.cos(angle),
      y: H / 2 + r * Math.sin(angle),
    };
  });

  return (
    <svg
      width="100%" height="100%"
      viewBox={`0 0 ${W} ${H}`}
      style={{ background: "var(--bg)", borderRadius: 10 }}
    >
      {/* 边 */}
      {data.edges.map((edge) => {
        const src = positions[edge.source];
        const tgt = positions[edge.target];
        if (!src || !tgt) return null;
        return (
          <g key={edge.id} onClick={() => onSelectEdge(edge)} style={{ cursor: "pointer" }}>
            <line
              x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
              stroke={selectedId === edge.id ? "var(--accent)" : "rgba(154,160,173,.5)"}
              strokeWidth={selectedId === edge.id ? 2.5 : 1.4}
            />
            <text
              x={(src.x + tgt.x) / 2}
              y={(src.y + tgt.y) / 2 - 4}
              textAnchor="middle"
              fontSize={9}
              fill="var(--fg-subtle)"
            >
              {edge.relation}
            </text>
          </g>
        );
      })}

      {/* 节点 */}
      {data.nodes.map((node) => {
        const pos = positions[node.id];
        const color = nodeColor(node.type);
        const isSelected = selectedId === node.id;
        return (
          <g
            key={node.id}
            transform={`translate(${pos.x},${pos.y})`}
            onClick={() => onSelectNode(node)}
            style={{ cursor: "pointer" }}
          >
            <circle
              r={RADIUS + (node.degree ?? 1)}
              fill={color}
              opacity={isSelected ? 1 : 0.75}
              stroke={isSelected ? "var(--fg)" : "rgba(255,255,255,.3)"}
              strokeWidth={isSelected ? 2.5 : 1.5}
            />
            <text
              textAnchor="middle" dominantBaseline="central"
              fontSize={10} fontWeight={600} fill="#fff"
              style={{ pointerEvents: "none", userSelect: "none" }}
            >
              {node.name.length > 10 ? node.name.slice(0, 9) + "…" : node.name}
            </text>
          </g>
        );
      })}
    </svg>
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

  const selectedId = selectedNode?.id ?? selectedEdge?.id ?? null;

  useEffect(() => {
    loadGraph();
  }, []);

  async function loadGraph() {
    setLoading(true);
    try {
      const res = await getGraph();
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
      const res = await buildGraph();
      if (isReserved(res)) {
        setBuildReserved(res.available_in);
      } else {
        toast("图谱构建已启动", "ok");
        setTimeout(loadGraph, 2000);
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
      const res = await queryGraph(queryInput);
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

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>
      {/* 视效层 */}
      <SunBloom size={420} style={{ top: -80, right: -40, opacity: 0.65, zIndex: 0 }} />
      <DotField />

      {/* 主视图 */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* 工具条 */}
        <div
          className="fx-glass"
          style={{ position: "sticky", top: 0, zIndex: 3, padding: "10px 16px", display: "flex", alignItems: "center", gap: 8 }}
        >
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--heading)", flex: 1 }}>
            {t("nav_graph")}
          </h1>
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
            <div style={{ width: "100%", height: "100%", borderRadius: 12, overflow: "hidden", border: "1px solid var(--border)" }}>
              <SVGGraph
                data={graphData}
                onSelectNode={(n) => { setSelectedNode(n); setSelectedEdge(null); }}
                onSelectEdge={(e) => { setSelectedEdge(e); setSelectedNode(null); }}
                selectedId={selectedId}
              />
            </div>
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              暂无图谱数据，点击「{t("graph_build")}」开始构建
            </div>
          )}
        </div>

        {/* 图谱查询 */}
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
          <div style={{ color: "var(--fg-muted)", fontSize: 12, padding: 8 }}>
            点击节点或关系查看详情，或在下方输入查询词
          </div>
        )}
      </div>
    </div>
  );
}
