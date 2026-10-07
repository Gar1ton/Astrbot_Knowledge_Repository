# 下一位 agent 的任务指令

下面的代码块可直接复制给下一个 agent。详细方案见同目录 `embedding-optimization-plan.md`。

本指令本身不是用户对实施的批准。用户若明确说“按这份计划执行”，可视为代码实施授权；若只是要求你继续评估，应保持只读，提交修订方案。

```text
工作区：/home/gar1ton/DEV-WORKSPACE/projects/Astrbot_KAPlugin

任务：按 deliverables/embedding-optimization-plan.md 优化 AstrBot Knowledge Arch：
1. 删除有调用证据支持的冗余代码；
2. 在现有文本知识库继续运行的前提下，兼容一个有明确协议的多模态 embedding 模型；
3. 检查 KCL AI Hub embedding API，给出分级且有证据的兼容报告。

先读 CLAUDE.md，按 ARCHITECTURE → CONVENTIONS → TODO 的顺序加载规范，再读完整方案、相关测试与当前实现。
确认本轮用户已明确批准代码实施；若未批准，先做只读核验，交付具体修订计划，遵循 Plan-First。
获批准后，先在 TODO 顶部登记未完成 Phase，再逐阶段修改/验证；测试通过后才勾完成；最后追加 CHANGELOG。

基线与边界：
- 上一位 agent 调查时在 developer，HEAD cf04a02；当前工作树已有 Notion 的修改和新增文件。
- 重新检查 git status/diff，基线以当前工作树为准。不要 reset/checkout/覆盖用户改动。
- 不碰真实知识库、运行实例或宿主配置；不写真实 Notion/R2/Zotero，不做远端 Git 操作。
- pages 只通过前端 build + tools/sync_frontend.py 生成，不手改。
- completed TODO 内部细节保持不变；只在新计划中记录本次工作。

实施顺序：
Phase 0：固定基线，补齐 KCL 的 arc:embedvl 调用协议，确定文本模型兼容还是完整图文检索范围。
Phase 1：清理已证实无调用代码：
  notion_schema.chunk_preview_blocks、large_file_callout_block；
  adapters/astrbot_kb.py 的旧 to_document_chunk 模块（删除前再次查动态/公开引用）。
  同步去掉失效 export/import，修正文档；保留旧摘要识别与 QA 正文函数。
Phase 2：加固 external：URL、index/数量、非空有限数值、首测锁定维度、批量上限、有界重试、错误脱敏；
  修复缓存冷启动/部分命中边界，升级独立连接探针，核实 KCL 协议。
Phase 3：增加可选多模态输入/能力契约、arc:embedvl 已核实协议的适配器与独立缓存；旧文本 ABC 不强加新 abstract method。
Phase 4：若范围包含 PDF 图文检索，增加独立图片资产、追加迁移、独立向量 collection、检索融合与页码引用。
  对矢量图表明确页面渲染/区域策略，不仅提内嵌位图就宣称支持全部图表。
Phase 5：配置/schema/API/UI/诊断同步；修 astr 快配；接上已有 testEmbeddingConnection。
  新多模态 REBUILD 只失效旁路索引，不可误触发原 API 的主 Milvus/LightRAG 全失效分支。
Phase 6：完整回归、前端构建同步（如改前端）、文档、TODO 和 CHANGELOG 闭环。

必须保留的不变量：
- 新功能默认关闭；旧 local/external 指纹和文本缓存 key 逐字节不变；astr 热重载/维度保护不退化。
- 不改变现有 clean.md、chunk ID/hash、页偏移；旁路补建不触发主文本全量重处理。
- 主文本 embedding 模型切换仍须重建，即使新旧维度相同；不可混合不同向量空间。
- 多模态独立配置/缓存/索引；其失败不阻断原文本入库与检索。
- 新能力开启后的 query 使用多模态模型自身文本 query 向量，不用旧 e5 query 搜其他模型图片。
- 图片命中不等于 LLM 能看图；返回可追溯页码/资产/文字证据，禁止自动编造图片结论。
- 旧配置 fallback、migrations/runner.py、kacore/main.py、memory/noop/base 默认实现保留。
- source_store/processing.py 是相对 import 的真实原子提交路径，不得因静态扫描误删。
- 不截断或补零向量；不上传真实论文用于服务验证；不泄露 key、认证重定向参数或完整响应。

KCL 当前证据：
- 用户链接：https://ai.create.kcl.ac.uk/docs/getting-started
- 官方公开入口：https://docs.er.kcl.ac.uk/CREATE/ai_hub/
- 已知平台声明 OpenAI 兼容；具体文档匿名访问跳转学校 Microsoft SSO。
- 用户随后已提供文档摘录：LiteLLM 代理、API key 认证；arc:embedvl 对应 Qwen/Qwen3-VL-Embedding-2B（FP16）。
- 模型目录的 32768 是上下文长度，不是维度；Qwen 官方模型卡给出最大 2048 维，服务实际输出仍须实测锁定。
- arc:rerankvl 对应独立 reranker，不用于本次 embedding，也不扩展此次 rerank 范围。
- key 默认 internal-only；公网部署需要允许公网的 key，且须满足 IP/CIDR 限制；免费模型仍限流。
- 未核实 actual API base、Embeddings endpoint、批量限额与图片输入格式；未做真实 API 联调。
- 用户只需补登录后实际 API base/调用协议片段；模型名已知，密钥应通过环境变量注入，不要求粘贴进聊天。
- 不猜 /v1，也不把网站登录要求等同于 API 认证要求。
- 若符合标准 OpenAI Embeddings，复用 external，无需 kcl 专属 provider。
- 输出 verified / conditional / unverified / unsupported；明确模型与文本/图片范围。

Qwen 协议注意：
- 官方模型卡：https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B
- 官方 vLLM 在线例：https://docs.vllm.ai/en/stable/examples/pooling/embed/
- vLLM 对该模型的在线例采用 POST /embeddings 的 messages 扩展，包含 system/user/assistant，
  text 或 image_url 内容，encoding_format=float、continue_final_message=true、add_special_tokens=true。
- 这是 vLLM 参考协议，不是已经验证的 KCL 协议；上游类型、LiteLLM 版本和字段透传仍需确认。
- 当前 input:list[str] 不能表达上述图片请求。分别核验标准文本、messages 文本、纯图片、组合输入。
- 若一份 messages 只嵌入一条输入，批量使用有界并发单条请求，不能把全部文档拼成一份长对话。
- 缓存/旁路索引指纹纳入模板/指令/输出维度/图片预处理；不擅自加 e5 前缀、不绕过代理直连上游。

现有 external 离线复现：
- 配完整 /v1/embeddings 后又追加 /embeddings。
- 接受 [None]、[[]]、短批次、重复 index、NaN。
- 查询维度 3 → 4 直接覆写不拒绝。
- 现 test_external_provider_mock 只检查初始维度，未验证 HTTP 请求。
应针对这些实际故障补 meaningful 协议测试。

验证：
- shell 没有 python 命令，.venv/bin/python 可用；先检查依赖与运行环境。
- 现已完成 79 项配置/指纹/AstrBot 适配测试；包含 SQLite/缓存的套件在 aiosqlite 等待处停滞并中止。
- 后续需定位测试运行问题再跑完整相关套件，不能把中止或 deselected 写成通过。
- 当前 torch/sentence_transformers 未安装；历史两个依赖 torch 的用例有失败记录。
- 跑计划列出的 pytest、ruff、mypy、git diff --check；有前端变更再跑 tsc/lint/build/sync。
- 不为纯删除新增“没有某个函数”的镜像测试，复用行为回归。

交付：
1. Phase 状态与 changed files；
2. 删除项及零调用/替代路径证据；
3. 支持的模型、协议、模态范围与 KCL 兼容等级；
4. 旧库/缓存/指纹保护证据；
5. 测试结果、既有失败、未决项；
6. 配置与升级/回滚说明。
不得宣称 mock 测试已证明真实 KCL 可用，不得将只有文本分支可用写成完整多模态检索完成。
```
