# 知识库控制台 · 重构落地实施文档（Handoff）

> 面向**本地开发 Agent / 工程师**。本文件指导如何把已确认的视觉设计（暖色 Fumadocs 演绎）落地为生产前端，并**完整对接现有 `/api/*` 后端端口**。
>
> 设计稿来源：本项目 `控制台 · Fumadocs 演绎.html`（React + 内联组件，仅作视觉参考）。
> 设计 token / 组件源码：`mockups/shared.jsx`、`mockups/warm.jsx`、`mockups/AskAstrBot.jsx`、`mockups/WorkbenchWarm.jsx`、`mockups/SettingsWarm.jsx`。
>
> **本文件是规格，不是最终代码。** 落地时按下方技术栈与端口契约实现。

---

## 0. 阅读顺序

1. §1 决策摘要 —— 先读，确认技术栈与架构边界。
2. **§6 端口契约（API Reference）** —— 最关键，所有数据交互的唯一事实来源。
3. §3 设计 token → §4 信息架构 → §5 各界面规格 —— 按界面实现。
4. §7 Ask Agent（新增端口）→ §8 视效 → §9 落地步骤 → §10 验收。

---

## 1. 决策摘要

| 项 | 决策 | 理由 / 备注 |
|---|---|---|
| 前端技术栈 | **Next.js (App Router) + `fumadocs-ui`** | 用户明确要求引入 Fumadocs 构建，放弃原「零构建单页」约束。 |
| 后端 | **保持不变**：`aiohttp`，所有业务经 `/api/*` 委派给 `core/api` | 本次只重构前端，后端端口契约**不得破坏**。 |
| 部署形态 | Next 用 **静态导出**（`output: 'export'`），产物经 `tools/sync_frontend.py` 同步到 `pages/`，由 `aiohttp` 单进程托管 | 保留「单进程、一键启动」的运维体验；前端构建只发生在开发期。 |
| 设计语言 | 暖色奶油 + 橙色强调 + 半调网点（Fumadocs 视觉演绎） | 见 §3，全部以 CSS 自定义属性落地。 |
| 主题 | 浅色 / 深色双主题 + 色系切换 | 切换 UI 在**设置页**，见 §5.3。 |
| i18n | 中英双语可切换 | 见 §3.5。 |
| 新增能力 | **Ask Agent**（基于知识库的对话 + 引用来源） | 后端**尚无**对应端口，需新建，见 §7。 |

### 1.1 Fumadocs 使用边界（重要）

`fumadocs-ui` 本质是**文档站**框架（MDX + 阅读型布局）。本控制台是**应用**（数据表、行内编辑、对话）。因此：

- **采用**：Fumadocs 的设计 token 体系、主题切换机制（`next-themes`）、排版与代码块样式、侧栏 `Tree`/导航原语、`RootProvider`。检索/图谱等阅读型界面可直接用其布局原语。
- **自建**：文档数据表 + 行内编辑、检查器、批量操作、Ask Agent 对话与来源面板 —— 这些是 app 级交互，用自定义 React 组件实现，但**复用同一套 CSS token**（§3），保证视觉统一。
- 不要把业务数据塞进 MDX；MDX 仅用于可能的「帮助/about」静态页。

---

## 2. 仓库结构（建议）

```
web/frontend/            # Next.js 源码（开发期）
  app/
    layout.tsx           # RootProvider + 主题 + i18n
    (console)/
      ask/page.tsx       # Ask Agent
      documents/page.tsx # 文档工作台（默认页）
      search/page.tsx    # 知识库检索
      graph/page.tsx     # 知识图谱
      sync/page.tsx      # 同步 / 备份
      quota/page.tsx     # 配额
      settings/page.tsx  # 设置
  components/
    rail/                # 左栏导航（§4）
    docs/                # 数据表 + 检查器 + 批量条
    ask/                 # 对话 + 来源面板
    fx/                  # 视效层（§8）
    ui/                  # Btn / Tag / Segmented 等原子
  lib/
    api.ts               # 端口封装（§6 唯一出口）
    theme.ts palette.ts i18n.ts
  styles/tokens.css      # §3 全部 CSS 变量
next.config.mjs          # output:'export'
tools/sync_frontend.py   # 构建产物 → pages/
pages/                   # aiohttp 托管的静态产物（构建生成，勿手改）
```

