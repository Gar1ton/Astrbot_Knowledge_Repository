# 清洗、证据展开与重处理升级：执行版

状态：v1.2.0-preview（2026-09-12）；升级一致性修复已接入，真实语料效果 pending。下面的执行说明取代初始草案中的过期状态。

## 本轮采用的范围

依据本轮提供的对话和 TODO 中记录的后续用户决定：

- 保留 PyMuPDF4LLM → 清洗 → 切片 → 索引。质量优先，导入速度次要，不引入重型解析器。
- 脚注保留原文和页码；确定的脚注不生成普通召回 chunk，随关联正文读取，也可显式单独读取。
- 保留结构切片，加通用章节识别与 token 上限；未知模型 tokenizer 时明确使用估算，不声称精确保证。
- enhanced/deep 复用已有子查询、SEA、自检缺口补查。普通模式和外部 agent 不建立新探索会话。
- 不增加判断来源集中度的 LLM 调用，不统一降权书籍，不固定来源比例。
  对话末尾的“按需分组补查/单次分组搜索”未选定，因此本轮不擅自启用两者。
- 沿用已经确认的简化决定：新清洗直接生效，旧文档通过手动维护重新抽取；不恢复 W1/W6
  已删除的代次账本、租约、持久队列和 staging 发布系统。
- 两个已有 chunk 读取入口继续按用户要求“旧 schema 自动重切一次”；它不是重新抽取 PDF。
- 原始 PDF 不改；不执行真实库迁移、真实模型效果评测或远端 Git 操作。

## 实际实现与验收

| 阶段 | 实现 | 行为验收 |
| --- | --- | --- |
| W0 契约核查 | 已有调用链/依赖/测试核查；本轮复查差异 | 保留已有授权边界，区分真实效果与自动化验证 |
| W2 清洗与切片 | `artifact_cleaning`、`structural_protection`、`generic_headings`、`chunk_token_limits` | 保护结构，优先段落/句子切分；原 PDF hash 不变 |
| W2 来源与身份 | `artifact_provenance`、`IngestManager` | raw pages/脚注持久化；同制品重切 ID 稳定，新正文或新边界更换 ID；零正文页保留页码 |
| W3 证据会话 | `evidence_session`、`evidence_cache` | 请求隔离，检索/embedding 并发复用，排除集合变化触发新检索，缓存只存原始重排分数 |
| W3 用量 | `usage_ledger`、两种 LLM adapter、`llm_json` | actual/estimated/unknown 分开；JSON 重试与内部 fallback 逐调用计账 |
| W4 发现与选择 | `retrieval_orchestrator`、`evidence_selection` | scope/排除先于 top-k；fallback 有界扩召回并报告不足；已覆盖方面不挤占未覆盖方面 |
| W4 阅读视图 | `evidence_views`、`evidence_actions` | canonical 原文与 hash 不变；同修订正文多层续接、脚注附读、来源列表、受控截断 |
| W5 编排 | enhanced/deep 两编排器与 prompts | 充分路径仍两次逻辑 LLM 调用；可选阅读动作复用现有自检；纠偏失败恢复答案和来源视图 |
| W1/W6 替代 | 现有 API 的手动重处理 + 维护脚本 | 默认预览；处理版本检测；索引失败下次只补索引；新向量成功后清理旧修订向量 |
| W7 交接 | 维护/对照导出脚本、测试与本文 | 无新前端树图、无新数据库迁移；真实质量与 120% 目标由用户验证 |

实现采用轻量会话和明确的来源边，不另外建立因果 DAG 服务。SEA 的支持/冲突关系带
`provenance=SEA`，邻接边只表示阅读关系，不能作为因果推断。

### 数据契约

- `clean.md` 是正文 canonical 文本，chunk 的 `[start_char:end_char]` 精确对应其 `text`。
- `provenance.json` 保存原始逐页 Markdown 与脚注，脚注偏移针对原始页；页眉遮蔽不改变这些偏移。
  脚注有 `page/marker/source_start/source_end/link_status/body_marker_span/doc_id`。
- `pages.json` / SQLite page chunks 针对正文；空正文页面也保留页身份。全文模式补入脚注附录，
  canonical Markdown 下载仍保持原有字符定位；脚注也有独立只读入口。
- 新 chunk ID 形如 `<doc>_c0000_r<revision>`。修订由 canonical 文本、脚注、切片边界和处理版本
  决定。重处理后旧 ID 不会静默指向新正文；历史 sources 已保存的原文仍可阅读。
- `metadata.evidence_view` 包含独立视图 ID、text、sources、token_count 和 truncated；不改原 chunk
  的正文/hash。最终引用编号和视图一起冻结，纠偏失败一起回滚。
- 没有全库代次承诺。读取已取得的旧 chunk 可以继续使用其快照；邻接展开拒绝未知/不同修订。
  手动维护逐篇更新，期间不提供全库一致快照。处理与索引通过同进程共享锁串行执行；
  没有跨进程写入协调。

### 预算和额外消费

- 切片默认目标 400 estimated tokens，embedding 输入参考上限 512，预留 32；仍保留旧字符结构规则。
- 重排输入按 query + 正文 + 特殊 token 预算制作窗口，缓存基于完整原文 hash 与模型实例。
- 阅读视图默认总正文预算 8000 estimated tokens，新增上下文 800，最多沿邻接走两层；
  显式动作仅接受 `expand_before/expand_after/read_footnote` 及本会话已知来源 ID，重复动作不触发新纠偏。
- enhanced 在纠偏前检查 24000 token 安全阀，并预留 4000 输出 tokens；这是估计安全阀，
  不是对未知 provider 最终输出的硬截断，也不是“每道题旧版消费 × 1.2”。
- 两次是常规路径的逻辑调用数，JSON 重试、provider fallback、纠偏和 API 兜底均可能增加真实调用。
  台账逐条保存，未知失败消费不记作零。补检/重排仍可能增加计算或收费服务消费。
- `thinking_trace.evidence_trace` 返回证据边、选择原因、缓存数量、不足原因、最终证据 ID、视图来源及 usage。
  有 sources 的答案把同一 trace 放入第一条 source 的 `request_trace`，随既有聊天记录持久化。
  无来源的失败依赖既有错误/运行事件诊断，不新建持久任务或审计数据库。

## 手动维护指南

这些命令供用户在自己的部署中执行，本轮没有运行 `--apply`。

```bash
# 密码通过 KA_WEB_PASSWORD 环境变量提供；使用实际 WebUI 地址和用户名。
python3 tools/reprocess_cleaning.py --url http://127.0.0.1:8080 --username admin
# 核对预览结果后重抽取并索引，可能产生 embedding 消费。
python3 tools/reprocess_cleaning.py --url http://127.0.0.1:8080 --username admin --apply
```

- `POST /api/documents/reprocess-cleaning`，JSON `{ "dry_run": true }` 为默认，只读文档元数据，
  不调用可能触发重切的 chunks GET。`false` 执行维护。沿用 WebUI session 鉴权，非法布尔值返回 400。
- 手动维护、重抽取和自动/手动索引共用进程内任务可重入锁。自动任务被唤醒后等待维护
  释放锁，再重读待索引集合；不继承父任务的锁所有权；取消时等待制品旁车写入线程结束后再释放锁。
  维护时仍应避开跨进程写入、全库
  恢复和其他未纳入锁的管理操作；这是手动维护，不是后台持久迁移系统。
