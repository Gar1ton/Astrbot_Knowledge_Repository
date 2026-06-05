"""本地开发测试配置模板。

使用方法：
    复制本文件为同目录下的 config.py，填入真实值。
    config.py 已被 .gitignore，不会被提交。

配置说明：
    主 LLM（答案生成，必填）：
        用于 Ask 页最终答案生成，推荐 DeepSeek 等云端模型。

    图谱构建 LLM（可选，留空则与主 LLM 共用）：
        用于 LightRAG 在 build 阶段做实体/关系抽取，支持本地 LM Studio。
        设置后，图谱构建打本地，答案生成仍走主 LLM，两者完全独立。

    Embedding 有两种选择：
        EMBEDDING_PROVIDER = "local"    → sentence_transformers 本地运行，无需 key
        EMBEDDING_PROVIDER = "external" → 云端 API（OpenAI 兼容），需填入 API 配置
"""

# ── 主 LLM（答案生成，必填）────────────────────────────────────────
# Ask 页的最终答案由此 LLM 生成，与图谱构建 LLM 相互独立
DEEPSEEK_API_KEY = "sk-your-key-here"
LLM_MODEL = "deepseek-chat"
LLM_API_URL = "https://api.deepseek.com/v1"

# ── 图谱构建专用 LLM（可选）────────────────────────────────────────
# LightRAG build 阶段的实体/关系抽取调用此 endpoint，留空则沿用主 LLM
# 典型值：LM Studio 本地服务（启动后在 LM Studio → Local Server 查看端口）
LIGHTRAG_LLM_BASE_URL = ""          # 本机直接运行: "http://localhost:1234/v1"
                                    # devcontainer/Docker 内访问 Windows: "http://host.docker.internal:1234/v1"
LIGHTRAG_LLM_MODEL = ""             # 例："Qwen2.5-7B-Instruct-GGUF" / "phi4"
LIGHTRAG_LLM_API_KEY = ""           # 本地服务通常留空；远程 OpenAI-compatible 服务填入 key
LIGHTRAG_LLM_TIMEOUT_SECONDS = 900   # 本地 phi4 慢推理建议显著高于 180s
LIGHTRAG_LLM_MAX_RETRIES = 2
LIGHTRAG_LLM_RETRY_BACKOFF_SECONDS = 2.0
LIGHTRAG_SECONDS_PER_CHUNK_LOCAL = 90.0
LIGHTRAG_SECONDS_PER_CHUNK_REMOTE = 20.0

# ── Embedding 模式选择 ──────────────────────────────────────────────
# "local"    → sentence_transformers 本地运行，无需 API key（推荐本地测试）
# "external" → 云端 API，需填写下方配置
EMBEDDING_PROVIDER = "local"

# ── 本地 Embedding 配置（EMBEDDING_PROVIDER = "local" 时生效）──────
# 模型首次使用时自动从 HuggingFace 下载（约 200-400 MB）
EMBEDDING_LOCAL_MODEL = "intfloat/multilingual-e5-small"  # dim=384

# ── 云端 Embedding 配置（EMBEDDING_PROVIDER = "external" 时生效）──
EMBEDDING_API_KEY = "sk-your-key-here"
EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_API_URL = "https://api.openai.com/v1"
