"""QuotaManager 阶梯预警与阻断机制单元测试。

验证 R2 用量在 80% 警戒阈值与 100% 硬配额上限下的 WARN/BLOCK 动作正确触发。
"""
from __future__ import annotations

import pytest

from core.config import R2SyncConfig
from core.domain.models import QuotaLevel, SyncTargetKind
from core.managers.quota_manager import QuotaManager
from core.repository.sync_targets.memory import InMemorySyncTarget


@pytest.fixture
def r2_config() -> R2SyncConfig:
    return R2SyncConfig(
        enabled=True,
        account_id="mock",
        bucket="mock",
        free_tier_gb=10,
        warn_threshold=0.8,
    )


async def test_quota_level_ok(r2_config: R2SyncConfig) -> None:
    # 5GB / 10GB = 50%, OK
    target = InMemorySyncTarget(
        kind=SyncTargetKind.R2,
        limit_bytes=10 * 1024 * 1024 * 1024,
        base_used_bytes=5 * 1024 * 1024 * 1024,
    )
    manager = QuotaManager(
        sync_targets={SyncTargetKind.R2: target},
        r2_config=r2_config,
    )

    warning = await manager.check_quota("r2", pending_bytes=100)
    assert warning.level == QuotaLevel.OK
    assert warning.message == ""


async def test_quota_level_warn_above_80_percent(r2_config: R2SyncConfig) -> None:
    # 8.1GB / 10GB = 81%, WARN
    target = InMemorySyncTarget(
        kind=SyncTargetKind.R2,
        limit_bytes=10 * 1024 * 1024 * 1024,
        base_used_bytes=8 * 1024 * 1024 * 1024,
    )
    manager = QuotaManager(
        sync_targets={SyncTargetKind.R2: target},
        r2_config=r2_config,
    )

    # 加上待同步增量共 8.1GB
    warning = await manager.check_quota("r2", pending_bytes=100 * 1024 * 1024)
    assert warning.level == QuotaLevel.WARN
    assert "接近配额上限" in warning.message
    assert "预计用量达 81.0%" in warning.message
    assert "10.00 GB" in warning.message


async def test_quota_level_block_above_100_percent(r2_config: R2SyncConfig) -> None:
    # 10.1GB / 10GB = 101%, BLOCK
    target = InMemorySyncTarget(
        kind=SyncTargetKind.R2,
        limit_bytes=10 * 1024 * 1024 * 1024,
        base_used_bytes=9.9 * 1024 * 1024 * 1024,
    )
    manager = QuotaManager(
        sync_targets={SyncTargetKind.R2: target},
        r2_config=r2_config,
    )

    # 预计用量达到 10.1GB，硬超额阻断
    warning = await manager.check_quota("r2", pending_bytes=200 * 1024 * 1024)
    assert warning.level == QuotaLevel.BLOCK
    assert "已被硬性安全阻断" in warning.message
