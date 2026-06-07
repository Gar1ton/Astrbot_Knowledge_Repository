# Flow Page 重构 — 本地 Agent 复现 Prompt（v2 · 已通过方向）

> 目标：把 `frontend/app/(console)/flow/page.tsx`「数据流 / 配置向导」页，
> 从当前**纵向堆叠、视觉凌乱**的形态，重构为 **Langflow 风格的固定分支拓扑图**。
> **参数功能 100% 不变**（切换后端 = 写配置、安装依赖、重新检测、后果横幅）。
> 只改「呈现层」与「信息层级」，不动数据契约与网络出口（`lib/api.ts`）。
>
> 设计稿（交互 demo，逐项已确认）：`flow/Flow Page Redesign.html`
> 拆分文件：`flow.data.js`（数据/拓扑/文案）、`flow.icons.jsx`（占位图标）、
> `flow.node.jsx`（节点）、`flow.diagram.jsx`（网格布局 + 连线 + 交互）。

---

## 0. 不可触碰的契约（务必保留）

来自 `lib/api.ts` / 现有 `page.tsx`，逐字保留逻辑、只换 UI：

- 数据源 `getCapabilities()` → `CapabilitiesData { pipeline: PipelineStage[]; dependencies: DependencyStatus[]; diagnostics }`。前端**只渲染**，状态由后端 `core/capabilities.py` 决定，不在前端反推。
- `PipelineStage`：`id / current / candidates / status('ready'|'degraded'|'off'|'info') / switchable / consequence('none'|'restart'|'rebuild') / required_deps / configured / detail`。
- 切换参数（`SWITCH_MAP` 保持）：
  ```ts
  const SWITCH_MAP = {
    embedding:    { section: "embedding",  key: "provider" },
    vector_store: { section: "vector_db",  key: "backend" },
    ask:          { section: "ask",        key: "conversation_enhancement_mode" },
    graph:        { section: "graph",      key: "enabled", toBool: true },
  };
  ```
  点候选 → `updateConfigValue(section,key,value)`；`rebuild_required`→rebuild 横幅，`restart_required`→restart 横幅，否则 `toast("已保存")`；保存后 `getCapabilities()` 重拉。
- 安装依赖 `installDependency(dep.key)` → `recheckDependencies()` 重拉 + 横幅「安装完成，需重启」。
- 重新检测 `recheckDependencies()`。
- i18n key（`flow_*`）保持；新增纯展示文案走 i18n。
- `savingId / installingKey / banner / justActivatedId` 状态机原样保留。
- **删除** `page.tsx` 末尾独立的 `DependencyPanel` / `DepCard`（功能已内联进节点，见 §5）。

---

## 1. 总体形态：横向分支拓扑图 + 可平移/缩放画布

- **横向流向**（左→右）：主干 `ingest→embedding→vector_store→…→ask` 横向推进；并联的 retrieval/graph 上下叠放；sync 为 ingest 的纵向旁路。
- **画布可平移/缩放**（恢复拖拽）：`viewport(overflow:hidden, cursor:grab)` › `world(transform:translate+scale)` › `diagram-grid`。**节点位置固定**（不可单独拖节点），但整图可拖动平移、滚轮/按钮缩放、一键 fit。
- 节点之间用 **贝塞尔连线 + 端口 handle** 连接，遵循 Langflow「组件节点」规范。
- 页头（sticky 毛玻璃）：`flow_title` + `flow_subtitle`、状态图例 +「检索编排 ∥ LightRAG 并联」说明 +「滚轮缩放·拖拽空白处平移」提示、`flow_recheck`、后果横幅。
- 画布底：点阵网格（`radial-gradient` 圆点）随 `world` 的平移/缩放联动（`background-size:26*s`、`background-position:x,y`）。

### 1.1 节点拓扑（**并联 + 旁路**，横向）

```
   ⑦ 同步/备份 ★
       ▲ (备份旁路·虚线)
   ① 上传/分块 ─► ② 向量化 ─► ③ 向量库 ─┬─(默认)─►  ④ 检索编排 ─┐
                                          └─(高精度)► ⑤ LightRAG ─┴─► ⑥ 问答 Ask ★
```

