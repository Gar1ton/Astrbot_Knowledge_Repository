# Knowledge Repository · Design System

设计系统：**AstrBot 知识库控制台**（Knowledge Repository）的前端品牌、控件与界面重构。
本系统服务于一个把文档库 / Zotero 文献 / 检索 / 知识图谱 / 问答整合在一起的本地 RAG 控制台。

> 本轮为一次**前端优先的重构**：界面从「左栏导航 + 多路由页面」改为
> **三段式集成面板**，美术风格转向 [Heptabase](https://heptabase.com) 演绎（白卡片、
> 极淡灰画布、保守圆角、柔和卡片质感、单一可换肤强调色）。

---

## 来源 / Sources

- **代码库**（只读，本地挂载）：`Astrbot_Knowledge_Repository/`
  - 重构前前端：`web/frontend/`（Next.js App Router + fumadocs-ui + next-themes；`components/ui`、`components/rail`、`components/fx`、`components/flow`、`lib/api.ts`、`lib/i18n.ts`、`styles/tokens.css`）。
  - 设计规格：`deliverables/design-spec.md`（原暖色 Fumadocs 演绎 + `/api/*` 端口契约）。
  - 后端：`core/`（aiohttp，所有业务经 `/api/*` 委派 `core/api`）。
- **手绘草图**（本轮重构依据）：`uploads/Fig1_Notes_Sidebar.png`、`Fig2_DocumentFileDisplay_MainPage.png`、`Fig3_OverallPanelDefault_MainPage.png`、`Fig4_OverallPanel_DocumentViewPage.png`。
- 字体：按要求改用 **Inter**（替换原 Geist）；等宽用 **JetBrains Mono**（替换原 Geist Mono，最接近的开源替身 — 见下「字体替换 FLAG」）。

---

## 产品与信息架构

控制台是一个 **app**（数据表 + 行内编辑 + 对话），不是文档站。重构后的界面：

**顶栏**：品牌标识（sparkle 方块）+ 右上三个**带框**标签按钮（弹出全屏面板）：
- **Setting** — 外观 / 同步·备份 / 后端配置 / 终端日志（原 Setting + Sync + Terminal 整合）。
- **AstrBot** — Embedding / 向量库 / LightRAG Core / Research Agent 等 AstrBot 相关配置。
- **WorkFlow** — 数据流拓扑（封装原 Flow 逻辑，节点按新美术重绘）。

**三段式常驻面板**（间距均衡的卡片，无固定比例 — 草图比例仅参考）：
1. **File**（左）— 树状集合管理，三个分区：`Zotero Sync`（可展开）/ `Local Collection` / `LightRAG Collection`。
   - 行内**无框**图标按钮（hover 出现功能名 tooltip），与右上**带框**按钮形成层级区分。
   - 树激活行：浅色界面**暗色高亮**、深色界面**亮色高亮**；激活分支上有一条**主题色脉冲**（从左到右掠过连接线）。
   - 选中 **LightRAG Collection** → 全屏切换到**高级模式配色**（violet 映射）。
   - 正在构建图谱时，**进度条渲染在 LightRAG Collection 行内**；构建与 Sync **隔离**（成本可控）。
2. **Documents**（中）— 两态：
   - **列表视图**：Zotero 风格文献条目（标题 / 作者 / 期刊年份 / 类型 / 标签）。
   - **阅读视图**：点击某篇 → 面包屑返回 + `md / PDF` 切换 + 摘要 + 分块原文。
3. **Chat**（右，Research Agent）— 引用 `[n]` 角标点击 → 中间面板打开该文档并**滚动到 chunk 高亮**；
   - 问答范围 = 选中单篇 PDF（以该文为背景）或选中 collection（以集合为背景）。
   - 「Add to Linked Notes」存为该文献的关联笔记；「锁定回答」使回答**持续保留**，清空对话也不消失。

**Note 面板**（Fig1 / Fig4）— 打开某文档时**替换左侧 File 面板**：Zotero 风格的元数据表 + Tags + 彩色 Annotations（只读，来自 Zotero 同步）+ 本地 Notes（可写）+ Abstract。关闭（×）返回 File。

> 新设计用到、但后端尚不存在的能力（Note 读写、原件取流、引用定位、锁定持久化、构建隔离等）
> 全部记录在 **`web/reports/backend-changes-report.md`**。

---

## CONTENT FUNDAMENTALS · 内容与文案

- **语言**：中文为主，保留中英双语架构（`lib/i18n.ts` 的 `zh` / `en` 两套表）。
- **人称 / 语气**：对用户用克制的祈使与陈述（「向知识库提问…」「选择文档查看详情」），不卖萌、不用「您」之外的情绪化措辞；操作确认直白（「确认删除」「立即同步」）。
- **术语保留英文**：`collection` / `chunk` / `RRF` / `embedding` / `LightRAG` / `Milvus` / `Top-K` 等技术术语在中文文案中**保留英文**，不强行翻译。
- **casing**：英文 UI 词组用 Title/词首大写（File、Documents、Chat、Setting、WorkFlow、Add to Linked Notes）；eyebrow 小标签用全大写 + letter-spacing（`ANNOTATIONS`、`TAGS`、`ABSTRACT`）。
- **数字与状态**：用精确值而非модель化措辞（`3.2 GB / 10 GB`、`RRF 0.0331`、`142e·318r`、`48 chunks`）；预留功能统一「即将上线 vX.Y.Z」，不报红。
- **Emoji**：不使用（品牌不含 emoji）；图标一律用线性 SVG。
- **Vibe**：克制、工程感、信息密集但留白充分；像一个给研究者用的「知识工作台」，不是消费级 App。

---

## VISUAL FOUNDATIONS · 视觉基础

- **色彩**：白卡片（`--surface #ffffff`）浮在极淡暖灰画布（`--bg #f6f6f4`）上；文字深炭灰（`--heading #1b1c1f` / `--fg #26272b`）。强调色**单一、HSL 驱动**（默认蓝 `hsl(225 72% 56%)`），由 Settings 滑杆一处调节、全站 `color-mix` 级联换肤。次级语义色 ok/warn/danger/info 克制使用。**LightRAG 高级模式**整体映射到 violet（`[data-mode="lightrag"]`）。
- **强调色用法**：主按钮填充、激活/选中、链接、引用角标、featured 卡片描边。大面积留白，不滥用强调色。
- **字体**：UI = Inter（400/450/500/600/700）；等宽 = JetBrains Mono（ID / chunk / RRF / 配置值）。标题 −0.02em 字距，正文 13px（控制台密度）。
- **背景**：纯净浅灰，无渐变、无大面积图案、无插画、无颗粒（与旧暖色「半调太阳/点场」演绎告别）。质感来自**卡片分层**而非装饰。
- **圆角**：保守（曲度降低）— 卡片 8–12px，控件/输入 6px，胶囊仅用于 tag / badge / 进度条 / toggle。
- **阴影系统**：卡片质感 = 1px 发丝色环 + 柔和投影三层（`--shadow-card`）；悬浮面板 `--shadow-raised`；弹窗 `--shadow-pop`。深色模式用更深的黑色阴影。
- **边框**：发丝边 `--border #e7e7e3`，强调边 `--border-strong`；面板之间用 gap 留白分隔而非粗线。
- **hover**：表面变浅（`--surface-hover` / `--bg-inset`）、图标变深；**press**：`scale(0.975)` 轻微缩放。
- **动画**：克制。仅 `transform`/`opacity`：进场 `fadeUp`（只动 transform，基线 opacity:1，避免内容消失）、弹窗 `modalIn`、树枝主题色 `branchPulse`、引用 `citeFlash` 高亮呼吸、`spin` loading。遵守 `prefers-reduced-motion`。
- **透明 / 模糊**：极少。弹窗遮罩用半透明黑，不依赖 backdrop-blur（避免渲染开销与截图失真）。
- **选中态（反色高亮）**：树激活行用 `--select-bg`（浅色=暗、深色=亮），与强调色软背景区分层级。
- **卡片长相**：白底 + 1px 发丝边 + 柔和分层阴影 + 8–12px 圆角；featured 卡片加 `--accent-border` 描边 + 轻微 accent 辉光。

---

## ICONOGRAPHY · 图标

- **系统**：Lucide 风格的线性图标（`stroke-width` 1.7–1.8，round cap / join，24×24 viewBox，`fill:none`，`currentColor` 描边）。源代码库 `components/rail/Rail.tsx`、`components/flow/Icons.tsx` 即手写内联此风格。
- **实现**：本系统把这套图标收敛为 `web/icons.jsx` 的单组件 `<Icon name size strokeWidth />`（30+ 字形：sparkle / doc / file / folder / search / chat / note / graph / settings / flow / sync / upload / download / pin / link / quote / db / layers / terminal …）。**不用图标字体、不用 emoji、不用 unicode 当图标**。
- **品牌标识**：sparkle 星芒（`assets/mark-sparkle.svg`）置于强调色圆角方块中（`assets/logo-tile.svg`）。无独立 wordmark，文字标识用 Inter 700「Knowledge Repository」。
- **层级约定**：右上**带框**按钮 = 顶层弹出面板入口；面板内**无框**图标按钮（hover tooltip 出功能名）= 面板内操作，借此区分功能层级。
- 取色：图标随强调色 / 语义色 / 中性灰变化；annotations 用 Zotero 五色（purple/yellow/green/red/blue）。

---

## 字体替换 FLAG ⚠

- 原前端使用 **Geist / Geist Mono**（`next/font`）。按本次要求改为 **Inter**（UI）。等宽改用 **JetBrains Mono** 作为 Geist Mono 的最接近开源替身。
- 当前通过 Google Fonts `@import` 加载（在线即用）。若需自托管 woff2 或换回 Geist，请提供字体文件，我会写入 `@font-face` 并替换 `--font-sans` / `--font-mono`。

---

## INDEX · 目录与清单

**Token（全局，consumers 仅 link `styles.css`）**
- `styles.css` — 入口，仅 `@import`。
- `tokens/fonts.css` — Inter + JetBrains Mono（`@import` Google Fonts）。
- `tokens/colors.css` — 表面 / 文字 / 边框 / HSL 强调 / 反色选中 / 语义 / annotations / 浅·深主题 / LightRAG 模式 / 6 个调色板。
- `tokens/typography.css` — 字族、字号阶（10→26）、字重、行高、字距、语义别名。
- `tokens/spacing.css` — 4px 间距阶、保守圆角阶、卡片三层阴影、布局尺寸。
- `tokens/effects.css` — 关键帧与工具类。

**Components（`window.<Namespace>` 暴露；card 在各目录）**
- `components/buttons/` — `Button`（primary/outline/ghost/danger）、`IconButton`。
- `components/forms/` — `Input`、`Tag`、`Toggle`、`Select`。
- `components/display/` — `Card`、`Badge`、`StatusChip`、`QuotaBar`。

**Guidelines（基础规范卡片，Design System tab）**
- `guidelines/colors-*.card.html`（surfaces / text / accent / semantic / palettes / dark / annotations）
- `guidelines/type-*.card.html`（inter / mono / scale）
- `guidelines/spacing-*.card.html`（scale / radii / shadows）

**重构产物 · web/（本轮主交付：可参考的控件 + 静态 HTML）**
- `web/index.html` — **可交互高保真原型**（三段式面板 + Note + 三弹窗 + 引用跳转 + LightRAG 模式）。`<!-- @dsCard group="Console" -->`。
- `web/tokens.css` — 重构主题（自带 reset + 关键帧；与根 tokens 同值）。
- `web/icons.jsx` · `web/ui.jsx` · `web/mock.jsx` — 图标 / 共享控件 / 演示数据。
- `web/FilePanel.jsx` · `web/DocumentsPanel.jsx` · `web/NotePanel.jsx` · `web/ChatPanel.jsx` — 四个核心面板。
- `web/SettingModal.jsx` · `web/AstrBotModal.jsx` · `web/WorkflowModal.jsx` — 三个全屏弹出面板。
- **`web/reports/backend-changes-report.md`** — 后端改动与端口报告（新端口 / 字段调整 / 迁移清单 / 前端用到但暂无的后端）。

**Assets**
- `assets/mark-sparkle.svg` · `assets/logo-tile.svg`。

**其他**
- `SKILL.md` — Agent Skill 入口（下载到 Claude Code 可直接用）。

---

## 如何消费

1. Consumers 链接根 `styles.css` 一个文件即可获得全部 token + 字体。
2. 控件经编译进 `_ds_bundle.js`，用 `const { Button, Card, … } = window.<Namespace>` 取用（Namespace 见 `check_design_system`）。
3. 要复刻完整界面，直接参考 `web/index.html` 与其面板 JSX；它们用普通 React + 内联样式，所有视觉值取自 CSS 变量。
