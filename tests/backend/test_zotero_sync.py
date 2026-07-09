"""Zotero 单向 Pull 集成测试：合成 zotero.sqlite → reader → pipeline（三种 sync_mode）。

构造最小 Zotero schema 子集 + storage/<key>/paper.pdf，验证：
镜像表、制品包生成、incremental 跳过、conservative 硬删除、strict 脱管(detached)、archive 只增不删、
linked 存储模式（原件留外部）、zotmoov 存储模式（ZotMoov 目录解析 + 文件名索引兜底）。
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import fitz
import pytest

from knowledge_arch.adapters.zotero.sqlite_reader import ZoteroSqliteReader
from knowledge_arch.config import Config, SourceStoreConfig
from knowledge_arch.domain.models import DocumentLifecycle, DocumentOrigin
from knowledge_arch.managers.ingest_manager import IngestManager, make_document_id
from knowledge_arch.pipelines.zotero_sync_pipeline import ZoteroSyncPipeline
from knowledge_arch.repository.source_store.memory import InMemorySourceDocumentStore
from knowledge_arch.zotero_sync_job import ZoteroSyncJob

_pdf_available = importlib.util.find_spec("pymupdf4llm") is not None
pytestmark = pytest.mark.skipif(not _pdf_available, reason="pymupdf4llm not installed")

LIB = "1"
ITEM = "ITEMAAAA"
ATT = "ATTAAAAA"
DOC_ID = f"{LIB}_{ITEM}_{ATT}"


def _make_pdf(path: Path, text: str = "Zotero synced paper content. Value ecology.") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 750), text)
    doc.save(path)
    doc.close()


def _build_zotero_db(
    data_dir: Path,
    *,
    with_attachment: bool = True,
    version: int = 5,
    linked_attachments: list[tuple[str, str]] | None = None,
) -> None:
    """构造最小 Zotero schema 子集。linked_attachments 为 (attachment_key, db_path) 的
    linkMode=2 附件行（模拟 ZotMoov 移动后的 linked_file），挂在同一文献条目下。"""
    db = sqlite3.connect(data_dir / "zotero.sqlite")
    db.executescript(
        """
        CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER,
                            key TEXT, version INTEGER, dateAdded TEXT, dateModified TEXT);
        CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, lastName TEXT, firstName TEXT,
                              fieldMode INTEGER);
        CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER,
                                  orderIndex INTEGER);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT,
                                 parentCollectionID INTEGER, key TEXT, libraryID INTEGER);
        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER, orderIndex INTEGER);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER);
        CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, linkMode INTEGER,
                                     contentType TEXT, path TEXT, storageHash TEXT);
        """
    )
    db.execute("INSERT INTO libraries VALUES (1, 'user')")
    db.execute("INSERT INTO itemTypes VALUES (1, 'journalArticle')")
    db.execute("INSERT INTO itemTypes VALUES (2, 'attachment')")
    # 文献条目
    db.execute(
        "INSERT INTO items VALUES (10, 1, 1, ?, ?, '2026-06-01 10:00:00', '2026-06-02 10:00:00')",
        (ITEM, version),
    )
    # 字段：title/date/DOI/abstractNote/publicationTitle
    db.executemany("INSERT INTO fields VALUES (?, ?)", [
        (1, "title"), (2, "date"), (3, "DOI"), (4, "abstractNote"), (5, "publicationTitle"),
    ])
    db.executemany("INSERT INTO itemDataValues VALUES (?, ?)", [
        (101, "Ecological Value"), (102, "2025-03-01"), (103, "10.1/x"),
        (104, "An abstract."), (105, "Journal of Ecology"),
    ])
    db.executemany("INSERT INTO itemData VALUES (?, ?, ?)", [
        (10, 1, 101), (10, 2, 102), (10, 3, 103), (10, 4, 104), (10, 5, 105),
    ])
    db.execute("INSERT INTO creators VALUES (1, 'Li', 'Wei', 0)")
    db.execute("INSERT INTO itemCreators VALUES (10, 1, 1, 0)")
    # 集合
    db.execute("INSERT INTO collections VALUES (100, 'Value Ecology', NULL, 'COLLAAAA', 1)")
    db.execute("INSERT INTO collectionItems VALUES (100, 10, 0)")
    # 标签
    db.execute("INSERT INTO tags VALUES (1, 'ecology')")
    db.execute("INSERT INTO itemTags VALUES (10, 1, 0)")
    # 附件
    if with_attachment:
        db.execute(
            "INSERT INTO items VALUES (11, 2, 1, ?, ?, '2026-06-01 10:00:00', "
            "'2026-06-02 10:00:00')",
            (ATT, version),
        )
        db.execute(
            "INSERT INTO itemAttachments VALUES (11, 10, 0, 'application/pdf', "
            "'storage:paper.pdf', 'md5hash')"
        )
        _make_pdf(data_dir / "storage" / ATT / "paper.pdf")
    for i, (att_key, db_path) in enumerate(linked_attachments or []):
        item_id = 20 + i
        db.execute(
            "INSERT INTO items VALUES (?, 2, 1, ?, ?, '2026-06-01 10:00:00', "
            "'2026-06-02 10:00:00')",
            (item_id, att_key, version),
        )
        db.execute(
            "INSERT INTO itemAttachments VALUES (?, 10, 2, 'application/pdf', ?, NULL)",
            (item_id, db_path),
        )
    db.commit()
    db.close()


def _pipeline(
    tmp_path: Path,
    data_dir: Path,
    sync_mode: str,
    storage_mode: str = "managed_copy",
    extra: dict | None = None,
):
    store = InMemorySourceDocumentStore()
    ingest = IngestManager(
        source_store=store, config=SourceStoreConfig(), data_dir=tmp_path / "plugin"
    )
    section: dict = {
        "enabled": True,
        "zotero_data_dir": str(data_dir),
        "sync_mode": sync_mode,
        "storage_mode": storage_mode,
    }
    section.update(extra or {})
    cfg = Config({"zotero_sync": section})
    indexed: list[str] = []

    async def index_cb(doc_id: str, collection: str) -> None:
        indexed.append(doc_id)

    removed: list[str] = []

    async def remove_cb(doc_id: str) -> None:
        removed.append(doc_id)

    pipeline = ZoteroSyncPipeline(
        source_store=store,
        ingest_manager=ingest,
        config=cfg,
        index_document=index_cb,
        remove_index=remove_cb,
    )
    return store, pipeline, indexed, removed


# ── reader ───────────────────────────────────────────────────────


def test_reader_parses_items_and_attachments(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    snap = ZoteroSqliteReader(data_dir).read_snapshot()
    assert snap.library.library_id == "1"
    assert len(snap.items) == 1
    item = snap.items[0]
    assert item.item_key == ITEM
    assert item.title == "Ecological Value"
    assert item.creators == ["Li, Wei"]
    assert item.year == "2025"
    assert item.venue == "Journal of Ecology"
    assert item.doi == "10.1/x"
    assert len(snap.attachments) == 1
    assert Path(snap.attachments[0].resolved_path).parts[-2:] == (ATT, "paper.pdf")
    assert snap.collection_items == [("COLLAAAA", ITEM)]
    assert snap.item_tags[ITEM][0].tag == "ecology"


# ── pipeline: conservative ───────────────────────────────────────


async def test_pull_conservative_creates_artifact_bundle(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, indexed, _ = _pipeline(tmp_path, data_dir, "conservative")

    result = await pipeline.pull()
    assert result.new_document_ids == [DOC_ID]
    assert indexed == [DOC_ID]

    doc = await store.get_document(DOC_ID)
    assert doc is not None
    assert doc.origin is DocumentOrigin.ZOTERO
    assert doc.read_only is True
    assert doc.collection == "Value Ecology"
    assert doc.last_synced_at is not None
    assert doc.lifecycle_state is DocumentLifecycle.ACTIVE
    # 制品包 clean.md 落盘
    assert (tmp_path / "plugin" / "library" / DOC_ID / "clean.md").exists()
    # 镜像表
    assert (await store.get_zotero_item("1", ITEM)) is not None

    # 第二次 pull：增量跳过
    result2 = await pipeline.pull()
    assert result2.skipped_unchanged == 1
    assert result2.new_document_ids == []


# ── pipeline: server(web api) 模式惰性下载 ───────────────────────


async def test_pull_server_mode_downloads_lazily_and_skips_unchanged(tmp_path: Path) -> None:
    """web 模式回归：首次按需下载并摄入；二次增量跳过且**不再下载**。

    守护「reading 阶段不再串行拉全库 = 进度不假死在 3%」与「未变更件不重下整库」两条修复，
    防止 read_snapshot 的预下载回归。"""
    cloud_pdf = tmp_path / "cloud" / "paper.pdf"
    _make_pdf(cloud_pdf)
    downloads: list[str] = []

    class FakeClient:
        def get_current_key(self) -> dict:
            return {
                "userID": 123,
                "username": "alice",
                "access": {"user": {"library": True, "files": True}},
            }

        def list_user_collections(self, user_id: str) -> list[dict]:
            return [{"key": "COLL1", "data": {"key": "COLL1", "name": "Papers"}}]

        def list_user_items(self, user_id: str) -> list[dict]:
            return [
                {"key": "ITEM1", "version": 7, "data": {
                    "key": "ITEM1", "itemType": "journalArticle",
                    "title": "Server Paper", "collections": ["COLL1"]}},
                {"key": "ATT1", "version": 7, "data": {
                    "key": "ATT1", "itemType": "attachment", "parentItem": "ITEM1",
                    "contentType": "application/pdf", "filename": "paper.pdf",
                    "linkMode": "imported_file"}},
            ]

        def download_user_file(self, user_id: str, item_key: str, target_path: Path) -> Path:
            downloads.append(item_key)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(cloud_pdf.read_bytes())
            return target_path

    store = InMemorySourceDocumentStore()
    ingest = IngestManager(
        source_store=store, config=SourceStoreConfig(), data_dir=tmp_path / "plugin"
    )
    cfg = Config({"zotero_sync": {"enabled": True, "access_mode": "server"}})
    pipeline = ZoteroSyncPipeline(
        source_store=store,
        ingest_manager=ingest,
        config=cfg,
        web_client_factory=lambda key: FakeClient(),  # type: ignore[arg-type,return-value]
        zotero_api_key_provider=lambda: "k",
        web_cache_dir=tmp_path / "webcache",
    )

    doc_id = make_document_id("123", "ITEM1", "ATT1")
    result = await pipeline.pull()
    assert result.new_document_ids == [doc_id]
    assert downloads == ["ATT1"]  # 首次：按需下载恰好一次
    assert (await store.get_document(doc_id)) is not None

    result2 = await pipeline.pull()
    assert result2.skipped_unchanged == 1
    assert result2.new_document_ids == []
    assert downloads == ["ATT1"]  # 二次增量：未变更不重下


async def test_pull_derives_unified_tree_and_membership(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, _ = _pipeline(tmp_path, data_dir, "conservative")

    await pipeline.pull()

    # Zotero 集合派生进统一 collections（树形 + 只读），coll_key=lib:zkey
    cols = {c.coll_key: c for c in await store.list_collections()}
    assert "1:COLLAAAA" in cols
    zc = cols["1:COLLAAAA"]
    assert zc.origin is DocumentOrigin.ZOTERO and zc.read_only is True
    assert zc.name == "Value Ecology"

    # 文档多归属真相源指向统一 coll_key
    doc = await store.get_document(DOC_ID)
    assert doc.collection_keys == ["1:COLLAAAA"]
    # 含后代范围检索能命中该文档
    listed = await store.list_documents_by_collection_key("1:COLLAAAA", descendants=True)
    assert [d.doc_id for d in listed] == [DOC_ID]


async def test_pull_conservative_deletes_removed(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, removed = _pipeline(tmp_path, data_dir, "conservative")
    await pipeline.pull()
    assert await store.get_document(DOC_ID) is not None

    # 模拟 Zotero 删除附件：重建无附件的 DB
    (data_dir / "zotero.sqlite").unlink()
    _build_zotero_db(data_dir, with_attachment=False)
    result = await pipeline.pull()
    assert result.removed_document_ids == [DOC_ID]
    assert await store.get_document(DOC_ID) is None
    assert removed == [DOC_ID]


# ── pipeline: strict (detached) ──────────────────────────────────


async def test_pull_strict_detaches_removed_and_reattaches(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, removed = _pipeline(tmp_path, data_dir, "strict_mirror")
    result1 = await pipeline.pull()
    assert result1.needs_milvus_rebuild is True

    # Zotero 删除附件 → strict 应脱管（detached），不删除文档、不动 LRAG
    (data_dir / "zotero.sqlite").unlink()
    _build_zotero_db(data_dir, with_attachment=False)
    result2 = await pipeline.pull()
    assert result2.detached_document_ids == [DOC_ID]
    assert DOC_ID in removed  # Milvus 移除
    doc = await store.get_document(DOC_ID)
    assert doc is not None and doc.lifecycle_state is DocumentLifecycle.DETACHED

    # 附件回归 → 重新 active（reattach）
    (data_dir / "zotero.sqlite").unlink()
    _build_zotero_db(data_dir)
    result3 = await pipeline.pull()
    assert result3.reattached_document_ids == [DOC_ID]
    doc3 = await store.get_document(DOC_ID)
    assert doc3 is not None and doc3.lifecycle_state is DocumentLifecycle.ACTIVE


# ── pipeline: archive (只增不删) ─────────────────────────────────


async def test_pull_archive_keeps_removed(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, _ = _pipeline(tmp_path, data_dir, "archive")
    await pipeline.pull()

    (data_dir / "zotero.sqlite").unlink()
    _build_zotero_db(data_dir, with_attachment=False)
    result = await pipeline.pull()
    assert result.removed_document_ids == []
    assert result.detached_document_ids == []
    assert await store.get_document(DOC_ID) is not None  # 归档：保留


# ── pipeline: linked 存储模式 ────────────────────────────────────


async def test_pull_linked_keeps_original_external(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, _ = _pipeline(tmp_path, data_dir, "conservative", storage_mode="linked")
    await pipeline.pull()

    doc = await store.get_document(DOC_ID)
    assert doc is not None
    # linked：file_path 指向 Zotero storage 外部原件，不在插件制品包内
    assert str(data_dir / "storage" / ATT / "paper.pdf") == doc.file_path
    assert not (tmp_path / "plugin" / "library" / DOC_ID / "original.pdf").exists()
    # 但派生制品 clean.md 仍在插件内
    assert (tmp_path / "plugin" / "library" / DOC_ID / "clean.md").exists()


# ── reader: linked_file 路径解析回归 ─────────────────────────────


def test_reader_linked_relative_leaves_resolved_empty(tmp_path: Path) -> None:
    """回归：'attachments:rel' 不得按 CWD 相对路径误判，resolved 留空交 pipeline 解析。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK01", "attachments:sub/a.pdf")],
    )
    snap = ZoteroSqliteReader(data_dir).read_snapshot()
    assert len(snap.attachments) == 1
    att = snap.attachments[0]
    assert att.link_mode == "linked_file"
    assert att.filename == "a.pdf"
    assert att.resolved_path == ""


