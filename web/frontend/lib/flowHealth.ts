import type { CapabilitiesData, PipelineStage } from "@/lib/api";

export type WorkflowStatus = "red" | "green" | "purple";

const CORE_STAGE_IDS = new Set(["ingest", "embedding", "vector_store", "retrieval", "ask"]);
const OPTIONAL_STAGE_IDS = new Set(["zotero", "graph", "sync"]);

export function deriveWorkflowStatus(caps: CapabilitiesData | null | undefined): WorkflowStatus {
  if (!caps) return "red";
  const stages = new Map(caps.pipeline.map((stage) => [stage.id, stage]));
  const coreReady = [...CORE_STAGE_IDS].every((id) => {
    const stage = stages.get(id);
    return Boolean(stage && stage.status === "ready" && stage.configured !== false);
  });
  const optionalBroken = caps.pipeline.some((stage) => (
    OPTIONAL_STAGE_IDS.has(stage.id) &&
    stage.configured === true &&
    stage.status === "degraded"
  ));
  if (!coreReady || optionalBroken) return "red";

  const zotero = stages.get("zotero");
  const sync = stages.get("sync");
  if (isReadyEnabled(zotero) || sync?.detail?.r2_enabled === true) return "purple";
  return "green";
}

function isReadyEnabled(stage: PipelineStage | undefined): boolean {
  return Boolean(stage && stage.configured === true && stage.status === "ready");
}
