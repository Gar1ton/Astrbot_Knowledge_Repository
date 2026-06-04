# LightRAG Core 部署后手动探针

本探针只应在 AstrBot 已配置真实 LLM 和 Embedding Provider 后运行。它不会使用 mock；真实 provider 无响应时会明确失败。

## 前置配置

- `graph.enabled = true`
- `embedding.provider/model/base_url/max_token_size` 已配置
- 启动日志未报告 Embedding 真实维度探针失败或索引指纹不兼容
- AstrBot LLM Provider 可正常响应
- 插件 Embedding Provider 可正常响应

## 执行

登录 Web 控制台后，携带现有 `kr_session` cookie 调用：

```bash
curl -X POST http://127.0.0.1:6520/api/graph/probe \
  -H 'Content-Type: application/json' \
  -H 'Cookie: kr_session=<session>' \
  -d '{
    "confirmed": true,
    "collection": "lightrag-probe",
    "doc_id": "kr-lightrag-probe-doc",
    "text": "Knowledge Repository uses official LightRAG Core for entity and relationship indexing.",
    "query": "What does Knowledge Repository use for graph indexing?"
  }'
```

该端点会触发真实 LLM/Embedding 调用，因此必须显式传入 `confirmed: true`。

## Terminal 输出

AstrBot terminal 会按顺序输出易读行：

```text
KR LightRAG initialize_storages collection='lightrag-probe'
KR LightRAG ainsert collection='lightrag-probe' doc_id='kr-lightrag-probe-doc' ...
KR LightRAG aquery collection='lightrag-probe' mode='mix' only_need_context=True ...
KR LightRAG aquery collection='lightrag-probe' mode='mix' ...
KR LightRAG export_data collection='lightrag-probe' ...
KR LightRAG adelete_by_doc_id collection='lightrag-probe' doc_id='kr-lightrag-probe-doc'
KR LightRAG probe ... OK
```

## 判定

响应中以下字段必须满足：

- `status = "success"`
- 所有 `steps[].status = "ok"`
- `aquery_context` 步骤成功，确认高精度 Ask 可只取 LightRAG context
- `delete_strategy = "adelete_by_doc_id"`
- `delete_stable = true`
- `export_data_before_delete.result.nodes` 非空
- 删除后的导出结果与删除前不同

若失败，保留完整响应和 AstrBot terminal 中的 `KR LightRAG` 行用于诊断。