- 返回 `reprocessed/pending_reindex/skipped_already_new/skipped_not_pdf/failed`。`reprocessed`
  表示处理流程完成，不代表索引就绪；未配置索引组件、非 ACTIVE 或索引不兼容时列入
  `pending_reindex`（保留 needs_reindex），不向不兼容索引直接写入。索引异常列入 `failed`。
- 重处理开始前持久保存 `processing_pending` 和 `needs_reindex`。派生文件发布后，将
  chunks、page_chunks 和处理元数据作为单个 SQLite 事务提交；成功清除 processing_pending。
  文件与 SQLite 不是跨介质原子事务，失败期间只读全文/脚注入口拒绝读取待恢复制品。
- 中断后可以再次执行；pending 优先于 processing_version，下一次重切/索引先从保留原件
  恢复处理，原件缺失则报错并保留标记，不能清除待索引状态。已完成抽取而仅索引失败的
  文档下次只补索引。SQLite integrity_check=ok 不能替代页映射/处理状态/召回验证。
- 旧 v3 chunks 不因代码更新自动成为新清洗产物。要使用新脚注/修订身份，仍需执行本维护；
  升级前保留数据库、文档制品和向量索引的一致备份。
- `GET /api/documents/{doc_id}/footnotes` 返回全部脚注（包括未关联脚注和仅含脚注的页面），
  文档不存在返回 404；请求保持只读，脚注原始 offset 不冒充正文 offset。
- 维护不自动启动全库同步、不删除原 PDF。旧向量的清理发生在新向量成功写入之后。
- Milvus 正常关闭前显式 flush，避免把未落盘数据留到解释器退出时才交给 PyArrow 处理。

## 用户对照测试

选同一组定义、机制、对比、争议、脚注及指定文档问题，分别保存旧/新 Ask JSON 响应。
记录代码版本、语料快照、配置、模型和实际端到端耗时；不要在日常问答中双跑旧版。

```bash
python3 tools/export_evidence_comparison.py response.json   --question-id q01 --code-version CODE_SHA   --corpus-version CORPUS_ID --config-version CONFIG_ID --latency-ms 1234
```

导出单条 JSONL，不含问答正文、文档全文或密钥。旧版本缺少 usage 时 `usage_available=false`，
不能用估算填成 actual。评价正确证据召回、同书多方面覆盖、反驳证据、脚注定位和响应时间。

120% 目标采用同一问题集的 `sum(new input+output) / sum(old input+output)`；actual 与 estimated
分开比较，存在 unknown 或缺 baseline 时不宣称达标。真实 PDF 的脚注识别准确率与实际导入提速
均未由合成测试证明。

## 验证记录

v1.2.0-preview 全量 1037 passed / 2 skipped / 2 deselected（仅排除两个缺 torch 的既有用例），
退出码 0，62.06s。最后文件线程取消保护补充回归 151 passed，4.93s；ruff、mypy、
diff whitespace 和版本一致性检查通过。新增 10 项升级故障/恢复/并发回归。
真实 Milvus 测试包含排除下推与旧修订清理；关闭前 flush 修复后，全量进程正常退出。
两项 torch 环境缺失未通过安装重型模型依赖掩盖，具体名称与命令见 TODO。

## 初始草案（历史背景）

下文保留 2026-09-11 初始设计以便追溯。它的 proposed 状态、W1/W6 持久迁移要求、读取只读要求
已被上述用户后续决定替代；具体交付以本执行版和 TODO 最新记录为准，不应再次按旧草案恢复复杂基础设施。

<details>
<summary>展开初始设计与原验收矩阵</summary>

# 清洗、证据展开与可恢复重建计划

状态：proposed，供执行 agent 接手；功能选择已确认，本文实施计划尚待明确批准。2026-09-11。
本轮仅扩充计划文档，不修改生产代码、数据或索引。用户要求便于交给其他 agent 执行，不等于
已经授权当前 agent 开始编码或操作真实语料。

## 接手说明与阅读导航

本文应独立于聊天记录使用。先读「已确认范围」确定产品约束，再读 Phase 0–6 理解工作包，
最后按「执行顺序」「数据契约」「恢复矩阵」「验收矩阵」实施。

- **用户决定**：已确认范围中的行为与边界，不能由执行 agent 自行降级。
- **建议设计**：下文给出的模块名、类型名、表名、状态名和算法细节，是可执行起点，不是已存在的代码。
  可按代码证据调整命名与内部实现，但必须保留可观察行为、依赖方向和测试要求。
- **待验证能力**：必须用当前锁定依赖和隔离数据验证，不能根据上游最新文档直接推定支持。
- 接手先完整阅读 `CLAUDE.md` → `ARCHITECTURE.md` → `CONVENTIONS.md` → `TODO.md`，再读本文。
  检查当前 Git diff，保留用户已有修改。本文中的代码核查以规划时工作树为准，行号不作为契约。
- 如果接手消息明确批准按本文实施，则先更新 TODO，随后逐工作包实现和测试；不必反复请求同一授权。
  若仅要求评审，则只输出评审发现，不修改生产代码。
- 不自动同步真实 Zotero、不启动真实全库迁移、不运行付费模型评测、不执行远端 Git 操作。
  使用临时目录、测试库与 mock；真实测试由用户进行。必要的依赖/网络操作按环境权限执行。
- 本任务可以由单 agent 顺序完成。不要为了“可交接”自行启动并行 agent；若后续用户另行授权，
  共享接口、SQL 迁移、组合根和 API 必须由一个集成负责人统一管理。

## 已确认范围

- 保留 PyMuPDF4LLM → 清洗 → 切片 → 索引的数据流；不引入 MinerU、Docling 等重型解析器。
- 入库质量优先，导入提速次要；修复水印、页眉页脚、脚注混排、章节识别和跨页正文续接。
- 脚注保留原文与定位，默认不独立竞争普通召回名额；随相关正文或明确注释查询读取。
- 切片优先保持段落完整，使用模型 token 预算约束。
- 检索策略升级限定 enhanced / deep thinking；普通模式不启用新证据探索策略，但共享新清洗产物。
- 两模式允许多层证据展开，利用已有规划、自检和推理步骤；不增加专门判断来源集中度的 LLM 调用。
- 单次问答内复用计算；后续发现性补查排除已命中 chunk，已有证据仍可支持多个子问题。
- 按相关性、子问题覆盖、内容冗余选择证据；不统一降权 book，不固定书与论文比例。
- 前后文与脚注按需扩展，合并重叠范围，受总 token 预算约束。
- 证据树只做后端结构化记录和查询，不增加前端树图。
- enhanced 的输入＋输出 token 总量以同一评测集旧版的 120% 为目标，不是逐问题承诺。
- 增益与深度仅为软参考，保留总预算与异常循环保护。用户负责真实语料效果测试。
- 更新入口检测独立处理版本，旧格式触发一次全库迁移；之后只比较版本，不扫描全部文档格式。
- 原始 PDF 不改；派生产物在新代次就绪后统一切换，旧代次在构建期继续服务。
- 重建、排队写入均持久化，重复触发复用任务，支持断连/重启恢复。
- 没有已部署 LightRAG 实例，不做旧图谱迁移；保持未来索引引用契约。

## 代码核查与必须解决的契约差异

