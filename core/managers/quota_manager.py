"""配额评估管理器实现（managers 层）。

提供针对已配置同步目标的用量检测、硬限额阻断（BLOCK）及阶梯预警（WARN）机制。
保障用户云端对象存储开销的安全可控。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.domain.models import QuotaLevel, QuotaWarning, SyncTargetKind
from core.managers.base import BaseQuotaManager

if TYPE_CHECKING:
    from core.config import R2SyncConfig
    from core.repository.sync_targets.base import SyncTarget

logger = logging.getLogger("QuotaManager")


class QuotaManager(BaseQuotaManager):
    """具体的配额预警与阻断管理器。"""

    def __init__(
        self,
        *,
        sync_targets: dict[SyncTargetKind, SyncTarget],
        r2_config: R2SyncConfig,
    ) -> None:
        super().__init__()
        self._sync_targets = sync_targets
        self._r2_config = r2_config

    def _fmt_size(self, b: int) -> str:
        if b < 1024:
            return f"{b} B"
        if b < 1048576:
            return f"{b / 1024:.1f} KB"
        if b < 1073741824:
            return f"{b / 1048576:.1f} MB"
        return f"{b / 1073741824:.2f} GB"

    async def check_quota(self, target_kind: str, pending_bytes: int = 0) -> QuotaWarning:
        try:
            kind = SyncTargetKind(target_kind)
        except ValueError:
            return QuotaWarning(SyncTargetKind.R2, QuotaLevel.OK)

        target = self._sync_targets.get(kind)
        if target is None:
            # 目标未配置，视为无限制
            return QuotaWarning(kind, QuotaLevel.OK)

        # 获取底层仓储提供的存储用量详情
        usage = await target.check_quota(pending_bytes)

        # 不以字节计额度（如 Notion），默认放行
        if usage.limit_bytes <= 0:
            return QuotaWarning(kind, QuotaLevel.OK)

        # 1) 判断是否将硬超额（已用 + 新增字节 > 限制额度）
        if usage.will_exceed:
            proj_str = self._fmt_size(usage.projected_bytes)
            limit_str = self._fmt_size(usage.limit_bytes)
            msg = (
                f"同步将超出配额上限（预计用量 {proj_str} / 上限 {limit_str}），"
                f"同步已被硬性安全阻断！"
            )
            logger.error(msg)
            return QuotaWarning(kind, QuotaLevel.BLOCK, msg)

        # 2) 判断是否达到阶梯预警比例（默认 80%）
        warn_ratio = self._r2_config.warn_threshold
        projected_ratio = usage.projected_bytes / usage.limit_bytes
        if projected_ratio >= warn_ratio:
            msg = (
                f"用量接近配额上限（预计用量达 {projected_ratio * 100:.1f}%，"
                f"上限 {self._fmt_size(usage.limit_bytes)}），请合理安排备份原件。"
            )
            logger.warning(msg)
            return QuotaWarning(kind, QuotaLevel.WARN, msg)

        return QuotaWarning(kind, QuotaLevel.OK)


__all__ = ["QuotaManager"]
