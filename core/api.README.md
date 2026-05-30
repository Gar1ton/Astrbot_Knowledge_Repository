# core/api — 框架无关业务门面

> 真实项目中体现为 `core/api.py`。**仅当项目有 web/HTTP 或多入口时需要。** 纯后端可省略。

## 职责

提供一组**框架无关的纯业务函数**：不含 HTTP 概念、不含 aiohttp/FastAPI 类型。
`web/` 层把请求翻译后**委派给这里**，再把返回值包装成 HTTP 响应。

## 为什么单独一层

- 让「业务能力」与「传输方式」解耦：同一个 `api` 函数既能被 HTTP 调，也能被 CLI / 测试直接调。
- web 路由因此变薄：只做参数解析 + 调 `api` + 序列化响应。

## 约定

```python
# core/api.py —— 纯函数，返回 domain/dict，不返回 HTTP 响应
async def get_stats(event_repo, persona_repo) -> dict:
    ...

# web/server.py —— 只负责 HTTP 包装
async def handle_stats(request):
    data = await get_stats(request.app["event_repo"], request.app["persona_repo"])
    return json_response(data)
```

- 依赖经参数注入（repository、manager），不读全局。
- 不 import 任何 web 框架类型；返回 `domain` 对象 / 纯 dict。