| 现状 | 计划中的处理 |
| --- | --- |
| `markdown_extractor.py` 将空行间单换行统一合并，只消费逐页 Markdown 文本 | 先保护结构块，再修正文；有歧义时利用同一 PyMuPDF 栈的版面信息辅助，不假定纯正则能可靠恢复所有脚注 |
| `chunking.py` 按字符长度，章节主要依赖编号正则 | 补通用书籍标题与章节，注入 tokenizer 预算能力 |
| `IngestManager` 原位覆写派生文件；重清洗路径不同时更新所有 page chunks | 统一构建派生产物包：文本、映射、脚注、chunks、page chunks 与元信息一起发布 |
| chunk ID 为文档 ID 加序号，重切片可复用同 ID 指向不同正文 | 新 ID 包含不可变代次身份；兼容旧引用读取，禁止静默重定向 |
| `api.get_chunk_context()` 等读取路径会调用旧 chunk 自动重建 | 读取只读固定代次，迁移只经任务入口 |
| `api.rebuild_vector_store()` 先标不兼容并 `clear()` 活跃向量库 | 构建独立 staging 索引，旧代次不失效；不能沿用先清空再写入 |
| Milvus/Zotero job 主要是纯内存对象，单飞保护也是进程内状态 | 持久任务账本、阶段检查点、租约与持久队列；现有对象成为状态投影 |
| enhanced 是 PLAN-lite → 检索 → SYNTH+CHECK → 可选补检及重合成 | 保留轻量主路径，增加有来源的分支动作，不复制 deep 全部循环 |
| deep 已有 checklist、discovered aspects、next queries、来源轮转 | 复用这些机制，新增共享证据池与分支关联，不重造第二套 planner |
| `llm_json.py` 按字符估算 token，异常重试可能丢失累计量 | 从每次实际模型调用计账，区分 usage 与估算，异常/重试/兜底也计入 |
| `agent_evidence.py` 被 enhanced 和外部 agent 入口共用 | 通过模式/会话策略显式启用；外部 agent 无插件 LLM 生成的契约保持不变 |

已阅读相关测试：ingest 的偏移和书目契约；enhanced 两次调用、纠偏及答案/证据回滚；deep
覆盖、补检、预算和并发检索；API 的旧格式读取、全量清空、单飞与部分失败；auto_reindex 退避/park。
重建相关测试位于 `test_api.py`，不是单独的 `test_milvus_build.py`。

## Phase 0 — 契约与最小能力验证

动作：批准后先在 TODO 登记本计划与阶段状态；建立单次问答、语料代次、处理版本、结构块与
检索策略的类型化契约。核对当前依赖下 tokenizer、模型输入上限、Milvus 过滤/排除能力，以及
派生数据涉及的 SQLite 表、FTS、文件读取、下载、引用与索引路径。

- 处理版本由清洗规则、切片规则、tokenizer/预算策略等明确配置构成，不使用插件版本或文件 mtime。
- embedding 指纹单独记录，模型切换与处理格式迁移不能互相冒充。
- 明确 `generation_id` 与全库 active 指针、源文档快照、原文 hash 的关系。
- tokenizer 未知时使用明确标识的保守预算与输入检查；不能声称精确保证未知外部模型上限。
- 不靠加载完整 embedding/reranker 模型取得 tokenizer；缓存 tokenizer 和计数结果。
- 无需本轮部署新的向量库、解析器或跑用户真实数据库。

理由：后面的清洗偏移、引用恢复与原子切换必须使用同一身份契约。
完成条件：能力检查与接口替身验证通过；若当前环境不支持关键能力，提出具体替代方案再确认。

## Phase 1 — 可追溯清洗与 token 感知切片

落点：`managers/markdown_extractor.py`、`chunking.py`、`ingest_manager.py`；必要的纯模型放 domain，
按职责提取清洗、token 预算辅助模块，避免继续扩大巨型文件。

- 保留原始逐页抽取文本及必要位置线索，确定的水印/页边噪声从检索文本排除。
- 列表、表格、公式与标题先保护，再修复正文换行、断词、跨页续接。
- 页眉识别支持章节变化和奇偶页模式；真实章节标题不能因重复而直接删除。
- 脚注单独保存为带来源区间的结构块，链接标记包括文档、页/章节上下文与注号，防止重复编号串线。
- 低置信分类/关联保留原文并标记，不强删、不臆造脚注连接。
- 正文 clean.md 与脚注派生表示分离；重建所有字符映射。跨页片段可映射多个原页区间，不能
  强行用一个原始连续区间覆盖被移走的脚注。
- 明确正文 chunk 的 `clean.md[start:end] == text` 不变量；脚注和扩展上下文使用各自来源区间。
- 支持无编号标题、Chapter/Part/§ 等；长段按句子/token 拆分，标题上下文计入预算。
- reranker 需计入 query 与特殊 token，查询长度变化时做运行时窗口控制，不能仅靠入库预算保证。
- 普通向量与词法检索排除确定的脚注/噪声块；全文阅读仍能访问脚注，明确脚注请求走注释读取。
- 导入阶段分段计时；重抽取/重清洗的阻塞操作下放线程，避免多次解析和重复 tokenizer 计数。

测试：截图形态的自造短样本、跨页括号/断词、脚注重复编号、页眉误删、表格/列表保护、中英
token 边界、原始 PDF hash 不变、页码与 offset、书目信息优先级、所有派生产物一致。
真实 PDF 的脚注准确率由用户验证，不用合成测试替代效果结论。

## Phase 2 — 单次问答证据会话与实际用量

落点：domain 证据模型、新共享 evidence session 服务、`llm_json.py`、LLM adapter、两个编排器。

- 每个请求固定语料代次；共享证据池存一次正文，各子问题引用同一证据节点。
- 分支是探索树，证据可多父复用，内部按无环关系存储，避免复制正文或制造循环。
- 记录 query/aspect、父分支、来源片段、扩展动作、选择理由和问题缺口；不要求模型输出私有思维链。
- 邻接/脚注关系由结构决定；支持、反驳或因果关系必须携带证据依据与不确定性，不将邻接推断为因果。
- query embedding、检索、重排在本次请求内缓存并合并并发同键调用。
- 检索缓存键含 query、scope、代次、排除集合、候选预算与模型配置；改变排除集合不能命中旧结果。
- 重排缓存保存原始 `(query, content_hash, model)` 分数，候选池归一化每次重算，不能缓存池内名次。
- 所有模型调用在 adapter 边界计账：输入、输出、实际/估算来源、重试、错误与 fallback。
  缺 usage 不能记成零，无法确认的失败消费标 unknown。reasoning token 不与已包含它的 completion 重复计数。

测试：缓存键隔离、并发复用、代次固定、多父引用、usage 缺失/重试、兜底合成计账、正文不重复发送。

## Phase 3 — 新证据发现与覆盖选择

落点：`retrieval_orchestrator.py`、`deep_thinking_evidence.py`、共享 evidence session；source/vector
store 的过滤与邻接读取接口及 SQLite/Milvus/memory 实现。

- 新策略显式限定 enhanced/deep；普通检索保持原有排序策略。
- 已选 B：后续发现性检索排除已命中 chunk，排除应在候选截断之前下推向量/词法路径；
  不支持的后端用有界扩召回再过滤，暴露不足，不偷偷突破 scope。
