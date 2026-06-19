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


class DocumentOrigin(str, Enum):
    """文档/集合/标签的来源。

    ZOTERO 表示由 Zotero 单向 Pull 镜像而来——在文档系统中**只读**（不可删/改），
    以保证本轮单向同步不污染上游；LOCAL 表示用户在插件内手动上传，可编辑可删除。
    继承 str 以便直接序列化进持久化键。
    """

    ZOTERO = "zotero"
    LOCAL = "local"


class DocumentLifecycle(str, Enum):
    """文档生命态。

    ACTIVE 为正常参与检索的文档；DETACHED 为 strict_mirror 同步模式下被脱管的文档——
    其制品/Milvus 索引已移除但 **LRAG workspace 保留**，切回 conservative/archive 模式重扫后
    可恢复为 ACTIVE。检索默认过滤 DETACHED。
    """

    ACTIVE = "active"
    DETACHED = "detached"


# ── 知识库源 ────────────────────────────────────────────────────


@dataclass
class Collection:
    """集合：一组文档的逻辑分类，组织成树形（对应 Zotero 的 collection 树）。

    标识契约（v0.26.3 统一多归属树起）：
        - coll_key 是**稳定逻辑主键**（持久化按 coll_key 定位、唯一）：local 集合为 'L'+随机 hex，
          zotero 集合为 library_id+':'+zotero_collection_key。
        - name 降级为**展示名**，仅要求「同一 parent_key 下唯一」，不再全局唯一。
        - parent_key 为空表示顶层；据此构成树形层级。
        - library_id 区分来源库（本地集合用 'LOCAL'）。

    来源契约：
        - origin=LOCAL 为用户手动创建，可改名/移动/删除/建子集合；origin=ZOTERO 由同步镜像而来，
          **只读**（不可编辑），zotero_collection_key 回链 Zotero 原集合 key。
        - read_only 是 origin 的派生便捷标志（origin=ZOTERO 时为 True），由 service 层强制。
    """

    name: str
    description: str = ""
    created_at: datetime | None = None
    origin: DocumentOrigin = DocumentOrigin.LOCAL
    zotero_collection_key: str = ""
    read_only: bool = False
    coll_key: str = ""
    parent_key: str = ""
    library_id: str = "LOCAL"


@dataclass
class SourceDocument:
    """源文档（制品包，如一个 Zotero PDF 附件或本地上传文件）。

    这是「制品包模型」的核心：`doc_id == document_id == <library_id>_<item_key>_<attachment_key>`，
    其下集中存放全部派生制品（original.pdf / clean.md / pages.json / meta.json / chunks / 向量）。
    无独立 UUID、无兼容层（插件未发行，无旧行）。

    契约：
        - doc_id 即 document_id，是制品包目录名与跨系统稳定主键；content_hash 为原件字节哈希。
        - file_path 指向本地原件位置；markdown_rel_path / pages_rel_path 为制品包内相对路径
          （相对 data_dir/library/<doc_id>/），clean.md 无可见页码，pages.json 存页→字符偏移。
        - origin=ZOTERO 时 read_only=True：文档系统只读，由 service 层强制；LOCAL 可编辑。
        - library_id / zotero_item_key / attachment_key 为 Zotero 标识体系
          （本地上传用 LOCAL 库 + 合成 key）。
        - collection 为**冗余 primary 集合名**（默认展示 + 给需要单一标签的子系统兜底，如
          R2 key 前缀 / Notion select / milvus collection_tag）；归属**真相源**是 collection_keys
          （多归属，对应 collections.coll_key 列表）。tags 为自由标签集合（去重由调用方保证）。
    """

    doc_id: str
    title: str
    file_path: str
    content_type: str
    size_bytes: int
    content_hash: str
    collection: str
    tags: list[str] = field(default_factory=list)
    collection_keys: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    needs_reindex: bool = False
    # ── 制品包 / Zotero 镜像扩展 ──
    library_id: str = "LOCAL"
    zotero_item_key: str = ""
    attachment_key: str = ""
    origin: DocumentOrigin = DocumentOrigin.LOCAL
    read_only: bool = False
    zotero_version: int = 0
    markdown_rel_path: str = ""
    pages_rel_path: str = ""
    converter: str = ""
    converter_version: str = ""
    lifecycle_state: DocumentLifecycle = DocumentLifecycle.ACTIVE
    last_synced_at: datetime | None = None
    local_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def document_id(self) -> str:
        """制品包 ID 的语义别名（与 doc_id 同值）。"""
        return self.doc_id


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


