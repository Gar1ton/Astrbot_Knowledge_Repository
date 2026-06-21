from __future__ import annotations

from pathlib import Path

from core.adapters.zotero.web_api import ZoteroWebApiReader, current_key_identity
from core.secret_store import EncryptedSecretStore


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