- 已有证据仍对新 aspect 重新评估；明确的定位/验证读取可复用已有片段，这不是再次发现性召回。
- 原文 scope、生命周期、代次先过滤，再融合；同文档不同章节不统一惩罚。
- 每个 aspect 保留相关候选，再以相关性、覆盖贡献与文本重叠做确定性贪心选择。
- 不直接引入 Dartboard 或固定文档配额；它们保留为实验候选，当前以少改流与可解释性为优先。
- 对已发现的覆盖缺口生成预算内补查动作，复用现有子查询/纠偏输出。
  “来源占比高”仅为 trace 信号，不足以单独判错或扣分。
- 结构锚点保留来源与作用域约束，不让宽泛锚点挤占全部证据预算。
- 选定后读取必要相邻正文与关联脚注；中间推理确需上下文时可提前扩展，仍由共享池去重与计预算。
- 扩展结果使用独立 evidence view 与完整来源列表，不修改原 chunk 正文并沿用旧 hash。

测试：同书多章节保留、相邻重复让位、稀有知识不因来源丢失、先过滤再 top-k、多 aspect 共用证据、
空候选、无 reranker、失败降级、默认模式行为不变、扩展页码/Harvard 引用准确。

## Phase 4 — 两模式的多层展开与消费控制

- deep 复用 PLAN/SEA/VERIFY 与 discovered/next_sub_queries，将动作和 coverage 连接到证据会话。
- enhanced 保留轻量 PLAN 与合成自检，将多层局部结构扩展放在不调用 LLM 的读取动作中；
  推理缺口通过已有自检输出继续发现，避免为每个分支增加分析调用。
- 正常充分路径仍以两次 LLM 调用为基线；多层证据关系不等于每层必须调用一次 LLM。
- 如确需追加纠偏，预算内优先替换重复证据、保留简短缺口记录，避免反复发送完整答案/树/全部历史。
- 深度、增益为软参考；保留最大调用量、输入/输出预算预留、重复动作检测与取消保护。
- 预算不足时返回当前有效答案及未解决缺口，不能把“完成纠偏”直接当作“证据已充分”。
- 修正 enhanced 当前纠偏完成即 `verified=True` 的语义，复用既有自检结果/明确状态；不为此
  新增独立验证调用。重合成失败仍将答案、引用池和上下文一起回滚。
- 后端 trace 增加代次、分支、来源关系、缓存命中、排除数、上下文 token、调用消费与未解决缺口；
  接入现有 API/鉴权，保持旧字段兼容，不做新前端可视化。
- 外部 agent enhanced/deep 入口可消费确定性证据结构；不自行调用插件 LLM，不暗增跨请求会话。

测试：两模式多层扩展、正常两次调用、补查、预算结束、重复循环、失败回滚、无额外判断调用、
trace 来源可核查、外部 agent 无生成式调用契约。

## Phase 5 — 持久全库迁移与代次发布

这是本轮最大的基础设施改动；保留用户数据流，但必须扩展内部仓储契约。
建议以 SQLite 持久账本/active generation 指针为发布真相源，派生文件和向量索引按代次隔离。
不复制或替换整份包含聊天、配置、Zotero 镜像的业务数据库。

- 新增编号迁移：代次、重建任务、文档阶段检查点、写操作队列及必要的派生记录版本字段。
- 更新入口轻量比较目标与已完成处理版本；不一致先取得写入协调权，创建/恢复唯一迁移任务，
  原始同步请求入队；成功切换后执行同步，保证新文档用新规则。
- 冻结目标文档集合及原文 hash；所有插件语料写路径（同步、上传、删除、移动、手动重抽取、
  自动索引、镜像移除）走协调器，重复同步合并；上传须先持久暂存，不能只排临时文件路径。
- 保留 ACTIVE 可检索范围与 detached 语义，不能因“全库”把 detached 文档重新加入搜索。
  对保留的非活跃源记录登记版本状态，重新激活时按当前规则处理。
- 文档阶段：原件可用性 → 抽取/清洗 → 切片及映射 → embedding 批次 → staging upsert → 校验。
  PDF 从原件重新抽取以恢复结构，TXT/MD 走各自路径，不伪装 PDF。相同 hash/指纹复用已完成产物。
- 使用稳定批次 ID 与幂等 upsert，应对“写成功但尚未记完成就断电”；不承诺网络调用物理上恰好一次。
- 浏览器重连读取同一 job；重启按持久状态、租约及文件校验恢复，跨重启时间用持久时间戳。
- 原文是外部 linked 文件，不能被插件队列锁住；开工/恢复/发布前核对变更，发现变化则使对应
  staging 产物失效重做，不用旧 hash 标记新文本。
- staging 全量校验成功后，将 active 指针与任务提交状态在同一 SQLite 事务发布；文件/索引
  必须先持久就绪，不能声称 SQLite 与 Milvus 之间存在分布式事务。
- 每次请求固定代次；发布前启动的检索完成旧代次读取，发布后的检索使用新代次。
  重启先恢复 active 指针对应资源，再开放检索。
- 部分失败、磁盘不足、原件缺失均不切换、不标完成；保留旧库和断点，有限退避后 park。
- auto_reindex 复用迁移协调器，不能绕过它清库或把 partial_failure 标为新格式完成。
- 发布后执行持久队列，按幂等键和执行状态防止重复副作用；聊天等非语料写入不阻塞。
- 旧代次在读者退出后回收可重建的向量数据；历史引用保留必要文本/定位快照，旧 ID 绝不能
  静默指向新文本。清理顺序也持久化，清理失败不能回滚已成功发布的新代次。
- 仅覆盖逻辑上的当前派生产物，不物理覆写正在被旧请求使用的文件，不改原 PDF。

测试重点：每个阶段前后注入异常/重启，upsert 成功未记账、提交前后退出、重复点击、浏览器断连、
租约恢复、原文变动、磁盘/原件错误、队列重放、发布时并发查询、历史引用、读路径不触发迁移。
通过 SQLite＋内存索引做契约测试，并对本地 Milvus 可用环境做隔离持久化集成测试。

## Phase 6 — 接线、回归与用户验收准备

- 组合根注入共享预算、证据服务、代次资源和迁移协调器；API/路由保持薄委派。
- 沿用已有状态轮询与进度组件；必要时兼容新增 queued/recovering/publishing 状态文案，
  不新增页面或证据树 UI，不手改 pages/。
- 文档记录同步触发迁移、排队、失败恢复、token 来源和测试方法。
- 提供由用户主动运行的新旧对照入口/导出，不在日常问答中双跑旧版。
- 用同一问题集、模型、语料比较总输入＋输出；baseline 需保存旧版配置/代码标识及统计口径。
  清洗前后语料分别标识，能区分入库改进与检索策略的贡献。
- 20% 是待用户验证的总体目标；真实 usage 不可得时明确估算，不能以离线 mock 通过宣称达标。
- 按阶段运行相关测试，最后全量 pytest、ruff、mypy；若有前端兼容改动再运行 build/sync 检查。
  本轮规划未执行测试，也不声称已有基线全绿。
- 通过后才在 TODO 勾完成并追加 CHANGELOG，真实效果尚待用户测试时单列 pending。

## 接口变更理由与控制范围

- source store：代次隔离、只读来源区间/脚注/邻接访问，是一致发布与准确引用的必要变化。
- vector store：指定代次、排除 chunk、staging 生命周期，是不停机迁移与发现性补查的必要变化。
- LLM adapter / generation result：区分实际用量、估算、未知及重试消费，是 token 目标的必要变化。
- composition root：集中创建新服务与资源生命周期，不让业务类自建数据库或模型。
- 所有变更同步 base 契约、生产实现、memory 替身、调用方和测试；不顺带重构无关子系统。

