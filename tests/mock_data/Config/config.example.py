"""本地开发测试配置模板。

使用方法：
    复制本文件为同目录下的 config.py，填入真实值。
    config.py 已被 .gitignore，不会被提交。

配置说明：
    - LLM（Deepseek）用于 LightRAG 图谱问答，必须填入真实 key
    - Embedding 有两种选择：
        EMBEDDING_PROVIDER = "local"    → 使用本机 sentence_transformers，无需 key
        EMBEDDING_PROVIDER = "external" → 使用云端 API，需填入下方 API 配置
"""

# ── LLM（LightRAG 问答，必填）──────────────────────────────────
DEEPSEEK_API_KEY = "sk-your-key-here"
LLM_MODEL = "deepseek-chat"
LLM_API_URL = "https://api.deepseek.com/v1"

# ── Embedding 模式选择 ──────────────────────────────────────────
# "local"    → sentence_transformers 本地运行，无需 API key（推荐本地测试）
# "external" → 云端 API，需填写下方配置
EMBEDDING_PROVIDER = "local"

# ── 本地 Embedding 配置（EMBEDDING_PROVIDER = "local" 时生效）──
# 模型首次使用时自动从 HuggingFace 下载（约 200-400 MB）
EMBEDDING_LOCAL_MODEL = "intfloat/multilingual-e5-small"  # dim=384

# ── 云端 Embedding 配置（EMBEDDING_PROVIDER = "external" 时生效）
EMBEDDING_API_KEY = "sk-your-key-here"
EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_API_URL = "https://api.deepseek.com/v1"