- **③ 向量库 分叉**到 **④ 检索编排**（上）与 **⑤ LightRAG 图谱**（下），二者**并联**（标注「默认 / 高精度」），再**汇入 ⑥ 问答**。
- **⑦ 同步/备份** 是 **① 上传/分块** 引出的**纵向旁路备份分支**（虚线、更弱），与检索互不影响。
- 横向三行网格放置（col 左→右推进；row 1 上 / 2 主干 / 3 下）：
  | 节点 | 列(左→右) | 行(1上/2中/3下) |
  |---|---|---|
  | sync | 1 | 1 |
  | ingest | 1 | 2 |
  | embedding | 2 | 2 |
  | vector_store | 3 | 2 |
  | retrieval | 4 | 1 |
  | graph | 4 | 3 |
  | ask | 5 | 2 |
  ```css
  .diagram-grid{
    position:relative; display:grid;
    grid-template-columns:272px 248px 248px 268px 300px;
    column-gap:72px; row-gap:38px; align-items:center; padding:16px;
  }
  ```
- 拓扑边集中声明（便于扩展）：
  ```js
  const EDGES = [
    { from:"ingest", to:"embedding" },
    { from:"embedding", to:"vector_store" },
    { from:"vector_store", to:"retrieval", label:"默认" },
    { from:"vector_store", to:"graph",     label:"高精度" },
    { from:"retrieval", to:"ask" },
    { from:"graph", to:"ask" },
    { from:"ingest", to:"sync", label:"备份旁路", dashed:true, vertical:true },
  ];
  ```

### 1.2 连线（测量 + 流动动效，**务必保留动效**）

- 在 `diagram-grid`（`position:relative`）内叠一层 `<svg class="conn-svg" pos:absolute inset:0 z:0 pointer-events:none>`。
- 用 ref 测每个节点 `offsetLeft/Top/Width/Height`，按边方向算锚点：
  - **横向主干边**：`out=(right_from, midY_from)`，`in=(left_to, midY_to)`，路径 `M x1 y1 C x1+dx y1, x2-dx y2, x2 y2`，`dx=clamp((x2-x1)*0.5,30,90)`。split/merge 因 from/to 有 Y 差，曲线自然形成分叉/汇聚。
  - **纵向旁路边（`vertical`，sync 在 ingest 上方）**：`out=(cx_from, top_from)`，`in=(cx_to, bottom_to)`，路径用纵向控制点向上弯。
- **连线状态色逻辑（诚实反映数据流）**：
  ```
  if (from==off || to==off) st="off";        // 整条置灰 + 虚线
  else if (from==ready && to==ready) st="ready";  // 唯一「流动」态
  else st="degraded";                         // 琥珀，不流动
  ```
  `dashed`：显式旁路 或 `st==off`。`live`（流动动效）：`st==ready && !dashed`。
- 颜色：`live/ready` 用 `--st-ready`，`degraded` 用 `--st-warn`，`off`/旁路 用 `--conn`（中性）。线宽 2px、round。
- 流动动效：在路径上叠一条 `stroke-dasharray:5 12` 的覆盖线，`animation:connFlow 1.05s linear infinite`（`@keyframes connFlow{to{stroke-dashoffset:-17}}`）。`prefers-reduced-motion` 下关停。
- 重算时机：`useLayoutEffect`(依赖 caps) + `ResizeObserver(grid)` + 字体加载后 `setTimeout(measure,220)`。用 `JSON` 比对避免无效 setState。

### 1.3b 画布平移 / 缩放（恢复拖拽）

- `view={s,x,y}`；`world` 应用 `transform:translate(x,y) scale(s)`，`transform-origin:0 0`。
- 平移：`pointerdown` 命中空白（`!e.target.closest('.node')`）才起拖；`setPointerCapture`。**坑**：`onPointerMove` 里**先把 `pan.current` 取成局部变量**再算，不要在 `setView(v=>…)` 内读 `pan.current`（pointerup 后会变 null → 崩溃）。
- 缩放：`onWheel`（`preventDefault`）按光标缩放：`ns=clamp(s*(deltaY<0?1.08:0.926),0.4,1.5)`；`x=px-(px-x)*ns/s`，y 同理。右下角 `zoom-ctl`（+/数值/−/fit）。
- `fit()`：按 viewport 与 grid 实测尺寸把整图居中缩放到适配（`clamp≤1`），首次 `geo` 测量完成后自动 fit 一次。

### 1.3 端口 handle

- 由 EDGES 推导：每条边在 from 出锚、to 入锚各放一个 `11px` 圆点（按 `节点:边侧` 去重）。
- 默认空心（描边 `--conn`）；当所在节点 `status!=off` → 描边/填充转状态色 + 轻微外发光。
- 旁路边用 ingest 右侧 / sync 左侧锚点。

