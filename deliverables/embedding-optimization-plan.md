# OpenAI 文本 embedding 与旧库兼容优化

更新：2026-10-07。用户已批准本轮收敛计划；本文件替代此前包含完整 PDF 图文检索的方案。
基线：`developer` / `fd77de5`。实际验证以文末及 CHANGELOG 为准，不引用历史测试数量冒充本轮结果。

## 本轮范围与实施顺序

1. 登记 TODO：文本协议、缓存、连接探针、旧库兼容保护及无用代码清理；图片机制仅登记研究任务。
2. external 支持 API base/完整端点，保留代理前缀；请求浮点向量；严格检查完整唯一 index、数量、有限非空向量；完整有效批次才锁定维度。
3. cached 在 external 实测维度就绪后读缓存；损坏记录按 miss；整批校验后事务回填；懒加载维度或身份改变时不混入旧命中。
4. API 连接探针共用生产适配；非法地址/模型及异常响应返回结构化诊断。
5. 删除无调用的 Notion 旧正文预览/大文件提示生成器、旧 AstrBot chunk 翻译模块，修正失效说明。
6. 协议/缓存/已有数据库和索引回归、本地 distributor 文本实测；测试通过后更新 TODO，追加 CHANGELOG。

多模态模型通过文本入口服务原有文字库，不写 KCL 专属 provider。图片 embedding 本轮不实现。
不增加图片表、占位、制品、视觉模型调用、后台任务、补 VL 按钮或图片检索。

## 兼容不变量

- URL 归一化只影响网络请求，不改用户配置、factory namespace 或 embedding fingerprint。
- local/external 默认 identity 仍为空；历史缓存 key 和冻结指纹保持原样。
- embedding_cache 保留 content_hash/vector 两列；源数据库无新迁移、表或字段。
- 首个有效外部向量确定真实维度；随后漂移拒绝返回，不截断、补零或静默更新旧索引。
- 同模型/配置/真实维度的索引继续复用；真正换向量空间仍走既有重建机制，源文档和正文保留。
- 不改 clean.md、页偏移、chunk ID、CHUNK_SCHEMA、处理版本及 LightRAG 数据。
- 不改变 AstrBot provider 生命周期/热重载保护；不增加 base 抽象方法或新配置必填项。
- 空批次无网络/缓存副作用；异常不附带请求、完整响应、凭据或含认证信息的 URL。

## 服务证据

经用户授权使用已有 distributor：`http://127.0.0.1:8899/v1`，显式模型 `arc:embedvl`。
其上游 base 是 `https://ai.create.kcl.ac.uk/api/v1`。这些是测试记录，不是代码硬编码。
凭据只读入内存；不创建 token、不改总机、不切换 hub、不上传论文或打印向量。

- 实施前单条/三条文本返回 HTTP 200、2048 维、正确数量/index 和有限数值。
- 图片 messages 及 input 图文消息均 HTTP 400；Data URI 字符串成功未证明图像语义。
- 模型本身支持图文不等于代理开放图片协议，本轮只声明文本兼容。

参考：[Qwen 官方项目](https://github.com/QwenLM/Qwen3-VL-Embedding)、
[vLLM 图片 embedding 示例](https://docs.vllm.ai/en/stable/examples/pooling/embed/)。

## 后续研究（未实施）

1. 位图/矢量图表/扫描页检测；裁剪与整页渲染；独立占位如何关联文字而不改变偏移。
2. 图片表/旁路仓储、稳定身份和修订、相对路径、去重删除、备份恢复及兼容旧库的增量迁移。
3. VL 描述后文本 embedding 与原生图片 embedding 的协议、费用和增量策略。
4. 机制确定后再设计文章级补充按钮、取消续跑和检索开关，不自动重跑正文库。

## 验证记录

- 已用现有 Windows Docker CLI 接通 tooling/dev，镜像构建成功，但创建容器失败：
  Docker Desktop 缺少 WSL distro mount socket（ubuntu-24-04.sock）。未修改宿主设置。
- 新自动化测试覆盖协议、缓存冷启动/损坏/并发/原子回填，以及已有源数据库和索引接线。
- git diff --check 通过。pytest/ruff/mypy 及修改后真实服务验证待执行；
  等待恢复 WSL 集成或用户明确授权使用现有宿主 .venv，实施 TODO 不标完成。
