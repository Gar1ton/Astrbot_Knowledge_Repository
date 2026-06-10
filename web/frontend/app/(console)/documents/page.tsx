"use client";

import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Btn } from "@/components/ui/Btn";
import { Select } from "@/components/ui/Select";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  Collection,
  KrDocument,
  ApiError,
  listCollections,
  createCollection,
  deleteCollection,
  listDocuments,
  uploadDocument,
  patchDocument,
  deleteDocument,
  downloadDocument,
  rebuildIndexPending,
} from "@/lib/api";

// ─── 工具函数 ─────────────────────────────────────────────────

function fmtSize(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
  });
}

function extBadgeColor(ext?: string): string {
  switch (ext?.toLowerCase()) {
    case "pdf": return "#e05b5b";
    case "md": return "#5b8def";
    case "txt": return "#9c9580";
    case "docx": return "#4a90d9";
    default: return "var(--fg-subtle)";
  }
}

function docTitle(doc: KrDocument): string {
  return doc.title || doc.filename || doc.doc_id;
}

const SYSTEM_COLLECTION = "_uncategorized";

// ─── 删除集合确认弹窗 ─────────────────────────────────────────

interface DeleteCollectionModalProps {
  collectionName: string;
  docCount: number;
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteCollectionModal({ collectionName, docCount, onConfirm, onCancel }: DeleteCollectionModalProps) {
  const { t } = useI18n();
  const [input, setInput] = useState("");
  const canDelete = input === collectionName;

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.35)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300,
      }}
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, padding: 24, width: 380, boxShadow: "var(--shadow-pop)" }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
          {t("docs_delete_collection_title")}：<span style={{ color: "var(--accent)" }}>{collectionName}</span>
        </h3>
        {docCount > 0 && (
          <div style={{ background: "color-mix(in srgb, #e05b5b 10%, transparent)", border: "1px solid #e05b5b44", borderRadius: 8, padding: "8px 12px", fontSize: 12, color: "#e05b5b", marginBottom: 14, lineHeight: 1.5 }}>
            {t("docs_delete_collection_warn").replace("{n}", String(docCount))}
          </div>
        )}
        <div style={{ fontSize: 12, color: "var(--fg-muted)", marginBottom: 6 }}>
          {t("docs_delete_collection_confirm_hint")}
        </div>
        <input
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && canDelete) onConfirm(); if (e.key === "Escape") onCancel(); }}
          placeholder={collectionName}
          style={{ width: "100%", marginBottom: 16, fontFamily: "var(--font-geist-mono)", fontSize: 13 }}
        />
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Btn variant="ghost" size="sm" onClick={onCancel}>{t("btn_cancel")}</Btn>
          <Btn size="sm" variant="danger" disabled={!canDelete} onClick={onConfirm}>
            {t("docs_delete_collection_btn")}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── 上传对话框 ───────────────────────────────────────────────

interface UploadModalProps {
  collections: Collection[];
  onClose: () => void;
  onUploaded: (doc: KrDocument) => void;
}

