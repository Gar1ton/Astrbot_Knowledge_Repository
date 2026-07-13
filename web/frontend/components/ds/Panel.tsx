import React from "react";

interface Crumb {
  label: string;
  onClick?: () => void;
  separator?: string; // separator shown BEFORE this crumb; defaults to "/"
}

interface PanelProps {
  title?: string;
  crumbs?: (string | Crumb)[];
  right?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
  bodyStyle?: React.CSSProperties;
  flush?: boolean;
}

export function Panel({ title, crumbs, right, children, style, bodyStyle, flush = false }: PanelProps) {
  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-card)",
        overflow: "hidden",
        ...style,
      }}
    >
      <header
        style={{
          height: 38,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 8px 0 13px",
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12.5,
          }}
        >
          {title && (
            <span style={{ fontWeight: 650, color: "var(--heading)", letterSpacing: "-.01em", flexShrink: 0 }}>
              {title}
            </span>
          )}
          {crumbs?.map((c, i) => {
            const crumb = typeof c === "string" ? { label: c } : c;
            const showSeparator = Boolean(title) || i > 0;
            return (
              <React.Fragment key={i}>
                {showSeparator && (
                  <span style={{ color: "var(--fg-subtle)", flexShrink: 0 }}>
                    {crumb.separator !== undefined ? crumb.separator : "/"}
                  </span>
                )}
                <span
                  style={{
                    color: i === crumbs.length - 1 ? "var(--fg)" : "var(--fg-muted)",
                    fontWeight: i === crumbs.length - 1 ? 600 : 400,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    maxWidth: i === crumbs.length - 1 ? 260 : 150,
                    cursor: crumb.onClick ? "pointer" : "default",
                  }}
                  onClick={crumb.onClick}
                >
                  {crumb.label}
                </span>
              </React.Fragment>
            );
          })}
        </div>
        {right && (
          <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
            {right}
          </div>
        )}
      </header>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          padding: flush ? 0 : 14,
          ...bodyStyle,
        }}
      >
        {children}
      </div>
    </section>
  );
}
