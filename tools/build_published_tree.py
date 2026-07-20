#!/usr/bin/env python3
"""从 developer 的指定提交生成正式 main 文件树与市场 ZIP。

发布内容只由 ``release/published-files.txt`` 决定。默认读取已提交的 ``HEAD``；
``WORKTREE`` 仅供本地准备阶段预览，不得用于正式发布。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "release" / "published-files.txt"
DEFAULT_OUTPUT = ROOT / "dist" / "published"
MAX_ZIP_MIB = 15
PREFIX = "astrbot_plugin_knowledge_repository"
SENTINEL = ".published-source"

REQUIRED = {
    ".agents/skills/operate-knowledge-arch/SKILL.md",
    ".agents/skills/operate-knowledge-arch/agents/openai.yaml",
    ".agents/skills/operate-knowledge-arch/references/lightrag.md",
    ".agents/skills/operate-knowledge-arch/references/research.md",
    ".agents/skills/operate-knowledge-arch/references/settings.md",
    ".agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py",
    "main.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "requirements-additional.txt",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "logo.png",
    "web/server.py",
    "pages/index.html",
    ".published-source",
}
FORBIDDEN_PREFIXES = (
    "data/",
    "deliverables/",
    "dev/",
    "docs/",
    "tests/",
    "tools/",
    "web/frontend/",
)
FORBIDDEN_FILES = {
    "TODO.md",
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "CONVENTIONS.md",
    "pyproject.toml",
    "rebuild.sh",
    "requirements-dev.txt",
    "kacore/main.py",
}


@dataclass(frozen=True)
class Rule:
    source: str
    target: str | None = None
    exclude: bool = False


def _run_git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def _source_revision(source: str) -> str:
    if source == "WORKTREE":
        return "WORKTREE"
    return _run_git("rev-parse", "--verify", f"{source}^{{commit}}").decode().strip()


def _load_rules() -> list[Rule]:
    rules: list[Rule] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            source, target = (part.strip() for part in line.split("=>", 1))
            rules.append(Rule(source=source, target=target))
        elif line.startswith("!"):
            rules.append(Rule(source=line[1:], exclude=True))
        else:
            rules.append(Rule(source=line))
    return rules


def _matches(path: str, pattern: str) -> bool:
    """让 ``**`` 同时匹配零层或多层目录。"""
    if not any(char in pattern for char in "*?["):
        return path == pattern
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if "/**/" in pattern:
        return fnmatch.fnmatchcase(path, pattern.replace("/**/", "/"))
    return PurePosixPath(path).match(pattern)


def _list_source_files(source: str) -> list[str]:
    if source == "WORKTREE":
        output = _run_git("ls-files", "--cached", "--others", "--exclude-standard")
        return sorted(
            path
            for path in output.decode("utf-8", errors="surrogateescape").splitlines()
            if (ROOT / path).is_file()
        )
    output = _run_git("ls-tree", "-r", "--name-only", source)
    return sorted(output.decode("utf-8", errors="surrogateescape").splitlines())


def _select_files(source: str) -> dict[str, str]:
    files = _list_source_files(source)
    rules = _load_rules()
    selected: dict[str, str] = {}
    excludes = [rule.source for rule in rules if rule.exclude]

    for rule in rules:
        if rule.exclude:
            continue
        matches = [path for path in files if _matches(path, rule.source)]
        if rule.target:
            if len(matches) != 1:
                raise RuntimeError(
                    f"映射规则必须且只能命中一个文件：{rule.source} -> {matches}"
                )
            selected[rule.target] = matches[0]
            continue
        for path in matches:
            selected[path] = path

    for target, original in list(selected.items()):
        if any(_matches(original, pattern) for pattern in excludes):
            selected.pop(target)
    return selected


def _read_source_file(source: str, path: str) -> bytes:
    if source == "WORKTREE":
        return (ROOT / path).read_bytes()
    return _run_git("show", f"{source}:{path}")


def _prepare_output(output: Path) -> None:
    output = output.resolve()
    allowed_root = (ROOT / "dist").resolve()
    if output != allowed_root and allowed_root not in output.parents:
        raise RuntimeError(f"拒绝危险输出目录：{output}")
    if output.exists():
        sentinel = output / SENTINEL
        if not sentinel.is_file():
            raise RuntimeError(f"拒绝清理非生成目录（缺少 {SENTINEL}）：{output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)


def build_tree(source: str, output: Path) -> str:
    revision = _source_revision(source)
    selected = _select_files(source)
    _prepare_output(output)
    for target, original in selected.items():
        destination = output / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_read_source_file(source, original))
    (output / SENTINEL).write_text(
        f"source={revision}\nmanifest_sha256={hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}\n",
        encoding="utf-8",
    )
    validate_tree(output)
    return revision


def _tree_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def validate_tree(output: Path) -> None:
    files = _tree_files(output)
    missing = sorted(REQUIRED - files)
    forbidden = sorted(
        path
        for path in files
        if path in FORBIDDEN_FILES or path.startswith(FORBIDDEN_PREFIXES)
    )
    if missing or forbidden:
        detail = []
        if missing:
            detail.append(f"缺少必需文件：{missing}")
        if forbidden:
            detail.append(f"包含禁止文件：{forbidden}")
        raise RuntimeError("；".join(detail))


def build_zip(output: Path, destination: Path, max_mib: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.name != SENTINEL:
                relative = path.relative_to(output).as_posix()
                archive.write(path, f"{PREFIX}/{relative}")
    size = destination.stat().st_size
    limit = max_mib * 1024 * 1024
    if size > limit:
        raise RuntimeError(f"发布 ZIP {size / 1024 / 1024:.2f} MiB 超过 {max_mib} MiB")
    return size


def _generated_map(source: str) -> dict[str, bytes]:
    """按白名单从 ``source`` 生成 ``target -> 内容`` 映射（含 sentinel）。"""
    selected = _select_files(source)
    generated = {
        target: _read_source_file(source, original)
        for target, original in selected.items()
    }
    revision = _source_revision(source)
    generated[SENTINEL] = (
        f"source={revision}\n"
        f"manifest_sha256={hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}\n"
    ).encode()
    return generated


def check_against(source: str, ref: str) -> list[str]:
    """重新生成发布树并与已发布 ``ref`` 逐文件比对，返回差异描述列表。"""
    generated = _generated_map(source)
    published = set(_list_source_files(ref))
    diffs: list[str] = []
    diffs.extend(f"main 缺少应生成文件：{path}" for path in sorted(set(generated) - published))
    diffs.extend(f"main 含未授权文件：{path}" for path in sorted(published - set(generated)))
    diffs.extend(
        f"内容漂移：{path}"
        for path in sorted(set(generated) & published)
        if _read_source_file(ref, path) != generated[path]
    )
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="HEAD", help="developer commit/ref；预览可用 WORKTREE")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--max-mib", type=int, default=MAX_ZIP_MIB)
    parser.add_argument(
        "--check",
        metavar="MAIN_REF",
        help="不写盘：从 --source 重新生成并与已发布 MAIN_REF 逐文件比对，发现漂移即失败",
    )
    args = parser.parse_args()

    try:
        if args.check is not None:
            diffs = check_against(args.source, args.check)
            if diffs:
                print(f"published main（{args.check}）漂移检测失败：", file=sys.stderr)
                for detail in diffs:
                    print(f"  - {detail}", file=sys.stderr)
                return 1
            revision = _source_revision(args.source)
            print(f"published main（{args.check}）与 source={revision} 重新生成结果一致。")
            return 0
        revision = build_tree(args.source, args.output)
        files = _tree_files(args.output)
        print(f"published tree: {len(files)} files, source={revision}")
        if args.zip_path:
            size = build_zip(args.output, args.zip_path, args.max_mib)
            print(f"published zip: {args.zip_path} ({size / 1024 / 1024:.2f} MiB)")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
