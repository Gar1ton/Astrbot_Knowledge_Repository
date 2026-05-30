# dev/ — 本地开发运行器

> 放**本地调试/联调脚本**，与生产运行解耦。这些脚本只在开发机用，发布包通常剥离（见 `.gitattributes`）。

## 典型成员（参考）

```
dev/
  run_realtime_dev.py   # 本地拉起后端做实时联调
  run_webui_dev.py      # 本地拉起 WebUI / 前端热重载联调
  reset_realtime_dev.py # 重置本地 dev 数据（危险操作，需确认）
  run_config.example.py # 本地运行配置样例 → 复制为 run_config.py（git 忽略）
```

## 约定

- dev 脚本**可 import `core`**（把根加入 `sys.path`）以复用真实业务逻辑。
- 本地敏感/机器相关配置走 `run_config.py`（由 `run_config.example.py` 复制而来），并在 `.gitignore` 忽略真实文件。
- 重置/清库类脚本默认安全、需显式确认参数。
- 前端联调流程见 `../web/frontend/README.md`（构建 → `tools/sync_frontend.py` 同步到 `../pages/`）。
