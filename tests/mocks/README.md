# tests/mocks/ — 测试替身

放**可注入的测试替身**，与 `kacore/` 的 `base.py` 接口严格一致，用于接口对换测试。

典型成员：

```
mocks/
  in_memory_repository.py   # 实现 repository/base 的接口，纯内存、无 I/O
  fake_provider.py          # LLM/embedding provider 桩，返回可控结果
  fake_encoder.py           # 确定性向量编码桩
```

约定：

- 替身**实现真实接口**（继承同一 ABC 或满足同一协议），保证「换上即可跑业务」。
- 行为可控、确定性强（无随机、无网络），让测试可重复。
- 替身归属测试代码，**不出现在生产 import 路径**（生产用 `kacore/repository/memory.py` 之类时除外）。

## 真实开发环境入口

`run_dev_realtime.py` 是当前分支可跟踪的本地组合根，装配真实 SQLite、Milvus Lite、
Embedding、LightRAG、LLM 与 WebUI，并支持 PDF 种子、索引自动重建以及 `.test_data/`
归档/恢复。真实配置文件和测试 PDF 仍受 `.gitignore` 保护。

准备与启动：

```powershell
Copy-Item tests/mock_data/Config/config.example.py tests/mock_data/Config/config.py
# 编辑 config.py，至少配置 LLM / Embedding；测试 MemEcho 时设置 MEMECHO_ENABLED = True。
$env:KR_MEMECHO_API_KEY = "as_your_key_here"
python tests/mocks/run_dev_realtime.py --fresh
```

后续可用 `--keep` 复用当前 `.test_data/`，或用 `--restore` 恢复最近归档。WebUI 地址为
`http://127.0.0.1:6521`，本地调试登录为 `admin / admin123`。

### MemEcho API 验证

只读检查：Flow 面板保存/读取 Key 后执行 Probe，或登录取得 cookie 后请求：

```powershell
curl.exe -c .test_data/dev.cookies -H "Content-Type: application/json" `
  -d '{"username":"admin","password":"admin123"}' `
  http://127.0.0.1:6521/api/login
curl.exe -b .test_data/dev.cookies http://127.0.0.1:6521/api/memecho/probe
curl.exe -b .test_data/dev.cookies http://127.0.0.1:6521/api/memecho/vaults
```

以下操作会写入 MemEcho 并可能消耗额度，需显式执行：

```powershell
# 新建 vault；从响应中取得 id/library_id，并写入 config.py 的 MEMECHO_DEFAULT_VAULT_ID。
curl.exe -b .test_data/dev.cookies -H "Content-Type: application/json" `
  -d '{"name":"KR dev smoke","description":"local development smoke test"}' `
  http://127.0.0.1:6521/api/memecho/vaults

# 把本地 default 集合文档导入指定 vault。
curl.exe -b .test_data/dev.cookies -H "Content-Type: application/json" `
  -d '{"collection":"default","vault_id":"YOUR_VAULT_ID"}' `
  http://127.0.0.1:6521/api/memecho/import

# MEMECHO_QUERY_READONLY=True 时召回本身不写查询历史；写回仍由
# MEMECHO_WRITE_BACK_ENABLED 独立控制（默认 False）。
curl.exe -b .test_data/dev.cookies -H "Content-Type: application/json" `
  -d '{"question":"概括刚导入文档的核心观点","retrieval_mode":"memecho"}' `
  http://127.0.0.1:6521/api/ask
```

若在服务启动后才通过 Flow 保存 Key，先停止服务并用 `--keep` 重启，Ask 的 MemEcho
召回对象才会按新 Key 装配；`probe`、vault 和 import 端点可动态读取新 Key。
