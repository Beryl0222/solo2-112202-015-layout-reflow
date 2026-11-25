"""工步抽取：把恢复后的句段落成可发放/可暂停的工步。

工步只从正文块产生；图、图注、勘误、角注作为工步的参照与语义风险来源。
模块归属只接受显式 M 标记或跨语言同动作对齐，不用块间距归属；指代解析
只沿文本中的显式指代（该卡/上一页/右图）回溯，解析不到就标记语义不确定，
其余可用句子照常保留。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .discourse import (
    build_paragraphs,
    classify_connectors,
    split_clauses,
)
from .figures import FigureRecord, fig_mentions, module_mentions
from .geometry import RIGHT, block_column, parse_box

# 状态桶：可练 / 需老师解释（语言校订）/ 暂停 / 限新模型不进旧版包。
STEP_STATUSES = ("practicable", "teacher_required", "held", "gated")

# 静态语义风险原因（与发放状态无关的部分）。
REASON_VIEW_CONFLICT = "VIEW_CONFLICT"
REASON_OCCLUDED = "LABEL_OCCLUDED"
REASON_TRANSLATION_SWAP = "TRANSLATION_SWAP"
REASON_LAYOUT_DEICTIC = "LAYOUT_DEICTIC"
REASON_AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
# 发放相关原因（distribution/planning 使用，集中在此处维护常量）。
REASON_MISSING_ANTECEDENT = "MISSING_ANTECEDENT"
REASON_MISSING_FIGURE = "MISSING_FIGURE"
REASON_OLD_VIEW = "OLD_VIEW"
REASON_MONOPOLY = "PARTNER_MONOPOLY_RISK"
REASON_MODEL_GATED = "MODEL_GATED"
REASON_NOT_ISSUED = "NOT_ISSUED"

ACTION_VERBS: dict[str, str] = {
    "装": "install",
    "插入": "install",
    "保留": "leave",
    "留": "leave",
    "拔掉": "remove",
    "拔": "remove",
    "取出": "remove",
    "核对": "verify",
    "对照": "verify",
    "复述": "recite",
    "面向": "orient",
}
EN_VERB_PATTERNS = (
    ("leave", "leave"),
    ("remove", "remove"),
    ("install", "install"),
    ("confirm", "confirm"),
    ("verify", "verify"),
    ("orient", "orient"),
)
OBJECT_PATTERNS = (
    ("白卡", "white_tab"),
    ("蓝卡", "blue_tab"),
    ("卡槽", "slot"),
    ("槽号", "slot_number"),
    ("时钟标记", "clock_mark"),
    ("white tab", "white_tab"),
    ("blue tab", "blue_tab"),
)
PARTNER_VERIFY_TOKENS = ("让搭档核对", "搭档核对", "partner confirms", "as seen by the partner")


@dataclass(frozen=True)
class Finding:
    """工步上的一条语义/发放风险。severity 为 hold 或 language。"""

    reason: str
    severity: str
    detail: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    figures: tuple[str, ...] = field(default_factory=tuple)
    block_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class WorkStep:
    step_id: str
    block_id: str
    page: int
    lang: str
    clause_index: int
    text: str
    action: str | None
    objects: tuple[str, ...]
    actor: str
    partner_verification: bool
    connector_roles: tuple[str, ...]
    figure_refs: tuple[str, ...]
    layout_deictic: tuple[str, ...]
    module_scope: frozenset[str] = frozenset()
    scope_basis: str = "none"
    anaphora: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    companion_block_ids: tuple[str, ...] = field(default_factory=tuple)

    def add_finding(self, finding: Finding) -> None:
        if not any(existing.reason == finding.reason for existing in self.findings):
            self.findings.append(finding)


def reading_order(blocks: Iterable[dict]) -> list[dict]:
    """阅读顺序：页 -> 栏（左先于右，跨栏置顶）-> 纵向坐标。"""
    column_rank = {"跨栏": 0, "左栏": 1, "右栏": 2}

    def key(block: dict) -> tuple:
        return (
            int(block["page"]),
            column_rank.get(block_column(block), 9),
            parse_box(block["box"]).y,
        )

    return sorted(blocks, key=key)


def _detect_action(text: str) -> str | None:
    for verb, normalized in ACTION_VERBS.items():
        if verb in text:
            return normalized
    lowered = text.lower()
    for pattern, normalized in EN_VERB_PATTERNS:
        if pattern in lowered:
            return normalized
    return None


def _detect_objects(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    found: list[str] = []
    for pattern, normalized in OBJECT_PATTERNS:
        if pattern in text or pattern in lowered:
            found.append(normalized)
    return tuple(found)


def _is_partner_verification(text: str) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in PARTNER_VERIFY_TOKENS)


def _layout_deixis(text: str) -> tuple[str, ...]:
    tokens = ("右图", "左图", "上图", "下图", "如右")
    found: list[str] = []
    for token in tokens:
        if token in text and token not in found:
            found.append(token)
    return tuple(found)


def build_steps(
    blocks: list[dict],
    figures: dict[str, FigureRecord],
) -> list[WorkStep]:
    """从正文句段构造工步，绑定图号、指代、模块范围与静态语义风险。

    工步按阅读顺序（页->栏->纵向）产生，保证“随后/该卡/上一页”只能向
    阅读顺序更早的工步回溯，不会把后出现的英文对照句当成先行对象。
    """
    paragraphs = build_paragraphs(blocks)
    sentences_by_block: dict[str, list[tuple[str, dict]]] = {}
    for paragraph in paragraphs:
        for sentence, block in paragraph.sentences:
            sentences_by_block.setdefault(block["id"], []).append((sentence, block))

    figures_by_page: dict[int, list[FigureRecord]] = {}
    for record in figures.values():
        for page in record.pages:
            figures_by_page.setdefault(page, []).append(record)

    steps: list[WorkStep] = []
    counters: dict[str, int] = {}
    # 按对象记忆最近一次出现该对象的工步，供“该卡/上一页”回溯。
    last_by_object: dict[str, WorkStep] = {}
    last_step: WorkStep | None = None
    # 同一块内“For M1 / For M2”等模块标记小句的作用域，传给后续动作小句。
    block_marker_scope: dict[str, frozenset[str]] = {}

    for block in reading_order(b for b in blocks if b["kind"] == "正文"):
        for sentence, _ in sentences_by_block.get(block["id"], []):
            for index, clause in enumerate(split_clauses(sentence)):
                block_index = counters.get(block["id"], 0)
                counters[block["id"]] = block_index + 1
                step = WorkStep(
                    step_id=f"{block['id']}-{block_index + 1}",
                    block_id=block["id"],
                    page=int(block["page"]),
                    lang=block["lang"],
                    clause_index=index,
                    text=clause,
                    action=_detect_action(clause),
                    objects=_detect_objects(clause),
                    actor="搭档" if _is_partner_verification(clause) else "操作者",
                    partner_verification=_is_partner_verification(clause),
                    connector_roles=tuple(classify_connectors(clause)),
                    figure_refs=tuple(fig_mentions(clause)),
                    layout_deictic=_layout_deixis(clause),
                )
                _bind_layout_figures(step, block, figures_by_page)
                _resolve_anaphora(step, block, last_by_object, last_step, steps)
                _apply_explicit_scope(step)
                if not step.module_scope and step.block_id in block_marker_scope:
                    step.module_scope = block_marker_scope[step.block_id]
                    step.scope_basis = f"block_marker:{step.block_id}"
                if step.module_scope and step.scope_basis == "explicit" and step.action is None:
                    block_marker_scope[step.block_id] = step.module_scope
                steps.append(step)
                for obj in step.objects:
                    last_by_object[obj] = step
                last_step = step

    resolve_scopes(steps)
    _link_companions(steps, blocks, figures)
    _annotate_static_findings(steps, figures)
    return steps


def _bind_layout_figures(
    step: WorkStep,
    block: dict,
    figures_by_page: dict[int, list[FigureRecord]],
) -> None:
    """“右图”只解析为同页右栏里显式登记的图，且只是版面右不是站位右。"""
    if not step.layout_deictic:
        return
    page = int(block["page"])
    candidates = [
        record
        for record in figures_by_page.get(page, [])
        if any(block_column(fig_block) == RIGHT for fig_block in record.figure_blocks)
    ]
    refs = set(step.figure_refs)
    if len(candidates) == 1:
        refs.add(candidates[0].number)
    else:
        step.add_finding(
            Finding(
                reason=REASON_AMBIGUOUS_REFERENCE,
                severity="hold",
                detail=f"{step.step_id} 的版面指示词无法唯一解析到同页右栏图",
                evidence=(step.text,),
            )
        )
    step.figure_refs = tuple(sorted(refs))


def _resolve_anaphora(
    step: WorkStep,
    block: dict,
    last_by_object: dict[str, WorkStep],
    last_step: WorkStep | None,
    earlier_steps: list[WorkStep],
) -> None:
    """只沿文本中的显式指代，向阅读顺序更早的工步回溯。

    - “该卡/the tab”：找更早工步里最近的卡对象；
    - “上一页”：限定为页码更早的工步；
    - 其他承接（如“露出的卡槽编号”）只链上一工步，不产生对象丢失风险。
    解析不到时标记语义不确定，同段其他句子照常保留。
    """
    roles = set(step.connector_roles)
    if "指代" not in roles and "跨页" not in roles:
        return
    text = step.text
    lowered = text.lower()
    targets: list[WorkStep] = []
    explicit_object = "该卡" in text or "the tab" in lowered or "the card" in lowered
    if explicit_object:
        for obj in ("white_tab", "blue_tab"):
            candidate = last_by_object.get(obj)
            if candidate is not None and candidate in earlier_steps and candidate not in targets:
                targets.append(candidate)
    if "上一页" in text:
        current_page = int(block["page"])
        previous = [
            candidate
            for candidate in reversed(earlier_steps)
            if candidate.page < current_page and candidate not in targets
        ]
        if step.action is not None:
            same_action = [candidate for candidate in previous if candidate.action == step.action]
            previous = same_action or previous[:1]
        else:
            previous = previous[:1]
        targets.extend(previous)
    if not targets and not explicit_object and last_step is not None:
        targets.append(last_step)

    seen: set[str] = set()
    for target in targets:
        if target.step_id in seen:
            continue
        seen.add(target.step_id)
        cross_page = target.page != step.page
        step.anaphora.append(
            {
                "kind": "object" if target.objects else "previous_step",
                "target_step": target.step_id,
                "target_block": target.block_id,
                "target_page": target.page,
                "cross_page": cross_page,
                "resolved": bool(target.objects) or not explicit_object,
            }
        )
    if explicit_object and not targets:
        step.add_finding(
            Finding(
                reason=REASON_AMBIGUOUS_REFERENCE,
                severity="hold",
                detail=f"{step.step_id} 的指代在更早工步中找不到先行对象",
                evidence=(text,),
            )
        )


def _apply_explicit_scope(step: WorkStep) -> None:
    explicit = module_mentions(step.text)
    if explicit:
        step.module_scope = frozenset(explicit)
        step.scope_basis = "explicit"


def _effective_objects(step: WorkStep, all_steps: list[WorkStep]) -> tuple[str, ...]:
    """工步的有效对象：本句对象 + 跨页指代解析到的先行对象。"""
    by_id = {candidate.step_id: candidate for candidate in all_steps}
    objects = set(step.objects)
    for link in step.anaphora:
        target = by_id.get(link["target_step"])
        if target is not None:
            objects.update(target.objects)
    return tuple(sorted(objects))


def resolve_scopes(steps: list[WorkStep]) -> None:
    """补齐模块范围：显式 M 标记优先；否则只按跨语言同动作对齐。

    同语言内不做距离推断；中英两个模块共用一张图时，英文句中的 M1/M2
    标记可通过动作对齐回填到对应中文工步，这是显式模块信息的语言间映射，
    不是几何归属。对象集合为空或相交（含跨页指代解析出的对象）即相容。
    """
    by_action: dict[str, list[WorkStep]] = {}
    for step in steps:
        if step.action:
            by_action.setdefault(step.action, []).append(step)

    for step in steps:
        if step.scope_basis == "explicit" or not step.action:
            continue
        donor = next(
            (
                candidate
                for candidate in by_action.get(step.action, [])
                if _is_scope_donor(candidate, step, steps)
            ),
            None,
        )
        if donor is not None:
            step.module_scope = donor.module_scope
            step.scope_basis = f"aligned:{donor.step_id}"


def _is_scope_donor(candidate: WorkStep, step: WorkStep, all_steps: list[WorkStep]) -> bool:
    if candidate is step or candidate.lang == step.lang or not candidate.module_scope:
        return False
    if candidate.scope_basis != "explicit" and not candidate.scope_basis.startswith(
        "block_marker:"
    ):
        return False
    return _effective_objects_compatible(step, candidate, all_steps)


def _effective_objects_compatible(
    left: WorkStep, right: WorkStep, all_steps: list[WorkStep]
) -> bool:
    left_objects = set(_effective_objects(left, all_steps)) or set(left.objects)
    right_objects = set(right.objects)
    if not left_objects or not right_objects:
        return True
    return bool(left_objects & right_objects)


def _link_companions(
    steps: list[WorkStep],
    blocks: list[dict],
    figures: dict[str, FigureRecord],
) -> None:
    """就近可读清单：工步所需参照图、图注、角注与勘误块。

    只纳入通过显式图号或页面唯一图关联的块；没有显式图号又无法唯一
    归页的角注不进入清单。
    """
    block_by_id = {block["id"]: block for block in blocks}
    for step in steps:
        companions: list[str] = []
        for number in step.figure_refs:
            record = figures.get(number)
            if record is None:
                continue
            for group in (
                record.figure_blocks,
                record.captions,
                record.errata,
                record.in_frame_labels,
            ):
                for block in group:
                    if block["id"] != step.block_id and block["id"] not in companions:
                        companions.append(block["id"])
        for link in step.anaphora:
            target_block = link["target_block"]
            if target_block in block_by_id and target_block not in companions:
                companions.append(target_block)
        step.companion_block_ids = tuple(companions)


def _annotate_static_findings(
    steps: list[WorkStep],
    figures: dict[str, FigureRecord],
) -> None:
    for step in steps:
        if step.layout_deictic:
            step.add_finding(
                Finding(
                    reason=REASON_LAYOUT_DEICTIC,
                    severity="language",
                    detail="“右图”指原始双栏版面的右栏，不指工人站位的右",
                    evidence=step.layout_deictic,
                    figures=step.figure_refs,
                    block_ids=(step.block_id,),
                )
            )
        for number in step.figure_refs:
            record = figures.get(number)
            if record is None:
                step.add_finding(
                    Finding(
                        reason=REASON_AMBIGUOUS_REFERENCE,
                        severity="hold",
                        detail=f"{step.step_id} 引用了资料中不存在的 {number}",
                        figures=(number,),
                        block_ids=(step.block_id,),
                    )
                )
                continue
            if record.viewpoint_conflict:
                step.add_finding(
                    Finding(
                        reason=REASON_VIEW_CONFLICT,
                        severity="hold",
                        detail=(
                            f"{number} 同时登记背面翻转视角与正视视角；"
                            "未拿到更正前，左右方向语义不确定"
                        ),
                        evidence=tuple(block["text"] for block in record.figure_blocks + record.errata),
                        figures=(number,),
                        block_ids=tuple(
                            block["id"]
                            for block in record.figure_blocks + record.errata
                        ),
                    )
                )
            if record.occluded:
                affected = _occlusion_affected(step, record)
                if affected:
                    step.add_finding(
                        Finding(
                            reason=REASON_OCCLUDED,
                            severity="hold",
                            detail=(
                                f"{number} 的 {sorted(affected)} 标注被遮挡或仅虚线轮廓，"
                                "依赖该标注的工步语义不确定；同图其他段仍可用"
                            ),
                            evidence=tuple(note["note"] for note in record.note_blocks)
                            + tuple(block["text"] for block in record.figure_blocks),
                            figures=(number,),
                            block_ids=tuple(block["id"] for block in record.figure_blocks),
                        )
                    )
            viewpoint_note = _viewpoint_note(step, record)
            if viewpoint_note is not None:
                step.add_finding(
                    Finding(
                        reason=REASON_VIEWPOINT_CONVENTION,
                        severity="language",
                        detail=(
                            f"{number} 存在视角约定（操作者/搭档方向相反），"
                            "核对方向时各用本方视角材料"
                        ),
                        evidence=(viewpoint_note,),
                        figures=(number,),
                    )
                )
    _annotate_translation_swaps(steps)


# 新的语言级原因：视角约定，不阻断练习但需老师点明站位。
REASON_VIEWPOINT_CONVENTION = "VIEWPOINT_CONVENTION"

_OCCLUSION_KEYWORDS = {
    "slot_label": ("右", "槽", "方向", "侧", "right", "slot"),
    "white_tab": ("白卡", "white tab"),
    "blue_tab_reference": ("蓝卡", "blue tab", "方向标记"),
}


def _occlusion_affected(step: WorkStep, record: FigureRecord) -> list[str]:
    """只有工步文本真正涉及被遮对象时才判定受影响。"""
    lowered = step.text.lower()
    affected: list[str] = []
    for subject in record.occlusion_subjects:
        keywords = _OCCLUSION_KEYWORDS.get(subject, ())
        if any(keyword.lower() in lowered for keyword in keywords):
            affected.append(subject)
    return affected


def _viewpoint_note(step: WorkStep, record: FigureRecord) -> str | None:
    for note in record.note_blocks:
        text = note["note"]
        if "视角" in text or "站位" in text or "操作者" in text or "搭档" in text:
            return text
    return None


def _annotate_translation_swaps(steps: list[WorkStep]) -> None:
    """译文把动作和对象/确认条件的顺序调换时，标记对应工步语义不确定。

    中文常把“搭档核对”拆成动作之后的独立小句（先拔卡、再让搭档核对），
    英文则用 when/if 条件句把搭档确认写成拔卡的前置条件。检测口径：
    中文主动作小句在同块后续小句里出现搭档核对，而跨语言同动作的英文
    小句带 when/if + partner，则两边都保留可用内容，只给 language 级风险。
    跨语言配对只按相同动作、对象集合相容，不使用几何距离。
    """
    by_action: dict[str, list[WorkStep]] = {}
    for step in steps:
        if step.action:
            by_action.setdefault(step.action, []).append(step)
    for position, step in enumerate(steps):
        if step.lang != "zh" or not step.action:
            continue
        following_partner = None
        for later in steps[position + 1 :]:
            if later.block_id != step.block_id or later.lang != step.lang:
                break
            if later.partner_verification:
                following_partner = later
                break
        if following_partner is None:
            continue
        for candidate in by_action.get(step.action, []):
            if candidate.lang != "en" or not _effective_objects_compatible(
                step, candidate, steps
            ):
                continue
            lowered = candidate.text.lower()
            if not re.search(r"\b(when|if)\b", lowered) or "partner" not in lowered:
                continue
            for target in (step, candidate):
                target.add_finding(
                    Finding(
                        reason=REASON_TRANSLATION_SWAP,
                        severity="language",
                        detail=(
                            "中文把搭档核对放在拔卡之后，英文 when 条件句把搭档确认"
                            "写成拔卡前置条件，动作/条件顺序被译文调换，需老师语言校订"
                        ),
                        evidence=(step.text, following_partner.text, candidate.text),
                        figures=step.figure_refs,
                        block_ids=(step.block_id, candidate.block_id),
                    )
                )
            break
