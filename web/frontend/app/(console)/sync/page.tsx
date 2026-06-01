"use client";

import React, { useEffect, useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/lib/i18n";
import {
  ApiError, isReserved,
  SyncRecord, notionInit, syncNotionPull, syncDocuments, getSyncStatus,
  backupNow, restoreBackup,
} from "@/lib/api";

interface ActionCardProps {
  title: string;
  description?: string;
  actionLabel: string;
  onAction: () => Promise<void>;
  danger?: boolean;
}

function ActionCard({ title, description, actionLabel, onAction, danger }: ActionCardProps) {
  const [loading, setLoading] = useState(false);

  async function handle() {
    setLoading(true);
    try {
      await onAction();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14, padding: "14px 18px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
      }}
    >
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--heading)", marginBottom: description ? 4 : 0 }}>{title}</div>
        {description && <p style={{ margin: 0, fontSize: 12, color: "var(--fg-muted)" }}>{description}</p>}
      </div>
      <Btn
        variant={danger ? "danger" : "outline"}
        size="sm"
        loading={loading}
        onClick={handle}
        style={{ flexShrink: 0 }}
      >
        {actionLabel}
      </Btn>
    </div>
  );
}

export default function SyncPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [records, setRecords] = useState<SyncRecord[]>([]);

  useEffect(() => {
    getSyncStatus()
      .then((res) => {
        if (!isReserved(res)) setRecords(res);
      })
      .catch(() => {});
  }, []);

  async function handlePush(target: "r2" | "notion") {
    try {
      const res = await syncDocuments(target);
      if (isReserved(res)) {
        toast(`${target.toUpperCase()} 同步即将上线（${res.available_in}）`, "info");
      } else {
        toast(`${target.toUpperCase()} 同步完成，成功 ${res.synced_count ?? 0} 条`, "ok");
        const status = await getSyncStatus();
        if (!isReserved(status)) setRecords(status);
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleNotionInit() {
    try {
      const res = await notionInit("", "Knowledge Repository");
      if (isReserved(res)) {
        toast(`Notion 初始化即将上线（${res.available_in}）`, "info");
      } else {
        toast("Notion 数据库初始化成功", "ok");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleNotionPull() {
    try {
      const res = await syncNotionPull();
      if (isReserved(res)) {
        toast(`Notion 同步即将上线（${res.available_in}）`, "info");
      } else {
        toast(`从 Notion 拉取完成${res.updated_count !== undefined ? `，更新 ${res.updated_count} 条` : ""}`, "ok");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleBackup() {
    try {
      const res = await backupNow();
      if (isReserved(res)) {
        toast(`备份功能即将上线（${(res as { available_in: string }).available_in}）`, "info");
      } else {
        toast("备份已完成", "ok");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  async function handleRestore() {
    try {
      const res = await restoreBackup();
      if (isReserved(res)) {
        toast(`恢复功能即将上线（${(res as { available_in: string }).available_in}）`, "info");
      } else {
        toast("已恢复备份", "ok");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("error_generic"), "error");
    }
  }

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      <div style={{ padding: "30px 24px", maxWidth: 720, margin: "0 auto", position: "relative", zIndex: 1 }}>
        <div style={{ color: "var(--fg-subtle)", fontSize: 11, fontWeight: 700, marginBottom: 4 }}>运维</div>
        <h1 style={{ margin: "0 0 20px", fontSize: 24, fontWeight: 700, color: "var(--heading)", letterSpacing: "-0.04em" }}>
          {t("nav_sync")}
        </h1>

        {/* Notion */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 700, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Notion 镜像
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <ActionCard
              title={t("sync_notion_init")}
              description="在 Notion 中创建标准知识库 Database"
              actionLabel="初始化"
              onAction={handleNotionInit}
            />
            <ActionCard
              title={t("sync_notion_pull")}
              description="从 Notion 拉取 Collection / Tags 元数据（不覆盖本地文件）"
              actionLabel="拉取"
              onAction={handleNotionPull}
            />
            <ActionCard
              title="推送本地镜像"
              description="将本地文档元数据与摘要增量推送至 Notion"
              actionLabel="推送"
              onAction={() => handlePush("notion")}
            />
          </div>
        </div>

        {/* R2 同步 */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 700, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            R2 同步
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <ActionCard
              title={t("sync_r2")}
              description="将插件托管原件与 knowledge_repository.db 快照增量备份至 Cloudflare R2"
              actionLabel="同步"
              onAction={() => handlePush("r2")}
            />
          </div>
        </div>

        {/* 备份恢复 */}
        <div>
          <h2 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 700, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            备份与恢复
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <ActionCard
              title={t("sync_backup")}
              description="立即创建完整备份"
              actionLabel="备份"
              onAction={handleBackup}
            />
            <ActionCard
              title={t("sync_restore")}
              description="从最近一次备份恢复（此操作不可逆）"
              actionLabel="恢复"
              onAction={handleRestore}
              danger
            />
          </div>
        </div>

        {records.length > 0 && (
          <div>
            <h2 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 700, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              最近同步状态
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {records.slice(-8).reverse().map((record) => (
                <div key={`${record.doc_id}:${record.target}`} style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", fontSize: 12 }}>
                  <strong>{record.target.toUpperCase()}</strong> · {record.doc_id} · {record.status}
                  {record.message ? <div style={{ marginTop: 3, color: "var(--fg-muted)" }}>{record.message}</div> : null}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
