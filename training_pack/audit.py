"""课后追溯：学生实际看到哪份图、哪段操作被授权。

attempts 记录学生实际消费过的材料；issue_log 记录发放签收与版本。
两份来源独立，本模块只做核对，不替任何一方补数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .distribution import ClassroomContext
from .figures import FigureRecord
from .steps import WorkStep


@dataclass
class AttemptTrace:
    attempt_id: str
    classroom_id: str
    block_id: str
    archived: bool
    detail: str
    figure_numbers: tuple[str, ...] = ()
    figure_versions: dict[str, str] = field(default_factory=dict)
    effective_viewpoint: str = ""
    usable_for: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def trace_attempts(
    attempts: list[dict],
    contexts: dict[str, ClassroomContext],
    figures: dict[str, FigureRecord],
    blocks: list[dict],
) -> list[AttemptTrace]:
    """逐条核对学生实际看到的图与视角，指出该条报告仍能核对什么。"""
    block_by_id = {block["id"]: block for block in blocks}
    traces: list[AttemptTrace] = []
    for row in attempts:
        context = contexts[row["classroom"]]
        block = block_by_id.get(row["block"])
        text = block["text"] if block else ""
        numbers = tuple(_figures_for_block(block, figures))
        trace = AttemptTrace(
            attempt_id=row["id"],
            classroom_id=row["classroom"],
            block_id=row["id"] and row["block"],
            archived=row["archive"] == "是",
            detail=row["detail"],
            figure_numbers=numbers,
        )
        for number in numbers:
            record = figures[number]
            recipient = _recipient_from_detail(row["detail"])
            version, viewpoint, warnings = _view_for_attempt(
                context, record, row["detail"], recipient
            )
            trace.figure_versions[number] = version
            trace.effective_viewpoint = viewpoint
            trace.warnings.extend(warnings)
        trace.usable_for = _usable_for(trace, text)
        traces.append(trace)
    return traces


def _figures_for_block(block: dict | None, figures: dict[str, FigureRecord]) -> list[str]:
    if block is None:
        return []
    if block["kind"] == "图":
        return [
            number
            for number, record in figures.items()
            if any(fig_block["id"] == block["id"] for fig_block in record.figure_blocks)
        ]
    from .figures import fig_mentions

    return fig_mentions(block["text"])


def _recipient_from_detail(detail: str) -> str | None:
    """attempts 明细里的甲=操作者、乙=搭档（沿用课堂登记口径）。"""
    if detail.startswith("乙") or "乙另" in detail:
        return "搭档"
    if detail.startswith("甲"):
        return "操作者"
    return None


def _view_for_attempt(
    context: ClassroomContext,
    record: FigureRecord,
    attempt_detail: str,
    recipient: str | None,
) -> tuple[str, str, list[str]]:
    """以该角色实际发放和学生登记的实际使用方式判断有效视角。

    attempts 是已消费材料的留档，没有时间戳；若明细明确写“原图/后侧”，
    以学生实际看到的旧版为准，不能用后来补发的勘误倒推当时视角。
    发给另一角色的勘误页不能提升本条记录的版本。
    """
    target_recipients = [recipient] if recipient else list(context.issues_by_recipient)
    issued_figure = None
    for name in target_recipients:
        for block in record.figure_blocks:
            issued = context.latest_issue(name, block["id"])
            if issued is not None:
                issued_figure = issued
                break
        if issued_figure is not None:
            break
    erratum_issued = bool(recipient) and any(
        context.latest_issue(recipient, block["id"]) is not None
        for block in record.errata
    )
    used_rear = any(token in attempt_detail for token in ("后侧", "背面", "原图", "rear"))
    warnings: list[str] = []
    if used_rear or not erratum_issued:
        version = issued_figure.version if issued_figure else "未见发放记录"
        viewpoint = "背面翻转视角（与学生正面站位左右相反）"
        warnings.append("学生实际看到的是旧版背面翻转图，左右方向不能直接用于正面操作")
    else:
        version = "含正视勘误的更正版"
        viewpoint = "正视视角"
    if record.occluded:
        warnings.append("被遮挡标注（右槽标签/白卡虚线轮廓）未补印，相关方向描述仍不可直接核对")
    return version, viewpoint, warnings


def _usable_for(trace: AttemptTrace, text: str) -> list[str]:
    """该条报告仍可用于核对的内容（剔除被视角/遮挡污染的部分）。"""
    usable: list[str] = []
    lowered = text.lower()
    if any(token in text for token in ("槽号", "卡槽", "slot")):
        usable.append("卡槽编号核对")
    if any(token in text for token in ("蓝卡", "blue tab")):
        usable.append("蓝卡方向标记识别（标记本身不依赖左右镜像）")
    if "partner" in lowered or "搭档" in text:
        usable.append("搭档视角描述的英文图注留档")
    if not usable:
        usable.append("仅作为已消费材料的签收留档，不用于方向核对")
    return usable


def authorization_trace(
    context: ClassroomContext,
    steps: list[WorkStep],
) -> dict[str, list[dict]]:
    """按角色列出实际授权可操作的工步：工步所在页必须在该角色签收范围内。"""
    authorized: dict[str, list[dict]] = {}
    for recipient in context.issues_by_recipient:
        rows = []
        issued = context.issued_blocks(recipient)
        for step in steps:
            if step.block_id not in issued:
                continue
            missing_companions = [
                block_id
                for block_id in step.companion_block_ids
                if block_id not in issued
            ]
            rows.append(
                {
                    "step_id": step.step_id,
                    "block_id": step.block_id,
                    "version": issued[step.block_id].version,
                    "figures": list(step.figure_refs),
                    "missing_companions": missing_companions,
                    "authorized": not missing_companions,
                }
            )
        authorized[recipient] = rows
    return authorized
