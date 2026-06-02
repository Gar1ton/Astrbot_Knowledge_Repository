"""领域模型（依赖图圆心，零依赖）。

本文件定义知识库应用的全部纯数据模型：原件、集合、分块、同步记录、配额、图谱实体/关系。
只允许标准库与类型注解——不 import 任何框架/数据库/HTTP/其它业务层（见 ../README.md 铁律）。

设计取向：
    - 时间统一为 UTC aware datetime；对外用稳定字符串 ID（UUID/哈希），内部 rowid 不进 domain。
    - 枚举集中领域常量，杜绝散落的魔法字面量（如同步目标、状态）。
    - dataclass 语义为值对象；派生量（如配额比例）用 @property 就地计算，不落字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ── 领域枚举 ────────────────────────────────────────────────────


class SyncTargetKind(str, Enum):
    """同步目标种类。值用于配置/持久化键，故继承 str 以便直接序列化。"""

    NOTION = "notion"
    R2 = "r2"


class SyncStatus(str, Enum):
    """单文档对单目标的同步状态。

    PENDING 表示待同步（含内容哈希已变、需重传）；SYNCED 表示远端与本地哈希一致；
    SKIPPED 表示按规则有意跳过（如超 Notion 5MiB 改走链接）；FAILED 表示尝试过但失败。
    """

    PENDING = "pending"
    SYNCED = "synced"
    SKIPPED = "skipped"
    FAILED = "failed"


class QuotaLevel(str, Enum):
    """配额预警级别。OK 无需提示；WARN 接近阈值提示；BLOCK 将超额，须用户确认后才继续。"""

    OK = "ok"
    WARN = "warn"
    BLOCK = "block"


# ── 知识库源 ────────────────────────────────────────────────────


@dataclass
class Collection:
    """集合：一组文档的逻辑分类，对应 AstrBot 的一个知识库（collection）。

    name 是集合的稳定标识（同时用作 R2 key 前缀与 AstrBot collection 名），全局唯一。
    """

    name: str
    description: str = ""
    created_at: datetime | None = None


@dataclass
class SourceDocument:
    """源文档（原件，如 PDF）。原件是备份与管理的一等公民，不做 LLM 转换。

    契约：
        - doc_id 为稳定外部标识（UUID）；content_hash 为原件字节的哈希，用于增量同步判定。
        - file_path 指向本地原件位置（插件数据目录内的相对/绝对路径）。
        - collection 指定所属集合名；tags 为自由标签集合（手动分类，去重由调用方保证）。
    """

    doc_id: str
    title: str
    file_path: str
    content_type: str
    size_bytes: int
    content_hash: str
    collection: str
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    needs_reindex: bool = False


@dataclass
class DocumentChunk:
    """文档分块：原件抽取并切分后的文本片段，供检索与图谱抽取使用。

    契约：chunk_id 稳定唯一；ordinal 为同一 doc 内的顺序号（从 0 起）；
    content_hash 为该 chunk 文本的哈希，是图谱增量抽取「是否需重抽」的依据。
    """

    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 在线同步 ────────────────────────────────────────────────────


@dataclass
class SyncRecord:
    """一条「文档 × 目标」的同步账目。组合键 (doc_id, target) 唯一。

    契约：
        - remote_ref 为远端引用（R2 object key / Notion page id），未同步时为 None。
        - content_hash 记录上次成功同步时的原件哈希；与当前原件哈希不等即需重传（增量依据）。
        - synced_at 为上次成功同步时间；status=FAILED 时 message 携带原因。
    """

    doc_id: str
    target: SyncTargetKind
    remote_ref: str | None = None
    content_hash: str | None = None
    status: SyncStatus = SyncStatus.PENDING
    synced_at: datetime | None = None
    message: str = ""


@dataclass
class QuotaUsage:
    """某在线目标的用量快照（push 前预检用）。

    契约：
        - used_bytes / limit_bytes 为存储用量与上限；limit_bytes<=0 表示无存储上限（如 Notion）。
        - pending_bytes 为本次将要写入的增量大小，用于判断「写入后是否超额」。
        - detail 携带目标特有的额外信息（如 Notion 的限流提示、R2 的操作次数），不参与阈值计算。
    """

    target: SyncTargetKind
    used_bytes: int
    limit_bytes: int
    pending_bytes: int = 0
    detail: str = ""

    @property
    def ratio(self) -> float:
        """当前用量占上限的比例；无上限时恒为 0.0。"""
        if self.limit_bytes <= 0:
            return 0.0
        return self.used_bytes / self.limit_bytes

    @property
    def projected_bytes(self) -> int:
        """写入本次增量后的预计用量。"""
        return self.used_bytes + self.pending_bytes

    @property
    def will_exceed(self) -> bool:
        """写入本次增量后是否将超过上限；无上限时恒为 False。"""
        if self.limit_bytes <= 0:
            return False
        return self.projected_bytes > self.limit_bytes


@dataclass
class QuotaWarning:
    """配额预警结果。level=OK 时 message 可为空；WARN/BLOCK 时 message 面向用户可读。"""

    target: SyncTargetKind
    level: QuotaLevel
    message: str = ""


# ── 知识图谱（LightRAG 风格属性图）────────────────────────────────


@dataclass
class GraphEntity:
    """图谱实体节点。

    契约：
        - entity_id 稳定唯一（通常由规范化 name 派生）；name 为展示名，entity_type 为类别。
        - source_chunk_ids 记录支撑该实体的来源 chunk；归并别名时合并描述并取并集。
        - degree 为关联边数，由 GraphStore 维护，非调用方手填。
    """

    entity_id: str
    name: str
    entity_type: str = ""
    description: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)
    degree: int = 0


@dataclass
class GraphRelation:
    """图谱关系边（有向：src → dst）。

    契约：
        - relation_id 稳定唯一；relation 为关系词；weight 为强度，重复抽取时累加。
        - source_chunk_ids 记录支撑该关系的来源 chunk。
    """

    relation_id: str
    src_entity_id: str
    dst_entity_id: str
    relation: str = ""
    description: str = ""
    weight: float = 1.0
    source_chunk_ids: list[str] = field(default_factory=list)


__all__ = [
    "SyncTargetKind",
    "SyncStatus",
    "QuotaLevel",
    "Collection",
    "SourceDocument",
    "DocumentChunk",
    "SyncRecord",
    "QuotaUsage",
    "QuotaWarning",
    "GraphEntity",
    "GraphRelation",
]
