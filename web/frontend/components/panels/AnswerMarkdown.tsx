"use client";

import React from "react";
import { buildCitationIndex, splitByCitations, type CitationIndex } from "@/lib/citationIndex";
import { parseAnswerMarkdown } from "@/lib/answerMarkdown";
import type { AskSource } from "@/lib/api";

const CITE_STYLE: React.CSSProperties = {
  cursor: "pointer",
  color: "var(--accent)",
  background: "var(--accent-soft)",
  borderRadius: 3,
  padding: "0 3px",
  fontWeight: 600,
  margin: "0 1px",
};

function CitationText({
  text,
  index,
  onCite,
}: {
  text: string;
  index: CitationIndex;
  onCite: (n: number) => void;
}) {
  return (
    <>
      {splitByCitations(text, index).map((part, partIndex) =>
        part.n === null ? (
          <React.Fragment key={partIndex}>{part.text}</React.Fragment>
        ) : (
          <span
            key={partIndex}
            role="button"
            tabIndex={0}
            onClick={() => onCite(part.n as number)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") onCite(part.n as number);
            }}
            style={CITE_STYLE}
          >
            {part.text}
          </span>
        ),
      )}
    </>
  );
}

function InlineText({
  text,
  index,
  onCite,
}: {
  text: string;
  index: CitationIndex;
  onCite: (n: number) => void;
}) {
  const pieces = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
  return (
    <>
      {pieces.map((piece, pieceIndex) => {
        if (/^\*\*[^*\n]+\*\*$/.test(piece)) {
          return (
            <strong key={pieceIndex} style={{ fontWeight: 700, color: "var(--heading)" }}>
              <CitationText text={piece.slice(2, -2)} index={index} onCite={onCite} />
            </strong>
          );
        }
        if (/^`[^`\n]+`$/.test(piece)) {
          return (
            <code
              key={pieceIndex}
              style={{ fontFamily: "var(--font-mono)", fontSize: ".92em", color: "var(--heading)" }}
            >
              {piece.slice(1, -1)}
            </code>
          );
        }
        return <CitationText key={pieceIndex} text={piece} index={index} onCite={onCite} />;
      })}
    </>
  );
}

export function AnswerMarkdown({
  text,
  sources,
  onCite,
}: {
  text: string;
  sources?: AskSource[];
  onCite: (n: number) => void;
}) {
  const citationIndex = buildCitationIndex(sources);
  const blocks = parseAnswerMarkdown(text);
  const inline = (value: string) => (
    <InlineText text={value} index={citationIndex} onCite={onCite} />
  );
  const headingStyle: React.CSSProperties = {
    color: "var(--heading)",
    fontWeight: 700,
    lineHeight: 1.35,
    margin: "1.15em 0 .45em",
  };

  return (
    <div style={{ fontSize: 12.5, lineHeight: 1.75, color: "var(--fg)" }}>
      {blocks.map((block, blockIndex) => {
        if (block.type === "heading") {
          const style = {
            ...headingStyle,
            fontSize: block.level <= 2 ? 15 : block.level === 3 ? 13.5 : 12.5,
          };
          if (block.level <= 2) return <h2 key={blockIndex} style={style}>{inline(block.text)}</h2>;
          if (block.level === 3) return <h3 key={blockIndex} style={style}>{inline(block.text)}</h3>;
          return <h4 key={blockIndex} style={style}>{inline(block.text)}</h4>;
        }
        if (block.type === "paragraph") {
          return <p key={blockIndex} style={{ margin: ".55em 0" }}>{inline(block.text)}</p>;
        }
        if (block.type === "code") {
          return (
            <pre
              key={blockIndex}
              style={{
                margin: ".75em 0",
                padding: "9px 11px",
                overflowX: "auto",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-md)",
                background: "var(--surface-raised)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                lineHeight: 1.55,
                whiteSpace: "pre",
              }}
            >
              <code>{block.text}</code>
            </pre>
          );
        }
        if (block.type === "rule") {
          return <hr key={blockIndex} style={{ border: 0, borderTop: "1px solid var(--border)", margin: "1em 0" }} />;
        }
        const List = block.type === "ordered-list" ? "ol" : "ul";
        return (
          <List key={blockIndex} style={{ margin: ".55em 0", paddingLeft: "1.55em" }}>
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex} style={{ margin: ".28em 0" }}>{inline(item)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}