# ── pipeline: zotmoov 存储模式 ───────────────────────────────────


async def test_pull_zotmoov_resolves_attachments_relative(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "sub" / "dir" / "paper2.pdf")
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK01", "attachments:sub/dir/paper2.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="zotmoov", extra={"zotmoov_root": str(zroot)},
    )

    avail = pipeline.is_available()
    assert avail["zotmoov_probe"]["valid"] is True  # type: ignore[index]

    doc_id = make_document_id(LIB, ITEM, "ATTLNK01")
    result = await pipeline.pull()
    assert result.new_document_ids == [doc_id]
    doc = await store.get_document(doc_id)
    assert doc is not None
    # zotmoov：file_path 指向 ZotMoov 目录内原件，原件不复制进插件制品包
    assert doc.file_path == str(zroot / "sub" / "dir" / "paper2.pdf")
    assert not (tmp_path / "plugin" / "library" / doc_id / "original.pdf").exists()
    assert (tmp_path / "plugin" / "library" / doc_id / "clean.md").exists()


async def test_pull_zotmoov_absolute_miss_falls_back_to_index(tmp_path: Path) -> None:
    """DB 存宿主机绝对路径（容器内失效）→ 按文件名递归索引兜底命中。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "x" / "paper3.pdf")
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK02", "/host/only/paper3.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="zotmoov", extra={"zotmoov_root": str(zroot)},
    )
    result = await pipeline.pull()
    doc_id = make_document_id(LIB, ITEM, "ATTLNK02")
    assert result.new_document_ids == [doc_id]
    doc = await store.get_document(doc_id)
    assert doc is not None
    assert doc.file_path == str(zroot / "x" / "paper3.pdf")


async def test_pull_zotmoov_duplicate_filename_skipped_with_error(tmp_path: Path) -> None:
    """重名且无法消歧：绝不静默挑一个，跳过并把原因写进 result.errors。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "a" / "paper.pdf")
    _make_pdf(zroot / "b" / "paper.pdf")
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK03", "/gone/paper.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="zotmoov", extra={"zotmoov_root": str(zroot)},
    )
    result = await pipeline.pull()
    assert result.new_document_ids == []
    assert await store.get_document(make_document_id(LIB, ITEM, "ATTLNK03")) is None
    assert any("同名" in e for e in result.errors)


