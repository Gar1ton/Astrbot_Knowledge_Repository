"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * 终端日志数据 hook：轮询、增量合并、暂停、清屏基线与客户端过滤。
 *
 * 设计约定（见 TODO.md v0.30.2）：后端缓冲与前端持有量对齐到 1000 行，
 * 过滤纯客户端完成——不引入服务端过滤参数，保持单一代码路径。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getLogs, type LogLine } from "@/lib/api";
import { LEVELS, normalizeLevel, type LevelKey } from "./format";

export const LOG_LIMIT = 2000;
const POLL_MS = 2500;

/** 默认隐藏 DEBUG：root logger 为 DEBUG 级，不过滤会淹没有效信息。 */
const DEFAULT_LEVELS: Record<LevelKey, boolean> = {
  DEBUG: false,
  INFO: true,
  WARNING: true,
  ERROR: true,
};

export interface TerminalLogs {
  /** 过滤后的可见行（渲染与复制/导出的数据源）。 */
  visible: LogLine[];
  /** 可见行中的 ERROR 计数（错误徽章）。 */
  errorCount: number;
  /** 当前缓冲内出现过的分类（下拉选项）。 */
  categories: string[];
  /** 累计追加的行数，随每次增量拉取单调递增（供"N 条新日志"pill 计数）。 */
  appendedTotal: number;
  /** 服务端确认已因缓冲轮转或单次上限无法返回的最少日志数。 */
  droppedCount: number;
  hasAnyLines: boolean;
  loading: boolean;
  available: boolean;
  paused: boolean;
  levels: Record<LevelKey, boolean>;
  category: string;
  query: string;
  toggleLevel: (level: LevelKey) => void;
  setCategory: (category: string) => void;
  setQuery: (query: string) => void;
  togglePause: () => void;
  refresh: () => void;
  clear: () => void;
}

export function useTerminalLogs(active: boolean): TerminalLogs {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const [paused, setPaused] = useState(false);
  const [appendedTotal, setAppendedTotal] = useState(0);
  const [droppedCount, setDroppedCount] = useState(0);
  const [levels, setLevels] = useState<Record<LevelKey, boolean>>(DEFAULT_LEVELS);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const lastSeqRef = useRef(0);
  /** 清屏基线：之后的所有拉取（含刷新）只取该序号以后的日志，清掉的不复活。 */
  const clearedSeqRef = useRef(0);
  const loadInFlightRef = useRef(false);

  const loadLogs = useCallback(async (mode: "replace" | "append") => {
    if (loadInFlightRef.current) return;
    loadInFlightRef.current = true;
    if (mode === "replace") setLoading(true);
    try {
      const afterSeq = mode === "append" ? lastSeqRef.current : clearedSeqRef.current;
      let result = await getLogs(afterSeq, LOG_LIMIT);
      const serverReset = result.latest_seq < afterSeq;
      if (serverReset) {
        lastSeqRef.current = 0;
        clearedSeqRef.current = 0;
        setDroppedCount(0);
        result = await getLogs(0, LOG_LIMIT);
      }
      setAvailable(true);
      if (result.lines.length > 0) {
        lastSeqRef.current = Math.max(lastSeqRef.current, ...result.lines.map((line) => line.seq));
      }
      if (result.dropped_count > 0) {
        setDroppedCount((n) => Math.max(n, result.dropped_count));
      }
      setLines((prev) => {
        if (mode === "replace" || serverReset) return result.lines;
        if (result.lines.length === 0) return prev;
        const merged = new Map<number, LogLine>();
        for (const line of prev) merged.set(line.seq, line);
        for (const line of result.lines) merged.set(line.seq, line);
        return [...merged.values()].sort((a, b) => a.seq - b.seq).slice(-LOG_LIMIT);
      });
      if (mode === "append" && result.lines.length > 0) {
        setAppendedTotal((n) => n + result.lines.length);
      }
    } catch {
      setAvailable(false);
    } finally {
      loadInFlightRef.current = false;
      if (mode === "replace") setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    loadLogs("replace");
  }, [active, loadLogs]);

  useEffect(() => {
    if (!active || paused) return;
    const timer = window.setInterval(() => {
      loadLogs("append");
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, paused, loadLogs]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter((line) => {
      if (!levels[normalizeLevel(line.level)]) return false;
      if (category !== "all" && (line.category || "other") !== category) return false;
      if (q) {
        const hay = `${line.msg} ${line.name} ${line.location || ""} ${line.exc || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [lines, levels, category, query]);

  const errorCount = useMemo(
    () => visible.reduce((n, line) => (normalizeLevel(line.level) === "ERROR" ? n + 1 : n), 0),
    [visible],
  );

  const categories = useMemo(() => {
    const seen = new Set<string>();
    for (const line of lines) seen.add(line.category || "other");
    return [...seen].sort();
  }, [lines]);

  const toggleLevel = useCallback((level: LevelKey) => {
    setLevels((prev) => ({ ...prev, [level]: !prev[level] }));
  }, []);

  const togglePause = useCallback(() => setPaused((v) => !v), []);

  const refresh = useCallback(() => {
    loadLogs("replace");
  }, [loadLogs]);

  const clear = useCallback(() => {
    clearedSeqRef.current = lastSeqRef.current;
    setLines([]);
    setDroppedCount(0);
  }, []);

  return {
    visible,
    errorCount,
    categories,
    appendedTotal,
    droppedCount,
    hasAnyLines: lines.length > 0,
    loading,
    available,
    paused,
    levels,
    category,
    query,
    toggleLevel,
    setCategory,
    setQuery,
    togglePause,
    refresh,
    clear,
  };
}

export { LEVELS };
export type { LevelKey };
