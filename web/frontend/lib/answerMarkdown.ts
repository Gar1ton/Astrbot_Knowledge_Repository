// 回答正文的最小 Markdown block parser：只识别展示所需结构，不解析/执行原始 HTML。

export type AnswerMarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "unordered-list"; items: string[] }
  | { type: "ordered-list"; items: string[] }
  | { type: "code"; language: string; text: string }
  | { type: "rule" };

const HEADING_RE = /^(#{1,6})\s+(.+?)\s*$/;
const STRONG_HEADING_RE = /^\*\*([^*\n]+)\*\*$/;
const UNORDERED_RE = /^\s*[-*+]\s+(.+?)\s*$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.+?)\s*$/;
const RULE_RE = /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/;
const FENCE_RE = /^\s*(`{3,}|~{3,})\s*([^\s]*)\s*$/;

function startsBlock(line: string): boolean {
  return (
    HEADING_RE.test(line) ||
    STRONG_HEADING_RE.test(line) ||
    UNORDERED_RE.test(line) ||
    ORDERED_RE.test(line) ||
    RULE_RE.test(line) ||
    FENCE_RE.test(line)
  );
}

export function parseAnswerMarkdown(markdown: string): AnswerMarkdownBlock[] {
  let inFence = false;
  let fenceMarker = "";
  let fenceLength = 0;
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n").map((rawLine) => {
    // 代码块中的反斜杠必须逐字保留；只在普通 Markdown 行兼容传输层的 \# / \- 转义
    // 和独立反斜杠硬换行。
    if (inFence) {
      if (new RegExp(`^\\s*${fenceMarker}{${fenceLength},}\\s*$`).test(rawLine)) {
        inFence = false;
      }
      return rawLine;
    }
    const opening = FENCE_RE.exec(rawLine);
    if (opening) {
      inFence = true;
      fenceMarker = opening[1][0];
      fenceLength = opening[1].length;
      return rawLine;
    }
    if (rawLine.trim() === "\\") return "";
    return rawLine
      .replace(/^(\s*)\\(?=(?:#{1,6}|[-*+])\s)/, "$1")
      .replace(/\\\s*$/, "");
  });
  const blocks: AnswerMarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = FENCE_RE.exec(line);
    if (fence) {
      const marker = fence[1][0];
      const minimumLength = fence[1].length;
      const code: string[] = [];
      index += 1;
      while (index < lines.length) {
        const closing = new RegExp(`^\\s*${marker}{${minimumLength},}\\s*$`).test(lines[index]);
        if (closing) {
          index += 1;
          break;
        }
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", language: fence[2], text: code.join("\n") });
      continue;
    }

    const heading = HEADING_RE.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }
    const strongHeading = STRONG_HEADING_RE.exec(line.trim());
    if (strongHeading) {
      blocks.push({ type: "heading", level: 3, text: strongHeading[1] });
      index += 1;
      continue;
    }
    if (RULE_RE.test(line)) {
      blocks.push({ type: "rule" });
      index += 1;
      continue;
    }

    const unordered = UNORDERED_RE.exec(line);
    const ordered = ORDERED_RE.exec(line);
    if (unordered || ordered) {
      const pattern = unordered ? UNORDERED_RE : ORDERED_RE;
      const items: string[] = [];
      while (index < lines.length) {
        const item = pattern.exec(lines[index]);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      blocks.push({ type: unordered ? "unordered-list" : "ordered-list", items });
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}
