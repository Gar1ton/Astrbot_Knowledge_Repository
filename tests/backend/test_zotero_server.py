from __future__ import annotations

from pathlib import Path

from kacore.adapters.zotero.web_api import ZoteroWebApiReader, current_key_identity
from kacore.secret_store import EncryptedSecretStore


def test_secret_store_encrypts_and_masks(tmp_path: Path) -> None:
    store = EncryptedSecretStore(tmp_path / "secrets")
    store.set_secret("zotero.server_api_key", "abcdef123456")

    assert store.get_secret("zotero.server_api_key") == "abcdef123456"
    assert store.masked_secret("zotero.server_api_key") == "ab****56"
    payload = (tmp_path / "secrets" / "zotero.server_api_key.secret").read_text()
    assert "abcdef123456" not in payload

    store.delete_secret("zotero.server_api_key")
    assert store.get_secret("zotero.server_api_key") == ""


def test_current_key_identity_requires_personal_user() -> None:
    identity = current_key_identity({
        "userID": 123,
        "username": "alice",
        "access": {"user": {"library": True, "files": True}},
    })

    assert identity["user_id"] == "123"
    assert identity["username"] == "alice"
    assert identity["access"]["library"] is True


def test_web_api_reader_builds_personal_snapshot(tmp_path: Path) -> None:
    class Client:
        def list_user_collections(self, user_id: str):
            assert user_id == "123"
            return [
                {"key": "COLL1", "data": {"key": "COLL1", "name": "Papers"}},
            ]

        def list_user_items(self, user_id: str):
            assert user_id == "123"
            return [
                {
                    "key": "ITEM1",
                    "version": 7,
                    "data": {
                        "key": "ITEM1",
                        "itemType": "journalArticle",
                        "title": "Server Paper",
                        "date": "2025-01-01",
                        "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
                        "publicationTitle": "Journal",
                        "collections": ["COLL1"],
                        "tags": [{"tag": "zotero"}],
                    },
                },
                {
                    "key": "ATT1",
                    "version": 7,
                    "data": {
                        "key": "ATT1",
                        "itemType": "attachment",
                        "parentItem": "ITEM1",
                        "contentType": "application/pdf",
                        "filename": "paper.pdf",
                        "linkMode": "imported_file",
                    },
                },
            ]

        def download_user_file(self, user_id: str, item_key: str, target_path: Path):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"%PDF-1.4")
            return target_path

    reader = ZoteroWebApiReader(
        Client(),  # type: ignore[arg-type]
        user_id="123",
        username="alice",
        download_dir=tmp_path / "cache",
    )
    snapshot = reader.read_snapshot()

    assert snapshot.library.library_id == "123"
    assert snapshot.library.name == "alice"
    assert snapshot.collections[0].name == "Papers"
    assert snapshot.items[0].title == "Server Paper"
    assert snapshot.items[0].creators == ["Lovelace, Ada"]
    assert snapshot.collection_items == [("COLL1", "ITEM1")]
    assert snapshot.item_tags["ITEM1"][0].tag == "zotero"
    assert snapshot.attachments[0].parent_item_key == "ITEM1"
    # read_snapshot 只读元数据、不预下载（下载延迟到 pipeline 的 syncing_documents 阶段）。
    assert snapshot.attachments[0].resolved_path == ""
    # 惰性单篇下载：按需调用才真正落盘。
    fetched = reader.fetch_attachment_file("ATT1", "paper.pdf")
    assert fetched is not None and fetched.exists()


def test_web_api_reader_includes_standalone_attachment_in_collection_items(
    tmp_path: Path,
) -> None:
    """独立放入集合、无 parent item 的 PDF 附件必须保留自己的集合归属，不落入 __unfiled__。"""

    class Client:
        def list_user_collections(self, user_id: str):
            return [{"key": "COLL1", "data": {"key": "COLL1", "name": "Papers"}}]

        def list_user_items(self, user_id: str):
            return [
                {
                    "key": "STANDALONE",
                    "version": 3,
                    "data": {
                        "key": "STANDALONE",
                        "itemType": "attachment",
                        "parentItem": "",
                        "contentType": "application/pdf",
                        "filename": "standalone.pdf",
                        "linkMode": "imported_file",
                        "collections": ["COLL1"],
                    },
                },
                {
                    "key": "NOTE1",
                    "version": 3,
                    "data": {
                        "key": "NOTE1",
                        "itemType": "note",
                        "collections": ["COLL1"],
                    },
                },
                {
                    "key": "ITEM1",
                    "version": 3,
                    "data": {
                        "key": "ITEM1",
                        "itemType": "journalArticle",
                        "title": "Parented Paper",
                        "collections": ["COLL1"],
                    },
                },
                {
                    "key": "ATT_OF_ITEM1",
                    "version": 3,
                    "data": {
                        "key": "ATT_OF_ITEM1",
                        "itemType": "attachment",
                        "parentItem": "ITEM1",
                        "contentType": "application/pdf",
                        "filename": "child.pdf",
                        "linkMode": "imported_file",
                        # 有 parent 的普通附件通常没有自己的 collections。
                    },
                },
            ]

        def download_user_file(self, user_id: str, item_key: str, target_path: Path):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"%PDF-1.4")
            return target_path

    reader = ZoteroWebApiReader(
        Client(),  # type: ignore[arg-type]
        user_id="123",
        username="alice",
        download_dir=tmp_path / "cache",
    )
    snapshot = reader.read_snapshot()

    # 独立附件贡献了自己的归属对，未落入 __unfiled__。
    assert ("COLL1", "STANDALONE") in snapshot.collection_items
    # 有 parent 的普通附件自己没有 collections，不产生多余归属。
    assert ("COLL1", "ATT_OF_ITEM1") not in snapshot.collection_items
    # note 仍被排除在集合成员之外（回归防呆）。
    assert ("COLL1", "NOTE1") not in snapshot.collection_items
    # 普通条目归属不受影响。
    assert ("COLL1", "ITEM1") in snapshot.collection_items