## 实施时仍需验证的边界

这些是实现验证项，不新增用户选择：脚注版面关联在现有解析栈的可靠程度；外部模型 tokenizer
可获得性；当前 Milvus Lite 版本的过滤/排除与多代索引行为；所有读取路径是否固定同一代次；
实际 provider 用量是否包含重试和 reasoning。若其中任一项要求改变已确认的数据流、成本或
可用性承诺，先报告具体证据并询问，不自行替换为重型解析器或降低验收范围。

## 执行顺序与可交付工作包

Phase 编号是功能分组，不表示可以先让新清洗原位覆盖旧数据。建议实际顺序如下：

| 工作包 | 依赖 | 交付物 | 此时允许接入生产入口吗 |
| --- | --- | --- | --- |
| W0 契约核查 | 无 | 调用点清单、依赖能力结果、TODO、基线结果 | 不改变行为 |
| W1 身份与存储基础 | W0 | Phase 5 的代次/修订模型、SQLite 迁移、仓储接口和 memory 实现 | 仅兼容读取旧库 |
| W2 清洗与切片 | W1 | Phase 1 的纯转换及 staging 构建、单元测试 | 暂不自动迁移 |
| W3 用量与证据会话 | W0、W1 | Phase 2 的 usage、缓存、来源视图 | 新策略尚不默认启用 |
| W4 检索与上下文 | W2、W3 | Phase 3 的过滤、覆盖选择、扩展 | 通过替身/隔离库测试 |
| W5 两模式编排 | W4 | Phase 4 的多层动作、自检、后端 trace | 仅目标模式启用 |
| W6 恢复与发布 | W1、W2 | Phase 5 剩余任务、队列、切换、GC、故障恢复 | 全套恢复测试后接线 |
| W7 集成与交接 | W5、W6 | Phase 6 的入口接线、回归、测试说明 | 可交用户测试 |

每个工作包结束时记录：改动文件、接口变化、运行命令与结果、已知限制、下一包依赖。
不能仅完成清洗函数就把整个 Phase 1 标完成；必须包括映射、持久化契约和回归。
不要为了分包创建大量默认开启的实验开关；未就绪功能通过装配边界保持不可达。

### W0 的具体检查任务

1. 从 `api.py` / `web/server.py` / `event_handler` / `plugin_initializer` 追踪全部语料写入口。
2. 查找 `replace_chunks`、`replace_page_chunks`、`clear`、`needs_reindex`、
   `_ensure_document_chunks_current`、原件/Markdown 下载及引用跳转的所有调用点，写入 TODO 核查清单。
3. 查看 `migrations/010_documents_artifacts.sql`、后续表迁移及 SQLite 初始化代码，核实运行时
   FTS/索引实现；不要假定最早 SQL 文件就是最终 schema。新迁移编号取执行时最大编号之后。
4. 记录增强与深度模式有效配置。规划时默认值：enhanced 子查询 3、wide_top_k 16、
   candidate_k 32、最终证据 12；deep 轮数 4、wide_top_k 24、最终证据 18。
   这些是现有基线，不代表用户要求固定不变，也不是提高预算的理由。
5. 使用隔离测试库验证：向量候选排除、作用域过滤、多实例/多目录索引读写、关闭重开、
   旧代索引仍读时新代写入。验证实际依赖版本并记录，不升级依赖掩盖失败。
6. 核对 tokenizer 和 provider usage；不获取真实 API key、不输出敏感配置。
7. 先跑有关联的既有测试建立失败基线；历史失败单列，不大范围修复无关问题。

## 数据与接口草案

以下为建议新增契约，名称可调整。字段选择要覆盖下述语义，不能只在任意 metadata 中堆字符串。

### 处理版本、全库代次与单篇修订

必须区分三个概念，否则统一迁移完成后的普通文档更新会再次破坏引用：

| 对象 | 含义 | 何时变化 |
| --- | --- | --- |
| processing fingerprint | 确定清洗/切片结果的处理配置摘要 | 有意升级规则、tokenizer 或切片预算 |
| corpus generation | 全库发布的兼容代次，绑定处理 fingerprint 和索引资源 | 全库迁移发布 |
| artifact revision | 某文档某次原文与派生产物的不可变修订 | 原文变化、重抽取或派生内容变化 |

- chunk ID 建议对 `(doc_id, artifact_revision, ordinal, chunk_kind)` 作稳定摘要；长度必须满足
  现有向量主键约束。完整身份单独保存在字段中，不能仅靠解析 ID 获得来源。
- 相同文档同一目标修订的失败重试生成相同 ID；不同正文绝不能复用相同 ID。
- 初次升级把已有数据登记为 legacy 代次，保留旧 chunk ID；这一步只是元数据迁移，不重新 embedding。
- `CorpusReadHandle` 持有代次、所读文档修订/已物化证据，以及向量与文本读句柄。
  普通增量更新也必须保持已读旧修订可解析，不能只固定全库 generation 就声称请求一致。
- embedding 模型在迁移期间改变：旧模型句柄可用则旧代继续查询；不能用新维度模型查旧索引。
  原有配置更新/模型卸载路径需要协调，不静默关闭被活跃请求引用的 provider。

### 文本、脚注与出处

建议 domain 类型：

| 类型 | 最小字段 |
| --- | --- |
| SourceSpan | 文档、修订、PDF page index、原始文本/块偏移、可选 bbox、定位质量 |
| StructuralBlock | block_id、kind、正文、section_path、source_spans、分类依据/置信等级 |
| FootnoteLink | 正文 block/span、注释 ID、注号、关联状态、关联证据 |
| ArtifactManifest | 原文 hash、处理 fingerprint、文件校验摘要、块/chunk/page 数、构建状态 |
| EvidenceView | evidence_id、组成 chunk/脚注 ID、展示文本、source_spans、token 数、截断标记 |

- 保存 canonical 正文与独立脚注；为全文阅读提供按原页阅读顺序组成的视图，不能因为正文
  `clean.md` 不含脚注，就让 fulltext API、原有全文模式或导出的内容漏掉注释。
- `pages.json` 的兼容页区间继续针对正文 canonical 文本；额外 provenance 用多区间映射。
  只有脚注/图片而无正文的页面也应保留页身份，不能把后续页码压缩。
- 标题 breadcrumb 可以出现在 embedding 输入里，但不得写回原 chunk.text；其 hash、embedding
  缓存键与 token 预算应基于实际 embedding 输入。引用仍锚定原文。
- 重排输入如果使用相邻上下文，其缓存 key 也必须包含 view/content hash，不能只用原 chunk hash。
- 未识别的脚注：先保留在原始抽取或明确标注的不确定块，不武断从正文删除。报告分类覆盖率，
  不以过滤更多文本作为质量提升指标。
- 明确注释查询可由显式脚注动作/编号或已有 planner 的 typed action 发起；旧 planner 纯查询格式
  仍能解析。普通模式不得因此新增规划调用或查询改写调用。

### 仓储与协调器接口

建议将持久重建账本放独立 `repository/corpus_build/{base,sqlite,memory}.py`，避免 source store
同时承担任务调度；同一 SQLite 事务要求通过共享事务边界实现，而不是分别开两个连接假装原子。

