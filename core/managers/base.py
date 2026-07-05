"""编排服务基类（managers 层，接口先行）。

定义统一的 BaseManager 与各个具体 Manager 的抽象契约。
遵循构造器注入，保证高可测试性与单一职责。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import QuotaWarning


class BaseManager(ABC):
    """编排服务公共基类。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)


class BaseIngestManager(BaseManager, ABC):
    """源文档摄入管理契约。"""

    @abstractmethod
    async def ingest(
        self,
        *,
        title: str,
        file_path: str,
        content_type: str,
        size_bytes: int,
        collection: str,
        tags: list[str] | None = None,
    ) -> str:
        """从本地文件登记源文档并利用 PyMuPDF 抽取文本、切分 Chunks 并存入仓储。

        返回生成的 doc_id。
        """
        ...


class BaseCategoryManager(BaseManager, ABC):
    """源文档分类与标签管理契约。"""

    @abstractmethod
    async def create_collection(self, name: str, description: str = "") -> None:
        """新建或更新集合。"""
        ...

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """删除集合（不级联删除文档）。"""
        ...

    @abstractmethod
    async def classify_document(
        self, doc_id: str, *, collection: str | None = None, tags: list[str] | None = None
    ) -> bool:
        """手动调整文档的集合与标签。"""
        ...

    @abstractmethod
    async def auto_tag_document(self, doc_id: str) -> list[str]:
        """为文档自动提取并打上推荐标签（预留 AI/LLM 提取接口，默认关闭并警示）。"""
        ...


class BaseQuotaManager(BaseManager, ABC):
    """配额预警与阻断管理契约。"""

    @abstractmethod
    async def check_quota(self, target_kind: str, pending_bytes: int = 0) -> QuotaWarning:
        """针对指定的目标进行配额评估，返回配额预警状态（包含 OK / WARN / BLOCK 级别）。"""
        ...


__all__ = ["BaseManager", "BaseIngestManager", "BaseCategoryManager", "BaseQuotaManager"]
