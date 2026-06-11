from __future__ import annotations

from typing import Any

from core.adapters.zotero.local_api import (
    ZoteroLocalApiClient,
    normalize_zotero_annotation,
)


class FakeResponse:
    def __init__(self, body: str, *, status: int = 200, headers: dict[str, str] | None = None):
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_zotero_client_lists_items_with_readonly_get() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Any, *, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["api_version"] = request.headers["Zotero-api-version"]
        seen["timeout"] = timeout
        return FakeResponse('[{"key":"ANN1","data":{"itemType":"annotation"}}]')

    client = ZoteroLocalApiClient(port=23119, timeout=1.5, opener=opener)
    items = client.list_items(item_type="annotation", include="data", limit=5)

    assert items == [{"key": "ANN1", "data": {"itemType": "annotation"}}]
    assert seen["method"] == "GET"
    assert seen["api_version"] == "3"
    assert seen["timeout"] == 1.5
    assert seen["url"].startswith("http://127.0.0.1:23119/api/users/0/items?")
    assert "itemType=annotation" in seen["url"]
    assert "include=data" in seen["url"]
    assert "limit=5" in seen["url"]


def test_zotero_client_reads_file_view_url() -> None:
    def opener(request: Any, *, timeout: float) -> FakeResponse:
        assert request.full_url.endswith("/api/users/0/items/ATTACH/file/view/url")
        return FakeResponse("file:///C:/Zotero/storage/ATTACH/paper.pdf\n", headers={})

    client = ZoteroLocalApiClient(opener=opener)

    assert client.get_file_view_url("ATTACH") == "file:///C:/Zotero/storage/ATTACH/paper.pdf"


def test_normalize_zotero_annotation_parses_position_and_page() -> None:
    item = {
        "key": "ANN1",
        "data": {
            "key": "ANN1",
            "annotationType": "underline",
            "annotationText": "quoted text",
            "annotationComment": "",
            "annotationColor": "#ffd400",
            "annotationPageLabel": "142",
            "annotationPosition": '{"pageIndex":0,"rects":[[1,2,3,4]]}',
            "dateAdded": "2026-06-10T11:49:59Z",
        },
    }

    assert normalize_zotero_annotation("doc1", item) == {
        "id": "ANN1",
        "doc_id": "doc1",
        "text": "quoted text",
        "type": "underline",
        "color": "#ffd400",
        "page": 142,
        "page_label": "142",
        "position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]]},
        "created_at": "2026-06-10T11:49:59Z",
    }
