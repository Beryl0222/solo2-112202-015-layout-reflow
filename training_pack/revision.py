"""教师更正与改图后的发放决策。

老师可以更正图号、坐标方向或图上遮挡。更正只改变语义评估，不会凭空
授予可见性：更正后的图和图注可以先发给部分教室，旧版引用仍按实际发放
和页面可见范围核对。改图发生在班级已领取后，本模块判断是只换同一工步
的讲义页即可，还是必须收回实物练习卡并暂停继续发放。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .distribution import ClassroomContext
from .planning import Plan, plan_classroom
from .steps import (
    REASON_MISSING_ANTECEDENT,
    REASON_MISSING_FIGURE,
    REASON_MODEL_GATED,
    REASON_MONOPOLY,
    REASON_NOT_ISSUED,
    REASON_OCCLUDED,
    REASON_OLD_VIEW,
    REASON_VIEW_CONFLICT,
    WorkStep,
)

CORRECTION_KINDS = ("figure_number", "orientation", "occlusion", "translation")
# 可由更正消除的语义风险。
CLEARABLE = {
    "figure_number": {REASON_VIEW_CONFLICT, REASON_OLD_VIEW, "AMBIGUOUS_REFERENCE"},
    "orientation": {REASON_VIEW_CONFLICT, REASON_OLD_VIEW, "VIEWPOINT_CONVENTION"},
    "occlusion": {REASON_OCCLUDED},
    "translation": {"TRANSLATION_SWAP"},
}


@dataclass(frozen=True)
class Correction:
    correction_id: str
    kind: str
    figure_number: str
    note: str
    target_block_ids: tuple[str, ...] = ()
    clear_reasons: frozenset[str] = frozenset()
    physical: bool = False
    reprinted_block_ids: tuple[str, ...] = ()


def load_corrections(path: str | Path) -> list[Correction]:
    """读取教师更正文件（JSON，UTF-8）。更正文件属于受信任的教师输入。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    corrections: list[Correction] = []
    for row in payload.get("corrections", []):
        kind = row["kind"]
        if kind not in CORRECTION_KINDS:
            raise ValueError(f"未知更正类型：{kind}")
        figure_number = row["figure_number"]
        clear = frozenset(row.get("clear_reasons", CLEARABLE[kind]))
        corrections.append(
            Correction(
                correction_id=row["id"],
                kind=kind,
                figure_number=figure_number,
                note=row["note"],
                target_block_ids=tuple(row.get("target_block_ids", ())),
                clear_reasons=clear,
                physical=bool(row.get("physical", False)),
                reprinted_block_ids=tuple(row.get("reprinted_block_ids", ())),
            )
        )
    return corrections


def apply_corrections(
    context: ClassroomContext,
    steps: list[WorkStep],
    corrections: list[Correction],
    grouping: str = "by_step",
) -> Plan:
    """在不修改原始资料与原始工步的前提下应用更正并重排练习计划。

    更正只对实际拿到更正页/更正卡的角色生效：target_block_ids 必须在该
    角色的签收范围内。没拿到更正的角色继续按旧版评估，旧版引用仍按实际
    发放和页面可见范围核对。
    """
    clearance: dict[str, set[tuple[str, str]]] = {
        recipient: set() for recipient in context.issues_by_recipient
    }
    notes_by_step: dict[str, list[str]] = {}
    for correction in corrections:
        # 更正只在材料实际到该角色手里时生效：
        # - 普通更正比 target_block_ids（更正讲义页/图注）；
        # - 实物卡/遮挡更正比 reprinted_block_ids，重印卡未到不放行。
        material_blocks = (
            correction.reprinted_block_ids
            if correction.physical or correction.kind == "occlusion"
            else correction.target_block_ids
        )
        for recipient in context.issues_by_recipient:
            if not material_blocks:
                # 实物重印未给出到块记录时，视为更正材料尚未发放，不放行。
                holds_correction = False
            else:
                holds_correction = any(
                    block_id in context.issued_blocks(recipient) for block_id in material_blocks
                )
            if not holds_correction:
                continue
            for step in steps:
                touches_figure = (
                    correction.figure_number in step.figure_refs
                    and correction.kind != "translation"
                )
                touches_translation = (
                    correction.kind == "translation"
                    and step.block_id in correction.target_block_ids
                    and any(finding.reason == "TRANSLATION_SWAP" for finding in step.findings)
                )
                if not (touches_figure or touches_translation):
                    continue
                # 翻译/视角类语言更正只在工步页实际发放时才放行；未发角色
                # 保留原语义风险，等材料到手后再评估。
                if touches_translation and step.block_id not in context.issued_blocks(recipient):
                    continue
                for reason in correction.clear_reasons:
                    clearance[recipient].add((step.step_id, reason))
                notes_by_step.setdefault(step.step_id, []).append(
                    f"{recipient}适用更正 {correction.correction_id}：{correction.note}"
                )
    plan = plan_classroom(context, steps, grouping=grouping, correction_clearance=clearance)
    plan.correction_notes = notes_by_step
    return plan


