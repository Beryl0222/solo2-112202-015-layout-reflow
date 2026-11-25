"""按实际发放与页面可见范围评估工步。

一切以工人实际拿到的一页或一叠为准：issue_log 决定每个操作角色能看到
哪些块、是哪个版本；旧版引用即使在资料里存在，也必须按实际发放和页面
可见范围核对。限新模型（M2）的工步不得进入旧模型（M1）练习包。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .figures import FigureRecord
from .steps import (
    REASON_MISSING_ANTECEDENT,
    REASON_MISSING_FIGURE,
    REASON_MODEL_GATED,
    REASON_MONOPOLY,
    REASON_NOT_ISSUED,
    REASON_OLD_VIEW,
    REASON_VIEW_CONFLICT,
    Finding,
    WorkStep,
)

ERRATUM_KIND = "勘误"
CAPTION_KIND = "图注"
FIGURE_KIND = "图"


@dataclass
class IssuedBlock:
    block_id: str
    version: str
    issued: str


@dataclass
class ClassroomContext:
    classroom: dict
    issues_by_recipient: dict[str, list[dict]]
    issued_by_recipient: dict[str, dict[str, IssuedBlock]]
    figures: dict[str, FigureRecord]
    blocks_by_id: dict[str, dict]
    model: str = ""
    mode: str = ""
    lesson: str = ""

    def issued_blocks(self, recipient: str) -> dict[str, IssuedBlock]:
        return self.issued_by_recipient.get(recipient, {})

    def latest_issue(self, recipient: str, block_id: str) -> IssuedBlock | None:
        return self.issued_by_recipient.get(recipient, {}).get(block_id)

    def has_erratum(self, recipient: str, figure_number: str) -> bool:
        """该角色是否实际拿到指定图的勘误块（按显式图号核对）。"""
        record = self.figures.get(figure_number)
        if record is None:
            return False
        erratum_ids = {block["id"] for block in record.errata}
        return any(block_id in erratum_ids for block_id in self.issued_blocks(recipient))

    def own_view_caption(self, recipient: str, figure_number: str) -> dict | None:
        """该角色可见且描述本方视角的图注（避免由对方独占方向说明）。"""
        record = self.figures.get(figure_number)
        if record is None:
            return None
        issued = self.issued_blocks(recipient)
        for caption in record.captions:
            if caption["id"] not in issued:
                continue
            text = caption["text"]
            if recipient == "搭档":
                if "搭档" in text or "partner" in text.lower():
                    return caption
            elif "练习者站位" in text or "操作者" in text or "operator" in text.lower():
                return caption
        return None


def build_context(
    classrooms: list[dict],
    issues: list[dict],
    blocks: list[dict],
    figures: dict[str, FigureRecord],
) -> dict[str, ClassroomContext]:
    blocks_by_id = {block["id"]: block for block in blocks}
    contexts: dict[str, ClassroomContext] = {}
    for classroom in classrooms:
        room_issues = [row for row in issues if row["classroom"] == classroom["id"]]
        issues_by_recipient: dict[str, list[dict]] = {}
        issued: dict[str, dict[str, IssuedBlock]] = {}
        for row in room_issues:
            recipient = row["recipient"]
            issues_by_recipient.setdefault(recipient, []).append(row)
            bucket = issued.setdefault(recipient, {})
            for block_id in row["blocks"].split("|"):
                if not block_id:
                    continue
                previous = bucket.get(block_id)
                if previous is None or row["issued"] > previous.issued:
                    bucket[block_id] = IssuedBlock(block_id, row["version"], row["issued"])
        contexts[classroom["id"]] = ClassroomContext(
            classroom=classroom,
            issues_by_recipient=issues_by_recipient,
            issued_by_recipient=issued,
            figures=figures,
            blocks_by_id=blocks_by_id,
            model=classroom["model"],
            mode=classroom["mode"],
            lesson=classroom["lesson"],
        )
    return contexts


def visible_blocks(context: ClassroomContext, recipient: str) -> set[str]:
    return set(context.issued_blocks(recipient))


@dataclass
class EvaluatedStep:
    step: WorkStep
    recipient: str
    visible: bool
    status: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def held_reasons(self) -> tuple[str, ...]:
        return tuple(item.reason for item in self.findings if item.severity == "hold")

    @property
    def language_reasons(self) -> tuple[str, ...]:
        return tuple(item.reason for item in self.findings if item.severity == "language")


def _model_gated(step: WorkStep, model: str) -> bool:
    return bool(step.module_scope) and model not in step.module_scope


def evaluate_classroom(
    context: ClassroomContext,
    steps: list[WorkStep],
    correction_clearance: dict[str, set[tuple[str, str]]] | None = None,
) -> dict[str, list[EvaluatedStep]]:
    """对每个领取角色给出逐工步评估。

    correction_clearance 是教师更正后的逐角色放行表：
    {角色: {(工步id, 风险原因)}}，只对实际拿到更正材料的角色生效。
    返回 {角色: [EvaluatedStep]}；未发教室的所有工步保持 NOT_ISSUED，
    由 planning 层在排练习包时排除并说明。
    """
    correction_clearance = correction_clearance or {}
    recipients = sorted(context.issues_by_recipient) or ["操作者"]
    results: dict[str, list[EvaluatedStep]] = {}
    not_issued = context.classroom["phase"] == "未发"
    for recipient in recipients:
        issued = context.issued_blocks(recipient)
        cleared = correction_clearance.get(recipient, set())
        evaluated: list[EvaluatedStep] = []
        for step in steps:
            item = EvaluatedStep(step=step, recipient=recipient, visible=False, status="held")
            item.findings.extend(
                finding
                for finding in _step_language_findings(step)
                if (step.step_id, finding.reason) not in cleared
            )
            if not_issued or step.block_id not in issued:
                # 未发是发放状态；静态语义风险（视角/遮挡/译文）仍要随工步留痕，
                # 便于老师在发之前先知道该工步将来为何暂停。
                item.findings.append(
                    Finding(
                        reason=REASON_NOT_ISSUED,
                        severity="hold",
                        detail=f"{step.step_id} 所在页未发放给{recipient}",
                        block_ids=(step.block_id,),
                    )
                )
                item.visible = False
            else:
                item.visible = True
                _evaluate_visible(context, recipient, step, item, cleared)
            item.status = _classify(item)
            evaluated.append(item)
        results[recipient] = evaluated
    return results


def _step_language_findings(step: WorkStep) -> list[Finding]:
    return [
        Finding(
            reason=finding.reason,
            severity=finding.severity,
            detail=finding.detail,
            evidence=finding.evidence,
            figures=finding.figures,
            block_ids=finding.block_ids,
        )
        for finding in step.findings
    ]


def _evaluate_visible(
    context: ClassroomContext,
    recipient: str,
    step: WorkStep,
    item: EvaluatedStep,
    cleared: set[tuple[str, str]],
) -> None:
    def allow(reason: str) -> bool:
        return (step.step_id, reason) not in cleared

    # 1. 模型门槛：限新模型的工步不进旧版练习包（最高优先级）。
    if _model_gated(step, context.model):
        item.findings.append(
            Finding(
                reason=REASON_MODEL_GATED,
                severity="gated",
                detail=(
                    f"{step.step_id} 仅适用于 {sorted(step.module_scope)}，"
                    f"本台为 {context.model}，不得入包"
                ),
                block_ids=(step.block_id,),
            )
        )
        return

    # 2. 先行对象（“随后拔掉该卡”的上一步对象）必须在该角色可见范围内。
    missing_targets = {
        link["target_block"]
        for link in step.anaphora
        if link["kind"] == "object"
        and link["target_block"] not in context.issued_blocks(recipient)
    }
    for target_block in sorted(missing_targets):
        if not allow(REASON_MISSING_ANTECEDENT):
            continue
        item.findings.append(
            Finding(
                reason=REASON_MISSING_ANTECEDENT,
                severity="hold",
                detail=(
                    f"{step.step_id} 的指代对象在 {target_block}，"
                    f"{recipient}未拿到，拆页后对象丢失"
                ),
                block_ids=(step.block_id, target_block),
            )
        )

    # 3. 参照图与图注必须在页面可见范围内；视角风险按该角色实际版本核对。
    for number in step.figure_refs:
        record = context.figures.get(number)
        if record is None:
            continue
        figure_ids = {block["id"] for block in record.figure_blocks}
        if not (figure_ids & set(context.issued_blocks(recipient))):
            if allow(REASON_MISSING_FIGURE):
                item.findings.append(
                    Finding(
                        reason=REASON_MISSING_FIGURE,
                        severity="hold",
                        detail=f"{recipient}的可见页面中没有 {number}",
                        figures=(number,),
                        block_ids=tuple(sorted(figure_ids)),
                    )
                )
            continue
        _evaluate_figure_version(context, recipient, step, record, item, cleared)

    # 4. 双人操作：需要搭档核对方向的工步，不能由对方独占本方视角说明。
    if step.partner_verification and recipient == "搭档":
        _check_partner_monopoly(context, recipient, step, item, cleared)


def _evaluate_figure_version(
    context: ClassroomContext,
    recipient: str,
    step: WorkStep,
    record: FigureRecord,
    item: EvaluatedStep,
    cleared: set[tuple[str, str]],
) -> None:
    has_erratum = context.has_erratum(recipient, record.number)
    if record.viewpoint_conflict and not has_erratum:
        if (step.step_id, REASON_OLD_VIEW) in cleared:
            return
        item.findings.append(
            Finding(
                reason=REASON_OLD_VIEW,
                severity="hold",
                detail=(
                    f"{recipient}持 {record.number} 旧版（背面翻转），"
                    "未收到正视勘误，左右方向与实际站位相反"
                ),
                figures=(record.number,),
                block_ids=tuple(block["id"] for block in record.figure_blocks),
            )
        )
    elif record.viewpoint_conflict and has_erratum:
        # 勘误到手后，视角冲突不再阻断；遮挡是否仍阻断由静态标注按
        # 具体被遮对象与工步文本决定（SN1：右槽标签未随勘误重印）。
        item.findings[:] = [
            finding
            for finding in item.findings
            if finding.reason != REASON_VIEW_CONFLICT
            or (step.step_id, finding.reason) in cleared
        ]


def _check_partner_monopoly(
    context: ClassroomContext,
    recipient: str,
    step: WorkStep,
    item: EvaluatedStep,
    cleared: set[tuple[str, str]],
) -> None:
    if (step.step_id, REASON_MONOPOLY) in cleared:
        return
    for number in step.figure_refs:
        if context.own_view_caption(recipient, number) is None:
            item.findings.append(
                Finding(
                    reason=REASON_MONOPOLY,
                    severity="hold",
                    detail=(
                        f"{recipient}没有 {number} 的本方视角图注，"
                        "若只听操作者转述方向即由对方独占核对，须改用本方材料"
                    ),
                    figures=(number,),
                    block_ids=(step.block_id,),
                )
            )


def _classify(item: EvaluatedStep) -> str:
    severities = {finding.severity for finding in item.findings}
    if "gated" in severities:
        return "gated"
    if "hold" in severities:
        return "held"
    if "language" in severities:
        return "teacher_required"
    return "practicable"
