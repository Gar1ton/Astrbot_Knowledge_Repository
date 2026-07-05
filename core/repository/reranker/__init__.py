"""重排器子系统：接口 + 实现 + 工厂（repository 层）。

工厂 build_reranker 按 provider 选择实现：auto 优先本地 cross-encoder，依赖缺失或
模型加载失败自动回退 Noop；noop 强制不重排。repository 层不依赖 config——工厂只接
原始参数，由组合根从 RerankConfig 解开传入（构造器注入、不读全局单例）。
"""
from __future__ import annotations

import importlib.util
import logging

from core.repository.reranker.base import Reranker, ScoredChunk
from core.repository.reranker.noop import NoopReranker

logger = logging.getLogger("Reranker")

# ── provider 常量（杜绝魔法字面量）─────────────────────────────
PROVIDER_NOOP = "noop"
PROVIDER_CROSS_ENCODER = "cross_encoder"
DEFAULT_RERANK_MODEL = "Alibaba-NLP/gte-reranker-modernbert-base"


def _has_sentence_transformers() -> bool:
    """sentence-transformers 是否可用（仅探测，不导入，便于测试 monkeypatch）。"""
    return importlib.util.find_spec("sentence_transformers") is not None


def build_reranker(
    *,
    provider: str = PROVIDER_NOOP,
    model: str = DEFAULT_RERANK_MODEL,
    device: str = "auto",
    batch_size: int = 32,
    max_candidates: int = 30,
) -> Reranker:
    """构造重排器（默认 noop——不重排，零模型零部署）。

    仅当 provider=cross_encoder 时才懒加载本地 cross-encoder（首次使用下载模型）；缺
    sentence-transformers 则记 warning 回退 NoopReranker，保证不影响普通 ask。其余
    provider（含历史 auto/mmr）一律 noop——rerank 精度交由 deep thinking 的 verification 承担。
    """
    if provider != PROVIDER_CROSS_ENCODER:
        return NoopReranker()
    if not _has_sentence_transformers():
        logger.warning("provider=cross_encoder 但 sentence-transformers 缺失，回退 noop。")
        return NoopReranker()
    from core.repository.reranker.bge_local import CrossEncoderReranker

    return CrossEncoderReranker(
        model=model, device=device, batch_size=batch_size, max_candidates=max_candidates
    )


__all__ = [
    "Reranker",
    "ScoredChunk",
    "NoopReranker",
    "build_reranker",
    "PROVIDER_NOOP",
    "PROVIDER_CROSS_ENCODER",
    "DEFAULT_RERANK_MODEL",
]