async def test_pull_zotmoov_duplicate_disambiguated_by_parent_dir(tmp_path: Path) -> None:
    """重名但 DB 路径父目录名尾段可消歧 → 正常命中。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "a" / "paper.pdf")
    _make_pdf(zroot / "b" / "paper.pdf")
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK03", "/gone/b/paper.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="zotmoov", extra={"zotmoov_root": str(zroot)},
    )
    result = await pipeline.pull()
    doc_id = make_document_id(LIB, ITEM, "ATTLNK03")
    assert result.new_document_ids == [doc_id]
    doc = await store.get_document(doc_id)
    assert doc is not None
    assert doc.file_path == str(zroot / "b" / "paper.pdf")
    assert result.errors == []


async def test_pull_zotmoov_mixed_imported_and_moved(tmp_path: Path) -> None:
    """混合库：仍在 storage/ 的 imported 件与已被 ZotMoov 移走的 linked 件都入库。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "moved.pdf")
    _build_zotero_db(
        data_dir,
        linked_attachments=[("ATTLNK04", "attachments:moved.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="zotmoov", extra={"zotmoov_root": str(zroot)},
    )
    result = await pipeline.pull()
    moved_id = make_document_id(LIB, ITEM, "ATTLNK04")
    assert set(result.new_document_ids) == {DOC_ID, moved_id}
    imported = await store.get_document(DOC_ID)
    moved = await store.get_document(moved_id)
    assert imported is not None and moved is not None
    assert moved.file_path == str(zroot / "moved.pdf")


async def test_pull_server_zotmoov_local_dir_wins_web_fallback(tmp_path: Path) -> None:
    """server+zotmoov：linked 件从本地目录解析（不下载），imported 件惰性下载且复制进制品包。"""
    cloud_pdf = tmp_path / "cloud" / "paper.pdf"
    _make_pdf(cloud_pdf)
    zroot = tmp_path / "zotmoov"
    _make_pdf(zroot / "sub" / "moved.pdf")
    downloads: list[str] = []

    class FakeClient:
        def get_current_key(self) -> dict:
            return {
                "userID": 123,
                "username": "alice",
                "access": {"user": {"library": True, "files": True}},
            }

        def list_user_collections(self, user_id: str) -> list[dict]:
            return []

        def list_user_items(self, user_id: str) -> list[dict]:
            return [
                {"key": "ITEM1", "version": 7, "data": {
                    "key": "ITEM1", "itemType": "journalArticle", "title": "Server Paper"}},
                {"key": "ATT1", "version": 7, "data": {
                    "key": "ATT1", "itemType": "attachment", "parentItem": "ITEM1",
                    "contentType": "application/pdf", "filename": "paper.pdf",
                    "linkMode": "imported_file"}},
                {"key": "ATTL", "version": 7, "data": {
                    "key": "ATTL", "itemType": "attachment", "parentItem": "ITEM1",
                    "contentType": "application/pdf", "linkMode": "linked_file",
                    "path": "attachments:sub/moved.pdf"}},
            ]

        def download_user_file(self, user_id: str, item_key: str, target_path: Path) -> Path:
            downloads.append(item_key)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(cloud_pdf.read_bytes())
            return target_path

    store = InMemorySourceDocumentStore()
    ingest = IngestManager(
        source_store=store, config=SourceStoreConfig(), data_dir=tmp_path / "plugin"
    )
    cfg = Config({"zotero_sync": {
        "enabled": True, "access_mode": "server",
        "storage_mode": "zotmoov", "zotmoov_root": str(zroot),
    }})
    pipeline = ZoteroSyncPipeline(
        source_store=store,
        ingest_manager=ingest,
        config=cfg,
        web_client_factory=lambda key: FakeClient(),  # type: ignore[arg-type,return-value]
        zotero_api_key_provider=lambda: "k",
        web_cache_dir=tmp_path / "webcache",
    )

    result = await pipeline.pull()
    imported_id = make_document_id("123", "ITEM1", "ATT1")
    moved_id = make_document_id("123", "ITEM1", "ATTL")
    assert set(result.new_document_ids) == {imported_id, moved_id}
    assert downloads == ["ATT1"]  # linked 件不触发下载

    moved = await store.get_document(moved_id)
    assert moved is not None
    assert moved.file_path == str(zroot / "sub" / "moved.pdf")
    # web 下载件强制复制进制品包（缓存目录不可作为 link 归宿）
    imported = await store.get_document(imported_id)
    assert imported is not None
    assert str(tmp_path / "plugin") in imported.file_path


# ── pipeline: linked 模式 'attachments:' 子路径兜底回归 ──────────


async def test_pull_linked_resolves_attachments_subpath(tmp_path: Path) -> None:
    """回归：linked 兜底须先按相对子路径拼 linked_root，不能只拼 basename 丢子目录。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    lroot = tmp_path / "linkedroot"
    _make_pdf(lroot / "sub" / "p.pdf")
    _build_zotero_db(
        data_dir,
        with_attachment=False,
        linked_attachments=[("ATTLNK05", "attachments:sub/p.pdf")],
    )
    store, pipeline, _, _ = _pipeline(
        tmp_path, data_dir, "conservative",
        storage_mode="linked", extra={"linked_root": str(lroot)},
    )
    result = await pipeline.pull()
    doc_id = make_document_id(LIB, ITEM, "ATTLNK05")
    assert result.new_document_ids == [doc_id]
    doc = await store.get_document(doc_id)
    assert doc is not None
    assert doc.file_path == str(lroot / "sub" / "p.pdf")


# ── 目录探针 ─────────────────────────────────────────────────────


def test_probe_zotmoov_root_branches(tmp_path: Path) -> None:
    from knowledge_arch.adapters.zotero import paths as zpaths

    unset = zpaths.probe_zotmoov_root("")
    assert unset["valid"] is False and "未配置" in str(unset["reason"])
    missing = zpaths.probe_zotmoov_root(str(tmp_path / "nope"))
    assert missing["valid"] is False and "不存在" in str(missing["reason"])
    ok = zpaths.probe_zotmoov_root(str(tmp_path))
    assert ok["valid"] is True and ok["resolved"] == str(tmp_path)


# ── pipeline: 本地干跑探针 ───────────────────────────────────────


def test_probe_local_read_counts_without_mirroring(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    store, pipeline, _, _ = _pipeline(tmp_path, data_dir, "conservative")

    probe = pipeline.probe_local_read()

    assert probe["available"] is True
    assert probe["item_count"] == 1
    assert probe["collection_count"] == 1
    assert probe["attachment_count"] == 1
    assert probe["pdf_attachment_count"] == 1
    # 干读：不写入 source_store
    assert store._documents == {}  # type: ignore[attr-defined]


# ── pipeline: 进度任务 + 错误可见性 ───────────────────────────────


async def test_pull_updates_progress_job(tmp_path: Path) -> None:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)
    _, pipeline, _, _ = _pipeline(tmp_path, data_dir, "conservative")

    job = ZoteroSyncJob(incremental=False)
    job.start()
    result = await pipeline.pull(incremental=False, progress=job)

    assert not result.errors
    assert job.docs_total == 1
    assert job.docs_processed == 1
    assert job.docs_failed == 0
    assert job.new_count == 1
    assert job.to_dict()["stage"] == "finalizing"  # 走完全部阶段


async def test_index_side_effect_failure_surfaces_in_errors(tmp_path: Path) -> None:
    """回归：索引副作用失败（如 VectorStore 未配置）必须进 result.errors，不可静默吞掉。"""
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    _build_zotero_db(data_dir)

    store = InMemorySourceDocumentStore()
    ingest = IngestManager(
        source_store=store, config=SourceStoreConfig(), data_dir=tmp_path / "plugin"
    )
    cfg = Config({
        "zotero_sync": {
            "enabled": True,
            "zotero_data_dir": str(data_dir),
            "sync_mode": "conservative",
        }
    })

    async def failing_index(doc_id: str, collection: str) -> None:
        raise RuntimeError("VectorStore 未配置")

    pipeline = ZoteroSyncPipeline(
        source_store=store,
        ingest_manager=ingest,
        config=cfg,
        index_document=failing_index,
    )

    job = ZoteroSyncJob()
    result = await pipeline.pull(progress=job)

    # 文档仍被镜像/摄入（制品包存在），但索引失败被上报（不再静默）
    assert await store.get_document(DOC_ID) is not None
    assert any("index_document failed" in e for e in result.errors)
    assert job.recent_error


def test_probe_local_read_missing_data_dir(tmp_path: Path) -> None:
    _, pipeline, _, _ = _pipeline(tmp_path, tmp_path / "nonexistent", "conservative")
    probe = pipeline.probe_local_read()
    assert probe["available"] is False
    assert "zotero.sqlite" in str(probe["reason"])


def test_probe_local_read_server_mode_is_skipped(tmp_path: Path) -> None:
    from knowledge_arch.config import Config, SourceStoreConfig
    from knowledge_arch.managers.ingest_manager import IngestManager
    from knowledge_arch.repository.source_store.memory import InMemorySourceDocumentStore

    store = InMemorySourceDocumentStore()
    ingest = IngestManager(
        source_store=store, config=SourceStoreConfig(), data_dir=tmp_path / "plugin"
    )
    cfg = Config({"zotero_sync": {"enabled": True, "access_mode": "server"}})
    pipeline = ZoteroSyncPipeline(source_store=store, ingest_manager=ingest, config=cfg)

    probe = pipeline.probe_local_read()
    assert probe["available"] is False
    assert "本地" in str(probe["reason"])
