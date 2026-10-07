# Notion 同步：MCP v2、正文笔记与消耗

## 升级运行实例

本仓库只提供适配器，不安装或修改 AstrBot 宿主的 MCP server。
开发代码已迁移到 `@suekou/mcp-notion-server@2.0.2`；不要用旧 MCP v1 搭配新代码。

1. 确保运行 MCP 的环境使用 **Node.js 22 或以上**（容器内 MCP 要检查容器内版本）。
2. 在 AstrBot MCP 配置中保留现有 server 名称（默认 `notion`）、token 与连接方式，
   将启动参数的包名锁为 `@suekou/mcp-notion-server@2.0.2`，例如：

   ```json
   {"command": "npx", "args": ["-y", "@suekou/mcp-notion-server@2.0.2"]}
   ```

   这是启动字段示例；token 留在原有宿主配置中，不复制到 KA 配置或仓库。
3. 重连该 MCP server，确认工具清单包含 `notion_query_data_source`、
   `notion_retrieve_data_source`、`notion_update_data_source`、`notion_create_data_source_item`。
4. 重新配置插件的 Articles / QA 目标：`database_id` / `qa_database_id` 填新版
   **Database 容器 ID**，`data_source_id` / `qa_data_source_id` 填对应的 **Data Source ID**。
   单源库可将源 ID 留空，由原有流程解析；多源库必须明确指定。
5. 如果要由插件新建两库，清空四个目标 ID，填写已授权的 `parent_page_id`，重新加载插件，
   再点击 WebUI「设置 → 同步 / 备份 → Notion 同步 → 初始化数据库」。
   曾自动保存过目标 ID 时，还需移除插件数据目录 `runtime_config.json` 中这四个 ID 的
   覆盖项，再重新加载；本轮不提供旧库迁移、映射清理或自动恢复功能。
6. 先手动同步，检查任务错误及「同步账本」；确认正常后开启自动同步。

本次只修复三点：工具能力预检、`data_sources` 响应的准确分类、真实失败账本展示。
预检失败只结束一轮任务，不逐篇写入同一个错误，不覆盖未尝试文档的历史账本。
`/api/sync/status` 合并 Notion 实体账本；`GET /api/sync/notion/status` 提供失败计数和合并原因。
旧 QA 正文默认不会完整保存在本地，本次没有旧内容恢复流程。

契约参考：[MCP v2.0.2 发布说明](https://github.com/suekou/mcp-notion-server/releases/tag/v2.0.2)、
[MCP 工具文档](https://github.com/suekou/mcp-notion-server/blob/main/docs/tools.md)、
[Notion Data Source 升级指南](https://developers.notion.com/docs/upgrade-guide-2025-09-03)。

## 自动同步与正文保护

- `notion_sync.enabled=true` 时，`auto_sync_enabled` 默认 true。
- 已提交的本地文档、集合和归属变更安静 **10 秒**后合并推送；导入、Zotero 拉取和既有
  Notion 推送忙时等待，继续保留待同步变更。
- `auto_sync_interval_sec` 默认 **300 秒**，补偿离线期间的变化并检查远端笔记。
  设为 0 只关闭周期补偿；关闭全部自动推送要关 `auto_sync_enabled`。手动同步仍可用。
  旧配置明确保存的 0 会继续保留，默认 300 只应用于未配置值。
- 失败后按周期（0 时按 300 秒）退避重试；开关与周期的 WebUI 修改即时生效。
- Articles 新页只写属性，不生成 Chunks Preview 或大文件 callout。
  更新、文件哈希变化和强制同步均不清空或写入文章正文；QA 保持原正文同步方式。
- 既有 Chunks Preview 和 callout 原样保留，避免删除夹在旧内容里的用户笔记。

`preserve` / `strict` 清理策略不变：笔记 checkbox 不参与删除判断。
默认 preserve 保留 detached 页面；strict 仍将 detached 页面移入回收站，即使它已做笔记。

## “已做笔记”的简单规则

MCP 完整读取正文块，由 KA 的固定规则判断，不调用语言模型。

- 非空文字、图片、文件或子页面等正文内容会勾选 `已做笔记`。
- 空白文字块和分隔线忽略；空容器继续读取嵌套内容。
- 精确标题为 `本地切片摘要 (Chunks Preview)` 的旧 toggle 及其内部内容不参与判断；
  旧程序大文件提示 callout 也忽略。旧摘要内部的笔记请手动勾选。
- 评论、页面标题与属性编辑不算正文笔记。
- 只把 checkbox 设置为 true，不自动取消；人工勾选始终保留。
- 第一次检查全部未勾选且带 DocID 的 Articles；之后按最近编辑时间增量检查。
  水位按 database/data source 保存，分页、读取或写入失败均不推进水位，下次重试。
  已勾选页不会反复检查；删除笔记后如需清除标记，请手动取消勾选。
- 极大页面超过 5,000 个块或 20 层嵌套时检查报错，保留既有标记。

这些是正文内容规则，并不推断编辑者身份。外部工具添加的正文也会被视为内容。

## Notion 内一键查看

在 Articles 新建一个表格视图，命名“已做笔记”，添加筛选条件：
**`已做笔记` → 已勾选 / true**。以后点击这个视图即可查看已标记文章。
视图由用户在 Notion 界面创建；KA 初始化负责增加 checkbox 列。
若关闭周期补偿，远端新增笔记会在下一次本地变更推送或手动同步时检查。

## 一轮同步的消耗

任务结果与进度条记录 `request_count`（MCP 工具调用尝试，含失败）、`elapsed_seconds`
（秒）和 `model_tokens=0`，以及本轮检查/勾选的文章数。
请求数不含宿主重连，也不是精确计费账单；一个 MCP 工具可能发出额外内部请求。

- **模型：0 token**。同步不做 LLM、Embedding 或摘要；本轮没有模型调用费用。
- **Notion 请求：** 元数据增量写入 + 数据源查询分页 + 候选正文块分页 + checkbox 更新。
  已有账本文章更新通常一次属性调用；新文章先 DocID 查询、再创建，通常两次。
  空白正文文章通常一次块读取；有笔记额外一次 checkbox 写入。data source 首次解析
  通常另需一次容器读取，QA、strict 清理和降级重试会增加调用。
- **没有变更：** preserve 模式、已完成扫描且没有远端变化时，通常一次空结果查询；
  不重写全部页面。300 秒补偿会持续产生这种检查请求。
- **首次笔记扫描示例：** 1,000 个未勾选文章、每篇正文不超过 100 块、均为空，
  约 10 次数据源分页查询 + 1,000 次正文读取 + 首次源解析。按 3 次/秒的客户端上限，
  仅限速等待约 5.6 分钟，实际还受网络延迟影响。之后只读发生变化的候选文章。
- **页面块：** Articles 不再新增摘要块；笔记检查只读正文并更新 checkbox。
  用户自己新增的正文与 QA 写入仍使用 Notion 页面/块容量。

耗时与费用以实际任务结果及宿主/Notion 配额为准；固定规则不会因文章长度产生模型 token。