---

## 2. 配色：中性 / token 驱动（**本期不做品牌色**）

整体色盘后续重做，本期**只保留状态语义色**，其余一律中性灰，全部走 token：

```css
--node:#fff; --node-bd:#e7e7e4; --node-bd-st:#dadad6;
--inset:#f4f4f2; --inset-2:#eeeeeb; --canvas:#f3f3f1; --conn:#d2d2cc;
--ink:#1b1b19; --muted:#6d6d68; --faint:#a2a29b;
/* 唯一保留色相——状态语义 */
--st-ready:#4f9d5b; --st-warn:#cc8a2e; --st-off:#b4b4ad; --st-info:#6c79c4;
```
- 节点本体不引入新色相；选中态用 `--ink` 描边 ring。
- 状态色相只用于：左 stripe、状态徽标、连线、handle。

---

## 3. 节点 anatomy（统一一套美术 = demo 最终方案）

卡片自上而下：`左 stripe(状态色)` → `头部(图标位 + 标题 + role 小药丸 + STAGE 0N + 状态徽标)` → `描述` → `参数区`。

- **头部**：`31×31` 圆角图标位（占位线性图标即可，按状态色微染）；标题 `14.5/700`（`white-space:nowrap`）；`role` 小药丸（只读 / 可切换 / 可选 / 界面…，`flex-wrap` 允许换行）；下一行 `STAGE 0N` mono 小字幕；右端**状态徽标**（点+文案，`degraded` 点带 1.7s 脉冲）。
- **stripe**：左缘 4px（dest 节点 5px），状态色渐变。
- **参数区（parameter 功能载体）**：
  - `switchable`：`<Field label>` + **分段控件**（候选=`stage.candidates`，当前=`stage.current`，点非当前项触发切换；on/off 同样用分段「开启/关闭」）。选中态=状态色描边高亮（`box-shadow:inset 0 0 0 1.5px`）+ 一次 `segFlash`。
  - 非 `switchable`（ingest/retrieval）：`<Field label locked>` + **只读字段**（虚线框 mono + 小锁）。
  - `detail` 摘要（照搬 `buildDetail`）：一排 mono **meta chips**（model、`384d`、`生效引擎 …`）。
  - `consequence!='none'`：一行 `↻` 小字，rebuild=warn 色、restart=muted。
  - 缺依赖：内联 `DepRow`（见 §5）。
  - 跳转入口（见 §4）。
- 候选标签照搬 `backendLabel()`。

---

## 4. ⑥问答 / ⑦同步 = 真实可进入界面（更显眼 + 跳转入口）

> 用户要求：ask、sync 是用户真正能交互的界面，要与管线环节**区分开**；即便功能暂不可用也要比其它节点**稍显眼**；并各带一个**跳转到自身页面**的入口（LightRAG 也给一个次级跳转）。

- `STAGE_META[id].kind`：`"pipe"`（管线环节）| `"dest"`（可进入界面）。`ask`、`sync` 为 `dest`。
- **dest 节点视觉区分**（`.node--dest`）：边框 1.5px、圆角 16、阴影更重（`--shadow-dest`）、图标右下角加一个 `--st-info` 的「外链/portal」小徽标、role 药丸用 info 色。**即使 `status==off` 也保持实线、不降透明度**（`.node--dest.is-off{opacity:.9;border-style:solid}`），确保「比别的明显」。
- **跳转入口**：
  - dest（ask/sync）：底部**主按钮**（ink 实心，整行，右侧箭头）：「进入问答界面 →」「进入同步设置 →」。
  - pipe-with-link（graph）：**次级文字链接**「打开图谱视图 →」。
  - 配置：`STAGE_META[id].link = { label, href }`（ask→`/ask`、sync→`/sync`、graph→`/graph`）。
  - 真实代码用 `next/link`/`router.push(href)`；若该功能后端为 `reserved`（如部分 sync 能力），按钮显示「即将开放」并 disabled，但**节点本身仍保持 dest 的显眼样式**。

---

## 5. 依赖管理：内联进节点 + 删除独立面板

