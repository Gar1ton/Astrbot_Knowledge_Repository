"""回收站集合不应进入 Zotero 快照（Web API data.deleted / 本地 deletedCollections）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from kacore.adapters.zotero.sqlite_reader import ZoteroSqliteReader
from kacore.adapters.zotero.web_api import ZoteroWebApiReader
from tests.backend.test_zotero_sync import _build_zotero_db


def _coll(key: str, parent: str = "", *, deleted: bool = False) -> dict:
    data: dict = {"key": key, "name": key, "parentCollection": parent or False}
    if deleted:
        data["deleted"] = True
    return {"key": key, "data": data}


def _item(key: str, collections: list[str]) -> dict:
    return {
        "key": key,
        "version": 1,
        "data": {"key": key, "itemType": "journalArticle", "collections": collections},
    }


def test_web_api_excludes_deleted_collection_and_unmarked_descendants() -> None:
    class Client:
        def list_user_collections(self, user_id: str):
            return [
                _coll("ROOT"),
                _coll("TRASH", "ROOT", deleted=True),
                _coll("CHILD", "TRASH"),  # 父进回收站，子集合不带 deleted 标记
                _coll("GRAND", "CHILD"),
                _coll("KEEP", "ROOT"),
            ]

        def list_user_items(self, user_id: str):
            return [_item("I1", ["KEEP", "TRASH"]), _item("I2", ["GRAND"])]

    snapshot = ZoteroWebApiReader(Client(), user_id="1").read_snapshot()  # type: ignore[arg-type]

    assert {c.collection_key for c in snapshot.collections} == {"ROOT", "KEEP"}
    # 指向已删集合的归属对一并剔除，避免 document_collections 悬空。
    assert snapshot.collection_items == [("KEEP", "I1")]


def _add_collection(db: sqlite3.Connection, cid: int, key: str, parent: int | None) -> None:
    db.execute(
        "INSERT INTO collections VALUES (?, ?, ?, ?, 1)", (cid, key, parent, key)
    )


def test_sqlite_reader_excludes_deleted_collections(tmp_path: Path) -> None:
    _build_zotero_db(tmp_path)
    db = sqlite3.connect(tmp_path / "zotero.sqlite")
    db.execute("CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY)")
    _add_collection(db, 101, "TRASHED", None)
    _add_collection(db, 102, "KIDOFTRSH", 101)
    db.execute("INSERT INTO deletedCollections VALUES (101)")
    db.execute("INSERT INTO collectionItems VALUES (102, 10, 0)")
    db.commit()
    db.close()

    snapshot = ZoteroSqliteReader(tmp_path).read_snapshot()

    assert {c.collection_key for c in snapshot.collections} == {"COLLAAAA"}
    assert all(ck == "COLLAAAA" for ck, _ in snapshot.collection_items)


def test_sqlite_reader_without_deleted_collections_table(tmp_path: Path) -> None:
    """Zotero 7 之前的库没有 deletedCollections 表，行为保持不变。"""
    _build_zotero_db(tmp_path)
    db = sqlite3.connect(tmp_path / "zotero.sqlite")
    _add_collection(db, 101, "OTHERKEY", None)
    db.commit()
    db.close()

    snapshot = ZoteroSqliteReader(tmp_path).read_snapshot()

    assert {c.collection_key for c in snapshot.collections} == {"COLLAAAA", "OTHERKEY"}