@dataclass
class ChangeDecision:
    classroom_id: str
    figure_number: str
    recipient_actions: dict[str, dict] = field(default_factory=dict)
    blocked_step_ids: list[str] = field(default_factory=list)
    continuable_step_ids: list[str] = field(default_factory=list)
    needs_recall: bool = False

    @property
    def action(self) -> str:
        if self.needs_recall:
            return "收回实物练习卡并暂停继续发放，更正卡重印后再发"
        return "只换同一工步的讲义页（换讲义页即可），实物卡不收回"


def change_decision(
    context: ClassroomContext,
    steps: list[WorkStep],
    figure_number: str,
    corrections: list[Correction] | None = None,
) -> ChangeDecision:
    """班级已领取后改图：逐角色判断换页还是收卡。

    判定口径：
    - 只改视角/图号且只重印讲义页、图注、勘误 -> 换同一工步的讲义页；
    - 图本体或印在实物练习卡上的角注/被遮标注需要重印（含 occlusion 更正）
      -> 收回该角色已持有的实物卡并暂停继续发放；
    - 无论哪种情况，都列出不依赖该图、当班可继续的练习。
    """
    corrections = corrections or []
    record = context.figures[figure_number]
    decision = ChangeDecision(
        classroom_id=context.classroom["id"],
        figure_number=figure_number,
    )
    physical_correction = (
        any(correction.kind == "occlusion" for correction in corrections)
        or any(correction.physical for correction in corrections)
    )
    for recipient in context.issues_by_recipient:
        physical_ids = [
            block["id"]
            for block in record.figure_blocks + record.in_frame_labels
            if block["id"] in context.issued_blocks(recipient)
        ]
        if not physical_ids:
            decision.recipient_actions[recipient] = {
                "action": "换讲义页",
                "detail": "该角色未持有该图实物卡，补发更正讲义页/图注即可",
            }
            continue
        if physical_correction:
            decision.needs_recall = True
            decision.recipient_actions[recipient] = {
                "action": "收回实物练习卡",
                "detail": (
                    f"图面重印/遮挡补印涉及已发实物卡 {physical_ids}，"
                    "收回并暂停该工步继续发放，待更正卡重印"
                ),
            }
        elif record.viewpoint_conflict:
            # 背面翻转图被正视勘误替代：实物卡上的朝向信息整体失效，
            # 只换讲义页不能让旧卡变正确，必须收卡并暂停继续发放。
            decision.needs_recall = True
            decision.recipient_actions[recipient] = {
                "action": "收回实物练习卡",
                "detail": (
                    f"已发实物卡 {physical_ids} 为背面翻转视角，与正视勘误冲突，"
                    "旧卡左右方向整体失效，收卡后随更正版重新发放"
                ),
            }
        else:
            # 默认改图只换同一工步的讲义页/图注；实物卡上的局部遮挡通过
            # 暂停依赖该标注的工步处理（见 blocked_step_ids），不整卡收回。
            decision.recipient_actions[recipient] = {
                "action": "换讲义页",
                "detail": "视角/图号/图注更正只涉及讲义页，实物卡可留用；被遮工步另行暂停",
            }
    related = [
        step
        for step in steps
        if figure_number in step.figure_refs
        or any(figure_number in finding.figures for finding in step.findings)
    ]
    hold_reasons = {
        REASON_OLD_VIEW,
        REASON_VIEW_CONFLICT,
        REASON_OCCLUDED,
        REASON_MISSING_FIGURE,
        REASON_MONOPOLY,
    }
    for step in related:
        if any(finding.reason in hold_reasons for finding in step.findings):
            decision.blocked_step_ids.append(step.step_id)
        else:
            decision.continuable_step_ids.append(step.step_id)
    # 不依赖该图的练习始终可继续。
    for step in steps:
        if step in related:
            continue
        if step.step_id not in decision.continuable_step_ids and not _structural_block(step):
            decision.continuable_step_ids.append(step.step_id)
    return decision


def _structural_block(step: WorkStep) -> bool:
    return any(
        finding.reason in (REASON_MODEL_GATED, REASON_NOT_ISSUED, REASON_MISSING_ANTECEDENT)
        for finding in step.findings
    )
