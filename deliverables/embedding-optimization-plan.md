# 插件清理、多模态 Embedding 与 KCL AI Hub 兼容性探索计划

日期：2026-10-07。状态：`proposed`，尚未批准实施。

本轮交付研究方案与下一位 agent 的执行指令，不修改业务代码、真实知识库、运行实例、TODO 状态或 CHANGELOG。实现前仍须遵循 `CLAUDE.md` 的 Plan-First；用户明确要求执行本方案后，才进入代码阶段。

## 1. 调查结论与推荐范围

1. **可以进行小范围清理。** 已找到两个无调用的旧 Notion 正文生成函数，以及一个无调用的旧 AstrBot KB 翻译适配器候选。不要把配置兼容、迁移、测试替身或接口空实现一起删掉。
2. **当前 Embedding 是文本契约。** `local`、`external`、`astr` 都实现 `embed_query(str)` / `embed_documents(list[str])`。工厂、缓存、真实维度探针和索引指纹提供了扩展位置，但未找到已实现的 `embed_image`、图片输入类型或多模态索引插槽。
3. **external 必须先补契约校验。** 离线模拟确认它接受缺失/空向量、数量不足、重复 index、NaN 和运行中维度漂移。扩展更多模型前，应先封住这些入口。
4. **KCL 文本接入具有条件兼容基础，图片接入尚未证实。** 用户提供的官方文档摘录明确其使用 LiteLLM，且提供 `arc:embedvl`（底层 `Qwen/Qwen3-VL-Embedding-2B`）。具体 API base、请求路径、图片 payload 与批量约束尚未提供，也没有进行带凭据联调。不能据此声称已经兼容 KCL 图文 Embeddings。
5. **推荐采用独立的多模态旁路。** 现有文本模型、缓存、Milvus collection 与 LightRAG 保持原有路径；新增多模态配置、缓存与索引默认关闭。这样可以逐步补建图像索引，避免升级插件即触发全库重建。

“能用多模态模型处理文本”与“能检索 PDF 图片/图表”是两个验收层次。以下方案包含完整图文能力的设计，但将其分阶段交付。首个目标确定为 KCL 的 `arc:embedvl`；用户尚未明确是否要求完整 PDF 图文检索，因此 Phase 4 单列范围。在代理协议未核实时，不实现凭空猜测的通用图片请求格式。

## 2. 当前状态与代码证据

当前分支为 `developer`，调查时 HEAD 为 `cf04a02`。工作树已有上一轮 Notion 改动，包括已修改和未跟踪文件；后续 agent 必须以当前工作树为基线，重新查看 diff，不能 reset、checkout 或覆盖它们。

| 范围 | 文件 / 位置 | 已确认事实 |
| --- | --- | --- |
| 文本接口 | `kacore/repository/embedding/base.py` | 只有文本嵌入；identity 默认空 dict，旨在保持旧缓存/指纹兼容 |
| 外部 HTTP | `kacore/repository/embedding/external.py` | `Bearer KR_EMBEDDING_API_KEY`；请求 `input` + `model`；URL 直接追加 `/embeddings` |
| 后端选择 | `kacore/repository/embedding/factory.py` | 支持 local / external / astr，统一套 CachedEmbeddingProvider |
| 缓存 | `kacore/repository/embedding/cached.py` | 旧 key 为 namespace + NUL + text 的 SHA-256；文档缓存、query 穿透 |
| 配置 | `kacore/config.py` / `_conf_schema.json` | 顶层 embedding；旧 vector_db / graph embedding 键仍可回退 |
| 装配 | `kacore/plugin_initializer.py` | 先调用真实文本探针，再按实测维度装配 Milvus / LightRAG |
| 索引保护 | `kacore/index_compatibility.py` | 主 embedding 模型/地址/维度变化会判旧索引不兼容 |
| 连通性探针 | `kacore/api.py::test_embedding_connection` | 临时 external provider，仅测试 `ping` 单条文本，返回 status / dimension / model |
| HTTP 端口 | `web/server.py::handle_test_embedding` | `POST /api/config/test-embedding`；参数 base_url / model_name |
| 前端 | `web/frontend/components/flow/QuickConfigPanel.tsx` | external 有 model / base_url；astr 被落入 local 提示分支，缺专用 ID 配置 |
| 前端测试按钮 | `web/frontend/lib/api.ts::testEmbeddingConnection` | 客户端函数已存在，源码搜索未找到组件调用 |
| 文档摄入 | `kacore/managers/markdown_extractor.py` / `ingest_manager.py` | clean.md、页面偏移、脚注等制品；未建立可索引的图片资产清单 |
| 图片数据模型 | `kacore/domain/models.py` | DocumentChunk 是文本块，metadata 可扩展，但没有图片资产领域模型 |
| 图谱 | `kacore/lightrag_core.py::LightRAGEmbeddingAdapter` | 对文本调用 embed_documents；不能直接注入图片内容 |

