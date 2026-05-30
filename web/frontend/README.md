# web/frontend/ — 前端源码

> **可选**。随 `web/` 一起存在或删除。

## 约定

- 独立前端工程（如 Next.js / Vite + React），自带 `package.json` / 构建配置。
- **目录分层**（参考）：
  ```
  frontend/
    app/         # 路由页面（按功能分目录）
    components/  # 复用组件
    hooks/       # 复用逻辑
    lib/         # 纯函数 / API 客户端 / 计算（如预算估算）
    styles/
  ```
- **纯计算抽到 `lib/`**：与渲染无关的算法（格式化、估算、派生）放 `lib/` 做成纯函数，便于复用与测试——前端同样遵守「单一职责 + 可视性」。
- 前后端契约：前端只经 `web/` 暴露的 API 交互，不假设后端内部结构。

## 构建与同步

```bash
# 1) 构建
cd web/frontend && npm run build
# 2) 把静态产物同步到运行时目录 ../../pages/
python tools/sync_frontend.py -f      # 从项目根运行
```

构建产物**不手改**，落地于 `../../pages/`（见 `../../pages/README.md`）。开发热重载用 `dev/` 下的 dev runner。
