"use client";
import React, { useEffect, useState } from "react";
import { Panel } from "@/components/ds/Panel";
import { IconButton } from "@/components/ds/IconButton";
import { Icon } from "@/components/ds/Icon";
import { useConsole } from "@/lib/ConsoleContext";
import { listCollections, getActiveBuildJob, getBuildJobHistory, buildGraph, deleteCollection, Collection, GraphBuildJob, BuildJobRecord } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";

// ─── Sub-components ───────────────────────────────────────────

function Caret({ open }: { open: boolean }) {
  return (
    <Icon
      name="chevR"
      size={13}
      style={{ transform: open ? "rotate(90deg)" : undefined, transition: "transform .15s", color: "var(--fg-subtle)" }}
    />
  );
}

interface RowProps {
  depth: number;
  active: boolean;
  leaf?: boolean;
  label: string;
  count?: number;
  icon: React.ReactNode;
  onClick: () => void;
  graphStatus?: "not_built" | "building" | "success";
  badge?: React.ReactNode;
}

function Row({ depth, active, leaf, label, count, icon, onClick, graphStatus, badge }: RowProps) {
  const [hover, setHover] = useState(false);
  const { t } = useI18n();
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: `5px 8px 5px ${10 + depth * 16}px`,
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        userSelect: "none",
        backgroundColor: active ? "var(--select-bg)" : hover ? "var(--bg-inset)" : "rgba(0,0,0,0)",
        color: active ? "var(--select-fg)" : leaf ? "var(--fg-muted)" : "var(--fg)",
        transition: "background-color .12s, color .12s",
        margin: "1px 0",
      }}
    >
      {/* Branch pulse on active leaf */}
      {active && depth > 0 && (
        <span
          aria-hidden
          style={{
            position: "absolute",
            left: 10 + (depth - 1) * 16 + 3,
            top: "50%",
            width: 13,
            height: 2,
            transform: "translateY(-50%)",
            overflow: "hidden",
          }}
        >
          <span
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: 8,
              height: 2,
              borderRadius: 2,
              background: "var(--accent)",
              boxShadow: "0 0 6px 1px var(--accent)",
              animation: "branchPulse 1.6s ease-in-out infinite",
            }}
          />
        </span>
      )}
      <span
        style={{
          display: "inline-flex",
          color: active
            ? leaf ? "var(--select-muted)" : "var(--select-fg)"
            : leaf ? "var(--fg-subtle)" : "var(--accent)",
          flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span
        style={{
          flex: 1,
          fontSize: 12.5,
          fontWeight: active && !leaf ? 600 : leaf ? 400 : 500,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      {badge}
      {count != null && (
        <span
          style={{
            fontSize: 10.5,
            fontWeight: 600,
            color: active ? "var(--select-muted)" : "var(--fg-subtle)",
            fontFamily: "var(--font-mono)",
            flexShrink: 0,
          }}
        >
          {count}
        </span>
      )}
      {graphStatus && (() => {
        const dotColor =
          graphStatus === "success"  ? "var(--ok)" :
          graphStatus === "building" ? "var(--ann-purple)" :
                                       "var(--danger)";
        const dotTitle =
          graphStatus === "success"  ? t("file_graph_built") :
          graphStatus === "building" ? t("file_graph_building") :
                                       t("file_graph_not_built");
        return (
          <span
            title={dotTitle}
            style={{ width: 5, height: 5, borderRadius: "50%", background: dotColor, flexShrink: 0 }}
          />
        );
      })()}
    </div>
  );
}

interface SectionHeadProps {
  icon: string;
  label: string;
  actions?: React.ReactNode;
}

function SectionHead({ icon, label, actions }: SectionHeadProps) {
  const { lang } = useI18n();

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px 4px 8px", marginTop: 2 }}>
      <span style={{ display: "inline-flex", color: "var(--fg-subtle)" }}>
        <Icon name={icon} size={14} />
      </span>
      <span
        style={{
          flex: 1,
          fontSize: lang === "zh" ? 11 : 10.5,
          fontWeight: 700,
          letterSpacing: lang === "zh" ? 0 : ".07em",
          textTransform: lang === "zh" ? "none" : "uppercase",
          color: "var(--fg-subtle)",
        }}
      >
        {label}
      </span>
      {actions && <div style={{ display: "flex", gap: 1 }}>{actions}</div>}
    </div>
  );
}

// ─── Build progress card ───────────────────────────────────────

interface BuildCardProps {
  job: GraphBuildJob;
}

function BuildCard({ job }: BuildCardProps) {
  const { t } = useI18n();
  const pct =
    job.total_chunks && job.total_chunks > 0
      ? Math.round(((job.processed_chunks ?? 0) / job.total_chunks) * 100)
      : 0;
  const stage =
    job.status === "running" ? (pct < 45 ? t("file_build_stage_entity") : pct < 80 ? t("file_build_stage_relation") : t("file_build_stage_embedding")) : job.status;

  return (
    <div
      style={{
        margin: "3px 6px 8px 24px",
        padding: "8px 10px",
        background: "var(--accent-soft)",
        border: "1px solid var(--accent-border)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
        <span
          style={{
            width: 9,
            height: 9,
            borderRadius: "50%",
            border: "2px solid var(--accent)",
            borderTopColor: "transparent",
            animation: "spin .7s linear infinite",
            flexShrink: 0,
          }}
        />
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", flex: 1 }}>
          {t("file_build_running")} · {stage}
        </span>
        <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
          {pct}%
        </span>
      </div>
      <div
        style={{
          height: 5,
          borderRadius: 999,
          background: "color-mix(in srgb, var(--accent) 18%, transparent)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            borderRadius: 999,
            background: "linear-gradient(90deg, var(--accent), var(--accent-strong))",
            transition: "width .4s",
          }}
        />
      </div>
      <div
        style={{
          fontSize: 10,
          color: "var(--fg-muted)",
          marginTop: 6,
          fontFamily: "var(--font-mono)",
        }}
      >
        {job.processed_chunks ?? 0}/{job.total_chunks ?? "?"} {t("unit_chunks")} · {t("file_build_isolated")}
      </div>
    </div>
  );
}

// ─── Active build status card (section-level, above all collections) ──────────

interface ActiveBuildCardProps {
  job?: GraphBuildJob | null;
  interrupted?: BuildJobRecord | null;
  onResume: (collection: string) => void;
}

function ActiveBuildCard({ job, interrupted, onResume }: ActiveBuildCardProps) {
  const { t } = useI18n();

  if (job && (job.status === "running" || job.status === "queued")) {
    const pct =
      job.total_chunks && job.total_chunks > 0
        ? Math.round(((job.processed_chunks ?? 0) / job.total_chunks) * 100)
        : 0;
    const stage =
      job.status === "running"
        ? pct < 45
          ? t("file_build_stage_entity")
          : pct < 80
          ? t("file_build_stage_relation")
          : t("file_build_stage_embedding")
        : t("file_build_queued");
    return (
      <div
        style={{
          margin: "4px 6px 6px",
          padding: "8px 10px",
          background: "var(--accent-soft)",
          border: "1px solid var(--accent-border)",
          borderRadius: "var(--radius-md)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 7 }}>
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              border: "2px solid var(--accent)",
              borderTopColor: "transparent",
              animation: "spin .7s linear infinite",
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", flex: 1 }}>
            {job.collection} · {stage}
          </span>
          <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
            {pct}%
          </span>
        </div>
        <div
          style={{
            height: 5,
            borderRadius: 999,
            background: "color-mix(in srgb, var(--accent) 18%, transparent)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              borderRadius: 999,
              background: "linear-gradient(90deg, var(--accent), var(--accent-strong))",
              transition: "width .4s",
            }}
          />
        </div>
        <div
          style={{
            fontSize: 10,
            color: "var(--fg-muted)",
            marginTop: 6,
            fontFamily: "var(--font-mono)",
          }}
        >
          {job.processed_chunks ?? 0}/{job.total_chunks ?? "?"} {t("unit_chunks")}
        </div>
      </div>
    );
  }

  if (interrupted) {
    return (
      <div
        style={{
          margin: "4px 6px 6px",
          padding: "8px 10px",
          background: "color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent)",
          border: "1px solid color-mix(in srgb, var(--warning, #f59e0b) 35%, transparent)",
          borderRadius: "var(--radius-md)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--warning, #f59e0b)",
              flex: 1,
            }}
          >
            {t("file_build_interrupted")} · {interrupted.collection}
          </span>
          <button
            onClick={() => onResume(interrupted.collection)}
            style={{
              fontSize: 11,
              padding: "2px 10px",
              borderRadius: 999,
              background: "var(--accent)",
              color: "var(--accent-fg, #fff)",
              border: "none",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {t("file_build_resume")}
          </button>
        </div>
      </div>
    );
  }

  return null;
}

// ─── Main FilePanel ────────────────────────────────────────────

// ─── Delete Collection Confirmation Dialog ─────────────────────

interface DeleteDialogProps {
  collectionName: string;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}

function DeleteCollectionDialog({ collectionName, onConfirm, onCancel, deleting }: DeleteDialogProps) {
  const { t } = useI18n();
  const [inputValue, setInputValue] = useState("");
  const canConfirm = inputValue === collectionName && !deleting;
  const [hintBefore, hintAfter] = t("file_delete_input_hint").split("{name}");

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") onCancel();
    if (e.key === "Enter" && canConfirm) onConfirm();
  }

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2000,
        background: "rgba(22,23,26,.46)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        animation: "overlayIn .15s ease",
      }}
    >
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-2xl)",
          boxShadow: "var(--shadow-pop)",
          width: 380,
          maxWidth: "calc(100vw - 32px)",
          padding: "22px 22px 18px",
          animation: "modalIn .18s cubic-bezier(.2,.7,.2,1)",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 11 }}>
          <span
            style={{
              width: 34,
              height: 34,
              borderRadius: "var(--radius-lg)",
              background: "var(--danger-soft)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              color: "var(--danger)",
            }}
          >
            <Icon name="trash" size={16} />
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--heading)", lineHeight: 1.3 }}>
              {t("file_delete_title")}
            </div>
            <div style={{ fontSize: 12, color: "var(--fg-muted)", marginTop: 4, lineHeight: 1.5 }}>
              {t("file_delete_warning")}
            </div>
          </div>
        </div>

        {/* Name confirmation input */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label
            style={{ fontSize: 12, fontWeight: 500, color: "var(--fg-muted)" }}
            htmlFor="delete-collection-input"
          >
            {hintBefore}<code style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              background: "var(--bg-inset)",
              padding: "1px 5px",
              borderRadius: "var(--radius-sm)",
              color: "var(--danger)",
            }}>{collectionName}</code>{hintAfter}
          </label>
          <input
            id="delete-collection-input"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={collectionName}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            style={{
              borderColor: inputValue && inputValue !== collectionName ? "var(--danger)" : undefined,
            }}
          />
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            style={{
              background: "var(--bg-inset)",
              border: "1px solid var(--border-strong)",
              color: "var(--fg-muted)",
              borderRadius: "var(--radius-xl)",
              padding: "7px 16px",
              fontSize: 12.5,
              fontWeight: 500,
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "background .12s",
            }}
          >
            {t("btn_cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            style={{
              background: canConfirm ? "var(--danger)" : "var(--bg-inset)",
              border: "1px solid transparent",
              color: canConfirm ? "#fff" : "var(--fg-subtle)",
              borderRadius: "var(--radius-xl)",
              padding: "7px 16px",
              fontSize: 12.5,
              fontWeight: 600,
              cursor: canConfirm ? "pointer" : "not-allowed",
              fontFamily: "inherit",
              transition: "background .15s, color .15s",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {deleting ? (
              <>
                <span style={{
                  width: 10, height: 10, borderRadius: "50%",
                  border: "2px solid rgba(255,255,255,0.4)",
                  borderTopColor: "#fff",
                  animation: "spin .6s linear infinite",
                  display: "inline-block",
                }} />
                {t("file_delete_loading")}
              </>
            ) : t("docs_delete_collection_btn")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main FilePanel ────────────────────────────────────────────

export function FilePanel() {
  const { selectedCollection, setSelectedCollection, setSelectedDocId } = useConsole();
  const { toast } = useToast();
  const { t } = useI18n();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [buildJob, setBuildJob] = useState<GraphBuildJob | null>(null);
  const [buildHistory, setBuildHistory] = useState<BuildJobRecord[]>([]);
  const [openKeys, setOpenKeys] = useState<Record<string, boolean>>({});
  const [deletingCollection, setDeletingCollection] = useState<string | null>(null);
  const [deleteInProgress, setDeleteInProgress] = useState(false);

  useEffect(() => {
    listCollections().then(setCollections).catch(() => {});
    getBuildJobHistory().then(setBuildHistory).catch(() => {});
  }, []);

  const prevBuildJobRef = React.useRef<GraphBuildJob | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      if (cancelled) return;
      try {
        const job = await getActiveBuildJob();
        if (!cancelled) {
          // job just finished → refresh history to reflect new status
          if (prevBuildJobRef.current && !job) {
            getBuildJobHistory().then(setBuildHistory).catch(() => {});
          }
          prevBuildJobRef.current = job;
          setBuildJob(job);
        }
      } catch { /* ignore */ }
      if (!cancelled) setTimeout(poll, job ? 2000 : 5000);
    }
    let job = buildJob;
    poll();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function getCollectionGraphStatus(collectionName: string): "not_built" | "building" | "success" {
    if (buildJob && buildJob.collection === collectionName &&
        (buildJob.status === "running" || buildJob.status === "queued")) {
      return "building";
    }
    const latest = buildHistory
      .filter((r) => r.collection === collectionName)
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
    if (latest?.status === "success") return "success";
    return "not_built";
  }

  const zoteroCollections = collections.filter((c) => c.origin === "zotero");
  const localCollections = collections.filter((c) => c.origin !== "zotero");
  // LightRAG collections: all non-system collections (user can build graph on any)
  const lightragCollections = collections.filter((c) => !c.is_system);

  const latestHistoryRecord = buildHistory
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  const interruptedJob: BuildJobRecord | null =
    !buildJob && latestHistoryRecord?.status === "interrupted" ? latestHistoryRecord : null;

  const isSel = (prefix: string, name: string) =>
    selectedCollection === `${prefix}${name}`;

  function toggleKey(k: string) {
    setOpenKeys((o) => ({ ...o, [k]: !o[k] }));
  }

  function selectCollection(key: string) {
    setSelectedCollection(key);
    setSelectedDocId(null);
  }

  return (
    <>
    <Panel
      title={t("panel_file")}
      flush
      style={{ flex: 1 }}
      right={
        <>
          <IconButton name="arrowUp" label={t("file_action_lightrag_build")} />
          <IconButton name="cloud" label={t("file_action_r2_backup")} />
          <IconButton name="sync" label={t("file_action_zotero_sync")} />
        </>
      }
    >
      <div style={{ padding: "6px 8px 14px" }}>
        {/* ZOTERO SYNC */}
        <SectionHead
          icon="sync"
          label={t("file_zotero_sync")}
          actions={
            <>
              <IconButton name="sync" label={t("file_action_zotero_sync")} size={14} />
              <IconButton name="plus" label={t("file_action_new_collection")} size={14} />
            </>
          }
        />
        {zoteroCollections.map((c) => {
          const k = `z:${c.name}`;
          const isOpen = openKeys[k] ?? false;
          return (
            <div key={k}>
              <Row
                depth={0}
                icon={<Caret open={isOpen} />}
                label={c.name}
                active={isSel("z:", c.name)}
                onClick={() => { toggleKey(k); selectCollection(k); }}
              />
            </div>
          );
        })}
        {zoteroCollections.length === 0 && (
          <div style={{ padding: "4px 10px 4px 26px", fontSize: 11, color: "var(--fg-subtle)" }}>
            {t("file_no_zotero")}
          </div>
        )}

        <div style={{ height: 1, background: "var(--border)", margin: "10px 6px" }} />

        {/* LOCAL COLLECTION */}
        <SectionHead
          icon="folder"
          label={t("file_local_collections")}
          actions={
            <>
              <IconButton name="upload" label={t("file_action_upload_document")} size={14} />
              <IconButton name="plus" label={t("file_action_new_collection")} size={14} />
            </>
          }
        />
        {localCollections.map((c) => {
          const k = `l:${c.name}`;
          const isOpen = openKeys[k] ?? false;
          const isActive = isSel("l:", c.name);
          return (
            <div key={k} style={{ position: "relative" }}>
              <Row
                depth={0}
                icon={<Caret open={isOpen} />}
                label={c.name}
                active={isActive}
                onClick={() => { toggleKey(k); selectCollection(k); }}
                badge={
                  isActive ? (
                    <IconButton
                      name="trash"
                      label={t("file_action_delete_collection")}
                      size={13}
                      side="left"
                      style={{
                        width: 22,
                        height: 22,
                        color: "var(--select-fg)",
                        background: "transparent",
                        flexShrink: 0,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeletingCollection(c.name);
                      }}
                    />
                  ) : null
                }
              />
            </div>
          );
        })}

        <div style={{ height: 1, background: "var(--border)", margin: "10px 6px" }} />

        {/* LIGHTRAG COLLECTION */}
        <SectionHead
          icon="graph"
          label={t("file_lightrag_collections")}
          actions={
            <IconButton name="spark2" label={t("file_action_lightrag_build")} size={14} />
          }
        />
        <ActiveBuildCard
          job={buildJob}
          interrupted={interruptedJob}
          onResume={(col) => { buildGraph(col).catch(() => {}); }}
        />
        {lightragCollections.map((c) => {
          const k = `lr:${c.name}`;
          return (
            <div key={k}>
              <Row
                depth={0}
                icon={<Icon name="layers" size={13} />}
                label={c.name}
                active={isSel("lr:", c.name)}
                graphStatus={getCollectionGraphStatus(c.name)}
                onClick={() => selectCollection(k)}
              />
            </div>
          );
        })}
      </div>
    </Panel>

    {/* Delete confirmation dialog */}
    {deletingCollection && (
      <DeleteCollectionDialog
        collectionName={deletingCollection}
        deleting={deleteInProgress}
        onCancel={() => setDeletingCollection(null)}
        onConfirm={async () => {
          setDeleteInProgress(true);
          try {
            await deleteCollection(deletingCollection);
            toast(t("file_deleted_toast", { name: deletingCollection }), "ok");
            if (selectedCollection === `l:${deletingCollection}`) {
              setSelectedCollection(null);
              setSelectedDocId(null);
            }
            setDeletingCollection(null);
            listCollections().then(setCollections).catch(() => {});
          } catch (err: unknown) {
            toast(t("file_delete_failed_toast", { message: err instanceof Error ? err.message : String(err) }), "error");
          } finally {
            setDeleteInProgress(false);
          }
        }}
      />
    )}
    </>
  );
}
