import type { ModelRuntime } from "@/lib/api";

// 与数据流按钮共用一套呼吸光效语义（globals.css 的 wf-pulse-*）：
//   green  = 模型全部已卸载，显存已让出，可以放心开本地大模型
//   purple = 有模型驻留，正常工作中
//   red    = 加载失败，或配置了 cuda 却读不到加速器
export type ModelStatus = "red" | "green" | "purple";

export function deriveModelStatus(runtime: ModelRuntime | null | undefined): ModelStatus {
  if (!runtime) return "red";
  const models = runtime.models ?? [];
  if (models.some((m) => m.state === "failed")) return "red";
  // 显式选了 CUDA 却没有可用加速器 → 实际会退回 CPU 或直接报错，等同故障。
  const wantsCuda = models.some((m) => (m.device ?? "").startsWith("cuda"));
  if (wantsCuda && runtime.accelerator === null) return "red";
  if (models.some((m) => m.state === "ready" || m.state === "loading")) return "purple";
  return "green";
}

/** 把字节数渲染为面板用的短串（1 位小数，GB/MB 自适应）。 */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "0 MB";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}