# ── Zotero 逻辑镜像（上游事实源的本地只读镜像）────────────────────
#
# 镜像 Zotero 的逻辑组织模型（library/collection/item/attachment/tag/relation），
# 而非 Zotero 内部 SQLite schema。每个值对象都保留 raw_zotero_json 原样备份，便于未来扩展
# 与 push-ready；归一化字段用于快速查询与 UI 展示。本地上传统一用合成 LOCAL 库表示。


@dataclass
class ZoteroLibrary:
    """Zotero 库。library_type 为 user/group/LOCAL（本地上传合成库）。"""

    library_id: str
    library_type: str
    name: str = ""
    raw_zotero_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZoteroCollection:
    """Zotero 集合（树状，item 可属于多个集合）。

    collection_key 在单个 library 内稳定；parent_collection_key 为空表示顶层。
    origin 标识来源（同步=ZOTERO 只读 / 本地=LOCAL）。
    """

    collection_key: str
    library_id: str
    name: str
    parent_collection_key: str = ""
    origin: DocumentOrigin = DocumentOrigin.ZOTERO
    raw_zotero_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZoteroItem:
    """Zotero 条目（journalArticle/book…）的归一化镜像 + 原始 JSON。

    item_key 在单个 library 内稳定；归一化的 creators/year/venue/doi/url/abstract 供引用与 UI 展示，
    完整字段以 raw_zotero_json 保真存档。version/deleted 用于增量同步判定（design §9）。
    """

    item_key: str
    library_id: str
    item_type: str
    version: int = 0
    deleted: bool = False
    title: str = ""
    creators: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    origin: DocumentOrigin = DocumentOrigin.ZOTERO
    date_added: datetime | None = None
    date_modified: datetime | None = None
    raw_zotero_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZoteroAttachment:
    """Zotero 附件（PDF 等子条目）。

    resolved_path 为解析后的本地绝对路径（由 zotero.sqlite/storage 解析）；md5 用于附件变更判定。
    """

    attachment_key: str
    parent_item_key: str
    library_id: str
    content_type: str = ""
    filename: str = ""
    path: str = ""
    resolved_path: str = ""
    link_mode: str = ""
    md5: str = ""
    raw_zotero_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ZoteroTag:
    """条目标签。type=0 为手动标签，type=1 为自动标签。origin 标识来源。"""

    item_key: str
    tag: str
    type: int = 0
    origin: DocumentOrigin = DocumentOrigin.ZOTERO


@dataclass
class ZoteroRelation:
    """条目间关系（如 dc:relation）。"""

    source_item_key: str
    relation_type: str
    target_item_key: str


@dataclass
class PageChunk:
    """页面级 provenance：clean.md 中某一页的字符偏移区间。

    契约（offset 不变量，见 ingest 清洗内核）：
        - markdown_start_char / markdown_end_char 是**写盘归一化（统一 LF）后** clean.md 的
          Python str 字符偏移（左闭右开），非每页局部偏移。
        - 语义分块的 pages 列表由 chunk 的 [start_char,end_char) 与各页区间求交得出。
    """

    document_id: str
    page: int
    markdown_start_char: int
    markdown_end_char: int


# ── 用户侧持久化状态 ────────────────────────────────────────────


@dataclass
class ScopedNote:
    """文档/集合笔记，字段形态贴近 Zotero note，便于后续 push 对接。

    scope_type 为 document 或 collection；scope_key 分别对应 doc_id 或 collection name。
    Zotero 相关字段只做本地对齐和备份，不代表当前会写回 Zotero。
    """

    id: str
    scope_type: str
    scope_key: str
    content: str
    note_html: str = ""
    doc_id: str = ""
    collection_name: str = ""
    library_id: str = "LOCAL"
    parent_item_key: str = ""
    parent_attachment_key: str = ""
    zotero_note_key: str = ""
    zotero_version: int = 0
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    relations: dict[str, Any] = field(default_factory=dict)
    linked: bool = False
    source: str = "manual"
    chat_conversation_id: str = ""
    chat_message_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    raw_zotero_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsoleScopeState:
    """控制台右侧上下文状态，用于恢复文档/集合层级的选择结果。"""

    scope_type: str
    scope_key: str
    selected_collection: str = ""
    selected_doc_id: str = ""
    note_doc_id: str = ""
    right_panel: str = ""
    reading_mode: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime | None = None


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


__all__ = [
    "SyncTargetKind",
    "SyncStatus",
    "QuotaLevel",
    "DocumentOrigin",
    "DocumentLifecycle",
    "Collection",
    "SourceDocument",
    "DocumentChunk",
    "ZoteroLibrary",
    "ZoteroCollection",
    "ZoteroItem",
    "ZoteroAttachment",
    "ZoteroTag",
    "ZoteroRelation",
    "PageChunk",
    "ScopedNote",
    "ConsoleScopeState",
    "SyncRecord",
    "QuotaUsage",
    "QuotaWarning",
]
