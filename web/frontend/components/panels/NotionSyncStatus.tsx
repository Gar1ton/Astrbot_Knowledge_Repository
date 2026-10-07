"use client";

import { useEffect, useState } from "react";
import { Field } from "@/components/ds/Card";
import { getNotionPushStatus, type NotionPushStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function NotionSyncStatus() {
  const { t } = useI18n();
  const [status, setStatus] = useState<NotionPushStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const value = await getNotionPushStatus();
        if (alive) { setStatus(value); setError(""); }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void refresh();
    const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  return <>
    <Field label={t("notion_ledger_status")}>
      {status && <div style={{ fontSize: 12, overflowWrap: "anywhere" }}>
        <div>{t("notion_documents_failed")}: {status.documents.failed ?? 0}</div>
        <div>{t("notion_qa_pending")}: {status.outbox_pending} · {t("notion_qa_failed")}: {status.outbox_failed}</div>
        {status.errors.map((item) => <div key={item.message} role="alert">{item.count} × {item.message}</div>)}
        <details style={{ marginTop: 8 }}><summary>{t("notion_target_ids")}</summary>
          <div>Articles Database ID: {status.database_id || "—"}</div>
          <div>Articles Data Source ID: {status.data_source_id || "—"}</div>
          <div>QA Database ID: {status.qa_database_id || "—"}</div>
          <div>QA Data Source ID: {status.qa_data_source_id || "—"}</div>
        </details>
      </div>}
      {error && <div role="alert" style={{ fontSize: 12 }}>{error}</div>}
    </Field>
  </>;
}
