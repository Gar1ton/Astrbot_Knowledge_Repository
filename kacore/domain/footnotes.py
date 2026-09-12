"""脚注结构块的纯数据模型（domain 层，零依赖）。

脚注与正文分离存储：clean.md 不含脚注文本，脚注携带独立来源区间与关联状态，
供全文阅读、显式脚注查询按需读取；默认不进入普通检索候选。
见 docs/ingest-evidence-upgrade-plan.md 「文本、脚注与出处」章节的 FootnoteLink 草案。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FootnoteLinkStatus(str, Enum):
    """脚注与正文引用点的关联置信度。

    LINKED 是正文找到唯一匹配标记的高置信关联；UNLINKED 是未找到匹配标记，保留脚注原文
    不臆造关联；AMBIGUOUS 是同页存在多个同标记候选、无法确定唯一归属，同样保留原文不强关联。
    三种状态下脚注文本本身都完整保留，绝不因关联失败而删除。
    """

    LINKED = "linked"
    UNLINKED = "unlinked"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FootnoteBlock:
    """一条从页面正文分离出的脚注候选。

    契约：
        - page 是 PDF 原始页码（1-based），不是数组下标。
        - marker 是脚注自身携带的标号原文（如 "14"、"a"、"*"）；不同页/不同章节允许复用同一
          marker，链接必须限定在同一页正文内比较，绝不能跨页假设编号连续或全局唯一。
        - source_start/source_end 是该脚注文本在**该页原始抽取文本**（清洗、行修复之前）中的
          字符偏移，不是 clean.md 偏移——脚注不进入 clean.md 字符空间，因此不需要为脚注移除
          在正文侧维护多区间映射。
        - link_status/body_marker_span 由链接阶段（link_footnotes）填充；未关联时
          body_marker_span 为 None，text 仍完整可读。
        - doc_id 默认为空，由调用方（ingest 管线）在持久化时回填，markdown_extractor 本身
          不感知 doc_id。
    """

    page: int
    marker: str
    text: str
    source_start: int
    source_end: int
    doc_id: str = ""
    link_status: FootnoteLinkStatus = FootnoteLinkStatus.UNLINKED
    body_marker_span: tuple[int, int] | None = None


__all__ = ["FootnoteLinkStatus", "FootnoteBlock"]
