"""练习包编排：多个合法组织方式 + 信息看不全时暂停。

同一份素材同时服务线上复习与现场双人练习。在线上先看到练习页之前，
必要的参照图、上一步留下的状态和相关术语必须就近可读；现场双人练习时
两人都要能用本方材料核对方向。教师可在三种合法组织方式之间选择，
被暂停的工步不进练习包，同时给出不依赖它的替代练习让当班继续。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .distribution import ClassroomContext, EvaluatedStep, evaluate_classroom
from .steps import (
    REASON_MODEL_GATED,
    REASON_NOT_ISSUED,
    WorkStep,
)

GROUPINGS = (
    "by_step",       # 按工步顺序组织
    "by_figure",     # 围绕参照图组织
    "as_issued",     # 按实际发放的页/卡片组织
)
STATUS_LABEL = {
    "practicable": "可练",
    "teacher_required": "待语言校订（老师解释后可练）",
    "held": "暂停（必要信息看不全）",
    "gated": "限新模型，不入旧版练习包",
}


@dataclass
class PlannedStep:
    recipient: str
    step: WorkStep
    status: str
    reasons: tuple[str, ...]
    required_block_ids: tuple[str, ...]
    missing_block_ids: tuple[str, ...]
    bundle_ready: bool

    @property
    def in_pack(self) -> bool:
        return self.status in ("practicable", "teacher_required")


@dataclass
class Plan:
    classroom_id: str
    lesson: str
    mode: str
    model: str
    phase: str
    grouping: str
    by_recipient: dict[str, list[PlannedStep]] = field(default_factory=dict)
    alternatives: dict[str, list[str]] = field(default_factory=dict)
    tablet_bundles: list[dict] = field(default_factory=list)
    correction_notes: dict[str, list[str]] = field(default_factory=dict)


def plan_classroom(
    context: ClassroomContext,
    steps: list[WorkStep],
    grouping: str = "by_step",
    correction_clearance: dict[str, set[tuple[str, str]]] | None = None,
) -> Plan:
    if grouping not in GROUPINGS:
        raise ValueError(f"未知组织方式：{grouping}，可选 {GROUPINGS}")
    evaluated = evaluate_classroom(context, steps, correction_clearance=correction_clearance)
    plan = Plan(
        classroom_id=context.classroom["id"],
        lesson=context.lesson,
        mode=context.mode,
        model=context.model,
        phase=context.classroom["phase"],
        grouping=grouping,
    )
    for recipient, items in evaluated.items():
        planned = [_plan_one(context, recipient, item) for item in items]
        if grouping == "by_figure":
            # 围绕参照图组织：带图工步（按图号）在前，无图工步垫后。
            planned.sort(
                key=lambda item: (
                    not bool(item.step.figure_refs),
                    item.step.figure_refs or ("~",),
                    item.step.step_id,
                )
            )
        elif grouping == "as_issued":
            order = {block_id: index for index, block_id in enumerate(context.issued_blocks(recipient))}
            planned.sort(key=lambda item: (order.get(item.step.block_id, 10**6), item.step.step_id))
        else:
            planned.sort(key=lambda item: item.step.step_id)
        plan.by_recipient[recipient] = planned
        plan.alternatives[recipient] = _alternatives(planned)
    # 线上复习与现场双人练习从同一批素材发放，bundle 清单两种模式都生成；
    # 平板模式要求练习页之前同屏可读，双人模式作为开练前的材料核对单。
    plan.tablet_bundles = _tablet_bundles(plan, context)
    return plan


def _plan_one(
    context: ClassroomContext,
    recipient: str,
    item: EvaluatedStep,
) -> PlannedStep:
    step = item.step
    issued = context.issued_blocks(recipient)
    required = {step.block_id, *step.companion_block_ids}
    for link in step.anaphora:
        required.add(link["target_block"])
    missing = tuple(sorted(block_id for block_id in required if block_id not in issued))
    reasons = tuple(finding.reason for finding in item.findings)
    bundle_ready = item.visible and not missing and item.status in (
        "practicable",
        "teacher_required",
    )
    return PlannedStep(
        recipient=recipient,
        step=step,
        status=item.status,
        reasons=reasons,
        required_block_ids=tuple(sorted(required)),
        missing_block_ids=missing,
        bundle_ready=bundle_ready,
    )


def _alternatives(planned: list[PlannedStep]) -> list[str]:
    """不依赖被暂停/受限工步的可练工步，供当班继续。"""
    blocked_figures = {
        figure
        for item in planned
        if item.status == "held"
        for figure in item.step.figure_refs
    }
    alternatives = []
    for item in planned:
        if item.status != "practicable":
            continue
        if any(figure in blocked_figures for figure in item.step.figure_refs):
            continue
        alternatives.append(item.step.step_id)
    return alternatives


def _tablet_bundles(plan: Plan, context: ClassroomContext) -> list[dict]:
    """线上平板页：练习页之前把参照图、上一步状态、术语就近打包同屏。"""
    bundles = []
    for recipient, planned in plan.by_recipient.items():
        for item in planned:
            if not item.in_pack:
                continue
            step = item.step
            needs = [
                {
                    "block_id": block_id,
                    "role": _companion_role(block_id, step, context),
                    "visible": block_id in context.issued_blocks(recipient),
                }
                for block_id in item.required_block_ids
                if block_id != step.block_id
            ]
            bundles.append(
                {
                    "recipient": recipient,
                    "step_id": step.step_id,
                    "practice_block": step.block_id,
                    "nearby_requirements": needs,
                    "ready": item.bundle_ready and all(need["visible"] for need in needs),
                }
            )
    return bundles


def _companion_role(block_id: str, step: WorkStep, context: ClassroomContext) -> str:
    block = context.blocks_by_id.get(block_id)
    if block is None:
        return "unknown"
    if block["kind"] == "图":
        return "参照图"
    if block["kind"] == "图注":
        return "视角图注"
    if block["kind"] == "勘误":
        return "勘误"
    if block["kind"] == "角注":
        return "图上术语"
    if any(link["target_block"] == block_id for link in step.anaphora):
        return "上一步状态"
    return "关联页"


def station_report(plan: Plan) -> dict:
    """按台位回答：工步还不能练，还是仅待语言校订。"""
    report = {
        "classroom": plan.classroom_id,
        "lesson": plan.lesson,
        "mode": plan.mode,
        "model": plan.model,
        "phase": plan.phase,
        "grouping": plan.grouping,
        "recipients": {},
    }
    for recipient, planned in plan.by_recipient.items():
        buckets = {status: [] for status in STATUS_LABEL}
        for item in planned:
            buckets[item.status].append(
                {
                    "step_id": item.step.step_id,
                    "reasons": list(item.reasons),
                    "missing": list(item.missing_block_ids),
                    "figures": list(item.step.figure_refs),
                }
            )
        report["recipients"][recipient] = {
            "summary": {status: len(rows) for status, rows in buckets.items()},
            "steps": buckets,
            "alternatives": plan.alternatives[recipient],
            "verdict": _verdict(buckets),
        }
    return report


def _verdict(buckets: dict[str, list]) -> str:
    if buckets["held"]:
        return "有工步还不能练：必要信息看不全，已暂停并给出替代练习"
    if buckets["gated"]:
        return "含限新模型工步，已从本台练习包剔除"
    if buckets["teacher_required"]:
        return "仅待语言校订：老师解释后即可练"
    return "当前工步均可练"


def gated_steps(plan: Plan) -> list[PlannedStep]:
    return [
        item
        for planned in plan.by_recipient.values()
        for item in planned
        if REASON_MODEL_GATED in item.reasons
    ]


def unissued_steps(plan: Plan) -> list[PlannedStep]:
    return [
        item
        for planned in plan.by_recipient.values()
        for item in planned
        if REASON_NOT_ISSUED in item.reasons
    ]
