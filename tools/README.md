# tools/ — 构建 / 版本 / 诊断脚本

## 职责

放**一次性或维护性脚本**：构建、版本号管理、数据诊断等。这些不是运行时业务代码，故独立于 `core/`。

## 典型成员（参考）

```
tools/
  sync_frontend.py   # 构建前端并把产物同步到 pages/
  bump_version.py    # 统一更新 metadata.yaml / CHANGELOG 的版本号
  diagnose_xxx.py    # 数据/状态诊断脚本
```

## 约定

- 每个脚本是**可独立运行的入口**（`if __name__ == "__main__":`），带清晰 `--help`/参数说明。
- 脚本可 import `core`（把根加入 `sys.path`），**复用业务逻辑**而非重复实现：
  ```python
  _ROOT = Path(__file__).parent.parent
  if str(_ROOT) not in sys.path:
      sys.path.insert(0, str(_ROOT))
  from core.utils.frontend_build import build_frontend
  ```
- 脚本顶部 docstring 说明用途与典型用法。
- 危险操作（删数据、重置）必须显式确认参数，默认 dry-run。
