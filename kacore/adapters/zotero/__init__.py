"""Zotero 本地接入适配层（adapters/zotero）。

把 Zotero 上游（zotero.sqlite + storage 目录 + 本地 API）翻译为本插件 domain 对象。
本地 pull 以 `sqlite_reader`（只读 zotero.sqlite）为主路径；`local_api` 仅做连接/状态探测；
`paths` 负责 OS 默认目录探测、覆盖与 linked_root / zotmoov_root 探针；
`zotmoov` 负责 ZotMoov 已移动附件（linked_file）的目录解析与文件名索引兜底。
"""
