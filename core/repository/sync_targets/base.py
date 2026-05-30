"""在线同步目标接口（repository 层，接口先行）。

统一 R2 / Notion 等在线目标的契约：推送、删除、配额预检。生产实现 r2.py / notion.py，
测试实现 memory.py 共用本接口。组合根用 dict[SyncTargetKind, SyncTarget] 注册可用目标。

本层只依赖 domain；与框架/SDK 的交互细节交给具体实现或经 adapters 翻译。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import QuotaUsage, SourceDocument, SyncTargetKind


class SyncTarget(ABC):
    """一个在线同步目标（崩溃备份 / 镜像）。

    契约：实现是「目标无关 push 语义」——把一个原件推送到远端并返回稳定 remote_ref。
    额度预检与硬警告由 quota_manager 基于 check_quota() 的返回组织，本接口只如实报告用量。
    """

    @property
    @abstractmethod
    def kind(self) -> SyncTargetKind:
        """该目标的种类（用于在组合根注册表中索引）。"""
        ...

    @abstractmethod
    async def push(self, document: SourceDocument, payload: bytes) -> str:
        """推送一个原件到远端，返回稳定 remote_ref（R2 object key / Notion page id）。

        payload 为原件字节。已存在同 ref 时按覆盖语义处理（幂等）。失败抛异常由上层捕获记账。
        """
        ...

    @abstractmethod
    async def delete(self, remote_ref: str) -> bool:
        """删除远端对象。返回 False 表示 remote_ref 不存在（非异常）。"""
        ...

    @abstractmethod
    async def check_quota(self, pending_bytes: int = 0) -> QuotaUsage:
        """报告当前用量快照；pending_bytes 为本次将写入的增量大小，用于判断是否将超额。

        实现应填好 used_bytes/limit_bytes/pending_bytes；不以字节计额度的目标用 limit_bytes<=0。
        """
        ...


__all__ = ["SyncTarget"]
