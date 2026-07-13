"""发布树布局契约测试。"""

from __future__ import annotations

from tools.build_published_tree import FORBIDDEN_FILES, FORBIDDEN_PREFIXES, REQUIRED


def test_published_tree_paths_follow_plugin_scoped_packages() -> None:
    """发布契约必须使用 v1.0.4 目录布局。"""
    assert "web/server.py" in REQUIRED
    assert "ka_web/server.py" not in REQUIRED
    assert "web/frontend/" in FORBIDDEN_PREFIXES
    assert "kacore/main.py" in FORBIDDEN_FILES
    assert "knowledge_arch/main.py" not in FORBIDDEN_FILES
