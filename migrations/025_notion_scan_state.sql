-- Notion 增量扫描水位与本地已提交内容版本；同步账本写入不触发版本变化。
CREATE TABLE notion_scan_state (scope TEXT PRIMARY KEY, cursor TEXT NOT NULL);
CREATE TABLE notion_local_revision (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO notion_local_revision(id, revision) VALUES (1, 0);
CREATE TRIGGER notion_revision_documents_insert
AFTER INSERT ON documents
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_documents_update
AFTER UPDATE ON documents
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_documents_delete
AFTER DELETE ON documents
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_collections_insert
AFTER INSERT ON collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_collections_update
AFTER UPDATE ON collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_collections_delete
AFTER DELETE ON collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_document_collections_insert
AFTER INSERT ON document_collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_document_collections_update
AFTER UPDATE ON document_collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;
CREATE TRIGGER notion_revision_document_collections_delete
AFTER DELETE ON document_collections
BEGIN
    UPDATE notion_local_revision SET revision = revision + 1 WHERE id = 1;
END;

