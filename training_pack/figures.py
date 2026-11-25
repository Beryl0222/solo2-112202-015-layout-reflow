"""图号登记：只认显式图号与显式模块标记。

图、图注、勘误、角注（图框内文字标记）通过文本中的“图 N / Fig. N”显式
标记关联；绝不按块间距离把英文图注或模块文字归给附近的图。角注本身不带
图号时，仅当该页只有一张图才按页面归入该图，否则保持未归属并标记。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .geometry import block_column

FIG_RE = re.compile(r"(?:图\s*(\d+)|Fig\.\s*(\d+))", re.IGNORECASE)
MODULE_RE = re.compile(r"M\d+")

# 视角/朝向词。朝向语义必须与工人站位、图面朝向关联到具体工步，
# 不能把“右图”的版面右当成工人站位的右。
REAR_TOKENS = ("背面", "从后", "rear", "from the back")
FRONT_TOKENS = ("正面", "正视", "front view", "front.")
FLIP_TOKENS = ("翻转", "flipped", "upside down", "上下翻")
PARTNER_TOKENS = ("搭档", "partner")
OPERATOR_TOKENS = ("练习者站位", "操作者", "operator")
# 图上标注被遮住或只给了虚线轮廓：相关工步语义不确定。
OCCLUSION_TOKENS = ("遮住", "遮挡", "虚线", "被遮", "没有一同重印", "未补印", "只作方向参考")
# 更正版实物卡显式声明遮挡已补印：解除对应对象的遮挡状态。
OCCLUSION_RESOLVED_TOKENS = ("已补印", "补印完成", "遮挡已消除", "实线重绘")


def fig_mentions(text: str) -> list[str]:
    """返回文本中显式出现的图号，规范化为 ``图 N``。"""
    found: list[str] = []
    for match in FIG_RE.finditer(text):
        number = match.group(1) or match.group(2)
        label = f"图 {number}"
        if label not in found:
            found.append(label)
    return found


def module_mentions(text: str) -> list[str]:
    """返回文本中显式出现的模块号（如 M1、M2），保持出现顺序去重。"""
    found: list[str] = []
    for match in MODULE_RE.finditer(text):
        if match.group(0) not in found:
            found.append(match.group(0))
    return found


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


@dataclass
class FigureRecord:
    """一张图在全部来源记录中的显式信息汇总。"""

    number: str
    figure_blocks: list[dict] = field(default_factory=list)
    captions: list[dict] = field(default_factory=list)
    errata: list[dict] = field(default_factory=list)
    in_frame_labels: list[dict] = field(default_factory=list)
    note_blocks: list[dict] = field(default_factory=list)
    orientation_aids: list[dict] = field(default_factory=list)
    module_scope: frozenset[str] = frozenset()
    viewpoints: frozenset[str] = frozenset()
    flipped_rear: bool = False
    front_view: bool = False
    occluded: bool = False
    occlusion_subjects: frozenset[str] = frozenset()
    orientation_corrected: bool = False
    occlusion_corrected: bool = False
    unassociated_labels: list[dict] = field(default_factory=list)

    @property
    def pages(self) -> set[int]:
        return {int(block["page"]) for block in self.figure_blocks}

    @property
    def viewpoint_conflict(self) -> bool:
        """同一张图同时出现背面翻转视角与正视/实物视角描述。"""
        return self.flipped_rear and self.front_view

    def label_texts(self) -> list[str]:
        return [block["text"] for block in self.in_frame_labels]


def build_figure_registry(
    blocks: list[dict],
    sheet_notes: list[dict] | None = None,
    aids: list[dict] | None = None,
) -> dict[str, FigureRecord]:
    """从文本块、印务观察和实物朝向登记建立图号索引。"""
    sheet_notes = sheet_notes or []
    aids = aids or []
    notes_by_block = {note["block"]: note for note in sheet_notes}
    records: dict[str, FigureRecord] = {}

    def record(number: str) -> FigureRecord:
        if number not in records:
            records[number] = FigureRecord(number=number)
        return records[number]

    figures_per_page: dict[int, list[str]] = {}
    for block in blocks:
        mentions = fig_mentions(block["text"])
        kind = block["kind"]
        if kind == "图":
            for number in mentions:
                figures_per_page.setdefault(int(block["page"]), []).append(number)
        for number in mentions:
            target = record(number)
            if kind == "图":
                target.figure_blocks.append(block)
            elif kind == "图注":
                target.captions.append(block)
            elif kind == "勘误":
                target.errata.append(block)
            note = notes_by_block.get(block["id"])
            if note is not None and note not in target.note_blocks:
                target.note_blocks.append(note)

    # 角注：图框内文字标记。仅当本页恰好一张图时按页面归入；
    # 同页多张图又没有图号时不猜归属。
    for block in blocks:
        if block["kind"] != "角注":
            continue
        page = int(block["page"])
        page_figures = sorted(set(figures_per_page.get(page, [])))
        if len(page_figures) == 1:
            record(page_figures[0]).in_frame_labels.append(block)
        else:
            for number in page_figures:
                record(number).unassociated_labels.append(block)

    for aid in aids:
        numbers = fig_mentions(aid["illustration"])
        for number in numbers:
            record(number).orientation_aids.append(aid)

    for target in records.values():
        block_texts = [
            block["text"]
            for block in (
                target.figure_blocks
                + target.captions
                + target.errata
                + target.in_frame_labels
            )
        ]
        note_texts = [note["note"] for note in target.note_blocks]
        aid_texts = [aid["orientation"] for aid in target.orientation_aids]
        texts = block_texts + note_texts + aid_texts
        joined = "\n".join(texts)
        modules = {
            module
            for text in texts
            for module in module_mentions(text)
        }
        viewpoints: set[str] = set()
        if _has_any(joined, REAR_TOKENS):
            viewpoints.add("背面视角")
        if _has_any(joined, FRONT_TOKENS):
            viewpoints.add("正视视角")
        if _has_any(joined, PARTNER_TOKENS):
            viewpoints.add("搭档视角")
        if _has_any(joined, OPERATOR_TOKENS):
            viewpoints.add("操作者视角")
        target.module_scope = frozenset(modules)
        target.viewpoints = frozenset(viewpoints)
        target.flipped_rear = _has_any(joined, REAR_TOKENS) and _has_any(joined, FLIP_TOKENS)
        target.front_view = _has_any(joined, FRONT_TOKENS)
        target.occluded = _has_any(joined, OCCLUSION_TOKENS)
        target.occlusion_subjects = _occlusion_subjects(joined)
        resolved_subjects = _resolved_subjects(
            "\n".join(block["text"] for block in target.figure_blocks)
        )
        if resolved_subjects:
            target.occlusion_subjects = frozenset(
                set(target.occlusion_subjects) - resolved_subjects
            )
            target.occluded = bool(target.occlusion_subjects)
        target.orientation_corrected = bool(target.errata) and _has_any(
            "\n".join(block["text"] for block in target.errata), FRONT_TOKENS
        )
        target.occlusion_corrected = not target.occluded and bool(
            target.errata
            or _has_any(
                "\n".join(block["text"] for block in target.figure_blocks),
                OCCLUSION_RESOLVED_TOKENS,
            )
        )
    return records


def _resolved_subjects(figure_text: str) -> frozenset[str]:
    if not _has_any(figure_text, OCCLUSION_RESOLVED_TOKENS):
        return frozenset()
    subjects: set[str] = set()
    if "右槽" in figure_text or "槽标签" in figure_text:
        subjects.add("slot_label")
    if "白卡" in figure_text:
        subjects.add("white_tab")
    return frozenset(subjects)


def _occlusion_subjects(text: str) -> frozenset[str]:
    """从印务观察/图框描述里识别被遮住的具体对象，不把风险泛化到整图。"""
    subjects: set[str] = set()
    if "右槽" in text or "槽标签" in text:
        subjects.add("slot_label")
    if "白卡" in text and ("虚线" in text or "遮住" in text):
        subjects.add("white_tab")
    if "蓝卡" in text and "只作方向参考" in text:
        subjects.add("blue_tab_reference")
    return frozenset(subjects)


def layout_side(block: dict) -> str:
    """块在原始双栏版面中的栏位（供“右图”这类版面指示词解析）。"""
    return block_column(block)
