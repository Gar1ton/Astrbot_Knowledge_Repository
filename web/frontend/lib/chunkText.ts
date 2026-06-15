export type ChunkHeadingKind = "thesis" | "section" | "subsection";

export interface ChunkHeadingPart {
  type: "heading";
  kind: ChunkHeadingKind;
  label: string;
  title?: string;
}

export interface ChunkParagraphPart {
  type: "paragraph";
  text: string;
}

export type ChunkTextPart = ChunkHeadingPart | ChunkParagraphPart;

interface ParsedHeading {
  part: ChunkHeadingPart;
  consumed: number;
}

const THESIS_HEADING_RE = /^\*\*(T\d+[A-Za-z]?)\*\*/;
const SECTION_HEADING_RE = /^\*\*((?:\d+(?:\.\d+)*\.?))\*\*(?:[ \t]+\*\*([^*\n]+?)\*\*)?/;
const SUBSECTION_HEADING_RE = /^_((?:\d+(?:\.\d+)*\.?))_(?:[ \t]+_([^_\n]+?)_)?/;

function parseHeading(paragraph: string): ParsedHeading | null {
  const thesis = paragraph.match(THESIS_HEADING_RE);
  if (thesis) {
    return {
      part: { type: "heading", kind: "thesis", label: thesis[1] },
      consumed: thesis[0].length,
    };
  }

  const section = paragraph.match(SECTION_HEADING_RE);
  if (section) {
    return {
      part: {
        type: "heading",
        kind: "section",
        label: section[1],
        title: section[2]?.trim() || undefined,
      },
      consumed: section[0].length,
    };
  }

  const subsection = paragraph.match(SUBSECTION_HEADING_RE);
  if (subsection) {
    return {
      part: {
        type: "heading",
        kind: "subsection",
        label: subsection[1],
        title: subsection[2]?.trim() || undefined,
      },
      consumed: subsection[0].length,
    };
  }

  return null;
}

export function parseChunkText(text: string): ChunkTextPart[] {
  const normalized = text.replace(/\r\n?/g, "\n");
  const paragraphs = normalized.split(/\n{2,}/);
  const parts: ChunkTextPart[] = [];

  for (const rawParagraph of paragraphs) {
    const paragraph = rawParagraph.trim();
    if (!paragraph) continue;

    const heading = parseHeading(paragraph);
    if (!heading) {
      parts.push({ type: "paragraph", text: paragraph });
      continue;
    }

    parts.push(heading.part);

    const remainder = paragraph.slice(heading.consumed).trim();
    if (remainder) {
      parts.push({ type: "paragraph", text: remainder });
    }
  }

  return parts;
}
