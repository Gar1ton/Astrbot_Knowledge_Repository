-- 004_chunk_metadata.sql
-- 为 chunks 表添加 metadata 字段以存储页码、段落等定位元数据

ALTER TABLE chunks ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';