- **删除** `DependencyPanel`/`DepCard` 整块。
- 节点参数区底部，对 `stage.required_deps` 反查未安装项渲染 `DepRow`：`⚠`(warn) +「缺少依赖：{名}」+ `pip_spec`(mono 省略) + 右侧 `[去安装]`。点 = `handleInstall(dep)`，`installing===dep.key` 时禁用并「安装中…」。
- 原面板的「查看终端日志」链接如仍需要，挪到页头副标题区即可，别再保留整块面板。

---

## 6. 状态分级（解决「凌乱 / 层级差」）

旧版同时用 边框色 + `saturate(0.18)` 去饱和 + 脉冲点 + 药丸 + 徽章 → 过载。新规则：
- **状态只由两处表达**：① 左 stripe 颜色；② 右上状态徽标（点+文案）。连线/ handle 跟随但不喧宾夺主。
- `off` 节点：`opacity:.72` + 虚线边（dest 例外，见 §4）；**不再重去饱和**。
- 微动态克制：仅 `degraded` 徽标脉冲；仅 `ready` 连线流动。`prefers-reduced-motion` 全关。
- 选中态：墨色描边 + ring（点节点选中、点空白取消）。

---

## 7. 文案优化（已在 demo 落定，照抄）

| 阶段 | 描述（zh） |
|---|---|
| ingest | 上传的文档先留存原件，再切成文本片段存入 SQLite。基础安装即可用。 |
| embedding | 把文本片段转成向量。可用本地模型离线计算，或调用云端 API。 |
| vector_store | 存放向量并做稠密检索。默认 Milvus Lite，可回退到 AstrBot 知识库。 |
| retrieval | 默认检索路径：向量与词汇多路召回，RRF 融合排序，自动完成。 |
| graph | 与检索编排并联的高精度路径，基于知识图谱召回。可选启用，不影响默认检索。 |
| ask | 知识库问答主界面。把检索到的上下文注入回答，或交由内部代理直接作答。 |
| sync | 把知识库镜像备份到 Cloudflare R2 / Notion，与检索互不影响。密钥经环境变量配置。 |

role 标签：ingest「只读」、embedding「可切换」、vector_store「可切换」、retrieval「只读 · 默认」、graph「可选 · 并联」、ask「界面 · 可切换」、sync「界面 · 旁路」。

---

## 8. 文件落点建议

- `app/(console)/flow/page.tsx`：重写呈现层；保留所有 handler、`SWITCH_MAP`、状态机、i18n；删除 `DependencyPanel`。
- 抽子组件到 `components/flow/`：`FlowDiagram`(网格+连线+测量)、`FlowNode`、`Segmented`、`StatusChip`、`DepRow`、`Connectors`。
- token 落 `styles/tokens.css`（中性组 + 状态语义）。
- keyframes（`connFlow`/`stPulse`/`segFlash`）落 `tokens.css`，遵守 reduced-motion。
- 拓扑 `EDGES`、`STAGE_META`（含 kind/link）、`SWITCH_MAP` 集中一处常量文件。

---

## 9. 验收清单

- [ ] 7 节点横向分支布局：③→④/⑤ 上下并联（标注 默认/高精度）→ 汇入 ⑥；① ──纵向旁路虚线──► ⑦。
- [ ] 连线随节点真实位置测量绘制；状态色逻辑诚实（off→灰虚线、degraded→琥珀不流动、双 ready→绿色流动）；流动动效保留且尊重 reduced-motion。
- [ ] 画布可拖拽平移 + 滚轮/按钮缩放 + fit；节点位置固定（不可单独拖节点）；缩放时点阵网格联动、连线随之正确。
- [ ] 切候选 → `updateConfigValue`；按 consequence 弹 rebuild/restart 横幅或「已保存」；切后重拉刷新；当前项一次 flash。
- [ ] ⑤graph、⑦sync 开启缺依赖 → 状态「待处理」并内联缺依赖；「去安装」→ `installDependency` → 重拉，依赖行消失、状态转就绪、相关连线转为流动。
- [ ] ⑥问答、⑦同步 为 dest 样式（更显眼、即便 off 也明显），各有主按钮跳转 `/ask`、`/sync`；⑤graph 次级链接跳转 `/graph`；reserved 功能按钮禁用但节点仍显眼。
- [ ] 旧 `DependencyPanel` 已删除，功能全部在节点内可达。
- [ ] 状态只由 stripe + 徽标表达；`off`（非 dest）仅降透明度+虚线；动效克制。
- [ ] 全部颜色走 token；深浅主题（`.dark`）均成立。
```