| 接口能力 | 契约要求 |
| --- | --- |
| acquire_read_handle | 在请求入口解析 active；后续读取沿用句柄，不每个 helper 重读 active |
| build_artifact_revision | 只写指定 staging 修订；不修改 active 文档指针 |
| list_chunks / page / notes / context | 可指定 generation/revision；仅纯读，无隐式重建 |
| search with exclusions | scope、生命周期、代次、排除集合先于候选 limit；返回不足原因 |
| create_or_resume_build | 同源代次＋目标 fingerprint 返回唯一未完成任务 |
| checkpoint_document | 阶段记录与校验摘要持久化，重复写幂等 |
| enqueue_mutation | 先持久化 payload/上传制品，再返回可查询的操作 ID |
| publish_generation | 校验预期 active、任务租约、目标 ready 后 CAS 提交 active 指针 |
| recover / drain_queue | 幂等恢复；任务是否完成以账本为准，不以进程对象为准 |

不要求一次把全部旧方法删除；可保留带默认 active handle 的兼容 facade。但有跨多次读取的问答
必须显式传句柄。所有直接 SQL 与批量 hydrate 路径也要审计，不能仅改 `list_chunks()`。

## 清洗与切片执行细则

处理顺序应固定且有独立测试：

1. 读取原件，保存 hash 与逐页原始抽取；获取已有解析结果可提供的版面线索。
2. 检测结构块：标题/正文/列表/表格/公式/脚注候选/页边噪声。
3. 确认水印与页边噪声，分离高置信脚注；保留删除或分离的依据。
4. 对正文执行断词和换行修复；保护代码/公式/列表，不全局删除下划线或连字符。
5. 跨页续接只在同一正文流、有句法续接信号且无章节边界时执行；识别 § 标题不能当页眉抹掉。
6. 生成 canonical 文本和来源映射，再做 token 感知切片；不能先存 offset 再修改正文。
7. 验证 chunk/token/映射后写 staging manifest，文件全部完成才记录 artifact_ready。

token 预算区分：`target_chunk_tokens`（期望大小）、`embedding_input_limit`（含元数据/特殊
token 的上限）、`rerank_pair_limit`（随 query 变化）、`context_budget`（整次合成证据预算）。
不要把现有 `chunk_size=1000` 直接解释为 1000 tokens；增加明确单位配置与旧值迁移规则。
未知 tokenizer 的估算要使用独立状态，远端返回输入超限应可诊断，不能无限缩短并重试。
巨型单句/表格不能绕过上限；受控拆分后记录 continuation，保留表头与必要出处。

## 检索会话与选择算法细则

### 发现、复用与并发

- `seen_chunk_ids` 指本会话成功获得的候选 ID（不只最终入选 ID）；已见但未入选的文本仍存在
  有界候选池中。若因内存预算淘汰，记录状态，不能出现“排除了且无处再读”的死角。
- `selected_evidence_ids` 与 seen 分开；新 aspect 先复用/评估池中证据，再发起缺口查询。
- 同一轮并发子查询使用轮开始时的 seen 快照；轮结束后统一合并，避免完成先后影响召回结果。
- 重复查询＋相同 exclusions 合并任务；重复查询＋新 exclusions 是新发现请求，不能缓存短路。
- 邻接/脚注/精确验证读取不受发现性排除阻挡，但以 visited action 集合阻止同一动作循环。
- action key 至少包含类型、查询或来源 ID、scope、revision 和方向/窗口；不同 aspect 可以
  复用动作结果并各自添加支持边，不重复 I/O。
- Milvus、SQLite lexical/anchor、AstrBot fallback 都必须说明过滤能力。不支持精准下推时
  只允许预算内 overfetch，返回 `candidate_exhausted` 等原因，不返回越权/错代结果。

### 可落地的初始选择策略

不要在本轮实现完整学习排序或新训练模型。用已有每子查询分数构建确定性选择器：

1. 按每个 aspect 建立候选与原始相关度映射；无需跨池比较未经校准的绝对分数。
2. 保留明确用户定位的有效锚点；其他自动锚点仍参与预算分配。
3. 先遍历有相关证据的 aspect，挑选能补充尚未覆盖方面且不重复的候选；一个候选可覆盖多个方面。
4. 剩余预算按相关度与非重复内容填充；章节路径用于判断局部重复，不作为“不同章必有新知识”的证明。
5. 文本近似重复只减少优先级；含不同否定、数值、结论的高相关证据要能共存，尤其保留反驳证据。
6. 稳定 tie-break 使用 query 顺序、doc/revision/ordinal 等，不依赖 set 遍历或异步完成顺序。
7. 输出选择原因、aspect→evidence 映射、未覆盖项与预算原因，不将程序启发式伪装成校准置信度。

相关性阈值/重复阈值是实现实验参数，不在无真实语料时宣称最优。保持测试可注入，先少量
内部策略值，只有需要用户调节的参数才进入 schema。不要为了 20% 目标降低基础证据质量门槛。

### 扩展预算与引用

局部扩展优先级建议：被截断的正文续接 → 明确标记的关联脚注 → 有理由的前后文 → 新缺口检索。
排序是初始策略，可被已有 planner 的明确动作覆盖。记录 depth，但不以每一层固定轮数强制结束。
同文档同修订的重叠区间合并；跨文档禁止拼成无来源的大段。先估预算再读取/拼装巨大段落。
展示证据编号在一次合成开始前冻结，答案与 sources 同快照输出；重合成失败恢复整个快照。
旧证据 ID 若已被删除，只能给明确 unavailable，不能按 ordinal 猜测新段落。

## enhanced 与 deep 的具体动作协议

建议给现有 JSON 增加可选字段，旧格式保持兼容：

```json
{
  "actions": [
    {"aspect_id": "a2", "kind": "expand_after", "source_id": "e7", "reason": "句子未结束"},
    {"aspect_id": "a2", "kind": "read_footnote", "source_id": "e7", "note_label": "14"},
    {"aspect_id": "a3", "kind": "search", "query": "限定领域的补充查询"}
  ]
}
```

- kind 限制为允许的动作，不执行模型生成的路径、SQL、任意 URL 或代码。
- source_id 必须属于当前会话且在 scope 内；未知引用忽略并记录，不扩大权限。
- 因果/支持边另存关系类型与证据 ID；reason 是简短可检查理由，不采集自由形式长推理记录。
- enhanced：PLAN-lite → 首轮检索与结构扩展 → SYNTH+CHECK；如不充分，处理其 actions /
  corrective_queries → 合并覆盖 → 在预算内再合成。可用同样的正文＋短 verdict 契约结束纠偏，
  这样无须独立 VERIFY 调用也能记录当前充分性。新增字段解析失败按既有降级行为处理。
- 多层动作可在一次计划后沿结构继续展开；若必须新增一轮语义发现，再由已有自检缺口驱动。
  不为兑现“树”强制每个问题多跑一轮，不承诺所有复杂问题都保持两次调用。
- deep：PLAN/SEA 的 checklist 与 discovered 使用稳定 aspect_id；下一轮动作来自 SEA /
  VERIFY 缺口。保留现有验证链，不能用文本去重结果替代事实核验。
- `verified` 沿用既有对外语义并补明确 provenance；缺省、解析失败、只完成纠偏都不能强制为真。

### token 台账与 20% 目标

每个真实调用记录 `call_id`、request_id、stage、attempt、provider/model、input/output token、
measurement（actual/estimated/unknown）、状态与耗时。只在一个边界累计，helper 读账本而不二次累加。
适配器内部 fallback 也有独立 call_id。超时但费用未知保留 unknown，不能算零后报告低消费。
账本按请求隔离，禁止用全局 mutable counter 混合并发问答。

