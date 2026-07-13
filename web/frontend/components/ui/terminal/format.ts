/**
 * 终端日志纯格式化工具（无 React 依赖）。
 *
 * 供 LogRow 渲染与 TerminalPanel 的复制/导出共用，保证屏显与导出文本一致。
 */
import type { LogLine } from "@/lib/api";

export const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
export type LevelKey = (typeof LEVELS)[number];

/** 把后端多种级别写法收敛为四档（CRITICAL→ERROR、WARN→WARNING）。 */
export function normalizeLevel(level: string | undefined): LevelKey {
  const up = (level || "INFO").toUpperCase();
  if (up === "ERROR" || up === "CRITICAL" || up === "FATAL") return "ERROR";
  if (up === "WARNING" || up === "WARN") return "WARNING";
  if (up === "DEBUG" || up === "TRACE") return "DEBUG";
  return "INFO";
}

export function levelShort(level: LevelKey): string {
  if (level === "DEBUG") return "DBG";
  if (level === "WARNING") return "WARN";
  if (level === "ERROR") return "ERR";
  return "INFO";
}

export function levelColor(level: LevelKey): string {
  if (level === "ERROR") return "var(--danger)";
  if (level === "WARNING") return "var(--warn)";
  if (level === "DEBUG") return "var(--fg-subtle)";
  return "var(--accent)";
}

/** ERROR/WARNING 行的整行底色，提升扫描性；其余级别返回 undefined。 */
export function rowBackground(level: LevelKey): string | undefined {
  if (level === "ERROR") return "color-mix(in srgb, var(--danger) 8%, transparent)";
  if (level === "WARNING") return "color-mix(in srgb, var(--warn) 7%, transparent)";
  return undefined;
}

/** HH:MM:SS.mmm（毫秒对并发时序排查是必需的）。 */
export function formatTime(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return "--:--:--.---";
  const d = new Date(ts * 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

/** metadata 中可展示的键值对（跳过空值）。 */
export function metadataPairs(line: LogLine): Array<[string, string]> {
  const meta = line.metadata;
  if (!meta) return [];
  return Object.entries(meta)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]);
}

/** 单行导出格式：`HH:MM:SS.mmm LEVEL [name location] msg`，traceback 缩进跟随其后。 */
export function formatLineText(line: LogLine): string {
  const level = normalizeLevel(line.level);
  const src = line.location ? `${line.name} ${line.location}` : line.name;
  const metaText = metadataPairs(line).map(([k, v]) => `${k}=${v}`).join(" ");
  let text = `${formatTime(line.ts)} ${levelShort(level).padEnd(4)} [${src}] ${line.msg}`;
  if (metaText) text += `  (${metaText})`;
  if (line.exc) {
    text += "\n" + line.exc.split("\n").map((l) => `    ${l}`).join("\n");
  }
  return text;
}

export function buildLogText(lines: LogLine[]): string {
  return lines.map(formatLineText).join("\n");
}
