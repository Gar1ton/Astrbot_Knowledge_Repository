"""Embedding 计算接口（repository 层，接口先行）。

定义将文本分块或提问转换为稠密浮点向量（dense vector）的契约。
本层只依赖 domain。实现：local（本地模型）/ external（OpenAI 兼容 API）/
astrbot（委托 AstrBot 已配置的 EmbeddingProvider）；`cached` 是套在任一实现外的磁盘缓存装饰器。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """Embedding 向量计算提供者接口。"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """将单个查询文本转换为稠密向量。"""
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量将文档分块文本转换为稠密向量列表。"""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """获取当前 Embedding 模型输出向量的维度（如 384, 1536 等）。"""
        ...

    def unload(self) -> None:
        """卸载常驻的本地模型并释放加速器缓存；下次调用时自动重新懒加载。

        契约：幂等（未加载时调用是空操作），不抛异常，不改变 provider 的可用性——卸载只影响
        「此刻是否占着显存」。远端 provider 无模型可卸，默认实现为空操作。
        """
        return None

    @property
    def identity(self) -> dict[str, str]:
        """返回参与缓存 namespace 与索引指纹的**非机密**运行时身份。

        契约：
          - 只含可安全落盘、写日志的字符串（如 provider ID、adapter 类型、模型名、实测维度），
            绝不含 API Key、Authorization 头、完整请求头或带凭据的 URL。
          - 默认空 dict = 身份完全由配置决定（local/external 的既有行为；其缓存 namespace
            与索引指纹因此和引入本属性之前逐字节一致，已建索引不会被误判为不兼容）。
          - 值可在首次成功嵌入后变化（例如 provider 未声明维度、由首个实测向量锁定），
            调用方必须每次使用时现读，不得缓存。
          - 读取绝不触发网络请求或模型加载。
        """
        return {}

    @property
    def runtime_status(self) -> dict[str, Any]:
        """返回运行态快照，供模型面板展示。

        契约：**绝不触发模型加载**（面板每几秒轮询一次，一次误触发就是几百毫秒的卡顿加
        一整块显存）。至少包含 `provider` 与 `state`；`state` 取
        `idle`（未驻留）/`loading`/`ready`（已驻留）/`failed`/`external`（无本地模型）。
        """
        return {
            "provider": "unknown",
            "state": "external",
            "model": None,
            "device": "",
            "last_error": None,
        }


__all__ = ["EmbeddingProvider"]