评测公式：`ratio = sum(new.input + new.output) / sum(old.input + old.output)`，目标 ≤ 1.20。
同一 provider 已把 reasoning 计入 output 时不重复加。缓存命中 token 与费用不是同一指标，
用户选的是 token，不能用折扣价格替代 token 限制。含 unknown 的评测不能宣称严格达标。
运行时预算是绝对上限/估计安全阀，不可用“未知旧版该题消费 × 1.2”实时计算。
在最终回答前预留输出预算；有限输入下优先压缩重复证据与轨迹，不静默取消重要子问题。

## 持久任务状态机与恢复规则

### 建议账本结构

| 记录 | 主键/唯一条件 | 必需内容 |
| --- | --- | --- |
| corpus_generations | generation_id | 处理 fingerprint、embedding fingerprint、索引位置、manifest、状态 |
| corpus_active | 单工作区唯一行 | active generation、发布序号、最后成功版本 |
| corpus_build_jobs | job_id；唯一未完成目标 | 源/目标代次、租约 owner/epoch、阶段、错误、持久时间戳 |
| corpus_build_documents | job_id＋doc_id | 原文 hash、artifact revision、各阶段摘要、重试次数 |
| corpus_build_batches | job/doc/batch | chunk ID 集摘要、embedding 指纹、写入确认 |
| corpus_mutations | operation_id / idempotency_key | 操作类型、持久 payload、顺序、执行状态与结果 |

实际表可合并，但不能用单个 JSON 文件覆写所有任务状态代替事务。派生产物修订和映射记录
可以放 source store 的版本表，外键与 GC 关系要明确。发布记录不得被进度轮询写入覆盖。

建议任务阶段：`queued → preparing → cleaning → indexing → validating → ready → publishing
→ published → draining → complete`。失败可进入 `retry_wait` 或 `parked`，记录 last_stage 以续建。
任务 published 之后发生排队操作失败，不能把 active 代次回退为旧代；分别报告发布与队列状态。
目标格式版本在 published 提交时生效，不必等待所有后续用户操作成功。

### 发布伪代码

```text
claim durable job lease (owner + fencing epoch)
prepare target artifacts and vector resources outside active namespace
checkpoint each validated document/batch
validate complete target manifest and source snapshot
ensure target resources are durable and readable
BEGIN SQLite transaction
  assert job lease epoch still current
  assert active_generation == job.source_generation
  assert target is ready and all required documents validated
  set active_generation = target_generation
  set completed_processing_fingerprint = target_fingerprint
  mark job published
COMMIT
serve new readers from target; existing readers retain old handles
drain durable mutation queue
retire old vector resources only after reader references are released
```

不要在 SQLite 事务中执行长时间解析、embedding 或远程请求。lease heartbeat 更新不代表
工作已完成；陈旧 worker 必须被 fencing epoch 阻止写检查点和发布。

### 断点/并发故障矩阵

| 故障位置 | 恢复动作 | 不能发生的行为 |
| --- | --- | --- |
| 浏览器关闭、轮询超时 | 任务继续，重连返回同一 job ID | 新建第二个全量任务 |
| 抽取文件只写了一半 | 校验不通过，清理目标临时文件并重做该修订 | 将半文件记 artifact_ready |
| embedding 完成但未落盘 | 复用可验证缓存，否则允许重算并记录 | 承诺绝不重复远端收费 |
| upsert 成功、checkpoint 前退出 | 同 ID 幂等重放并核对目标集合 | 生成新 ID 造成重复向量 |
| validating 失败 | 保留旧 active 和已完成断点，有限重试 | 部分成功就发布全库版本 |
| ready 后、事务前退出 | 重验资源和源快照后发布 | 仅凭内存 ready 直接切换 |
| active 提交后、进程刷新前退出 | 启动从 SQLite active 重建句柄 | 从旧 JSON/进度状态回退 active |
| 发布时仍有旧问答 | 旧请求完成旧句柄读取 | 删除其文本/索引或混用新 sources |
| 用户连续点击同步 | 合并同类待执行意图，返回原操作/任务状态 | 重复全库迁移 |
| 租约过期但旧 worker 仍运行 | 新 epoch 接管，旧 worker 的提交被拒 | 两个 worker 同时发布 |
| linked PDF 被外部修改 | 对应修订失效并重新处理，持续变化则 park | 将变更前 hash 与变更后文本绑定 |
| 队列操作已写入、确认前退出 | 按 operation ID 重放，核对副作用 | 重复创建文档或删除错误代次 |
| 旧代清理失败 | 重试清理，active 不变 | 将新库标不可用或删除原 PDF |

外部 linked 文件的 hash 检查无法对任意外部写入者提供原子锁：最好读取稳定快照或读取前后
校验，记录限制。只读快照属于临时处理副本，不移动/覆盖 Zotero 原件，不改变 linked 存储模式。
若源在发布后才变化，由后续同步生成新修订，不回头篡改已发布内容。

### 队列具体语义

- 迁移入口拿到协调权之前已开始的语料写任务，先等待安全边界完成再冻结快照，不能半途捕获。
- 重复同步只合并未执行的等价意图；`incremental=False` 等更强请求不能被弱请求覆盖。
- 删除/移动/上传顺序保留，不能因为 doc_id 相同就全部去重成一个操作。
- 队列执行者通过内部受控路径取得写租约，避免调用公开 API 后把自己再次排入队列。
- 删除原件等已有用户行为沿用原授权与只读约束；本迁移任务本身从不删除原 PDF。
- parked 迁移期间队列保持 queued，返回真实阻塞原因，不向用户报告同步成功；允许现有任务
  查询/重试入口恢复。若需要新增取消并恢复旧版本写入的产品流程，先询问，不偷偷丢队列。
- 旧版二进制可能不认识新 schema/active 机制，不能承诺可直接降级运行；回滚测试以数据快照
  与兼容版本为基础，不指示用户直接切 Git 分支读已迁移数据库。

## API、配置及文件落点交接表

| 范围 | 优先复用的文件 | 可能新增的职责模块 |
| --- | --- | --- |
| 清洗与切片 | `kacore/managers/markdown_extractor.py`、`chunking.py`、`ingest_manager.py` | 清洗块规则、token budget、制品构建器 |
| 证据模型 | `kacore/domain/deep_thinking.py`、`models.py` | evidence view/action、artifact provenance、corpus revision |
| 检索与选择 | `kacore/pipelines/retrieval_orchestrator.py`、`deep_thinking_evidence.py`、`agent_evidence.py` | evidence session、coverage selector、context expansion |
| 编排与 prompt | `enhanced_recall_orchestrator.py`、`deep_thinking_orchestrator.py` 及对应 prompts | 共享动作验证/执行服务 |
| 用量 | `kacore/adapters/llm.py`、`domain/llm_generation.py`、`pipelines/llm_json.py` | 请求级 usage ledger |
| 文本与向量仓储 | `repository/source_store/*`、`repository/vector_store/*` | corpus build repository |
| 任务与同步 | `api.py`、`milvus_build.py`、`zotero_sync_job.py`、`auto_reindex.py`、`pipelines/zotero_sync_pipeline.py` | build coordinator、generation registry |
| 装配与 HTTP | `plugin_initializer.py`、`config.py`、`_conf_schema.json`、`web/server.py` | 优先不新增路由文件或框架 |

