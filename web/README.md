# web/ — 可选全栈层（后端路由 + 前端）

> **可选**。无 WebUI/HTTP 的项目可整目录删除。

## 职责

承载 HTTP/WebUI。后端只做**传输适配**：解析请求 → 委派给 `core/api` 纯函数 → 包装响应。
**业务逻辑不在 web，在 `core`。**

## 典型成员

```
web/
  server.py         # 独立 HTTP 服务（如 aiohttp）：路由 → 委派 core/api
  plugin_routes.py  # 挂载到宿主框架（如 astrbot Plugin Pages）的路由
  registry.py       # 扩展/面板注册中心：供第三方插件挂载自己的面板
  auth.py           # 鉴权
  config_schema.py  # web 侧配置 schema
  frontend/         # 前端源码（见下）
```

## registry 模式（可选）

允许**第三方扩展**在统一 UI 中挂载新面板，而无需改本项目：

```python
@dataclass(slots=True)
class PanelManifest:
    plugin_id: str
    panel_id: str
    title: str
    api_prefix: str
    frontend_url: str
    permission: str  # "public" | "auth" | "sudo"
```

前端拉取已注册清单并动态加载脚本。是「开放扩展、封闭修改」的落地。

## 约定

- 路由薄、`core/api` 厚：路由函数 = 取参 + 调 api + 序列化。
- 后端不 import `managers` 的内部实现细节，经 `core/api` 门面交互。
- 前端构建产物落到 `../pages/`（见 `frontend/README.md` 与 `../pages/README.md`）。
