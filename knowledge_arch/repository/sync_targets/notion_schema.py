"""Notion 两表（Articles / QA）的属性 schema 与页面载荷构造（repository 层纯函数）。

为什么存在：属性构造、路径/祖先名展开、指纹计算与正文切块都是纯数据翻译，
独立成模块让 notion.py 专注幂等 upsert 编排并守住文件行数红线。
本模块只依赖 domain，无 I/O。

表设计（用户确认的「单库 filter」方案）：
    - Articles 单库：所有文章一行一篇；文件树不建独立实体，编码进两个可筛选属性——
      Collections multi_select 含**归属集合及其全部祖先名**（在 Notion 里筛任一集合名
      即得其子树全部文章），Collection Path select 为 primary 集合完整路径（分组用）。
    - QA 库：agent/Ask 推送的问答记录（append-only），Citations relation 链回 Articles。
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from knowledge_arch.domain.models import Collection, DocumentChunk, SourceDocument

# ── 属性名常量（schema 与页面载荷共用，降级逻辑按名剔除）─────────

PROP_NAME = "Name"
PROP_DOC_ID = "DocID"
PROP_TAGS = "Tags"
PROP_COLLECTIONS = "Collections"
PROP_COLLECTION_PATH = "Collection Path"
PROP_ORIGIN = "Origin"
PROP_LIFECYCLE = "Lifecycle"
PROP_CONTENT_HASH = "Content Hash"
PROP_SIZE_BYTES = "Size Bytes"
PROP_UPDATED = "Updated"

PROP_QUESTION = "Question"
PROP_NOTE_ID = "NoteID"
PROP_CITATIONS = "Citations"
PROP_SOURCE = "Source"
PROP_CREATED = "Created"

# Notion 平台约束：select/multi_select 选项名禁逗号、上限 100 字符；
# 单个 rich_text 块上限 2000 字符（切块留余量取 1800）。
_OPTION_MAX_LEN = 100
_RICH_TEXT_LIMIT = 2000
BLOCK_TEXT_LIMIT = 1800
MAX_BODY_BLOCKS = 30
PATH_SEPARATOR = " / "

# 指纹字段分隔符（不可见控制符，避免字段值拼接歧义）
_HASH_SEP = "\x1f"


# ── 基础构件 ────────────────────────────────────────────────────


def _option_name(name: str) -> str:
    """净化 select/multi_select 选项名：逗号会被 Notion 拆成多选项，替换为全角。"""
    return name.replace(",", "，")[:_OPTION_MAX_LEN]


def _rich_text_value(content: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": content[:_RICH_TEXT_LIMIT]}}]}


def paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


# ── 集合树展开（文件树 → 可筛选属性）────────────────────────────


def build_collection_paths(collections: list[Collection]) -> dict[str, str]:
    """coll_key → 完整路径（"根 / 子 / 孙"）。脏数据成环时截断该支并保留已解析前缀。"""
    by_key = {c.coll_key: c for c in collections if c.coll_key}
    paths: dict[str, str] = {}
    for coll in collections:
        if not coll.coll_key:
            continue
        names: list[str] = []
        seen: set[str] = set()
        node: Collection | None = coll
        while node is not None and node.coll_key not in seen:
            seen.add(node.coll_key)
            names.append(node.name)
            node = by_key.get(node.parent_key) if node.parent_key else None
        paths[coll.coll_key] = PATH_SEPARATOR.join(reversed(names))
    return paths


def expand_ancestor_names(
    coll_keys: list[str], collections: list[Collection]
) -> list[str]:
    """归属集合 + 各自全部祖先的展示名（排序去重）。

    这是「筛任一集合名即得其子树全部文章」的实现基础：文章带上祖先名后，
    在 Notion 用 Collections contains <祖先名> 即可命中整个子树。
    """
    by_key = {c.coll_key: c for c in collections if c.coll_key}
    names: set[str] = set()
    for key in coll_keys:
        node = by_key.get(key)
        seen: set[str] = set()
        while node is not None and node.coll_key not in seen:
            seen.add(node.coll_key)
            if node.name:
                names.add(node.name)
            node = by_key.get(node.parent_key) if node.parent_key else None
    return sorted(names)


def primary_collection_path(
    document: SourceDocument,
    collections: list[Collection],
    paths: dict[str, str],
) -> str:
    """primary 集合的完整路径：优先取归属中 name==document.collection 的节点路径，
    其次取首个归属节点路径，最后回退冗余 primary 名本身。"""
    by_key = {c.coll_key: c for c in collections if c.coll_key}
    for key in document.collection_keys:
        node = by_key.get(key)
        if node is not None and node.name == document.collection:
            return paths.get(key, document.collection)
    for key in document.collection_keys:
        if key in paths:
            return paths[key]
    return document.collection


# ── Articles DB ─────────────────────────────────────────────────


def articles_db_properties() -> dict[str, Any]:
    """Articles 库标准列 schema（建库/缺列对账的唯一真相源）。"""
    return {
        PROP_NAME: {"title": {}},
        PROP_DOC_ID: {"rich_text": {}},
        PROP_TAGS: {"multi_select": {}},
        PROP_COLLECTIONS: {"multi_select": {}},
        PROP_COLLECTION_PATH: {"select": {}},
        PROP_ORIGIN: {"select": {}},
        PROP_LIFECYCLE: {"select": {}},
        PROP_CONTENT_HASH: {"rich_text": {}},
        PROP_SIZE_BYTES: {"number": {}},
        PROP_UPDATED: {"date": {}},
    }


def article_page_properties(
    document: SourceDocument,
    *,
    path: str,
    collection_names: list[str],
) -> dict[str, Any]:
    """一篇文章的页面属性载荷（与 articles_db_properties 列对齐）。"""
    properties: dict[str, Any] = {
        PROP_NAME: {"title": [{"text": {"content": document.title}}]},
        PROP_DOC_ID: _rich_text_value(document.doc_id),
        PROP_TAGS: {
            "multi_select": [{"name": _option_name(t)} for t in document.tags if t]
        },
        PROP_COLLECTIONS: {
            "multi_select": [
                {"name": _option_name(n)} for n in collection_names if n
            ]
        },
        PROP_ORIGIN: {"select": {"name": document.origin.value}},
        PROP_LIFECYCLE: {"select": {"name": document.lifecycle_state.value}},
        PROP_CONTENT_HASH: _rich_text_value(document.content_hash),
        PROP_SIZE_BYTES: {"number": document.size_bytes},
    }
    if path:
        properties[PROP_COLLECTION_PATH] = {"select": {"name": _option_name(path)}}
    if document.updated_at is not None:
        properties[PROP_UPDATED] = {"date": {"start": document.updated_at.isoformat()}}
    return properties


def document_metadata_hash(
    document: SourceDocument,
    *,
    path: str,
    collection_names: list[str],
) -> str:
    """文章元数据指纹：进指纹的字段与 article_page_properties 载荷一一对应。

    集合改名/移动会改变 path 或 collection_names → 指纹变化 → 增量推送自动联动。
    """
    parts = [
        document.title,
        document.collection,
        "|".join(sorted(document.tags)),
        "|".join(sorted(collection_names)),
        path,
        document.origin.value,
        document.lifecycle_state.value,
        document.content_hash,
        str(document.size_bytes),
        # Updated 列来源 updated_at，纳入指纹以免「仅时间戳变化」时页面 Updated 滞后。
        document.updated_at.isoformat() if document.updated_at is not None else "",
    ]
    return hashlib.sha256(_HASH_SEP.join(parts).encode("utf-8")).hexdigest()


# ── QA DB ───────────────────────────────────────────────────────


def qa_db_properties(articles_database_id: str = "") -> dict[str, Any]:
    """QA 库标准列 schema；articles_database_id 非空时带 Citations relation。"""
    properties: dict[str, Any] = {
        PROP_QUESTION: {"title": {}},
        PROP_NOTE_ID: {"rich_text": {}},
        PROP_TAGS: {"multi_select": {}},
        PROP_SOURCE: {"select": {}},
        PROP_CREATED: {"date": {}},
    }
    if articles_database_id:
        properties[PROP_CITATIONS] = {
            "relation": {
                "database_id": articles_database_id,
                "single_property": {},
            }
        }
    return properties


def qa_page_properties(
    *,
    title: str,
    note_id: str,
    tags: list[str],
    citation_page_ids: list[str],
    source: str,
    created_at_iso: str,
) -> dict[str, Any]:
    """一条 QA 记录的页面属性载荷；citation_page_ids 为空时不写 Citations。"""
    properties: dict[str, Any] = {
        PROP_QUESTION: {"title": [{"text": {"content": title}}]},
        PROP_NOTE_ID: _rich_text_value(note_id),
        PROP_TAGS: {"multi_select": [{"name": _option_name(t)} for t in tags if t]},
        PROP_SOURCE: {"select": {"name": _option_name(source or "chat")}},
        PROP_CREATED: {"date": {"start": created_at_iso}},
    }
    if citation_page_ids:
        properties[PROP_CITATIONS] = {
            "relation": [{"id": page_id} for page_id in citation_page_ids]
        }
    return properties


# ── 正文块构造 ──────────────────────────────────────────────────


def text_to_paragraph_blocks(
    text: str,
    *,
    limit: int = BLOCK_TEXT_LIMIT,
    max_blocks: int = MAX_BODY_BLOCKS,
) -> list[dict[str, Any]]:
    """长文 → paragraph 块列表：按段落边界（空行）聚合，超长段硬切；超 max_blocks 截断。"""
    normalized = (text or "").strip()
    if not normalized:
        return []
    pieces: list[str] = []
    for para in normalized.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > limit:
            pieces.append(para[:limit])
            para = para[limit:]
        if para:
            pieces.append(para)
    truncated = len(pieces) > max_blocks
    blocks = [paragraph_block(p) for p in pieces[: max_blocks - 1 if truncated else max_blocks]]
    if truncated:
        blocks.append(paragraph_block("…（正文过长，其余内容已截断，完整内容见本地）"))
    return blocks


def chunk_preview_blocks(chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
    """文章页正文：可折叠 toggle + 前 3 个切片子段落（每块截断 1000 字符）。"""
    children: list[dict[str, Any]] = []
    for chunk in chunks[:3]:
        text = chunk.text
        if len(text) > 1000:
            text = text[:1000] + "..."
        children.append(paragraph_block(f"[Chunk #{chunk.ordinal}] {text}"))

    toggle: dict[str, Any] = {
        "rich_text": [
            {"type": "text", "text": {"content": "本地切片摘要 (Chunks Preview)"}}
        ]
    }
    if children:
        toggle["children"] = children
    return [{"object": "block", "type": "toggle", "toggle": toggle}]


def large_file_callout_block() -> dict[str, Any]:
    """>5MiB 大文件的提示块（不做二进制镜像）。"""
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": (
                            "⚠️ [Notion 免费版限制] 该文件大小超过 5MiB，"
                            "已跳过文件二进制镜像。您可以去本地原件中查看。"
                        )
                    },
                }
            ],
            "icon": {"emoji": "⚠️"},
            "color": "yellow_background",
        },
    }


__all__ = [
    "PROP_NAME",
    "PROP_DOC_ID",
    "PROP_TAGS",
    "PROP_COLLECTIONS",
    "PROP_COLLECTION_PATH",
    "PROP_ORIGIN",
    "PROP_LIFECYCLE",
    "PROP_CONTENT_HASH",
    "PROP_SIZE_BYTES",
    "PROP_UPDATED",
    "PROP_QUESTION",
    "PROP_NOTE_ID",
    "PROP_CITATIONS",
    "PROP_SOURCE",
    "PROP_CREATED",
    "BLOCK_TEXT_LIMIT",
    "MAX_BODY_BLOCKS",
    "PATH_SEPARATOR",
    "build_collection_paths",
    "expand_ancestor_names",
    "primary_collection_path",
    "articles_db_properties",
    "article_page_properties",
    "document_metadata_hash",
    "qa_db_properties",
    "qa_page_properties",
    "text_to_paragraph_blocks",
    "chunk_preview_blocks",
    "large_file_callout_block",
    "paragraph_block",
]