- 不预设新的 HTTP URL：先查现有 Ask 结果/历史、任务进度与详情端点。能扩展既有后端响应就
  不新开 endpoint；确需新增时在 TODO 写明 request/response/auth/error 契约并加路由测试。
- trace 要可查询，不能只存在日志或返回后即丢弃的 Python 对象；按已有问答记录机制存储。
  使用明确的 trace schema version；纯失败请求也保留最小诊断记录，避免存储大段重复原文。
- 若新增状态不被前端识别，会导致任务看似消失：必须做最小兼容，不以“不做树 UI”为理由
  留下 queued/recovering 状态显示漏洞。任何前端修改遵守 i18n 与构建同步流程。
- 内部解析器版本不作为用户可编辑选项。实际需要可配的是 token 预算、并发上限等；默认值
  写在 typed config，schema、有效配置输出和可写策略保持同源，不散落字面量。
- 不扩展备份/Notion/LightRAG 的产品功能；只检查它们是否误读 staging 或删除旧引用，必要时
  做兼容过滤。LightRAG 未部署不能成为放弃通用 chunk 身份一致性的理由。

## 可执行验收矩阵

每项必须有行为断言，不写仅检查 dataclass 字段存在的镜像测试。

| ID | 输入/情境 | 必须断言 |
| --- | --- | --- |
| C01 | 正文＋脚注＋下载行＋跨页续句 | 正文连续，脚注可单独读，下载行不进搜索 |
| C02 | 重复章节标题与页眉相似 | 真标题保留，页边噪声移除且有依据 |
| C03 | 不同章都含脚注 14 | 只关联本地正确注释，不跨章串线 |
| C04 | 中文、德语、公式、列表、长表格 | token 预算受控，结构与原文定位仍有效 |
| C05 | 只有脚注的页面 | 全文仍含该页脚注，PDF 页码不漂移 |
| C06 | 新修订重切片 | 旧 ID 不解析为新正文，PDF hash 不变 |
| R01 | 同书三个不同方面＋一篇相关论文 | 多方面保留，不按 book 类型扣分 |
| R02 | 重复 chunk 与含否定的反驳 | 重复降优先级，反驳不会因词汇相似被删除 |
| R03 | 多个子查询并发命中同段 | 文本只存/注入一次，支持多 aspect，结果顺序稳定 |
| R04 | 新轮次相同 query＋新排除集合 | 发起新检索，不能错误复用旧缓存 |
| R05 | scoped 搜索、fallback、排除前 top-k | 不返回错范围/错代/已排除结果，候选不足可见 |
| R06 | 相邻/脚注展开超预算 | 有出处的受控截断，未解决项记录，不无限递归 |
| E01 | enhanced 证据充分 | 常规两次 LLM，存在多层结构关系不增加判断调用 |
| E02 | enhanced 纠偏后重合成失败 | 原答案、原 sources、原 evidence views 一起返回 |
| E03 | deep 多轮发现及 VERIFY | 复用旧证据、可找到新分支，缺口不虚假标充分 |
| E04 | 普通及外部 agent 入口 | 普通排序不变，外部 agent 无新增插件生成调用 |
| U01 | provider actual/estimated/unknown | 分来源记录，未知不记零，账本不跨请求混合 |
| U02 | JSON 重试、adapter fallback、API 兜底 | 每次调用只计一次且没有遗漏 |
| M01 | 旧处理版本首次同步 | 一个持久任务；同步入队；旧库全程可读 |
| M02 | 同版本再次同步 | 不扫描全部 chunk 格式，不再全库重建 |
| M03 | 阶段故障/重启 | 按恢复矩阵继续，已完成工作不重复生成身份 |
| M04 | 任一文档永久失败 | 旧 active 不变，版本未完成，任务 park 不忙循环 |
| M05 | 发布前后并发问答 | 每个答案与引用来自一致快照 |
| M06 | 队列重放与重复点击 | 不重复创建/丢失文档，操作结果可查询 |
| M07 | legacy 预览/相邻读取 | 不再触发隐式重建 |

建议新增测试按职责命名：`test_artifact_provenance.py`、`test_chunk_token_budget.py`、
`test_evidence_session.py`、`test_evidence_selection.py`、`test_usage_ledger.py`、
`test_corpus_build_repository.py`、`test_corpus_generation.py`、`test_corpus_build_recovery.py`。
这些文件目前是计划名称；执行 agent 创建后再加入测试命令。

既有重点回归命令（从仓库根目录执行，环境按项目约定）：

```bash
python -m pytest tests/backend/test_ingest_manager.py tests/backend/test_source_store.py tests/backend/test_sqlite_source_store.py
python -m pytest tests/backend/test_retrieval_orchestrator.py tests/backend/test_retrieval_scope.py tests/backend/test_agent_evidence.py
python -m pytest tests/backend/test_enhanced_recall_orchestrator.py tests/backend/test_deep_thinking_orchestrator.py
python -m pytest tests/backend/test_llm_adapter.py tests/backend/test_citation_rendering.py tests/backend/test_cross_document_attribution.py
python -m pytest tests/backend/test_api.py tests/backend/test_auto_reindex.py tests/backend/test_build_hardening.py tests/backend/test_zotero_sync.py
python -m pytest
ruff check .
mypy
```

有些旧测试要求“读取触发重建”“全量先 clear”“纠偏完成 verified=true”，这是已指出的旧行为，
按新契约替换其断言并说明原因；不能仅删除失败测试。其余引用/范围/降级保护继续保留。
涉及进程重启的关键测试必须使用重新打开的 SQLite/索引或独立进程，不能只重建内存对象假装断电。

## 最终交接产物与完成定义

执行 agent 应留下：

1. TODO 中按 W0–W7 的状态、实际设计偏差与对应技术理由。
2. 新接口/迁移说明，包含升级触发、失败恢复、旧引用和临时空间使用。
3. 全部测试与检查结果；环境缺失和既有失败分别记录。
4. 用户测试指南：如何选同一组问题、导出新旧证据/usage/阶段耗时，如何查任务和恢复。
5. 最小对照导出格式：问题 ID、mode、代码/配置/语料版本、模型、调用数、实际/估算/未知 token、
   延迟、方面覆盖、证据 ID/来源、未解决缺口、错误；不导出密钥和不必要的原始文档全文。
6. CHANGELOG 中只描述已实现且测试验证的行为；真实召回质量和 20% 目标标记“待用户实测”。

完成不等于：写出一张树、增加了更多候选、所有 mock 都返回答案、或迁移任务显示 100%。
完成必须包括：真实生产路径接线、原始 PDF 不变、脚注可追溯、旧库构建期可查、重启续建、
统一发布、来源不串线、目标模式预算可观测，以及上述自动化验收。

## 必须停止并询问的情况

- 必须换解析器/向量数据库、新增付费服务或执行真实语料迁移才能推进。
- 无法在现有解析栈保留脚注/定位，拟改为直接丢弃或大范围 LLM 重写原文。
- 无法实现旧库可读与统一发布，拟改成先清空、逐篇切换或失败文档直接跳过发布。
- 需要改变已经确认的普通模式范围、20% token 目标、原 PDF 保留或无前端树图约束。
- 模型/依赖能力无法满足关键契约，替代方案会实质增加消费或减少功能。

常规模块拆分、合理迁移编号、测试命名、内部 helper 选择不需要重复询问；把判断写入 TODO。
遇到上述阻塞，先完成不依赖该决定的工作，再用“代码证据、影响、具体替代方案”询问用户。

</details>