### 2.1 external 的已复现问题

以下结果通过 fake aiohttp 响应在本地复现，没有调用真实服务：

| 输入/响应 | 当前行为 | 建议行为 |
| --- | --- | --- |
| base_url 以 `/v1/embeddings` 结尾 | 请求 `/v1/embeddings/embeddings` | 规范化一次或配置明确的请求路径 |
| data 元素没有 embedding | 返回 `[None]` | 拒绝契约错误 |
| embedding 是空数组 | 返回 `[[]]` | 拒绝；探针不得显示成功维度 0 |
| 两条输入只返回一条向量 | provider 接受 | 在 provider 层拒绝，不依赖下游缓存兜底 |
| 两个元素使用相同 index | 排序后接受 | 检查唯一性、范围、完整覆盖 |
| 向量含 NaN | 接受 | 拒绝非有限值 |
| 首次维度 3，后续维度 4 | 动态改成 4 | 首次有效结果锁定，随后拒绝漂移 |

`external.py` 关于“剥离 /embeddings 或 /v1”的注释与实现不符：实际只剥离末尾斜杠。不能通过删除 `/v1` 修复，版本前缀可能是必要路径。

缓存也需验证冷启动边界：它在调用 inner 前读取 expected_dim，未知模型若第一次直接进入 embed_documents 而未先做 query 探针，可能使用旧估计维度拒绝真实响应。正常组合根启动已有探针，修复必须保留这一流程，避免把正常启动误报为故障。

### 2.2 清理候选与禁止误删项

| 项目 | 证据与决策 |
| --- | --- |
| `notion_schema.py::chunk_preview_blocks` | 源码搜索仅定义与 __all__；现 Articles 禁止程序生成正文。确认无动态外部引用后删除函数、导出和仅为它服务的类型 import |
| `notion_schema.py::large_file_callout_block` | 同上；上一轮已移除 Articles 大文件正文提示的写入路径 |
| `kacore/adapters/astrbot_kb.py::to_document_chunk` | 未找到实际调用；生产 `kb_reader/astrbot.py` 已按真实返回字段自己翻译。可删除旧模块并修正 reader 中过期 docstring，但删除前再查动态 import 与公开文档 |
| local / external 常见维度字典 | 有重复模型条目；可提成 embedding 内部小模块，但必须保留各自默认值与查询前缀行为，不宜为几行重复扩大范围 |
| `source_store/processing.py` | **保留**：SQLite 中通过相对 import 调用 commit_processing，静态“无绝对 import”是误报 |
| `kacore/main.py` | **保留**：生命周期测试依赖它，发布树已排除；不是生产重复入口可直接删除 |
| `kacore/log_capture.py::install` | **保留**：多处以 import alias 调用，按函数名出现次数判断会误报 |
| `migrations/runner.py` | **保留**：兼容导入 shim；收益极小，没有必要破坏外部调用 |
| embedding 旧配置回退 | **保留**：用户要求现有库继续运行；有配置优先级测试 |
| 旧 Notion 摘要识别 / 已有正文保护 | **保留**：已存页面仍可能有旧程序摘要；不能因生成函数删除而删除识别器 |
| 各层 base 空实现、memory/noop | **保留**：接口契约、可选能力与测试替身 |
| `testEmbeddingConnection` | **优先接线**：它对应本任务需要的连接检查，不能因当前组件未引用就删掉 |

`api.py` 当前约 6167 行，其他多份文件超过 600 行，TODO 已有拆分登记。本轮只抽出直接涉及 embedding 的新增逻辑；不进行全仓搬迁或 Notion 大重构。

## 3. KCL AI Hub 核验报告

### 3.1 已证实与尚未证实