function UploadModal({ collections, onClose, onUploaded }: UploadModalProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const uploadableCollections = collections.filter((c) => !c.is_system);
  const [collection, setCollection] = useState(uploadableCollections[0]?.name ?? collections[0]?.name ?? "default");
  const [tagsInput, setTagsInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) setFiles(dropped);
  }

  async function handleSubmit() {
    if (!files.length) return;
    const tags = tagsInput.split(",").map((t) => t.trim()).filter(Boolean);
    setLoading(true);
    try {
      for (const file of files) {
        const doc = await uploadDocument(file, collection, tags);
        onUploaded(doc);
      }
      toast(`已上传 ${files.length} 个文件`, "ok");
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.3)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        style={{
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 14, padding: 24, width: 400, boxShadow: "var(--shadow-pop)",
        }}
      >
        <h3 style={{ margin: "0 0 16px", fontSize: 15, fontWeight: 700, color: "var(--heading)" }}>
          {t("btn_upload")}
        </h3>

        {/* 拖放区 */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? "var(--accent)" : "var(--border)"}`,
            borderRadius: 10, padding: 24, textAlign: "center",
            cursor: "pointer", color: "var(--fg-muted)", fontSize: 13,
            background: dragOver ? "var(--accent-soft)" : "var(--bg-inset)",
            transition: "all .15s", marginBottom: 14,
          }}
        >
          {files.length
            ? files.map((f) => f.name).join(", ")
            : t("docs_upload_hint")}
          <input
            ref={inputRef} type="file" multiple hidden
            onChange={(e) => { if (e.target.files) setFiles(Array.from(e.target.files)); }}
          />
        </div>

        {/* 集合选择 */}
        <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "block", marginBottom: 4 }}>
          {t("docs_upload_collection_label")}
        </label>
        <Select
          value={collection}
          onChange={setCollection}
          options={collections.map((c) => ({ value: c.name, label: c.name }))}
          style={{ width: "100%", marginBottom: 10 }}
        />

        {/* 标签 */}
        <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "block", marginBottom: 4 }}>
          {t("docs_upload_tags_label")}
        </label>
        <input
          value={tagsInput}
          onChange={(e) => setTagsInput(e.target.value)}
          placeholder="transformer, nlp"
          style={{ width: "100%", marginBottom: 16 }}
        />

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Btn variant="ghost" size="sm" onClick={onClose}>{t("btn_cancel")}</Btn>
          <Btn size="sm" loading={loading} disabled={!files.length} onClick={handleSubmit}>
            {t("btn_upload")}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── 检查器（右栏） ───────────────────────────────────────────

interface InspectorProps {
  doc: KrDocument | null;
  collections: Collection[];
  onClose: () => void;
  onUpdate: (updated: KrDocument) => void;
  onDelete: (id: string) => void;
}

function Inspector({ doc, collections, onClose, onUpdate, onDelete }: InspectorProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [editCollection, setEditCollection] = useState("");
  const [editTags, setEditTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (doc) {
      // Inspector draft follows the newly selected document.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setEditCollection(doc.collection);
      setEditTags([...doc.tags]);
    }
  }, [doc?.doc_id]);

  async function handleSave() {
    if (!doc) return;
    if (editCollection !== doc.collection && !window.confirm("移动文档会从旧 collection 的 LightRAG 索引删除该文档，并要求在目标 collection 手动重建索引。确认继续？")) return;
    setSaving(true);
    try {
      const updated = await patchDocument(doc.doc_id, {
        collection: editCollection,
        tags: editTags,
      });
      onUpdate(updated);
      toast("已保存", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!doc) return;
    if (!window.confirm("删除文档会同时调用 LightRAG adelete_by_doc_id 清理索引。确认继续？")) return;
    try {
      await deleteDocument(doc.doc_id);
      onDelete(doc.doc_id);
      toast("已删除", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "error");
    }
  }

  function addTag(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const v = tagInput.trim().replace(/,+$/, "");
      if (v && !editTags.includes(v)) {
        setEditTags([...editTags, v]);
      }
      setTagInput("");
    }
  }

  if (!doc) {
    return (
      <div
        style={{
          width: 286, flexShrink: 0, borderLeft: "1px solid var(--border)",
          padding: 20, color: "var(--fg-muted)", fontSize: 13,
          display: "flex", alignItems: "center", justifyContent: "center",
          textAlign: "center",
        }}
      >
        <div>
          <div style={{ fontSize: 28, color: "var(--border-strong)", marginBottom: 6 }}>♧</div>
          选择文档查看详情
        </div>
      </div>
    );
  }

  const dirty =
    editCollection !== doc.collection ||
    JSON.stringify(editTags.sort()) !== JSON.stringify([...doc.tags].sort());

  const readOnly = doc.origin === "zotero" || !!doc.read_only;
  const zmeta = doc.zotero_meta;

  return (
    <div
      style={{
        width: 286, flexShrink: 0, borderLeft: "1px solid var(--border)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}
      className="fx-glass-edge"
    >
      {/* 固定头部 */}
      <div
        className="fx-glass"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 2,
          height: "var(--topbar-h)",
          boxSizing: "border-box",
          padding: "0 10px 0 16px",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", lineHeight: 1, marginBottom: 3 }}>
            {t("docs_inspector_title")}
          </div>
          {doc && (
            <div
              style={{
                fontSize: 13, fontWeight: 600, color: "var(--heading)", lineHeight: 1,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}
              title={docTitle(doc)}
            >
              {docTitle(doc)}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          title="收起详情"
          style={{
            width: 24, height: 24, borderRadius: 6, border: "none",
            background: "transparent", color: "var(--fg-subtle)",
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", flexShrink: 0, transition: "all .15s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-inset)"; e.currentTarget.style.color = "var(--fg)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--fg-subtle)"; }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* 滚动内容 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        {/* 来源徽章 + 只读提示 */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999,
            background: doc.origin === "zotero" ? "rgba(140,90,200,0.14)" : "rgba(52,120,200,0.12)",
            color: doc.origin === "zotero" ? "#7a3fb0" : "#2e6bb0",
          }}>
            {doc.origin === "zotero" ? "Zotero 同步" : "本地上传"}
          </span>
          {readOnly && (
            <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999, background: "rgba(150,150,150,0.16)", color: "var(--fg-muted)" }}>
              只读
            </span>
          )}
          {doc.lifecycle_state === "detached" && (
            <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999, background: "rgba(200,120,40,0.16)", color: "#b8761f" }}>
              已脱管
            </span>
          )}
        </div>

        {/* 元数据 + 三指示 */}
        <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 14 }}>
          <tbody>
            {[
              ["大小", fmtSize(doc.size)],
              ["分块数", doc.chunks ?? "—"],
              ["更新时间", fmtDate(doc.updated)],
              ["类型", doc.ext?.toUpperCase() ?? "—"],
              ["末次同步", doc.last_synced_at ? fmtDate(doc.last_synced_at) : "—"],
              ["Milvus 索引", doc.milvus_covered ? "✓ 已覆盖" : "✗ 未覆盖"],
              ["LRAG 索引", doc.lightrag_index_status?.status === "indexed" ? "✓ 已建立"
                : doc.lightrag_index_status?.status === "needs_rebuild" ? "⟳ 需重构"
                : "○ 未建立"],
            ].map(([k, v]) => (
              <tr key={k as string}>
                <td style={{ padding: "4px 0", fontSize: 12, color: "var(--fg-muted)", width: 70 }}>{k}</td>
                <td style={{ padding: "4px 0", fontSize: 12, color: "var(--fg)", fontFamily: "var(--font-geist-mono)", wordBreak: "break-all" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Zotero 文献元数据 */}
        {zmeta && (
          <div style={{ marginBottom: 14, padding: "8px 10px", background: "var(--bg-inset)", borderRadius: 10 }}>
            {zmeta.creators && zmeta.creators.length > 0 && (
              <div style={{ fontSize: 12, color: "var(--fg)", marginBottom: 3 }}>{zmeta.creators.join("; ")}</div>
            )}
            <div style={{ fontSize: 11, color: "var(--fg-muted)" }}>
              {[zmeta.year, zmeta.venue, zmeta.item_type].filter(Boolean).join(" · ")}
            </div>
            {zmeta.doi && (
              <a href={`https://doi.org/${zmeta.doi}`} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: "var(--accent)", wordBreak: "break-all" }}>
                DOI: {zmeta.doi}
              </a>
            )}
            {zmeta.abstract && (
              <p style={{ margin: "6px 0 0", fontSize: 11, color: "var(--fg-muted)", lineHeight: 1.5, maxHeight: 88, overflow: "hidden" }}>{zmeta.abstract}</p>
            )}
          </div>
        )}

        {/* 集合编辑 */}
        <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "block", marginBottom: 4 }}>
          {t("docs_collection")}
        </label>
        {readOnly ? (
          <div style={{ width: "100%", marginBottom: 12, padding: "7px 10px", fontSize: 13, color: "var(--fg-muted)", background: "var(--bg-inset)", borderRadius: 8 }}>
            {doc.collection}
          </div>
        ) : (
          <Select
            value={editCollection}
            onChange={setEditCollection}
            options={collections.map((c) => ({ value: c.name, label: c.name }))}
            style={{ width: "100%", marginBottom: 12 }}
          />
        )}

        {/* 标签编辑 */}
        <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "block", marginBottom: 6 }}>
          {t("docs_tags")}
        </label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          {editTags.map((tag) => (
            <Tag key={tag} label={tag} onRemove={() => setEditTags(editTags.filter((t) => t !== tag))} />
          ))}
        </div>
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={addTag}
          placeholder="输入标签后按 Enter"
          disabled={readOnly}
          style={{ width: "100%", marginBottom: 14 }}
        />

        {/* 操作按钮 */}
        {readOnly ? (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <Btn size="sm" variant="ghost" title={t("docs_download")} onClick={() => downloadDocument(doc.doc_id)}>
              ↓ 下载
            </Btn>
            <span style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
              Zotero 同步来源只读，请在 Zotero 中修改后重新同步。
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {dirty && (
              <Btn size="sm" loading={saving} onClick={handleSave}>{t("btn_save")}</Btn>
            )}
            <Btn size="sm" variant="ghost" title={t("docs_download")} onClick={() => downloadDocument(doc.doc_id)}>
              ↓ 下载
            </Btn>
            <Btn size="sm" variant="danger" onClick={handleDelete}>
              {t("btn_delete")}
            </Btn>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 批量操作条 ───────────────────────────────────────────────

interface BatchBarProps {
  selected: Set<string>;
  docs: KrDocument[];
  collections: Collection[];
  onDone: (updatedDocs: KrDocument[], deletedIds: string[]) => void;
  onClear: () => void;
}

function BatchBar({ selected, collections, onDone, onClear }: BatchBarProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [moving, setMoving] = useState(false);
  const [targetCollection, setTargetCollection] = useState(collections[0]?.name ?? "default");

  async function handleMove() {
    if (!window.confirm("移动文档会影响旧 collection 的 LightRAG 索引，目标 collection 需要手动重建索引。确认继续？")) return;
    setMoving(true);
    const updated: KrDocument[] = [];
    try {
      for (const id of selected) {
        const doc = await patchDocument(id, { collection: targetCollection });
        updated.push(doc);
      }
      onDone(updated, []);
      toast(`已将 ${updated.length} 个文档移动到 ${targetCollection}`, "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "error");
    } finally {
      setMoving(false);
    }
  }

  async function handleDelete() {
    const ids = Array.from(selected);
    if (!window.confirm(`删除 ${ids.length} 个文档会同时清理其 LightRAG 索引。确认继续？`)) return;
    try {
      await Promise.all(ids.map((id) => deleteDocument(id)));
      onDone([], ids);
      toast(`已删除 ${ids.length} 个文档`, "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : t("error_generic"), "error");
    }
  }

  return (
    <div
      className="fx-glass"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 5,
        height: "var(--topbar-h)",
        boxSizing: "border-box",
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "0 22px",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--fg-muted)", marginRight: 4, lineHeight: 1 }}>
        {t("docs_batch_bar").replace("{n}", String(selected.size))}
      </span>

      <Select
        value={targetCollection}
        onChange={setTargetCollection}
        options={collections.map((c) => ({ value: c.name, label: c.name }))}
      />
      <Btn size="sm" variant="outline" loading={moving} onClick={handleMove}>
        {t("docs_batch_move")}
      </Btn>
      <Btn size="sm" variant="danger" onClick={handleDelete}>
        {t("docs_batch_delete")}
      </Btn>
      <Btn size="sm" variant="ghost" onClick={onClear}>{t("btn_cancel")}</Btn>
    </div>
  );
}

// ─── 文档工作台主页 ───────────────────────────────────────────

export default function DocumentsPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const searchParams = useSearchParams();

  const [collections, setCollections] = useState<Collection[]>([]);
  const [docs, setDocs] = useState<KrDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCollection, setActiveCollection] = useState<string | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [inspecting, setInspecting] = useState<KrDocument | null>(null);
  const [showInspector, setShowInspector] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [newColName, setNewColName] = useState("");
  const [showNewCol, setShowNewCol] = useState(false);
  const [sortKey, setSortKey] = useState<"title" | "tags" | "size" | "updated" | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [deleteTarget, setDeleteTarget] = useState<Collection | null>(null);
  const [rebuildingIndex, setRebuildingIndex] = useState(false);

  // 初始化并监听 ?doc_id 跳转（来自 Ask Agent）
  useEffect(() => {
    const docId = searchParams.get("doc_id");
    async function load() {
      setLoading(true);
      try {
        const [cols, allDocs] = await Promise.all([
          listCollections(),
          listDocuments(),
        ]);
        setCollections(cols);
        setDocs(allDocs);
        if (docId) {
          const target = allDocs.find((d) => d.doc_id === docId);
          if (target) setInspecting(target);
        }
      } catch {
        toast(t("error_generic"), "error");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // 筛选后的文档列表
  const filteredDocs = docs.filter((d) => {
    if (activeCollection && d.collection !== activeCollection) return false;
    if (activeTag && !d.tags.includes(activeTag)) return false;
    return true;
  });

  // 排序后的文档列表
  const sortedDocs = sortKey
    ? [...filteredDocs].sort((a, b) => {
        let diff = 0;
        if (sortKey === "title") diff = docTitle(a).localeCompare(docTitle(b), "zh");
        else if (sortKey === "size") diff = (a.size ?? 0) - (b.size ?? 0);
        else if (sortKey === "updated") diff = (a.updated ?? "").localeCompare(b.updated ?? "");
        else if (sortKey === "tags") diff = a.tags.length - b.tags.length;
        return sortDir === "asc" ? diff : -diff;
      })
    : filteredDocs;

  function handleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  }

  // 集合计数
  const collectionCount = (name: string) => docs.filter((d) => d.collection === name).length;

  // 所有标签（去重）
  const allTags = Array.from(new Set(docs.flatMap((d) => d.tags)));

  // 新建集合
  async function handleNewCollection(e: React.FormEvent) {
    e.preventDefault();
    if (!newColName.trim()) return;
    try {
      const col = await createCollection(newColName.trim());
      setCollections([...collections, col]);
      setNewColName("");
      setShowNewCol(false);
      toast(`已创建集合 ${col.name}`, "ok");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleDeleteCollection(name: string) {
    try {
      await deleteCollection(name);
      setCollections((prev) => prev.filter((col) => col.name !== name));
      if (activeCollection === name) setActiveCollection(null);
      const updatedDocs = await listDocuments();
      setDocs(updatedDocs);
      setDeleteTarget(null);
      toast(`已删除集合 ${name}`, "ok");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
      setDeleteTarget(null);
    }
  }

  async function refreshDocuments() {
    const allDocs = await listDocuments();
    setDocs(allDocs);
    if (inspecting) {
      setInspecting(allDocs.find((doc) => doc.doc_id === inspecting.doc_id) ?? null);
    }
  }

  async function handleRebuildMilvusIndex() {
    setRebuildingIndex(true);
    toast("正在重建 Milvus 索引", "info");
    try {
      const result = await rebuildIndexPending();
      await refreshDocuments();
      if ((result.failed_docs ?? 0) > 0) {
        toast(
          `Milvus 索引仍需重建：${result.errors?.[0]?.error || result.message || `${result.failed_docs} 个文档失败`}`,
          "error",
        );
      } else {
        toast(`已重建 ${result.rebuilt_docs} 个文档 / ${result.rebuilt_chunks} 个 chunk`, "ok");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    } finally {
      setRebuildingIndex(false);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === filteredDocs.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filteredDocs.map((d) => d.doc_id)));
    }
  }

  function handleBatchDone(updatedDocs: KrDocument[], deletedIds: string[]) {
    setDocs((prev) => {
      let next = prev.filter((d) => !deletedIds.includes(d.doc_id));
      for (const updated of updatedDocs) {
        next = next.map((d) => (d.doc_id === updated.doc_id ? updated : d));
      }
      return next;
    });
    setSelected(new Set());
    if (inspecting && deletedIds.includes(inspecting.doc_id)) setInspecting(null);
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", position: "relative" }}>
      {/* 左列：集合/标签 */}
      <div
        data-panel="left"
        style={{
          width: "var(--sidebar-left-w)", flexShrink: 0, borderRight: "1px solid var(--border)",
          display: "flex", flexDirection: "column", overflowY: "auto",
          background: "var(--surface)", position: "relative", zIndex: 1,
        }}
      >
        {/* topbar 对齐头部 */}
        <div
          className="fx-glass"
          style={{
            position: "sticky", top: 0, zIndex: 2,
            height: "var(--topbar-h)", boxSizing: "border-box",
            padding: "0 12px",
            display: "flex", alignItems: "center",
            borderBottom: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)" }}>
            文档库
          </span>
        </div>

        <div style={{ padding: "8px 12px 8px" }}>

          {/* 全部 */}
          <button
            onClick={() => { setActiveCollection(null); setActiveTag(null); }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              width: "100%", padding: "5px 8px", borderRadius: 8,
              background: !activeCollection && !activeTag ? "var(--accent-soft)" : "transparent",
              color: !activeCollection && !activeTag ? "var(--accent)" : "var(--fg-muted)",
              border: "none", cursor: "pointer", fontSize: 13, fontFamily: "inherit",
              transition: "all .15s",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="5" rx="2"/>
                <path d="M2 10h20M2 17h20"/>
              </svg>
              {t("docs_all")}
            </span>
            <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>{docs.length}</span>
          </button>

          {/* 未归档系统集合（置顶，仅在存在时显示） */}
          {collections.filter((c) => c.is_system).map((col) => (
            <button
              key={col.name}
              onClick={() => { setActiveCollection(col.name); setActiveTag(null); }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                width: "100%", padding: "5px 8px", borderRadius: 8,
                background: activeCollection === col.name ? "var(--accent-soft)" : "transparent",
                color: activeCollection === col.name ? "var(--accent)" : "var(--fg-subtle)",
                border: "none", cursor: "pointer", fontSize: 13, fontFamily: "inherit",
                transition: "all .15s",
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                  <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
                </svg>
                <span className="truncate" style={{ maxWidth: 100 }}>{t("docs_uncategorized")}</span>
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7, flexShrink: 0 }}>{collectionCount(col.name)}</span>
            </button>
          ))}

          {/* 集合分节标签 */}
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", padding: "8px 8px 3px", marginTop: 2 }}>
            集合
          </div>

          {/* 集合列表 */}
          {collections.filter((c) => !c.is_system).map((col) => (
            <div
              key={col.name}
              style={{ position: "relative" }}
              onMouseEnter={(e) => { const btn = e.currentTarget.querySelector<HTMLElement>(".del-btn"); if (btn) btn.style.opacity = "1"; }}
              onMouseLeave={(e) => { const btn = e.currentTarget.querySelector<HTMLElement>(".del-btn"); if (btn) btn.style.opacity = "0"; }}
            >
              <button
                onClick={() => { setActiveCollection(col.name); setActiveTag(null); }}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  width: "100%", padding: "5px 8px", paddingRight: 28, borderRadius: 8,
                  background: activeCollection === col.name ? "var(--accent-soft)" : "transparent",
                  color: activeCollection === col.name ? "var(--accent)" : "var(--fg-muted)",
                  border: "none", cursor: "pointer", fontSize: 13, fontFamily: "inherit",
                  transition: "all .15s",
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                  </svg>
                  <span className="truncate" style={{ maxWidth: 90 }}>{col.name}</span>
                </span>
                <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7, flexShrink: 0 }}>{collectionCount(col.name)}</span>
              </button>
              {/* 删除按钮（悬浮显示） */}
              <button
                className="del-btn"
                title={`删除集合 ${col.name}`}
                onClick={(e) => { e.stopPropagation(); setDeleteTarget(col); }}
                style={{
                  position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
                  width: 20, height: 20, borderRadius: 5, border: "none",
                  background: "var(--bg-inset)", color: "var(--fg-subtle)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer", opacity: 0, transition: "opacity .15s",
                  padding: 0,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = "#e05b5b"; e.currentTarget.style.background = "color-mix(in srgb, #e05b5b 12%, transparent)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = "var(--fg-subtle)"; e.currentTarget.style.background = "var(--bg-inset)"; }}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                </svg>
              </button>
            </div>
          ))}

          {/* 新建集合 */}
          {showNewCol ? (
            <form onSubmit={handleNewCollection} style={{ marginTop: 6, display: "flex", gap: 4 }}>
              <input
                value={newColName}
                onChange={(e) => setNewColName(e.target.value)}
                placeholder="集合名称"
                autoFocus
                style={{ flex: 1, fontSize: 12, padding: "4px 8px" }}
              />
              <button type="submit" style={{ background: "var(--accent)", color: "#fff", border: "none", borderRadius: 6, padding: "0 8px", cursor: "pointer", fontSize: 12 }}>✓</button>
              <button type="button" onClick={() => setShowNewCol(false)} style={{ background: "none", border: "1px solid var(--border)", borderRadius: 6, padding: "0 6px", cursor: "pointer", fontSize: 12, color: "var(--fg-muted)" }}>✕</button>
            </form>
          ) : (
            <button
              onClick={() => setShowNewCol(true)}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                width: "100%", padding: "5px 8px", marginTop: 4, borderRadius: 8,
                background: "none", border: "1px dashed var(--border)",
                color: "var(--fg-subtle)", cursor: "pointer", fontSize: 12,
                fontFamily: "inherit", transition: "all .15s",
              }}
            >
              + {t("btn_new_collection")}
            </button>
          )}
        </div>

        {/* 标签云 */}
        {allTags.length > 0 && (
          <div style={{ padding: "8px 12px", borderTop: "1px solid var(--border)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 6 }}>
              标签
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {allTags.map((tag) => (
                <button
                  key={tag}
                  onClick={() => { setActiveTag(activeTag === tag ? null : tag); setActiveCollection(null); }}
                  style={{ border: "none", background: "none", padding: 0, cursor: "pointer" }}
                >
                  <Tag label={tag} accent={activeTag === tag} />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 中列：文档表 */}
      <div style={{ flex: 1, minWidth: 200, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 1 }}>
        {/* 工具条（含批量操作）*/}
        {selected.size > 0 ? (
          <BatchBar
            selected={selected}
            docs={docs}
            collections={collections}
            onDone={handleBatchDone}
            onClear={() => setSelected(new Set())}
          />
        ) : (
          <div
            className="fx-glass"
            style={{
              position: "sticky",
              top: 0,
              zIndex: 4,
              height: "var(--topbar-h)",
              boxSizing: "border-box",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "0 22px",
            }}
          >
            <span style={{ flex: 1, display: "flex", alignItems: "baseline", gap: 6, lineHeight: 1 }}>
              <strong style={{ fontSize: 16, color: "var(--heading)", lineHeight: 1 }}>文档</strong>
              <span style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1 }}>
              {activeCollection
                ? `集合：${activeCollection}`
                : activeTag
                ? `标签：${activeTag}`
                : t("docs_all")}
              · {filteredDocs.length}
              </span>
            </span>
            <Btn size="sm" onClick={() => setShowUpload(true)}>
              {t("btn_upload")}
            </Btn>
            <Btn size="sm" variant="ghost" loading={rebuildingIndex} onClick={handleRebuildMilvusIndex}>
              重建 Milvus 索引
            </Btn>
            <button
              onClick={() => setShowInspector(v => !v)}
              title={showInspector ? "收起详情" : "展开详情"}
              style={{
                width: 28, height: 28, borderRadius: 7, border: "1px solid var(--border)",
                background: showInspector ? "var(--accent-soft)" : "var(--bg-inset)",
                color: showInspector ? "var(--accent)" : "var(--fg-subtle)",
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer", transition: "all .15s", flexShrink: 0,
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="15" y1="3" x2="15" y2="21"/>
              </svg>
            </button>
          </div>
        )}

        {/* 表格 */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              {t("loading")}
            </div>
          ) : filteredDocs.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--fg-muted)", fontSize: 13 }}>
              {t("docs_no_docs")}
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ width: 36, padding: "8px 12px", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={selected.size === filteredDocs.length && filteredDocs.length > 0}
                      onChange={toggleAll}
                      style={{ accentColor: "var(--accent)" }}
                    />
                  </th>
                  {([
                    { label: "标题", key: "title" },
                    { label: "标签", key: "tags" },
                    { label: "索引/状态", key: null },
                    { label: "大小", key: "size" },
                    { label: "更新时间", key: "updated" },
                  ] as { label: string; key: typeof sortKey | null }[]).map(({ label, key }) => (
                    <th
                      key={label}
                      style={{
                        padding: "8px 10px", textAlign: "left",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      {key !== null ? (
                        <button
                          onClick={() => handleSort(key)}
                          style={{
                            background: "none", border: "none", cursor: "pointer",
                            padding: 0, fontFamily: "inherit",
                            display: "flex", alignItems: "center", gap: 3,
                            fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
                            textTransform: "uppercase",
                            color: sortKey === key ? "var(--accent)" : "var(--fg-subtle)",
                            transition: "color .15s",
                          }}
                        >
                          {label}
                          {sortKey === key
                            ? <span style={{ fontSize: 10, lineHeight: 1 }}>{sortDir === "asc" ? "↑" : "↓"}</span>
                            : <span style={{ fontSize: 10, lineHeight: 1, opacity: 0.3 }}>↕</span>
                          }
                        </button>
                      ) : (
                        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--fg-subtle)" }}>
                          {label}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedDocs.map((doc, idx) => {
                  const isSelected = selected.has(doc.doc_id);
                  const isInspecting = inspecting?.doc_id === doc.doc_id;
                  return (
                    <tr
                      key={doc.doc_id}
                      onClick={() => { setInspecting(isInspecting ? null : doc); if (!isInspecting) setShowInspector(true); }}
                      style={{
                        background: isInspecting
                          ? "var(--accent-soft)"
                          : isSelected
                          ? "var(--bg-inset)"
                          : "transparent",
                        cursor: "pointer",
                        borderBottom: "1px solid var(--border)",
                        transition: "background .1s",
                        animation: `fadeUp .2s ${idx * 0.02}s both`,
                      }}
                    >
                      <td
                        style={{ padding: "8px 12px", textAlign: "center" }}
                        onClick={(e) => { e.stopPropagation(); toggleSelect(doc.doc_id); }}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(doc.doc_id)}
                          style={{ accentColor: "var(--accent)" }}
                        />
                      </td>
                      <td style={{ padding: "8px 10px", maxWidth: 260 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span
                            style={{
                              fontSize: 9, fontWeight: 700, padding: "1px 4px",
                              borderRadius: 4, background: extBadgeColor(doc.ext),
                              color: "#fff", letterSpacing: "0.04em",
                              flexShrink: 0,
                            }}
                          >
                            {doc.ext?.toUpperCase() ?? "FILE"}
                          </span>
                          <span
                            className="truncate"
                            style={{ fontSize: 13, color: isInspecting ? "var(--accent)" : "var(--fg)", fontWeight: 500 }}
                            title={docTitle(doc)}
                          >
                            {docTitle(doc)}
                          </span>
                          {doc.origin === "zotero" && (
                            <span
                              title={doc.lifecycle_state === "detached" ? "Zotero 同步（已脱管）" : "Zotero 同步（只读）"}
                              style={{
                                flexShrink: 0, fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                                background: doc.lifecycle_state === "detached" ? "rgba(200,120,40,0.16)" : "rgba(140,90,200,0.16)",
                                color: doc.lifecycle_state === "detached" ? "#b8761f" : "#7a3fb0",
                                letterSpacing: "0.04em",
                              }}
                            >
                              {doc.lifecycle_state === "detached" ? "ZOT·脱管" : "ZOT"}
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: "8px 10px" }}>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                          {doc.tags.slice(0, 3).map((tag) => (
                            <Tag key={tag} label={tag} />
                          ))}
                          {doc.tags.length > 3 && (
                            <Tag label={`+${doc.tags.length - 3}`} />
                          )}
                        </div>
                      </td>
                      {/* 索引/状态列 */}
                      <td style={{ padding: "8px 10px", whiteSpace: "nowrap" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                          <span
                            title={doc.milvus_covered ? "Milvus 索引已覆盖" : "Milvus 索引未覆盖"}
                            style={{
                              display: "inline-flex", alignItems: "center", gap: 4,
                              fontSize: 10, fontWeight: 600, fontFamily: "var(--font-geist-mono)",
                              color: doc.milvus_covered ? "#4f9d5b" : "#aaa",
                            }}
                          >
                            <span>{doc.milvus_covered ? "●" : "○"}</span>
                            <span>Milvus</span>
                          </span>
                          <span
                            title={
                              doc.lightrag_index_status?.status === "indexed" ? "LRAG 索引已建立"
                              : doc.lightrag_index_status?.status === "needs_rebuild" ? "LRAG 索引需重构"
                              : "LRAG 索引未建立"
                            }
                            style={{
                              display: "inline-flex", alignItems: "center", gap: 4,
                              fontSize: 10, fontWeight: 600, fontFamily: "var(--font-geist-mono)",
                              color: doc.lightrag_index_status?.status === "indexed" ? "#4f9d5b"
                                : doc.lightrag_index_status?.status === "needs_rebuild" ? "#cc8a2e"
                                : "#aaa",
                            }}
                          >
                            <span>{doc.lightrag_index_status?.status === "indexed" ? "●" : doc.lightrag_index_status?.status === "needs_rebuild" ? "⟳" : "○"}</span>
                            <span>LRAG</span>
                          </span>
                          {doc.lifecycle_state === "detached" && (
                            <span
                              title="Zotero 来源文档已脱管（原条目可能已在 Zotero 中删除）"
                              style={{
                                display: "inline-flex", alignItems: "center", gap: 4,
                                fontSize: 10, fontWeight: 600, fontFamily: "var(--font-geist-mono)",
                                color: "#cc8a2e",
                              }}
                            >
                              <span>△</span>
                              <span>脱管</span>
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: "8px 10px", fontSize: 12, color: "var(--fg-muted)", whiteSpace: "nowrap" }}>
                        {fmtSize(doc.size)}
                      </td>
                      <td style={{ padding: "8px 10px", fontSize: 12, color: "var(--fg-muted)", whiteSpace: "nowrap" }}>
                        {fmtDate(doc.updated)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 右列：检查器（可收起） */}
      {showInspector && (
        <div data-panel="inspector" style={{ display: "contents" }}>
        <Inspector
          doc={inspecting}
          collections={collections}
          onClose={() => { setShowInspector(false); setInspecting(null); }}
          onUpdate={(updated) => {
            setDocs((prev) => prev.map((d) => (d.doc_id === updated.doc_id ? updated : d)));
            setInspecting(updated);
          }}
          onDelete={(id) => {
            setDocs((prev) => prev.filter((d) => d.doc_id !== id));
            setInspecting(null);
            setShowInspector(false);
          }}
        />
        </div>
      )}

      {/* 上传对话框 */}
      {showUpload && (
        <UploadModal
          collections={collections}
          onClose={() => setShowUpload(false)}
          onUploaded={(doc) => setDocs((prev) => [doc, ...prev])}
        />
      )}

      {/* 删除集合确认弹窗 */}
      {deleteTarget && (
        <DeleteCollectionModal
          collectionName={deleteTarget.name}
          docCount={collectionCount(deleteTarget.name)}
          onConfirm={() => handleDeleteCollection(deleteTarget.name)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
