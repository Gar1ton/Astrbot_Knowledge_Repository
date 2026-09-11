"""从文件名启发式提取书目信息（domain 层·纯函数，zero-dependency）。

为何存在：不少用户习惯把 PDF 命名为 `Author (Year) - Title.pdf` 这类自描述格式（Zotero 自身的
「重命名附件」功能、ZotFile 等第三方工具都遵循这个约定）。当上游（Zotero 独立附件、无书目元数据的
本地上传）拿不出真正的作者/年份时，这份文件名本身就是一份可确定性提取的书目记录——不是编造，是
把已经写在文件名里的文本结构化出来。

边界：本模块只认识字符串（文件名），不认识 `SourceDocument`、Zotero/local 的存储形态、来源判断。
是否调用、调用后如何与权威数据（Zotero 镜像 / 用户手填）合并，由调用方（pipelines/managers 层）
决定——和 `citation.py` 一样，domain 层零依赖、对上层数据形态保持无知。

已知限制：
① `et al.` 会被直接截断，只保留其前面已列出的姓氏——文件名本身没写全部作者，本模块无法凭空补全，
   渲染出的 `X (Year)` 会比原始意图少一个「等」的语义，这是信息源的限制而非解析 bug。
② 只识别姓氏，不产出 given name 缩写（文件名一般不会保留全名）；喂给
   `citation.normalize_creators` 时因为姓氏本身不含逗号，会被正确当作裸姓氏处理。
③ 连字符年份区间（如 `1845-1846`）只取首年，Harvard 单年份字段本就放不下区间。
④ 匹配到多个候选切分点时用非贪婪 + 首个满足年份格式的括号/连字符，无法处理作者名本身包含
   `(YYYY)` 这种极端情况——概率极低，未特殊处理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Zotero「文件名已存在」去重时会在前面加 `<序号>_`，如 `16_Laozi Ch.37 (n.d.) - ...`。
_DEDUP_PREFIX_RE = re.compile(r"^\d+_")

# 年份 token：四位数字（可带连字符区间）或字面 `n.d.`（大小写、加不加点、中间加不加空格均可）。
_YEAR_TOKEN = r"(?:\d{4}(?:[-–]\d{2,4})?|n\.?\s*d\.?)"

# 主格式：`Author(s) (Year) - Title`。authors 非贪婪，交给年份 token 的强约束去定位分界。
_PATTERN_PAREN = re.compile(
    rf"^(?P<authors>.+?)\s*\((?P<year>{_YEAR_TOKEN})\)\s*-\s*(?P<title>.+)$",
    re.IGNORECASE,
)
# 变体：`Author(s) - Year - Title`（Zotero「按创建者-年份-标题」重命名模板的常见输出）。
_PATTERN_DASH = re.compile(
    rf"^(?P<authors>.+?)\s*-\s*(?P<year>{_YEAR_TOKEN})\s*-\s*(?P<title>.+)$",
    re.IGNORECASE,
)

_ET_AL_RE = re.compile(r"\bet\s*al\.?\s*$", re.IGNORECASE)
_ND_RE = re.compile(r"^n\.?\s*d\.?$", re.IGNORECASE)
_AMP_RE = re.compile(r"\s*&\s*")
_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)


@dataclass(frozen=True)
class FilenameBiblio:
    """从文件名解析出的书目猜测。

    契约：
        - `authors` 为姓氏元组，非空；不含逗号（不是 `姓, 名`，是纯姓氏裸串）。
        - `year` 为四位年份字符串或空串（空串表示文件名标注的是 `n.d.`）。
        - `title` 为去除作者/年份段落后剩余的标题文本，非空。
    """

    authors: tuple[str, ...]
    year: str
    title: str


def _split_authors(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    et_al = _ET_AL_RE.search(text)
    if et_al:
        text = text[: et_al.start()].strip()
    text = _AMP_RE.sub(", ", text)
    text = _AND_RE.sub(", ", text)
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _extract_year(raw: str) -> str:
    text = raw.strip()
    if _ND_RE.match(text):
        return ""
    match = re.match(r"\d{4}", text)
    return match.group(0) if match else ""


def parse_filename_biblio(filename: str) -> FilenameBiblio | None:
    """解析文件名为 `FilenameBiblio`；识别不出「作者 (年份) - 标题」结构就返回 `None`，绝不猜。"""
    stem = _DEDUP_PREFIX_RE.sub("", Path(filename).stem).strip()
    if not stem:
        return None
    match = _PATTERN_PAREN.match(stem) or _PATTERN_DASH.match(stem)
    if match is None:
        return None
    authors = _split_authors(match.group("authors"))
    title = match.group("title").strip()
    if not authors or not title:
        return None
    return FilenameBiblio(authors=authors, year=_extract_year(match.group("year")), title=title)


__all__ = ["FilenameBiblio", "parse_filename_biblio"]
