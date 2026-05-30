# pages/ — 前端构建产物落地目录

> **可选**，与 `web/frontend/` 配套。无前端则删除。

## 约定

- 存放前端**构建后的静态资源**（HTML/JS/CSS/字体），由运行时直接对外提供。
- **由 `tools/sync_frontend.py` 自动生成/同步，禁止手改**（手改会在下次构建被覆盖）。
- 内容随构建产物变化，通常按需 `.gitignore` 或仅保留 `.gitkeep` + 本说明（视发布策略而定）。
- 发布瘦身：可在 `.gitattributes` 用 `export-ignore` 控制是否随源码包分发。

> 子目录命名通常对应项目/插件标识（如 `pages/<project>/...`），与宿主框架的静态路由约定对齐。
