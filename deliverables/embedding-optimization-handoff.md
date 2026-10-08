# 本轮实施交接与后续研究指令

更新：2026-10-07。用户已批准收敛计划，不再执行之前的图片入库/视觉检索方案。
详细边界与证据见 [embedding-optimization-plan.md](embedding-optimization-plan.md)。

```text
工作区：/home/gar1ton/DEV-WORKSPACE/projects/Astrbot_KAPlugin
调查基线：developer / fd77de5。接手重新检查工作树，不覆盖用户和本轮已有修改。

先读 CLAUDE → ARCHITECTURE → CONVENTIONS → TODO，再读方案、相关实现、测试和 diff。
本轮授权：通用 OpenAI 文本 embedding、缓存、连接探针、旧库兼容及证实无用代码清理。

修改范围：
- external：API base/完整端点、浮点响应、完整唯一 index、数量/有限数值/维度校验。
- cached：实测维度就绪后读旧缓存，损坏按 miss，整批校验后事务回填。
- API 探针复用生产适配；清理旧 Notion 正文生成和无调用的 AstrBot 翻译模块。
- 无服务商专用 provider；多模态模型只验证文本输入。

保留：
- factory namespace、默认文本缓存 hash、local/external fingerprint、astr 生命周期保护。
- 源数据库 schema、正文/页偏移/chunk ID/CHUNK_SCHEMA/处理版本。
- 不同向量空间不能为避免重建而混用；兼容旧索引不自动重建。
- 迁移兼容入口、processing 事务模块、memory/noop 实现。

仅研究 TODO，禁止顺带实现：
- PDF 图片检测、裁剪、占位、图片表/制品/迁移。
- VL 调用、任务、Collection 按钮、图片检索和 LightRAG 图片写入。

验证：
- 新协议/缓存/旧库测试及既有 embedding/astrbot/config/vector/source-store/生命周期/API/Web/Notion 回归。
- 项目检查经 tooling/dev exec；环境例外遵循本轮用户授权，不把历史数量当作本轮通过结果。
- 本地 distributor：base http://127.0.0.1:8899/v1，model arc:embedvl，文本实测2048维。
- 凭据只读进内存；不新建 token、不改总机、不上传论文、不打印密钥或向量。
- 图片消息请求实施前均400；Data URI字符串成功不是图片能力通过。
- 测试通过才勾 TODO，收尾追加 CHANGELOG；不操作运行实例或 Git 远端。

未来研究输出必须确定资产身份、增量迁移、备份恢复、正文兼容和文章级只补缺失数据的机制。
```