所有网络访问**只能**经 `lib/api.ts`。组件内禁止裸 `fetch`。

### 2.1 Fumadocs Frontend 环境配置（照此执行）

> 用 `GET /api/config/effective` 的字段驱动前端配置，**不要硬编码**。下面命令默认在仓库根执行。

```bash
# ① 脚手架（在 web/frontend/）
npx create-next-app@latest web/frontend --ts --app --no-tailwind --eslint --src-dir=false --import-alias "@/*"
cd web/frontend

# ② 依赖
npm i fumadocs-ui fumadocs-core next-themes
#（如需 MDX 帮助页再装：npm i fumadocs-mdx）
```

**`next.config.mjs`** —— 关键：开发用 rewrite 代理到 aiohttp（端口取自 `web_console.port`）；生产用静态导出，由 aiohttp 同源托管（此时 `/api` 天然同源，无需代理）：

```js
const isDev = process.env.NODE_ENV !== 'production';
const API_PORT = process.env.KR_API_PORT || 26618;       // = config.web_console.port
const API_HOST = process.env.KR_API_HOST || '127.0.0.1';  // dev 代理目标
export default {
  reactStrictMode: true,
  // 生产：静态导出 → tools/sync_frontend.py → pages/ → aiohttp 托管
  output: isDev ? undefined : 'export',
  images: { unoptimized: true },                          // 静态导出必须
  // 仅开发期生效（export 模式无 server，不会跑 rewrites）
  async rewrites() {
    return isDev ? [{ source: '/api/:path*', destination: `http://${API_HOST}:${API_PORT}/api/:path*` }] : [];
  },
};
```

> ⚠ `output:'export'` 与 `rewrites` **不能同时生效**：导出无服务端。所以**开发**(`next dev`)走 rewrite 代理到 `:26618`，**生产**走静态导出 + aiohttp 同源（前端和 `/api` 同源，直接相对路径即可）。

**`app/layout.tsx`** —— 挂 Fumadocs `RootProvider` + `next-themes` + 全站 token：

```tsx
import { RootProvider } from 'fumadocs-ui/provider';
import { ThemeProvider } from 'next-themes';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import '@/styles/tokens.css';
export default function RootLayout({ children }) {
  return (
    <html lang="zh" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <ThemeProvider attribute="data-theme" defaultTheme="light" enableSystem
          themes={['light','dark']} disableTransitionOnChange>
          <RootProvider>{children}</RootProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
```
（`npm i geist` 取 Geist 字体；色系切换另用 `data-palette` 属性，见 §3.5。）

**开发流程**：① 起后端 `python -m <plugin> --serve`（监听 `web_console.host:port`）；② `cd web/frontend && npm run dev`（默认 26619，`/api/*` 经 rewrite 打到后端）。
**生产构建**：`npm run build`（导出到 `web/frontend/out/`）→ `python tools/sync_frontend.py`（`out/` → `pages/`）→ 后端单进程托管，浏览器访问 `web_console.host:port`。

### 2.2 把 `config/effective` 接进 UI 行为（不要写死）

| config 字段 | 驱动的 UI 行为 |
|---|---|
| `web_console.host` / `port` | dev rewrite 目标；生产托管地址。 |
| `source_store.default_collection` | 上传时默认集合；文档表「全部」之外的默认落点。 |
| `r2_sync.warn_threshold`（0.8） | 配额条变 warn/danger 的阈值。 |
| `r2_sync.free_tier_gb` | 配额条总量基准。 |
| `notion_sync.max_upload_mib`（5） | 上传前端体积校验上限提示。 |
| `graph.rrf_k` / `query_top_k` | 检索 / 图谱查询默认参数。 |
| `ask.top_k` / `cite_sources` | Ask Agent 默认 TopK、是否展示来源面板。 |
| 各 `*.enabled` | 对应导航项 / 卡片是否启用或灰显。 |

---

## 3. 设计 Token（`styles/tokens.css`）

权威值见 `mockups/warm.jsx`（`WARM_CREAM` / `WARM_INK`）。落地为 CSS 自定义属性，挂在 `:root` 与 `[data-theme="dark"]`。

### 3.1 浅色（默认 · cream）

```css
:root, [data-theme="light"] {
  --bg:#f7f4ed; --bg-subtle:#f1ecdf; --bg-inset:#e9e3d3;
  --surface:#fffefb; --surface-hover:#f4f0e6;
  --border:#e6dfce; --border-strong:#d6cdb6;
  --fg:#2b291f; --fg-muted:#6d6755; --fg-subtle:#9c9580; --heading:#3a3b21;
  --accent:#df7a18; --accent-fg:#ffffff; --accent-soft:#fbeedb; --accent-border:#f1d3a6;
  --accent-2:#83851f; --accent-2-soft:#eef0d6;
  --ok:#4f8a3d; --ok-soft:#e7f0dd;
  --warn:#c5851a; --warn-soft:#f6ebd2;
  --danger:#c5503b; --danger-soft:#f6e3dd;
  --ring:rgba(223,122,24,.26);
  --shadow:0 1px 2px rgba(60,50,30,.05), 0 6px 22px rgba(60,50,30,.07);
  --shadow-pop:0 12px 36px rgba(60,50,30,.16);
}
```

### 3.2 深色（ink）

```css
[data-theme="dark"] {
  --bg:#0b0b0c; --bg-subtle:#121211; --bg-inset:#1b1b18;
  --surface:#141413; --surface-hover:#1e1e1b;
  --border:#282823; --border-strong:#3a3a31;
  --fg:#ece9e0; --fg-muted:#9b978a; --fg-subtle:#6b6759; --heading:#f2efe6;
  --accent:#e8842a; --accent-fg:#ffffff; --accent-soft:rgba(232,132,42,.15); --accent-border:rgba(232,132,42,.38);
  --accent-2:#c2cb4a; --accent-2-soft:rgba(194,203,74,.14);
  --ok:#6abf5a; --ok-soft:rgba(106,191,90,.15);
  --warn:#e0a23b; --warn-soft:rgba(224,162,59,.15);
  --danger:#e06a55; --danger-soft:rgba(224,106,85,.15);
  --ring:rgba(232,132,42,.4);
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 22px rgba(0,0,0,.45);
  --shadow-pop:0 14px 40px rgba(0,0,0,.6);
}
```

### 3.3 字体

- UI：**Geist**（`next/font` 引入；权重 400/500/600/700）。
- 等宽（代码/分块/ID）：**Geist Mono**。
- 避免 Inter / Roboto / Arial。

### 3.4 形状 / 间距

- 圆角：控件/胶片 `999px`（pill）；卡片 `12–14px`；输入 `10px`。
- 标签（Tag）= pill；表格行高 ~44px；正文 13–14px，标题用 `--heading` 色、`letter-spacing:-.02em`。
- 间距基准 4px 网格。

### 3.5 色系切换 + i18n

- **色系**：在 `styles/` 维护若干「色板覆盖」（一组 `--accent*` 值），通过 `<html data-palette="...">` 切换；默认 = 暖橙。设置页提供 4 个 swatch（默认 / Moirai / 森林 / 石墨），具体值后续由产品方提供（先放占位）。
- **主题**：`next-themes`，`data-theme` 控制，支持「跟随系统」。
- **i18n**：中英文案表（`lib/i18n.ts`），`<html lang>` 同步切换。术语（collection / chunk / RRF / embedding）保留英文。

---

## 4. 信息架构与左栏（`components/rail`）

源码参考 `mockups/warm.jsx` 的 `WarmRail`。左栏自上而下：

1. **品牌区**：Knowledge Repo + sparkle 图标。
2. **全局搜索**（⌘K，pill 输入）—— 触发命令面板（可后置）。
3. **Ask Agent**（置顶，featured 高亮，橙色描边+辉光）→ `/ask`。
4. 分组「知识库」：**文档**（默认页 `/documents`）、**知识库检索** `/search`、**知识图谱** `/graph`。
5. 分组「运维」：**同步 / 备份** `/sync`、**配额** `/quota`（带用量 badge）。
6. **底部固定**：**设置** `/settings`（齿轮）+ 用户区（admin + 连接状态 + 登出）。

导航即应用路由（App Router）。`active` 态用 `--accent` + `--accent-soft`。

---

## 5. 各界面实现规格

> 通则：所有「编辑」动作（改集合、改标签、删除、移动）**一律用行内控件 / 侧栏检查器 / 弹层**，**彻底取代旧版 `prompt()`**。所有列表支持多选 + 批量操作。

### 5.1 文档工作台 `/documents`（默认页，参考 `WorkbenchWarm.jsx`）

三栏布局：

- **集合/标签列**（左，~198px）：集合树（`GET /api/collections`，计数来自文档聚合）+ 标签云。点击即筛选 → 调 `GET /api/documents?collection=&tag=`。「+」新建集合 → `POST /api/collections`。
- **文档表**（中）：列 = 勾选 / 标题(+类型徽标) / 标签(pill) / 大小 / 更新时间。可排序、可多选。
  - 多选后出现**批量操作条**：移动集合（逐条 `PATCH /api/documents/{id}` 改 `collection`）、批量打标签（`PATCH` 改 `tags`）、删除（逐条 `DELETE /api/documents/{id}`）。
  - 顶部「上传文档」→ `POST /api/documents`（multipart）。
- **检查器**（右，~296px）：选中文档的元数据；集合下拉（`PATCH` collection）、标签编辑器（pill 增删，`PATCH` tags）、大小/分块/更新/状态、分块预览、下载/删除。
  - **下载**：当前后端**无**显式下载端口 —— 见 §6.99「待确认」。

### 5.2 知识库检索 `/search`

- 选集合（`GET /api/kb/collections`）+ 查询词 + top-k → `GET /api/kb/search?collection=&q=&k=`。
- 结果 = chunk 列表（`chunk_id` / `ordinal` / `text`）。卡片式呈现，命中词高亮。

### 5.3 设置 `/settings`（参考 `SettingsWarm.jsx`）

独立**页面**（非弹窗）。

- **外观区**（页顶）：主题（浅/深/跟随）、语言（中/英）、**色系**（4 swatch）。
- **后端有效配置**（只读核对，来自 `GET /api/config/effective`）：分区卡片展示 源库 / R2 同步 / Notion 镜像 / Web 控制台 / 知识图谱 / Ask Agent。敏感字段后端已打码（`****`），前端原样显示，不回显明文。

### 5.4 知识图谱 `/graph`

- `GET /api/graph` 取 `{nodes, edges}` 渲染图。
- 「构建/增量更新」→ `POST /api/graph/build`（注意可能返回 `{reserved:true, available_in:"v0.6.0"}`，需处理「预留中」态）。
- 图谱查询 → `GET /api/graph/query?q=&collection=`，返回 `{entities, relations, chunks, context, debug.rrf_scores}`。

### 5.5 同步 / 备份 `/sync` 、配额 `/quota`

- 配额：`GET /api/quota` → 进度条（`ratio`、`used_bytes`/`limit_bytes`、`detail`）。
- 同步/备份/Notion：多为**预留端口**，返回 `{reserved:true, available_in:"vX"}` —— UI 需优雅展示「即将上线 / 版本号」，而非报错。见 §6。

---

## 6. 端口契约（API Reference）★ 唯一事实来源

**通则**
- Base：同源，前缀 `/api`。开发期 Next dev server 用 rewrite/proxy 转发到 `aiohttp`（默认 `0.0.0.0:26618`）。
- 认证：基于会话（登录后置 cookie）。每次进入控制台先 `GET /api/auth` 判断登录态。
- 约定响应：成功多为资源对象或 `{status:"ok"}`；**预留功能**返回 `{reserved:true, available_inः"vX.Y.Z"}` 形态（注意：前端必须识别 `reserved` 并降级展示）。
- 错误：非 2xx 时 body 可能含 `{error|detail}`，前端统一在 `lib/api.ts` 抛出并 toast。

> 下表 method / 参数 / 形状均**从现有前端实现（含 mock 镜像）反推**，与后端 `core/api` 对齐。落地前请以后端实现复核字段名。

### 6.1 认证 Auth

| Method | Path | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `GET` | `/api/auth` | — | `{ logged_in: boolean }` | 启动时判断登录态 |
| `POST` | `/api/login` | JSON `{ username, password }` | `{ status: "ok" }`（失败非2xx） | 登录，置会话 cookie |

> 登出：现有前端未见显式 `/api/logout`；左栏登出按钮的端口**待后端确认**（见 §6.99）。

### 6.2 集合 Collections

| Method | Path | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `GET` | `/api/collections` | — | `[{ name, description?, ... }]` | 集合列表（= AstrBot 知识库） |
| `POST` | `/api/collections` | JSON `{ name, description? }` | 新建的集合对象（重名应返回错误） | 新建集合 |
| `DELETE` | `/api/collections/{name}` | path：`name`（URL-encoded） | `{ status: "ok" }` | 删除集合 |

### 6.3 文档 Documents

| Method | Path | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `GET` | `/api/documents` | query：`collection?`、`tag?` | `[{ doc_id, filename/title, collection, tags[], size?, chunks?, updated?, ext? }]` | 文档列表（支持按集合/标签过滤） |
| `POST` | `/api/documents` | **multipart/form-data**：`file`、`collection`(默认 default)、`tags`(逗号分隔字符串) | 新建文档对象（含 `doc_id`） | 上传/入库（原件直入，PDF 不做 LLM 转换） |
| `PATCH` | `/api/documents/{id}` | JSON `{ collection?, tags?[] }` | 更新后的文档对象 | **改集合 / 改标签**（批量=逐条调用） |
| `DELETE` | `/api/documents/{id}` | path：`id` | `{ status: "ok" }` | 删除文档 |

> 字段名注意：列表项的标题字段在 mock 中为 `title`/`filename` 混用，**以后端实际返回为准**；`tags` 为字符串数组。

### 6.4 知识库检索 KB

| Method | Path | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `GET` | `/api/kb/collections` | — | `[ collectionName, ... ]`（字符串数组） | 可检索的知识库集合名 |
| `GET` | `/api/kb/search` | query：`collection`、`q`、`k?`(默认5) | `[{ chunk_id, ordinal, text }]` | 向量/关键词检索命中分块 |

### 6.5 配额 Quota

| Method | Path | 返回 | 用途 |
|---|---|---|---|
| `GET` | `/api/quota` | `[{ target, used_bytes, limit_bytes, ratio, detail }]`（如 r2 / notion） | 存储与外部服务用量 |

### 6.6 配置 Config

| Method | Path | 返回（结构见下） | 用途 |
|---|---|---|---|
| `GET` | `/api/config/effective` | 见下方完整结构 | 设置页只读核对后端有效配置 |

```jsonc
{
  "source_store":  { "db_filename":"knowledge_repository.db", "default_collection":"default", "ocr_enabled":false },
  "r2_sync":       { "enabled":true, "bucket":"...", "account_id":"ac****nt", "access_key_id":"ak****id",
                     "secret_access_key":"****", "free_tier_gb":10, "warn_threshold":0.8, "backup_interval_sec":86400 },
  "notion_sync":   { "enabled":true, "mcp_server_name":"notion", "database_id":"...", "parent_page_id":"...",
                     "database_title":"Knowledge Repository", "max_upload_mib":5, "link_large_to_r2":true, "rate_limit_rps":3 },
  "web_console":   { "enabled":true, "host":"0.0.0.0", "port":26618, "username":"admin", "password":"****" },
  "graph":         { "enabled":true, "llm_extraction":true, "incremental":true, "reuse_kb_embedding":true,
                     "merge_similarity_threshold":0.9, "rrf_k":60, "query_top_k":5, "entity_types":["Method/Algorithm","Dataset"] }
}
```
> 敏感值后端已打码（`****`）。前端**原样显示**，不得尝试解码或回显明文。

### 6.7 知识图谱 Graph

| Method | Path | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `GET` | `/api/graph` | — | `{ nodes:[{id,name,...}], edges:[{id,source,target,relation,description,weight,source_chunk_ids[],source_previews[]}] }` | 取图谱数据 |
| `GET` | `/api/graph/query` | query：`q`、`collection?` | `{ status, query, collection, chunks[], entities[], relations[], context, debug:{ vector_chunk_ids[], keyword_chunk_ids[], graph_chunk_ids[], rrf_scores:{} } }` | 图谱增强查询（含 RRF 调试分数） |
| `POST` | `/api/graph/build` | —（或集合范围参数） | `{ reserved, result:{status,message} }` **或** `{reserved:true, available_in:"v0.6.0"}` | 构建/增量更新图谱 |

### 6.8 预留端口 Reserved（同步 / 备份 / Notion）

> 这些功能**接口已占位、实现按版本灰度**。统一返回 `{ reserved:boolean, ... }`；当 `reserved:true` 时前端展示「即将上线（available_in 版本）」，不得当作错误。

| Method | Path | 返回 | 计划版本 |
|---|---|---|---|
| `POST` | `/api/notion/init` | `{ reserved:false, result:{status,database_id,created} }` | 已可用 |
| `POST` | `/api/sync/notion/pull` | `{ reserved:false, result:{status,updated_count,skipped_count,warnings[]} }` | 已可用 |
| `GET`  | `/api/sync/status` | `{ reserved:true, available_in:"v0.4.0" }` | v0.4.0 |
| `*`    | `/api/sync/{target}` | `{ reserved:true, available_in:"v0.4.0" }` | v0.4.0 |
| `POST` | `/api/backup` | `{ reserved:true, available_in:"v0.3.0" }` | v0.3.0 |
| `POST` | `/api/restore` | `{ reserved:true, available_in:"v0.3.0" }` | v0.3.0 |
| `*`    | `/api/graph/*`（除 build/query） | `{ reserved:true, available_in:"v0.6.0" }` | v0.6.0 |

### 6.99 待后端确认（设计新增依赖）

| 能力 | 现状 | 需要 |
|---|---|---|
| 文档**下载**（检查器/批量导出按钮） | 现有端口未见 | 新增 `GET /api/documents/{id}/raw`（或确认既有下载路径） |
| **登出** | 未见 `/api/logout` | 确认登出端口或改为前端清会话 |
| **Ask Agent 对话** | **完全没有** | 见 §7，需新建端口 |

> 落地 Agent：以上三项**先与后端负责人对齐**，不要臆造路径。

---

## 7. Ask Agent —— 新增能力与端口（净增量）

设计把 Ask Agent 提为顶级视图：用户问问题 → 后端基于知识库检索（embedding + RRF）→ LLM 生成答案 → **返回答案 + 引用来源**（右侧来源面板展示被引分块）。参考 `mockups/AskAstrBot.jsx`。

**后端尚无此端口，需新建。** 建议契约（供后端实现参考，最终以后端为准）：

```jsonc
// POST /api/ask
// body:
{ "question": "string",
  "collection": "string | null",   // null = 全部集合
  "top_k": 5,
  "conversation_id": "string | null" }

// 200 返回（流式或一次性）:
{ "conversation_id": "string",
  "answer": "string (markdown，含 [1][2] 角标)",
  "sources": [
    { "n":1, "doc_id":"seed-1", "title":"LightRAG 论文",
      "chunk_id":"k1", "ordinal":0, "text":"...片段...", "rrf_score":0.0327 }
  ] }
```

- 复用现有检索栈（`/api/kb/search` 同款 embedding + RRF）；`sources[].rrf_score` 对应 `graph/query` 的 `debug.rrf_scores`。
- 前端：答案 markdown 渲染，`[n]` 角标与来源卡片联动高亮；「在文档中打开」跳 `/documents` 并定位 `doc_id`。
- 流式可选（SSE / fetch stream）；首版可一次性返回。
- **设置页**已为其预留配置区（检索方式 / RRF k / Top K / 引用开关）——这些应进 `/api/config/effective` 的新 `ask` 段，请后端补充。

---

## 8. 视效层（`components/fx`）—— 含性能纪律

视觉「更丰富但低开销」。全部**纯 CSS / GPU 合成**，**禁止 JS 动画循环**、**禁止大面积 `filter:blur` 堆叠**。源码参考设计稿 `<style>` 块与 `warm.jsx` / `proto/*.jsx` 的 `Aurora`/`SunBloom`/`GrainSun`/`DotField`。

### 8.1 静态质感层

| 效果 | 实现 | 约束 |
|---|---|---|
| Aurora 环境光 | 角落静态 `radial-gradient`（`--accent-soft`/`--accent-2-soft`），`opacity~.7` | 单层，无动画 |
| 半调「太阳」SunBloom | 点阵 `radial-gradient` + 径向 mask 衰减 + 内层柔光 radial | 见 8.3 动态 |
| 胶片颗粒 grain | 单张内联 SVG `feTurbulence`，`opacity .04`，深色 `mix-blend:screen` | 单层伪元素 |
| 渐变描边 gborder | `mask-composite` 1px 内描边 | featured 卡片/输入框 |

### 8.2 毛玻璃衔接（frosted seams）★本次强化

目标：**面板交界处**有磨砂玻璃的通透层次，而非生硬实色边。做法 = 半透明面板背景 + `backdrop-filter`，让其下方滚动内容透出虚化。

- 适用：Ask 顶栏、**文档工具区 / 批量条（sticky 玻璃，悬浮于滚动表格之上）**、**检查器头部（sticky 玻璃）**、设置「外观条」（sticky）、来源面板与检查器**与主区相接的竖边**加 1px 渐变高光。
- 配方（统一 util，建议类名 `.fx-glass`）：
  ```css
  .fx-glass{
    background: color-mix(in srgb, var(--bg-subtle) 72%, transparent);
    backdrop-filter: saturate(1.25) blur(10px);
    -webkit-backdrop-filter: saturate(1.25) blur(10px);
    border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
  }
  .fx-glass-edge{ /* 竖向接缝高光 */
    box-shadow: inset 1px 0 0 color-mix(in srgb, var(--accent) 14%, transparent);
  }
  ```
- 性能：`backdrop-filter` 仅用于**细条/头部等小面积**（高度≤56px 的 sticky 区），**不要**整页大面积铺；同一视图同时活动的玻璃层 ≤3。

### 8.3 动态点状效果（dynamic dots）★本次强化

全部用 **transform / opacity** 动画（GPU 合成），不触发 layout：

| 效果 | 实现 | 参数 |
|---|---|---|
| 半调太阳 **缓旋 + 呼吸** | `SunBloom` 点阵层加 `@keyframes`：`rotate(0→360deg)` 90s 线性 + 叠加 `scale(1→1.04)` 8s ease | 单层 transform，极低开销 |
| **漂浮点场 DotField** | 页眉/英雄区放 10–14 个 `--accent` 小圆点，各自 `translate` 缓慢漂移 + `opacity` 闪烁（twinkle），错峰 `animation-delay` | 元素数固定上限，纯 transform/opacity |
| 点场 **视差感** | DotField 两组不同 size/速度叠加，营造深度 | 仅 2 层 |
| sparkle 轻浮动 | `translateY 3px` 4.5s | 单图标 |

`DotField` 参考实现（放入 `components/fx/DotField`）：
```jsx
// 固定 12 点，纯 CSS 动画，绝对定位于容器
const DOTS = Array.from({length:12},(_,i)=>({
  x: (i*37+13)%100, y:(i*53+7)%100, s: 2+(i%3), d:(i%6)*0.7, dur:7+(i%5)*1.6
}));
function DotField(){
  return <div aria-hidden style={{position:'absolute',inset:0,overflow:'hidden',pointerEvents:'none'}}>
    {DOTS.map((p,i)=><span key={i} style={{position:'absolute',left:p.x+'%',top:p.y+'%',
      width:p.s,height:p.s,borderRadius:99,background:'var(--accent)',opacity:.18,
      animation:`dotDrift ${p.dur}s ${p.d}s ease-in-out infinite, dotTwinkle ${p.dur*0.6}s ${p.d}s ease-in-out infinite`}}/>)}
  </div>;
}
/* @keyframes dotDrift{50%{transform:translate(6px,-8px)}}
   @keyframes dotTwinkle{0%,100%{opacity:.10}50%{opacity:.32}}
   @keyframes sunSpin{to{transform:rotate(360deg)}} */
```

### 8.4 进场与交互

| 效果 | 实现 | 约束 |
|---|---|---|
| 进场 fadeUp | **只动 `transform`，不动 `opacity`** | ⚠ 见下「关键修复」 |
| hover 抬升 / 按压 | `transition` transform+shadow | 仅交互元素 |
| 列表行错峰进场 | `animation-delay` 按 index 递增（≤0.04s 步进） | 行数多时封顶 |

> **⚠ 关键修复（务必遵守）**：进场动画**不要**把元素初始 `opacity` 设为 0 再靠动画恢复。在部分渲染环境下动画会停在首帧、`animation-fill-mode:both` 把内容永久钉在 `opacity:0` → 内容（对话气泡、表格行）整片消失。**正确做法**：内容基线 `opacity:1` 始终可见，进场动画**只过渡 `transform`**。

### 8.5 性能与可达性纪律

- 所有动画走 `transform`/`opacity`；避免动画 `width/top/background-position` 等触发 layout/paint 的属性。
- `backdrop-filter` 仅小面积 sticky 条；DotField 点数固定上限（≤14），SunBloom/DotField 每视图各 1 处。
- **必须**遵守 `prefers-reduced-motion: reduce`：关闭 `dotDrift`/`dotTwinkle`/`sunSpin`/`fadeUp`/`float`，保留静态外观。

---

## 9. 落地步骤（建议给本地 Agent 的执行顺序）

1. **脚手架**：`web/frontend/` 起 Next.js(App Router, TS) + `fumadocs-ui` + `next-themes`；`next.config.mjs` 设 `output:'export'`；dev 期配 `/api` rewrite → `http://127.0.0.1:26618`。
2. **token**：落 `styles/tokens.css`（§3），接 `next/font` 的 Geist / Geist Mono。
3. **api 层**：`lib/api.ts` 按 §6 封装全部端口（含 `reserved` 降级、错误 toast）。组件禁止裸 fetch。
4. **外壳**：`RootProvider` + 主题/色系/i18n + 左栏 `rail`（§4）+ 路由骨架。
5. **文档工作台**（§5.1）：三栏 + 数据表 + 检查器 + 批量条；接 `collections`/`documents`。这是核心，优先做实做细。
6. **设置页**（§5.3）：外观区 + `config/effective` 只读卡片。
7. **检索 / 配额**（§5.2 / 5.5）：接 `kb/*`、`quota`。
8. **Ask Agent**（§7）：先与后端定 `/api/ask`；前端做对话 + 来源面板（无端口时接 mock）。
9. **图谱 / 同步**（§5.4 / 5.5）：接 `graph/*`，预留端口做「即将上线」降级。
10. **视效层**（§8）+ `prefers-reduced-motion`。
11. **构建同步**：`tools/sync_frontend.py` 把 `out/` → `pages/`，验证 `aiohttp` 单进程托管可一键启动。

每步完成后对照设计稿核对视觉，并跑 §10 验收。

## 9.1 保留 `?mock` 离线预览

现有 index 有 `?mock` 离线模式（前端自带假数据，无后端可演示）。**请保留等价能力**：`lib/api.ts` 检测 `?mock` 时切到内置 mock（数据可直接移植自 `uploads/index-3797f157.html` 的 `mockCollections`/`mockDocs`/`mockKbChunks`/`mockGraph`）。便于纯前端调试与演示。

---

## 10. 验收清单

- [ ] 所有 §6 端口经 `lib/api.ts` 调通；`reserved` 功能优雅降级，不报红。
- [ ] 文档工作台：多选 → 批量改集合/标签/删除全部走 `PATCH`/`DELETE`，**无任何 `prompt()`**。
- [ ] 上传走 multipart `POST /api/documents`；列表过滤走 query。
- [ ] 设置页主题/语言/色系切换实时生效并持久化；`config/effective` 敏感字段打码原样显示。
- [ ] 进场动画**不致内容消失**（§8 关键修复）；`prefers-reduced-motion` 生效。
- [ ] 浅/深双主题、中/英双语全界面通过。
- [ ] `?mock` 离线预览可用。
- [ ] `output:'export'` 产物经 `sync_frontend.py` 同步后，`aiohttp` 单进程一键启动正常。
- [ ] Ask Agent：后端 `/api/ask` 定稿后，答案 + 来源角标联动、`在文档中打开`跳转正常。

---

## 附：端口总览（速查）

```
# 认证
GET    /api/auth
POST   /api/login                       {username,password}
# 集合
GET    /api/collections
POST   /api/collections                 {name,description?}
DELETE /api/collections/{name}
# 文档
GET    /api/documents?collection=&tag=
POST   /api/documents                   multipart: file,collection,tags
PATCH  /api/documents/{id}              {collection?,tags?}
DELETE /api/documents/{id}
# 知识库检索
GET    /api/kb/collections
GET    /api/kb/search?collection=&q=&k=
# 配额 / 配置
GET    /api/quota
GET    /api/config/effective
# 知识图谱
GET    /api/graph
GET    /api/graph/query?q=&collection=
POST   /api/graph/build                 (可能 reserved v0.6.0)
# 预留：同步 / 备份 / Notion
POST   /api/notion/init
POST   /api/sync/notion/pull
GET    /api/sync/status                 (reserved v0.4.0)
*      /api/sync/{target}               (reserved v0.4.0)
POST   /api/backup                      (reserved v0.3.0)
POST   /api/restore                     (reserved v0.3.0)
# 待后端确认（设计新增依赖）
GET    /api/documents/{id}/raw          ← 下载，待确认
?      /api/logout                      ← 登出，待确认
POST   /api/ask                         ← Ask Agent，需新建（§7）
```
