// 正文内 Harvard 短引 → 来源序号的还原索引（纯函数，无 React/DOM 依赖，便于单测）。
//
// 后端在 v1.1.0 起把答案里的 `[n]` 确定性改写成 `(Vaswani et al., 2017, p. 3)`，并在每条
// source 上回填同一份 `harvard_in_text` 串。前端据此把正文里的短引重新映射回 `n`，保住
// 「点击引用 → 跳到来源卡片」的交互。

export interface CitationIndex {
  /** 匹配正文里所有可点击引用片段的正则（带 g 标志，调用方每次使用前需重置 lastIndex）。 */
  re: RegExp;
  /** `harvard_in_text` 串 → 来源序号 n。 */
  map: Map<string, number>;
}

export interface CitationSource {
  n: number;
  harvard_in_text?: string;
}

/** 历史消息里仍是裸 `[n]`（v1.1.0 之前落库的），必须始终保留这条兜底分支。 */
const LEGACY_MARKER = "\\[\\d+\\]";

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function buildCitationIndex(sources: CitationSource[] | undefined): CitationIndex {
  const map = new Map<string, number>();
  for (const source of [...(sources ?? [])].sort((a, b) => a.n - b.n)) {
    const key = source.harvard_in_text?.trim();
    // 空串会让正则出现一个在任意位置都命中的空分支，必须跳过。
    if (!key) continue;
    // 首次出现者胜：同文档同页的两个 chunk 会产出相同短引，统一落到较小的 n。
    if (!map.has(key)) map.set(key, source.n);
  }
  // 按串长降序：否则 `Smith, 2020` 会遮蔽 `Smith, 2020, p. 3`，每条带页引用都会链错 chunk。
  const alternatives = [...map.keys()]
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp);
  alternatives.push(LEGACY_MARKER);
  return { re: new RegExp(`(${alternatives.join("|")})`, "g"), map };
}

/** 把一段文本按引用索引切分；`n` 非空表示该片段可点击。 */
export function splitByCitations(
  text: string,
  index: CitationIndex,
): { text: string; n: number | null }[] {
  const parts: { text: string; n: number | null }[] = [];
  let cursor = 0;
  index.re.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = index.re.exec(text)) !== null) {
    if (match.index > cursor) parts.push({ text: text.slice(cursor, match.index), n: null });
    const token = match[0];
    const legacy = /^\[(\d+)\]$/.exec(token);
    const n = legacy ? parseInt(legacy[1], 10) : (index.map.get(token) ?? null);
    parts.push({ text: token, n });
    cursor = match.index + token.length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), n: null });
  return parts;
}