官方公开入口：[King's ARC AI Hub](https://docs.er.kcl.ac.uk/CREATE/ai_hub/)。其说明确认平台位于 ai.create.kcl.ac.uk，提供 OpenAI 兼容 API，并指向站内技术文档。

用户提供：[Getting started](https://ai.create.kcl.ac.uk/docs/getting-started)。本轮匿名 curl 跟随跳转后实际得到 Microsoft 学校登录页；这只说明文档访问需要登录，不代表 API 调用必须走浏览器 SSO。

用户随后提供了文档正文，已补齐以下信息（来源为本轮用户提供的官方文档摘录）：

| 项目 | 已确认内容 | 对本插件的影响 |
| --- | --- | --- |
| 代理 | ARC-AI API 使用 LiteLLM proxy，API key 认证 | 现 external 的 OpenAI 风格请求可作为文本接入起点 |
| Embedding 模型别名 | `arc:embedvl` | 调用代理时使用这个别名，不默认填底层 HuggingFace ID |
| 底层模型 | `Qwen/Qwen3-VL-Embedding-2B`，FP16，2B | 多模态扩展可收敛到这个模型 |
| 上下文 | 32,768 | 这是 token 上限信息，不是 embedding dimension；实际服务上限仍需核实 |
| Reranker 别名 | `arc:rerankvl` | 独立 rerank 模型，不产生 embedding；本轮不增加 reranker 改造范围 |
| key 网络范围 | 默认 internal-only；另有 public internet key，可附加 IP/CIDR 限制 | 外部部署使用允许公网的 key，内部 key 按学校网络/VPN 条件使用；401/403 不应靠重复请求解决 |
| 限流/预算 | key 有各自限制，免费模型也计入限流 | 验证 key 与账号限制，不能因免费而取消请求预算 |

摘录的费用说明只明确几种生成模型；不据此单独保证 embedding 的价格或 SLA。

尚缺以下协议证据：

- 真正的 API base URL 与 Embeddings 请求路径，不能直接假定网站域名加 `/v1`。
- `arc:embedvl` 的实际调用权限、维度和 token/batch 上限。
- LiteLLM 的标准 Bearer API key 约定在 KCL 前置网关是否有额外请求头或路径要求。
- 响应是否包含 `data[].index` 与浮点数组；是否需要 input_type / task 等字段。
- 该模型是否接受图片；接受方式是 URL、data URI、上传文件还是专用请求结构。

### 3.2 当前适配器的兼容条件

若 KCL 满足下面的契约，现有 external 的正常文本路径原则上可接入：

```text
POST <配置的 base_url>/embeddings
Authorization: Bearer <环境变量 KR_EMBEDDING_API_KEY>
Content-Type: application/json

{"model": "arc:embedvl", "input": ["ping"]}

HTTP 200
{"data": [{"index": 0, "embedding": [0.1, 0.2, ...]}]}
```

上面是**插件当前契约结合已知 KCL 模型别名的待验证请求**，不是已经读到的 KCL 请求示例。当前 `arc:embedvl` 不会触发 text-embedding-3 子串分支，因而不会误发 dimensions。还需核实上游是否自动补 Qwen 所需模板/指令；HTTP 成功不足以证明检索语义正确。

初步配置模板仅在协议核实后使用：

```json
{
  "embedding": {
    "provider": "external",
    "model": "arc:embedvl",
    "base_url": "<文档声明的 API base，不含最终 embeddings 路径>"
  }
}
```

密钥沿用环境变量；不要写进配置、研究文档、日志或浏览工具输入。

### 3.3 下一位 agent 的验证顺序

1. 基于已提供摘录，只补 actual API base、Embeddings 调用示例、批量和图片协议；不要重新要求用户确认已知模型或粘贴密钥。
2. 用 fake HTTP fixture 验证确切请求路径、header、payload、响应解析、错误处理。
3. 如需真实验证，在用户允许使用其账号/API 后，以环境变量中的 key 调用一个合成 `ping`；不上传真实论文。不自动重建、切换当前配置或标记旧索引兼容。
4. 验证至少一次两条文本批量；单条 `ping` 成功不足以证明文档摄入兼容。记录实际维度、请求数量与耗时。
5. 若要证明与现有索引兼容，再用临时 SQLite / Milvus 数据和合成文本验证完整链路；不得在已有索引上试写其他模型。
6. 输出明确状态：`verified`（明确注明文本/图片与模型范围）、`conditional`（协议已核实，实测未做）、`unverified`（文档/权限未就绪）、`unsupported`（明确缺端点/模型或协议不满足）。

KCL 若符合 OpenAI Embeddings，无需新增名为 kcl 的 provider。只有真实存在协议差异时才引入命名协议适配器，避免服务名分支增殖。

### 3.4 Qwen 多模态输入与代理兼容缺口

Qwen 官方模型卡确认该模型将文本、图片与组合输入映射到共享向量空间，2B 模型最大向量维度为 2048，并支持配置较小输出维度；因此维度必须实测，不能沿用未知 external 模型的默认 1536。[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)

vLLM 官方在线示例使用 `/embeddings` 的 Chat Embeddings 扩展：请求体是 `messages`，包含 system 指令、user 的 text/image_url 内容和空 assistant 消息；示例还设置 `encoding_format=float`、`continue_final_message=true` 与 `add_special_tokens=true`。这与当前插件的 `input: list[str]` 请求不同。[vLLM 官方在线图像 Embedding 示例](https://docs.vllm.ai/en/stable/examples/pooling/embed/)

**推断：**若 KCL 上游按这一 vLLM 扩展提供图片嵌入，当前 external 不能直接调用完整能力；需要明确的 chat-embedding 协议序列化。尚未确认 KCL 使用何种上游，也未确认 LiteLLM 是否透传这些扩展字段，不能直接把 vLLM 示例当成学校服务契约。

下一位 agent 应分别核实四种情况：标准 `input` 文本、带 `messages` 的文本、纯图片、文本+图片。若 KCL 只开放标准文本输入，则报告 `arc:embedvl` 文本可用、图片未开放/未证实；不在客户端自行拼造模型私有 token 来绕过代理。

模型指令/模板、输出维度、图片预处理都进入新旁路指纹。KCL 必须使用代理 alias；不能为了调用扩展而未经用户指示绕过代理直连上游。LiteLLM 本身的 Embeddings 文档支持标准接口及部分服务专属参数，但不能证明 KCL 部署的版本与配置支持此模型的图片扩展。[LiteLLM 官方 Embeddings 文档](https://docs.litellm.ai/docs/embedding/supported_embedding)

## 4. 实施不变量

- 不修改旧 clean.md、页偏移、chunk ID、content hash；不为新增图片触发文本全量重处理。
- 新功能默认关闭时，旧配置、主 embedding 指纹和旧缓存 key 必须逐字节保持一致。
- 主文本模型切换意味着向量空间变化，即使维度相同也不能复用旧索引；仍走既有重启/重建流程。
- 不截断、补零或静默降级向量来伪装维度兼容。
- 多模态模型独立配置，建立独立缓存与向量 collection，不混入旧 Milvus 或 LightRAG。
- 多模态失败时旧文本路径继续工作；新能力的失败需要可见，不能展示成完整成功。
- schema 演进只追加新编号迁移；不改旧 SQL、不批量抹旧库、不删除迁移记录。
- 本地模型依赖仍可选、懒加载。首轮优先一个有明确协议的远端多模态模型；不默认给纯 API 用户安装 torch/视觉模型。
- 生命周期资源由组合根装配与关闭。复用 AstrBot 时不 terminate、不关闭宿主拥有的 client。
- 真实库、宿主配置、Notion/R2/Zotero 远端和 Git 远端不包含在本方案的代码授权中。

## 5. 按 Phase 执行

### Phase 0 — 固定基线、确认模型协议

动作：

1. 依次阅读 CLAUDE、ARCHITECTURE、CONVENTIONS、TODO，再读对应测试。
2. 记录 git status、分支、HEAD 和用户已有 diff；保留新加的 Notion 文件。
3. 首轮模型锁定 KCL `arc:embedvl` / Qwen3-VL-Embedding-2B，获取其 Embeddings base/path 和文本/图片输入规范。未拿到信息时，继续 Phase 1 和通用 HTTP 校验，不猜协议。
4. 明确交付目标：模型文本分支兼容，或包含 PDF 图片/图表检索。若仅要求前者，可停止在 Phase 3 的文本适配验收；不能称已完成完整图文检索。
5. 将批准范围新增到 TODO 顶部，保留 completed 段落内部技术细节。

理由：当前工作树不是干净 HEAD；服务协议与“多模态”的实际范围影响实现和验证。

验收：有基线记录、协议矩阵、可执行范围和未决项；尚未运行真实库迁移/重建。

### Phase 1 — 删除已证明无用的代码

动作：

1. 对 2.2 的三个删除候选，检查静态 import、别名、相对 import、动态加载、__all__、测试、文档和发布清单。
2. 删除确认无用的函数/模块与相应导出、仅为它们存在的 import；修正 reader 的陈旧说明。
3. 运行 Notion 正文保护、QA 正文写入、KB reader 和发布树测试；不改实际 Notion 行为。
4. 维度映射去重仅在能保留既有结果时实施；不要新增大型共享 registry。

理由：清理必须有调用证据；现有数据的兼容代码与无效生成代码性质不同。

验收：删除清单包含每项证据；已有 Articles 正文保护与 QA 正文功能不变；受影响测试通过。没有为删几段代码增加重复断言测试。

### Phase 2 — external 文本协议加固与 KCL 接入核验

主要位置：external.py、embedding 内部小型 protocol / validation 模块、cached.py、配置、API 探针、相关测试。

动作：

1. 明确 URL 语义：兼容 base 末尾斜杠与完整 embeddings 端点；保留已有版本/代理前缀，不自动追加 `/v1`。若 KCL 有特别路径，用已验证的协议或显式 endpoint_path；默认行为保持旧正常配置一致。
2. 将纯向量校验提到 embedding 内部模块：数量、非空、数值类型（bool 不视作数值）、有限性、整批一致维度。AstrBot 可以复用，但保持它自己的错误类型、stage、中文提示和脱敏契约。
3. 验证 data 是列表、index 是合法整数、唯一且完整覆盖输入；按 index 归位。标准协议缺 index 时应给明确错误；只有被确认的非标准协议才规定顺序兜底。
4. 区分预估维度与首次实测锁定维度；首次有效响应确定维度，后续漂移拒绝，不能每次覆写。不要把预估 1536 当作所有未知模型的强制真实维度。
5. 缓存前完整验证批次。未知维度按探针或首次完整批次建立；混合缓存命中与新结果遇维度变化时整批失败，不返回混合向量或部分结果。
6. 如协议确有需要，加显式的 dimensions / task 或 query/document input_type；默认不新增未经支持的字段，避免 text-embedding-3 子串判断带来的误发送。对 `arc:embedvl` 检查模板/指令由谁负责；不自动套 e5 query/passage 前缀。
7. 根据 KCL 批量上限做有界分批，保留输入顺序。处理 429 / 503 / 网络瞬断，遵守有上限的 Retry-After；400/401/403/协议错误快速失败。检查 API 外层索引重试，避免双层重试产生无界请求。
8. 非 JSON 或登录页响应给可读的阶段错误；只输出状态、错误类别与经处理的 request ID，不打印完整响应正文、认证重定向 query 或原始异常链。
9. 升级已有连接探针：保留原响应字段，增加可选协议/批量检查；不写缓存、不动运行配置、不使索引失效。前端应区分请求成功与文本/图片能力。

理由：现有探针和文档嵌入都依赖 external 正常返回，但当前 provider 边界过宽，尤其不适合直接接入未知模型。

验收：表 2.1 的问题都有失败回归；正常 OpenAI 风格批量按顺序返回；旧 local/external 指纹与缓存仍兼容；KCL 报告给出真实验证等级。

### Phase 3 — 添加多模态输入契约、能力声明与独立缓存

建议新增位置（命名可调整，保持分层）：

- `kacore/domain/embedding.py`：纯数据的 EmbeddingInput / ImageReference / 能力对象。
- `kacore/repository/embedding/base.py`：保留现有文本接口；增加可选的多模态接口或独立子接口。
- `kacore/repository/embedding/vllm_chat.py`：候选 Chat Embeddings 适配器；仅在 KCL 证实采用/透传此协议后启用；若代理使用其他协议，按实际协议命名。
- `kacore/repository/embedding/multimodal_cached.py`：独立输入缓存。
- `kacore/config.py` / `_conf_schema.json`：`multimodal_embedding` 配置与默认关闭状态。

动作：

1. 定义输入语义：纯文本、纯图片、文本+图片；document/query 角色明确；返回每个逻辑输入一条向量，不能将一张图片多条内部结果误作多份输入。以 `arc:embedvl` 为首轮实现，rerankvl 不在此接口内。
2. 声明支持的模态、组合输入、角色、批量约束及共享向量空间身份；图片不支持时明确报 unsupported，不能悄悄只嵌入文字。
3. 现有 provider 不增加强制的新 abstract method。缓存装饰器需要明确透传能力；不要假定套上 Cached 后仍能自动调用新方法。
4. 不给 `astr` 伪造图片能力：当前宿主公开 get_embedding/get_embeddings 是文本接口；只有经新宿主契约核实后才支持图片。
5. 新缓存 key 包含非机密 provider/model/revision、实测维度、模态、document/query 角色、任务/归一化参数、图片内容哈希及预处理版本。使用有界文件流计算图片 hash，不以绝对路径或图片 URL 充当内容身份。
6. 文本+图片以两者身份组合产生 key；同路径图片内容变化必须失效；原文本缓存仍使用原有 key。
7. query 与 document 编码格式若不同，应分别缓存和配置；不能只因为文字相同而共用角色不同的结果。
8. 先验证该多模态模型的文本分支能作为现有文本接口的实现；若用户主动将它选作主模型，仍明确要求重新建索引。
9. 若采用 vLLM Chat Embeddings，一份 messages conversation 表示一个逻辑输入，不能将批量文档拼成一个长对话；若代理不支持真正的批量，则以有界并发独立请求、按原索引归位，并遵守 key 限流。

理由：模型支持图片不等于现有文本 payload 能表达图片；能力、输入与缓存必须一起成立。

验收：旧文本 provider/mocks 继续满足原契约；首个指定模型完成 text/image/combined 支持范围测试；默认关闭时不创建新资源或触发旧库重建。若图片协议仍未知，本 Phase 只能标接口准备完成，不能标模型兼容完成。

### Phase 4 — 独立图片资产与向量索引，完成图文检索

本 Phase 适用于需要检索 PDF 图片/图表的范围。

建议新增位置：domain 的 DocumentAsset、repository 下独立 asset_store / multimodal index 实现、managers 下 image_extraction / multimodal_index_manager；新增模块控制在 400 行以内。

动作：

1. 以现有 original.pdf 为只读输入，提取图片资产或渲染必要页面，写入独立资产目录与清单。图表可能由 PDF 矢量元素组成，单纯提取内嵌位图不能证明图表可检索；首轮应明确页面渲染或图表区域策略。
2. 默认不修改 PDF→clean.md 抽取参数，不改变旧文本页偏移和切片。caption 只作为图片资产的附加文本，不覆盖旧 chunk 正文。
3. 新 asset ID 与 doc_id、page、区域/提取策略、内容 hash 稳定关联；bbox 坐标系统和页码起点写入契约。扫描/OCR 作为另外的能力声明，不默认为已实现。
4. 追加新编号迁移，建议新建 document_assets 与独立 indexing 状态。默认关闭时新表为空，不给旧文档添加主文本 needs_reindex。分批补建必须支持重试与幂等。
5. 使用独立 Milvus collection 与独立指纹；多模态模型的文本 query 只检索它自己的图像/组合向量。不要拿原 e5 文本向量去搜索其他模型的图片向量，即使维度相同。
6. 图文结果在检索编排层融合排序：文本结果仍来自旧链路，图片结果按 rank 融合或独立展示，不直接比较两个向量空间的原始分数。
7. 图片证据返回 asset_id/doc_id/page/bbox/caption/source；检索命中只证明相似性，不能自动编造图表结论。LLM 是否能看图应单独声明；纯文本 LLM 只能使用明确的 caption/既有文字。
8. 默认 fulltext、LightRAG 实体关系抽取继续处理文本；不要把 base64/图片 URL 写入图谱正文。
9. 新能力遵循已有文档访问范围、allowed_doc_ids、集合多归属、Zotero 只读与 detached 过滤；资产下载使用现有鉴权。删除/脱管及 R2 恢复后需有资产/索引清理或重建语义。
10. 图片提取或嵌入失败不影响已完成的文本入库；新增状态可重试。关闭功能后旧文本检索继续工作；不自动清空旁路资产。

理由：只改 provider 工厂不可能打通摄入、资产持久化、索引、检索和引用闭环。

验收：用临时库和小型合成 PDF 测 text→image 检索、页码回链和失败恢复；旧库升级后文本数据与指纹不变；图片补建失败不阻断文本检索。

### Phase 5 — 配置、诊断、前端接线

动作：

1. 配置 getter、public dict、diagnostics、CONFIG_KEY_POLICY、API 校验、工厂和 UI 同步，避免只有后端字段没有入口。
2. 主 embedding 的 REBUILD 行为保留；新多模态模型/预处理变化只使其独立索引失效。现有 `update_config_value` 对 REBUILD 统一调用 `_invalidate_embedding_indexes`，必须改为可区分目标的失效路由，不能直接复用而误伤主 Milvus/LightRAG。
3. 重启行为按 provider 生命周期处理；纯 batch/timeout 设置不应改变向量指纹。多模态 enabled 的切换也不能直接复用主 embedding 全失效逻辑。
4. 修复 Flow 快配 astr 分支，显示 astrbot_provider_id 与宿主托管提示；不要要求填写被忽略的本地 model/base_url。
5. 将现有 testEmbeddingConnection 接到 external 配置附近；显示成功维度、测试范围、失败阶段。图片能力只在实际验证/明确声明时显示。
6. 运行态面板轮询只读取已有状态，不发网络、不加载视觉模型；多模态失败与旧文本运行状态分别可见。
7. 新字段加中英 i18n；同步更新前端 mocks 中缺失的 astr 信息，移除误导性的可编辑 embedding.api_key 假字段。
8. 修改前端前读 web/frontend/AGENTS.md 及对应 Next 16.2.6 本地文档；产物仅通过 build + sync 脚本生成，不能手改 pages。

理由：配置与失效动作决定旧库是否被误重建；可观察性需要准确体现支持范围。

验收：主文本与多模态配置能够分别保存/测试/诊断；保存相同值不重复失效；旧库查询不中断；UI 不把文本探针当作完整图文验证。

### Phase 6 — 回归、文档与交付

动作：

1. 跑改动相关测试，完成全量回归与静态检查；把已有环境失败与新增失败分开记录。
2. 有前端改动时执行 tsc、lint、build 和 sync，核对 out / pages 一致。
3. 文档写明删除证据、支持模型/协议/输入范围、KCL 实测等级、默认关闭策略、主模型切换与旁路模型切换的不同重建范围。
4. 只在相关测试实际通过后勾 TODO；收尾追加 CHANGELOG。未做的真实 KCL/PDF 验收保留未完成状态。
5. 交付当前 diff、验证记录、未决项和回滚说明。不自动 bump 版本、commit、push、tag、PR 或 Release。

验收：代码、测试、配置/UI、文档闭环；没有以 mock 成功代替真实服务兼容结论。

## 6. 核心改动理由与边界

| 需改位置 | 必要理由 | 限制 |
| --- | --- | --- |
| embedding/base.py | 表达可选多模态契约与能力 | 不破坏已有文本 abstract 契约 |
| config.py / schema | 类型化新配置与默认关闭 | 旧 getter 优先级和默认值保持 |
| plugin_initializer.py | 创建/释放独立 provider、cache、index | 只接线，不塞图片业务算法 |
| index_compatibility.py 或独立旁路兼容模块 | 区分两个向量空间的指纹 | 旧指纹序列化完全不变 |
| API 配置失效路由 | 避免旁路 REBUILD 导致旧主索引失效 | 保留原公开 API，新增逻辑放小模块 |
| source_store/base 或新 asset_store/base | 图片资产和状态的持久化契约 | 优先独立仓储，SQLite 事务由拥有连接的实现负责 |
| retrieval orchestrator | 统一可选图片检索与证据映射 | 默认关闭时原排序/结果不变 |

优先抽小模块，不把新业务继续叠到 api.py、source_store/sqlite.py 或 chunking.py。若扩展仓储/向量库 base，memory 与生产实现必须一起改并做接口对换验证。

## 7. 测试矩阵与命令

| 组别 | 必须证明的行为 |
| --- | --- |
| external HTTP | URL、认证、payload、批量顺序、缺项/重复 index、NaN/Inf/bool、空向量、维度漂移、非 JSON、429/401/503、超时与请求预算 |
| 缓存 | 旧命中继续有效、未知维度冷启动、部分命中整批一致、内容重复输入顺序、多模态 hash/角色/版本隔离、失败不写缓存 |
| 索引 | local/external 历史 golden 指纹不变、astr 热重载与维度保护、不同空间不混写、旁路失效不影响主索引 |
| 摄入 | 旧 chunk/page offset 不变、资产清单幂等、矢量图表/位图范围声明、图片失败不阻断文本、Zotero 与本地上传一致 |
| 检索与访问 | 关闭时旧结果不变、两空间独立 query、融合可追溯、页码定位、跨集合/权限/detached 过滤、LLM 看图能力声明 |
| 升级 | 复制测试库再升级，document/chunk/page 数据与主指纹不变；新表空、新旁路按需补建；未写真实库 |
| 生命周期 | 关闭自有资源、保留 AstrBot 资源、并发加载与超时降级、轮询不加载、不发请求 |
| 清理回归 | KB reader、Articles 正文保护、QA 写入与发布树保持正确 |

本环境 shell 没有 `python` 命令，但 `.venv/bin/python` 可用。命令以下用它示意，执行 agent 先检查环境：

```bash
.venv/bin/python -m pytest tests/backend/test_embedding.py tests/backend/test_astrbot_embedding.py tests/backend/test_astrbot_embedding_wiring.py tests/backend/test_index_compatibility.py tests/backend/test_config.py
.venv/bin/python -m pytest tests/backend/test_processing_recovery.py tests/backend/test_ingest_manager.py tests/backend/test_vector_store.py tests/backend/test_lightrag_core.py tests/backend/test_retrieval_orchestrator.py tests/backend/test_notion_target.py tests/backend/test_published_tree.py
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
```

新增 meaningful 测试建议分成 `test_external_embedding_protocol.py`、`test_multimodal_embedding.py`、`test_multimodal_index.py` 与升级兼容测试，避免继续堆进原 embedding 测试文件。

前端命令，工作目录 `web/frontend`：

```bash
npx tsc --noEmit --incremental false
npm run lint
npm run build
```

随后回仓库根执行 `.venv/bin/python tools/sync_frontend.py`。

### 7.1 本轮实际验证范围

- 配置、索引指纹、AstrBot 适配三份测试：**79 passed**。执行命令使用 PYTHONDONTWRITEBYTECODE=1、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，显式加载 pytest_asyncio.plugin，禁用 pytest cacheprovider。
- external 异常响应/URL/维度漂移：独立 fake aiohttp 离线脚本复现，不是新增到仓库的测试。
- 包含缓存/SQLite 的测试执行在 aiosqlite 连接 worker 与 asyncio 等待处停滞，已中止；faulthandler 留下线程栈。尚未确定停滞根因，不将这些套件记为通过，也不在本轮顺带修改数据库代码。
- 本环境未安装 torch / sentence_transformers。历史 TODO 记录过两项 embedding 测试因缺 torch 失败；后续实际结果须重新记录，不能照抄历史绿灯或直接永久跳过。另尝试非缓存 local 测试，只输出部分进度后中止，未得到完整结论。
- 未测试真实 KCL Embeddings、未上传图片、未改真实库、未运行前端构建。

## 8. 交付顺序、风险与停止条件

建议每个 Phase 独立可审查，按 `0 → 1 → 2 → 3 → 4 → 5 → 6` 执行；Phase 5 中 astr 快配与文本连接按钮可提前接在 Phase 2。需要协议的适配部分在契约确认前不落地。

高优先级：external 校验、缓存/指纹兼容、目标模型协议、配置失效范围。低优先级：全仓大文件拆分、引入多种本地视觉模型、视频/音频支持。

停止或降范围条件：

- 已确认 KCL 模型目录有 arc:embedvl，但实际调用协议/权限未核实：完成现有 provider 加固并保留未验证状态，不编造端点。
- 模型不提供共享图文向量空间：不能承诺跨模态检索；分别索引只能作为另一个明确设计。
- UI/HTTP 探针正常、真实模型未测：状态保持 conditional，不写 verified。
- 默认关闭时旧 fingerprint/cache key 或正文/页偏移有变化：视为兼容回归，先修再继续。
- 老库自动索引策略可能被新设置误触发：先修目标化失效/调度，不让真实库承担验证。

代码回滚可回退单个 Phase 的改动；数据库只使用追加迁移并保持向后兼容，不通过删除新迁移记录回滚。主模型没有切换时旧索引应一直可用；用户主动换主模型产生的新索引需按原方案重建，不能在模型回滚时盲目标记兼容。

## 9. 需要补齐的信息

1. KCL 文档中的实际 API base、Embeddings 端点、批量及图片请求示例，不含密钥；模型 ID 已知为 arc:embedvl。
2. 是否要求 PDF 图片/图表检索；首个多模态目标已确定为 KCL 的 Qwen3-VL-Embedding-2B。
3. 若需要真实验收，允许使用的测试账号/环境与环境变量注入方式；本轮未要求提供密钥。

前两项不影响小范围清理与通用 HTTP 校验的实施；会影响真实 KCL 判定和多模态适配器完成条件。
