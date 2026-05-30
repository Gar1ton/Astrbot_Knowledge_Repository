# AGENTS.md

> 面向**非 Claude 系**的 coding agent（Cursor / Codex / Gemini / Aider 等）的入口。
> 为避免规范分裂，本项目的行为契约**只有一个真相源**：

## 唯一真相源 → [`CLAUDE.md`](./CLAUDE.md)

请将 `CLAUDE.md` 视为你的最高行为契约并完整阅读。它包含：

1. **工作目录边界**（只读/禁改区）；
2. **必读顺序**：`ARCHITECTURE.md` → `CONVENTIONS.md` → `TODO.md`；
3. **执行协议**（Plan-First，未批准不改代码）；
4. **每轮工作闭环**（先更新 TODO → 写码 → 测试过才标完成 → 追加 CHANGELOG）。

> 本文件不重复规范内容，只做指引。任何规范更新只改 `CLAUDE.md`，本文件保持为指针。
