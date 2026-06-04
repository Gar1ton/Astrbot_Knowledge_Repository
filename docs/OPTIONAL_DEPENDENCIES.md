# Additional Requirements

AstrBot automatically installs every package listed in the plugin root
`requirements.txt`. To keep plugin installation reliable, that file only contains the
lightweight dependencies required for PDF upload, SQLite storage/retrieval, and the Web
console.

All optional runtimes and development tools are consolidated in
`requirements-additional.txt`. Install it into the same Python environment that runs
AstrBot, then restart AstrBot. In the standard `uv tool` Docker installation shown by
AstrBot logs:

```bash
ASTRBOT_PY=/root/.local/share/uv/tools/astrbot/bin/python
PLUGIN_DIR=/item/data/plugins/astrbot_plugin_knowledge_repository
```

Paths can differ. Use the Python executable shown in the AstrBot traceback when needed.

PyPI's default Linux PyTorch package may download large CUDA components. For CPU
deployments, install CPU-only PyTorch before the combined additional requirements:

```bash
$ASTRBOT_PY -m pip install torch --index-url https://download.pytorch.org/whl/cpu
$ASTRBOT_PY -m pip install -r "$PLUGIN_DIR/requirements-additional.txt"
```

The combined file installs Milvus Lite, local Embedding, LightRAG, R2, and development
tools. It is never installed automatically by AstrBot.

## Embedding And Milvus

For local Embedding, keep `embedding.provider=local`. The configured Hugging Face model
is downloaded on the next plugin startup.

For external Embedding, configure `embedding.provider=external`, `embedding.base_url`,
`embedding.model`, and environment variable `KR_EMBEDDING_API_KEY`. Installed local
Embedding packages remain unused at runtime.

## LightRAG

Enable `graph.enabled` and restart before manually building a collection. LightRAG also
requires a working local or external Embedding provider.

## Cloudflare R2

Configure and enable `r2_sync` after installing the combined additional requirements.

## Base Install Behavior

Without optional dependencies, the plugin still supports:

- PDF upload and managed original storage.
- PyMuPDF text extraction and SQLite chunk persistence.
- SQLite lexical retrieval, including Chinese queries.
- AstrBot KB fallback and the independent Web console.

Milvus and LightRAG remain disabled with explicit runtime diagnostics until their
optional dependencies and Embedding provider are available.
