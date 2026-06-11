---
name: knowledge-repository-design
description: Use this skill to generate well-branded interfaces and assets for the AstrBot Knowledge Repository console (知识库控制台), either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping — Heptabase-style light theme, single recolorable accent, three-segment panel architecture.
user-invocable: true
---

Read the `readme.md` file within this skill, and explore the other available files.

Key context: this is a local RAG console that integrates a document/Zotero library, retrieval, a LightRAG knowledge graph, and a Research Agent chat. The current visual direction is a **Heptabase演绎**: white cards on a faint warm-grey canvas, conservative radii, soft layered card shadows, a single HSL-driven accent (default blue) recolorable from one place, and a violet "LightRAG advanced mode". UI font is Inter, mono is JetBrains Mono.

What to read:
- `readme.md` — full design guide: information architecture (three-segment File / Documents / Chat panels + Note panel + Setting/AstrBot/WorkFlow pop-out panels), content fundamentals, visual foundations, iconography.
- `styles.css` + `tokens/*` — global CSS variables (colors, type, spacing, radii, shadows). Link `styles.css` to inherit everything.
- `components/*` — reusable React primitives (Button, IconButton, Input, Tag, Toggle, Select, Card, Badge, StatusChip, QuotaBar).
- `web/` — the canonical reference: a high-fidelity interactive prototype (`index.html`) plus its panel JSX and shared controls. Copy these patterns to recreate the console.
- `web/reports/backend-changes-report.md` — the ports/backend work any new frontend feature depends on.

If creating visual artifacts (slides, mocks, throwaway prototypes), copy assets out and create static HTML files for the user to view. If working on production code, copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without other guidance, ask them what they want to build or design, ask some focused questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.
