"""句段恢复与连接词作用标注。

供应商把双栏讲义拆成平板页后，同一段的句子可能落在不同块、不同页。
本模块按“同页 + 同栏 + 同语言 + 阅读顺序”恢复段落，并对每个小句标注
连接词作用：时序、指代、版面指示、条件、搭档协同。连接词的作用随后要
与具体工步绑定，不能在拆页后悬空。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geometry import block_column, parse_box

SENTENCE_END = "。；;！？!?\n"
# 英文句点要先保护 “Fig. 2” 这类图号，再按句末点号切句。
_DOTTED_ABBR = re.compile(r"\b(Fig|No|Vol|Eq)\.", re.IGNORECASE)
_PLACEHOLDER = "\x00DOT\x00"

SEQUENCE_TOKENS = ("随后", "然后", "接着", "下一步", "上一步", "when ")
ANAPHORA_TOKENS = ("该卡", "该槽", "此卡", "上一页", "上一步", "露出的", "the tab", "the card")
LAYOUT_TOKENS = ("右图", "左图", "上图", "下图", "如右", "右侧", "左侧")
CONDITION_TOKENS = ("如", "当", "若", "when", "if")
PARTNER_TOKENS = ("搭档", "partner")
PAGE_TOKENS = ("上一页", "下一页", "this page", "previous page")

CLAUSE_SPLIT_RE = re.compile(r"[，,、]")
_SENTENCE_SPLIT_RE = re.compile(f"[{re.escape(SENTENCE_END)}]|(?<=[A-Za-z])\\.(?=\\s+[A-Z])")


def split_sentences(text: str) -> list[str]:
    """按句末标点切句，保护 ``Fig.`` 之类的缩写点号并保留句末点。"""
    protected = _DOTTED_ABBR.sub(lambda match: match.group(1) + _PLACEHOLDER, text)
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_SPLIT_RE.finditer(protected):
        piece = protected[start : match.end()].strip()
        if piece:
            sentences.append(piece.replace(_PLACEHOLDER, "."))
        start = match.end()
    tail = protected[start:].strip()
    if tail:
        sentences.append(tail.replace(_PLACEHOLDER, "."))
    return sentences


def split_clauses(sentence: str) -> list[str]:
    """把一句话切成小句（保留逗号连接关系，由 classify_connectors 标注）。"""
    return [piece.strip() for piece in CLAUSE_SPLIT_RE.split(sentence) if piece.strip()]


def classify_connectors(clause: str) -> list[str]:
    """返回小句中出现的连接词作用类别。"""
    lowered = clause.lower()
    roles: list[str] = []
    checks = (
        ("时序", SEQUENCE_TOKENS),
        ("指代", ANAPHORA_TOKENS),
        ("版面指示", LAYOUT_TOKENS),
        ("条件", CONDITION_TOKENS),
        ("搭档协同", PARTNER_TOKENS),
        ("跨页", PAGE_TOKENS),
    )
    for role, tokens in checks:
        if any(token.lower() in lowered for token in tokens):
            roles.append(role)
    return roles


@dataclass
class Paragraph:
    """恢复后的段落：同页、同栏、同语言、按阅读顺序连续的正文块。"""

    key: tuple[int, str, str]
    blocks: list[dict] = field(default_factory=list)
    sentences: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.key[0]

    @property
    def column(self) -> str:
        return self.key[1]

    @property
    def lang(self) -> str:
        return self.key[2]


def build_paragraphs(blocks: list[dict]) -> list[Paragraph]:
    """把正文块恢复成段落。标题、图、图注、勘误、角注不参与拼段。"""
    body = [block for block in blocks if block["kind"] == "正文"]
    body.sort(key=lambda block: (int(block["page"]), block_column(block), block["lang"], parse_box(block["box"]).y))
    grouped: dict[tuple[int, str, str], list[dict]] = {}
    for block in body:
        key = (int(block["page"]), block_column(block), block["lang"])
        grouped.setdefault(key, []).append(block)
    paragraphs: list[Paragraph] = []
    for key in sorted(grouped, key=lambda item: (item[0], item[1], item[2])):
        members = sorted(grouped[key], key=lambda block: parse_box(block["box"]).y)
        paragraph = Paragraph(key=key, blocks=members)
        for block in members:
            for sentence in split_sentences(block["text"]):
                paragraph.sentences.append((sentence, block))
        paragraphs.append(paragraph)
    return paragraphs
