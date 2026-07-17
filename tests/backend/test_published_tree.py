"""发布树布局契约测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.build_published_tree import (
    FORBIDDEN_FILES,
    FORBIDDEN_PREFIXES,
    REQUIRED,
    _select_files,
)

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ".agents/skills/operate-knowledge-arch"
SKILL_REQUIRED = {
    f"{SKILL_ROOT}/SKILL.md",
    f"{SKILL_ROOT}/agents/openai.yaml",
    f"{SKILL_ROOT}/references/research.md",
    f"{SKILL_ROOT}/references/settings.md",
    f"{SKILL_ROOT}/scripts/knowledge_arch_client.py",
}


def test_published_tree_paths_follow_plugin_scoped_packages() -> None:
    """发布契约必须使用 v1.0.4 目录布局。"""
    assert "web/server.py" in REQUIRED
    assert "ka_web/server.py" not in REQUIRED
    assert "web/frontend/" in FORBIDDEN_PREFIXES
    assert "kacore/main.py" in FORBIDDEN_FILES
    assert "knowledge_arch/main.py" not in FORBIDDEN_FILES


def test_published_tree_requires_project_skill() -> None:
    """正式安装包必须携带 Codex 项目级 Skill 的全部契约文件。"""
    assert SKILL_REQUIRED <= REQUIRED


def test_worktree_manifest_selects_project_skill() -> None:
    """发布白名单必须实际命中当前工作树中的 Skill 文件。"""
    selected = _select_files("WORKTREE")
    assert SKILL_REQUIRED <= set(selected)


def test_gitignore_only_allows_the_published_project_skill() -> None:
    """目标 Skill 可跟踪，其他 `.agents` 本地状态继续被忽略。"""

    def check(path: str) -> int:
        return subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", path],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode

    assert check(f"{SKILL_ROOT}/SKILL.md") == 1
    assert check(".agents/local-state.json") == 0
