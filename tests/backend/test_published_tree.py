"""发布树布局契约测试。"""

from __future__ import annotations

from tools.build_published_tree import FORBIDDEN_FILES, FORBIDDEN_PREFIXES, REQUIRED


def test_published_tree_paths_follow_plugin_scoped_packages() -> None:
    """顶层包改名后，发布必需/禁止路径不得退回通用旧包名。"""
    assert "ka_web/server.py" in REQUIRED
    assert "web/server.py" not in REQUIRED
    assert "ka_web/frontend/" in FORBIDDEN_PREFIXES
    assert "knowledge_arch/main.py" in FORBIDDEN_FILES
