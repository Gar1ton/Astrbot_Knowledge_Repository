"""本地模型驻留与显存 API 子门面。

为何存在：embedding 与 rerank 都是懒加载单例，加载后会一直占着显存直到 idle 超时
（默认 420s）。用户在同一台机器上跑本地大模型时，需要一个**立即**把显存让出来的手动开关
——对齐 LM Studio 的 eject。本 mixin 只暴露「现在驻留了什么 / 立刻卸载」，运行时依赖由
KnowledgeRepositoryApi 通过构造器注入（`_embedding_provider` / `_reranker`）。

显存读数是尽力而为：没有 torch 或没有 CUDA 时 `accelerator` 为 None，面板据此降级为
「CPU 模式」，而模型驻留状态在任何环境下都可用——那才是本功能的核心。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kacore.utils.torch_memory import accelerator_snapshot, release_accelerator_cache

if TYPE_CHECKING:
    from kacore.repository.embedding.base import EmbeddingProvider
    from kacore.repository.reranker.base import Reranker

logger = logging.getLogger("KnowledgeRepositoryApi")

KIND_EMBEDDING = "embedding"
KIND_RERANK = "rerank"
MODEL_KINDS = (KIND_EMBEDDING, KIND_RERANK)

# rerank 侧 status["status"] 的取值与 embedding 侧 runtime_status["state"] 同名同义
# （idle/loading/ready/failed），面板只认后者，故此处只做键名对齐。
_RERANK_STATE_KEY = "status"


class RuntimeModelsApiMixin:
    """本地模型驻留查询与手动卸载。"""

    _embedding_provider: EmbeddingProvider | None
    _reranker: Reranker | None

    def _embedding_runtime(self) -> dict[str, Any] | None:
        provider = getattr(self, "_embedding_provider", None)
        if provider is None:
            return None
        try:
            status = dict(provider.runtime_status)
        except Exception as exc:  # 面板每几秒轮询一次，读状态失败绝不能打断请求。
            logger.warning("读取 embedding 运行态失败: %s", exc)
            return None
        status["kind"] = KIND_EMBEDDING
        status.setdefault("state", "external")
        status.setdefault("model", None)
        return status

    def _rerank_runtime(self) -> dict[str, Any] | None:
        reranker = getattr(self, "_reranker", None)
        if reranker is None:
            return None
        try:
            raw = dict(reranker.status)
        except Exception as exc:
            logger.warning("读取 rerank 运行态失败: %s", exc)
            return None
        return {
            "kind": KIND_RERANK,
            "provider": raw.get("provider", "unknown"),
            "state": raw.get(_RERANK_STATE_KEY, "idle"),
            "model": raw.get("model"),
            "device": raw.get("device", ""),
            "enabled": raw.get("enabled", True),
            "last_error": raw.get("last_error"),
        }

    async def get_model_runtime(self) -> dict[str, Any]:
        """返回本地模型驻留快照 + 尽力而为的显存读数。

        契约：**绝不触发模型加载**——面板会持续轮询本接口。`accelerator` 为 None 表示
        无 torch/无 CUDA，调用方据此降级展示，而不是报错。
        """
        models = [
            entry
            for entry in (self._embedding_runtime(), self._rerank_runtime())
            if entry is not None
        ]
        return {
            "accelerator": accelerator_snapshot(),
            "models": models,
            "resident_count": sum(
                1 for m in models if m.get("state") in ("ready", "loading")
            ),
        }

    async def unload_models(self, kinds: list[str] | None = None) -> dict[str, Any]:
        """卸载指定类别的本地模型并清空加速器缓存，返回刷新后的驻留快照。

        `kinds` 为空表示全部。幂等：未加载的模型上调用是空操作。卸载不改变可用性——
        下次检索会自动重新懒加载，故这是一个安全的、可随时点击的操作。
        """
        wanted = [k for k in (kinds or MODEL_KINDS) if k in MODEL_KINDS]
        unloaded: list[str] = []
        errors: dict[str, str] = {}
        if KIND_EMBEDDING in wanted:
            provider = getattr(self, "_embedding_provider", None)
            if provider is not None:
                try:
                    provider.unload()
                    unloaded.append(KIND_EMBEDDING)
                except Exception as exc:
                    logger.warning("卸载 embedding 模型失败: %s", exc)
                    errors[KIND_EMBEDDING] = str(exc)
        if KIND_RERANK in wanted:
            reranker = getattr(self, "_reranker", None)
            if reranker is not None:
                try:
                    reranker.close()
                    unloaded.append(KIND_RERANK)
                except Exception as exc:
                    logger.warning("卸载 rerank 模型失败: %s", exc)
                    errors[KIND_RERANK] = str(exc)
        # 两个 provider 各自释放过一次；这里兜底再清一次，覆盖「provider 为 None 但显存
        # 仍被上一次加载留在缓存分配器里」的情况。
        release_accelerator_cache()
        runtime = await self.get_model_runtime()
        runtime["unloaded"] = unloaded
        runtime["errors"] = errors
        return runtime


__all__ = ["KIND_EMBEDDING", "KIND_RERANK", "MODEL_KINDS", "RuntimeModelsApiMixin"]
