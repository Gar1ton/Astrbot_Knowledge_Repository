"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { DotField } from "@/components/fx/DotField";
import { Btn } from "@/components/ui/Btn";
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
  const [collection, setCollection] = useState(collections[0]?.name ?? "default");
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
        <select
          value={collection}
          onChange={(e) => setCollection(e.target.value)}
          style={{ width: "100%", marginBottom: 10 }}
        >
          {collections.map((c) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
        </select>

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
  onUpdate: (updated: KrDocument) => void;
  onDelete: (id: string) => void;
}

function Inspector({ doc, collections, onUpdate, onDelete }: InspectorProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [editCollection, setEditCollection] = useState("");
  const [editTags, setEditTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (doc) {
      setEditCollection(doc.collection);
      setEditTags([...doc.tags]);
    }
  }, [doc?.doc_id]);

  async function handleSave() {
    if (!doc) return;
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
        选择文档查看详情
      </div>
    );
  }

  const dirty =
    editCollection !== doc.collection ||
    JSON.stringify(editTags.sort()) !== JSON.stringify([...doc.tags].sort());

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
          position: "sticky", top: 0, zIndex: 2,
          padding: "12px 16px 10px",
        }}
      >
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 4 }}>
          {t("docs_inspector_title")}
        </div>
        <div
          style={{
            fontSize: 13, fontWeight: 600, color: "var(--heading)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
          title={docTitle(doc)}
        >
          {docTitle(doc)}
        </div>
      </div>

      {/* 滚动内容 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        {/* 元数据 */}
        <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 14 }}>
          <tbody>
            {[
              ["大小", fmtSize(doc.size)],
              ["分块数", doc.chunks ?? "—"],
              ["更新时间", fmtDate(doc.updated)],
              ["类型", doc.ext?.toUpperCase() ?? "—"],
            ].map(([k, v]) => (
              <tr key={k as string}>
                <td style={{ padding: "4px 0", fontSize: 12, color: "var(--fg-muted)", width: 70 }}>{k}</td>
                <td style={{ padding: "4px 0", fontSize: 12, color: "var(--fg)", fontFamily: "var(--font-geist-mono)", wordBreak: "break-all" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* 集合编辑 */}
        <label style={{ fontSize: 12, color: "var(--fg-muted)", display: "block", marginBottom: 4 }}>
          {t("docs_collection")}
        </label>
        <select
          value={editCollection}
          onChange={(e) => setEditCollection(e.target.value)}
          style={{ width: "100%", marginBottom: 12 }}
        >
          {collections.map((c) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
        </select>

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
          style={{ width: "100%", marginBottom: 14 }}
        />

        {/* 操作按钮 */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {dirty && (
            <Btn size="sm" loading={saving} onClick={handleSave}>{t("btn_save")}</Btn>
          )}
          {/* 下载按钮（待后端实现 GET /api/documents/{id}/raw，见 TODO） */}
          <Btn size="sm" variant="ghost" disabled title={t("docs_download")}>
            ↓ 下载
          </Btn>
          <Btn size="sm" variant="danger" onClick={handleDelete}>
            {t("btn_delete")}
          </Btn>
        </div>
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

function BatchBar({ selected, docs, collections, onDone, onClear }: BatchBarProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [moving, setMoving] = useState(false);
  const [targetCollection, setTargetCollection] = useState(collections[0]?.name ?? "default");

  async function handleMove() {
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
        position: "sticky", top: 0, zIndex: 5,
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 16px", flexWrap: "wrap",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--fg-muted)", marginRight: 4 }}>
        {t("docs_batch_bar").replace("{n}", String(selected.size))}
      </span>

      <select
        value={targetCollection}
        onChange={(e) => setTargetCollection(e.target.value)}
        style={{ height: 30, fontSize: 12, padding: "0 8px", borderRadius: 8 }}
      >
        {collections.map((c) => (
          <option key={c.name} value={c.name}>{c.name}</option>
        ))}
      </select>
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
  const [showUpload, setShowUpload] = useState(false);
  const [newColName, setNewColName] = useState("");
  const [showNewCol, setShowNewCol] = useState(false);

  // 初始化并监听 ?doc_id 跳转（来自 Ask Agent）
  useEffect(() => {
    const docId = searchParams.get("doc_id");
    async function load() {
      setLoading(true);
      try {
        const [cols, allDocs] = await Promise.all([listCollections(), listDocuments()]);
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
      {/* Aurora 背景 */}
      <div
        aria-hidden
        style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          background: "radial-gradient(ellipse at 0% 0%, var(--accent-soft) 0%, transparent 40%)",
          opacity: 0.5,
        }}
      />
      <DotField />

      {/* 左列：集合/标签 */}
      <div
        style={{
          width: 198, flexShrink: 0, borderRight: "1px solid var(--border)",
          display: "flex", flexDirection: "column", overflowY: "auto",
          background: "var(--surface)", position: "relative", zIndex: 1,
        }}
      >
        <div style={{ padding: "12px 12px 8px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--fg-subtle)", marginBottom: 8 }}>
            集合
          </div>

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
            <span>{t("docs_all")}</span>
            <span style={{ fontSize: 11 }}>{docs.length}</span>
          </button>

          {/* 集合列表 */}
          {collections.map((col) => (
            <button
              key={col.name}
              onClick={() => { setActiveCollection(col.name); setActiveTag(null); }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                width: "100%", padding: "5px 8px", borderRadius: 8,
                background: activeCollection === col.name ? "var(--accent-soft)" : "transparent",
                color: activeCollection === col.name ? "var(--accent)" : "var(--fg-muted)",
                border: "none", cursor: "pointer", fontSize: 13, fontFamily: "inherit",
                transition: "all .15s",
              }}
            >
              <span className="truncate" style={{ maxWidth: 110 }}>{col.name}</span>
              <span style={{ fontSize: 11 }}>{collectionCount(col.name)}</span>
            </button>
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
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 1 }}>
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
              position: "sticky", top: 0, zIndex: 4,
              display: "flex", alignItems: "center", gap: 8,
              padding: "10px 16px",
            }}
          >
            <span style={{ flex: 1, fontSize: 13, color: "var(--fg-muted)" }}>
              {activeCollection
                ? `集合：${activeCollection}`
                : activeTag
                ? `标签：${activeTag}`
                : t("docs_all")}
              <span style={{ marginLeft: 6, color: "var(--fg-subtle)", fontSize: 12 }}>
                ({filteredDocs.length})
              </span>
            </span>
            <Btn size="sm" onClick={() => setShowUpload(true)}>
              {t("btn_upload")}
            </Btn>
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
                  {["标题", "标签", "大小", "更新时间"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "8px 10px", textAlign: "left",
                        fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
                        textTransform: "uppercase", color: "var(--fg-subtle)",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredDocs.map((doc, idx) => {
                  const isSelected = selected.has(doc.doc_id);
                  const isInspecting = inspecting?.doc_id === doc.doc_id;
                  return (
                    <tr
                      key={doc.doc_id}
                      onClick={() => setInspecting(isInspecting ? null : doc)}
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

      {/* 右列：检查器 */}
      <Inspector
        doc={inspecting}
        collections={collections}
        onUpdate={(updated) => {
          setDocs((prev) => prev.map((d) => (d.doc_id === updated.doc_id ? updated : d)));
          setInspecting(updated);
        }}
        onDelete={(id) => {
          setDocs((prev) => prev.filter((d) => d.doc_id !== id));
          setInspecting(null);
        }}
      />

      {/* 上传对话框 */}
      {showUpload && (
        <UploadModal
          collections={collections}
          onClose={() => setShowUpload(false)}
          onUploaded={(doc) => setDocs((prev) => [doc, ...prev])}
        />
      )}
    </div>
  );
}
