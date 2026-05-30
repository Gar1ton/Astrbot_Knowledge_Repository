# core/pipelines/ — 领域管线

> 本目录是「领域专属多步骤流水线」的**命名约定区**。真实项目通常把它展开为**多个并列的领域目录**，
> 例如 `extractor/`、`retrieval/`、`tasks/`、`sync/`、`embedding/` 等——每个目录是一条独立流水线。
> 模板里统一以本目录示范其边界与命名规则。

## 职责

承载**可独立测试、可复用的多步骤算法/流程**，由 `managers` 编排调用。
manager 回答「何时、为谁做」；pipeline 回答「具体怎么一步步做」。

## 命名与切分原则

- 一个 pipeline 目录 = 一条**领域流水线**，目录名是该领域的名词（`retrieval/`、`extractor/`、`tasks/`）。
- 流水线内部按**阶段**拆文件：解析 `parser.py` → 处理 `partitioner.py` / `noise_filter.py` → 产出 `formatter.py`。
- 周期性后台作业放 `tasks/`，由组合根的调度器注册（`decay`、`cleanup`、`backup`、`summary`…），每个任务一个文件。

## 约定

- 依赖 `repository` 接口 + `domain` + `utils`；**不直接 import 框架**。
- 输入输出尽量是 `domain` 对象或纯数据，便于单测与替换。
- 长耗时/外部调用（LLM、网络）走注入的 provider/encoder，**不在 pipeline 内硬编码**外部端点。
- 单文件超 `CONVENTIONS.md` 红线即按阶段进一步拆分。
