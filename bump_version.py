from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METADATA_PATH = ROOT / "metadata.yaml"
MAIN_PATH = ROOT / "main.py"
README_PATH = ROOT / "README.md"
TODO_PATH = ROOT / "TODO.md"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

# 本分支（Experiment-with-MemEcho-API）版本号格式固定为 x.x.x.ME：数字核心为 SemVer，
# 追加不可变构建后缀 .ME 标识 MemEcho 实验线。以下正则统一识别可选 (?:\.ME)? 后缀，
# bump 时保留 current 的后缀不变（数字核心照常 patch/minor/major 递增）。
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(\.ME)?$")
METADATA_VERSION_RE = re.compile(
    r"^(version:\s*)(v?\d+\.\d+\.\d+(?:\.ME)?)(.*)$", re.MULTILINE
)
MAIN_VERSION_RE = re.compile(
    r'^(_PLUGIN_VERSION\s*=\s*")v?\d+\.\d+\.\d+(?:\.ME)?(".*)$',
    re.MULTILINE,
)
README_BADGE_VERSION_RE = re.compile(
    r"(\[!\[version\]\(https://img\.shields\.io/badge/版本-)v?\d+\.\d+\.\d+(?:\.ME)?"
    r"(-blueviolet\)\]\(metadata\.yaml\))"
)
TODO_HEADING_RE = re.compile(
    r"^(##\s+)v?\d+\.\d+\.\d+(?:\.ME)?((?:\s*[:：]\s*|\s+).+)$",
    re.MULTILINE,
)
CHANGELOG_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*", re.MULTILINE)
CHANGELOG_RELEASE_RE = re.compile(r"^## \[v\d+\.\d+\.\d+(?:\.ME)?\]", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str, *, dry_run: bool) -> None:
    if not dry_run:
        path.write_text(content, encoding="utf-8", newline="\n")


def _parse_version(value: str) -> tuple[int, int, int, str]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(
            f"Invalid version: {value!r}; expected vX.Y.Z[.ME] or X.Y.Z[.ME]"
        )
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    suffix = match.group(4) or ""
    return (major, minor, patch, suffix)


def _format_version(major: int, minor: int, patch: int, suffix: str = "") -> str:
    return f"v{major}.{minor}.{patch}{suffix}"


def _current_metadata_version() -> str:
    metadata = _read(METADATA_PATH)
    match = METADATA_VERSION_RE.search(metadata)
    if not match:
        raise RuntimeError("metadata.yaml does not contain a version: vX.Y.Z line")
    return _format_version(*_parse_version(match.group(2)))


def _resolve_target(current: str, bump: str) -> str:
    if VERSION_RE.fullmatch(bump):
        return _format_version(*_parse_version(bump))

    major, minor, patch, suffix = _parse_version(current)
    if bump == "major":
        return _format_version(major + 1, 0, 0, suffix)
    if bump == "minor":
        return _format_version(major, minor + 1, 0, suffix)
    if bump == "patch":
        return _format_version(major, minor, patch + 1, suffix)
    raise ValueError("bump must be one of: patch, minor, major, or vX.Y.Z[.ME]")


def _update_metadata(target: str, *, dry_run: bool) -> bool:
    content = _read(METADATA_PATH)
    updated, count = METADATA_VERSION_RE.subn(rf"\g<1>{target}\g<3>", content, count=1)
    if count != 1:
        raise RuntimeError("Failed to update metadata.yaml version")
    _write(METADATA_PATH, updated, dry_run=dry_run)
    return updated != content


def _update_main_version(target: str, *, dry_run: bool) -> bool:
    content = _read(MAIN_PATH)
    updated, count = MAIN_VERSION_RE.subn(rf"\g<1>{target}\g<2>", content, count=1)
    if count != 1:
        raise RuntimeError("Failed to update main.py _PLUGIN_VERSION")
    _write(MAIN_PATH, updated, dry_run=dry_run)
    return updated != content


def _update_readme_badge(target: str, *, dry_run: bool) -> bool:
    content = _read(README_PATH)
    updated, count = README_BADGE_VERSION_RE.subn(rf"\g<1>{target}\g<2>", content, count=1)
    if count != 1:
        raise RuntimeError("Failed to update README.md version badge")
    _write(README_PATH, updated, dry_run=dry_run)
    return updated != content


def _update_todo_top_version(target: str, *, dry_run: bool) -> bool:
    content = _read(TODO_PATH)
    updated, count = TODO_HEADING_RE.subn(rf"\g<1>{target}\g<2>", content, count=1)
    if count != 1:
        raise RuntimeError("Failed to update the first TODO.md version heading")
    _write(TODO_PATH, updated, dry_run=dry_run)
    return updated != content


def _release_changelog(target: str, release_date: str, *, dry_run: bool) -> bool:
    content = _read(CHANGELOG_PATH)
    unreleased = CHANGELOG_UNRELEASED_RE.search(content)
    if not unreleased:
        raise RuntimeError("CHANGELOG.md does not contain ## [Unreleased]")

    next_release = CHANGELOG_RELEASE_RE.search(content, unreleased.end())
    if not next_release:
        raise RuntimeError("CHANGELOG.md does not contain an existing release heading")

    body = content[unreleased.end() : next_release.start()].strip()
    if not body:
        return False

    replacement = f"## [Unreleased]\n\n## [{target}] — {release_date}\n\n{body}\n\n"
    updated = content[: unreleased.start()] + replacement + content[next_release.start() :]
    _write(CHANGELOG_PATH, updated, dry_run=dry_run)
    return updated != content


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bump project version across metadata.yaml, main.py, README.md, "
            "the top TODO.md version heading, and CHANGELOG.md [Unreleased]. "
            "本分支版本格式固定为 x.x.x.ME；bump 时保留 .ME 后缀不变。"
        )
    )
    parser.add_argument(
        "bump",
        choices=("patch", "minor", "major"),
        nargs="?",
        default="patch",
        help="SemVer part to bump from metadata.yaml (default: patch).",
    )
    parser.add_argument(
        "--version",
        help="Explicit target version, e.g. v1.0.9.ME. Overrides the bump argument.",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Release date for CHANGELOG.md (default: today).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned version change without writing files.",
    )
    args = parser.parse_args()

    current = _current_metadata_version()
    target = _resolve_target(current, args.version or args.bump)

    changed = {
        "metadata.yaml": _update_metadata(target, dry_run=args.dry_run),
        "main.py": _update_main_version(target, dry_run=args.dry_run),
        "README.md": _update_readme_badge(target, dry_run=args.dry_run),
        "TODO.md": _update_todo_top_version(target, dry_run=args.dry_run),
        "CHANGELOG.md": _release_changelog(target, args.date, dry_run=args.dry_run),
    }

    mode = "Would bump" if args.dry_run else "Bumped"
    print(f"{mode} {current} -> {target}")
    for path, did_change in changed.items():
        print(f"- {path}: {'changed' if did_change else 'unchanged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
