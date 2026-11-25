"""计划的文本与 JSON 渲染。JSON 面向发练习包系统，文本面向教师当班阅读。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path

from .planning import GROUPINGS, Plan, STATUS_LABEL, station_report


def to_jsonable(value):
    """把计划/追溯结果转成可 json.dumps 的纯数据结构。"""
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


def render_plan_text(plan: Plan) -> str:
    lines = [
        f"教室 {plan.classroom_id}（{plan.lesson} / {plan.mode} / 模型 {plan.model} / {plan.phase}）",
        f"组织方式：{plan.grouping}；可选：{', '.join(GROUPINGS)}",
    ]
    for recipient, planned in plan.by_recipient.items():
        lines.append(f"\n[{recipient} 实际签收 {len(plan.by_recipient[recipient]) and '见下'}]")
        for item in planned:
            step = item.step
            reasons = f"；原因：{', '.join(item.reasons)}" if item.reasons else ""
            missing = f"；缺块：{', '.join(item.missing_block_ids)}" if item.missing_block_ids else ""
            figures = f"；图：{', '.join(step.figure_refs)}" if step.figure_refs else ""
            lines.append(
                f"  - {step.step_id} [{STATUS_LABEL[item.status]}] "
                f"{step.text}{figures}{reasons}{missing}"
            )
        lines.append(f"  替代练习（不依赖被暂停工步）：{', '.join(plan.alternatives[recipient]) or '无'}")
    if plan.tablet_bundles:
        lines.append("\n[平板同屏 bundle 就绪情况]")
        for bundle in plan.tablet_bundles:
            state = "就绪" if bundle["ready"] else "未就绪"
            needs = ", ".join(
                f"{need['block_id']}({need['role']})" for need in bundle["nearby_requirements"]
            )
            lines.append(f"  - {bundle['step_id']} {state}；就近需求：{needs or '无'}")
    if plan.correction_notes:
        lines.append("\n[教师更正适用记录]")
        for step_id, notes in sorted(plan.correction_notes.items()):
            for note in notes:
                lines.append(f"  - {step_id}：{note}")
    return "\n".join(lines)


def render_station_text(plan: Plan) -> str:
    report = station_report(plan)
    lines = [
        f"台位 {report['classroom']}（{report['model']} / {report['mode']}）结论：",
    ]
    for recipient, payload in report["recipients"].items():
        lines.append(f"\n[{recipient}] {payload['verdict']}")
        lines.append(f"  汇总：{payload['summary']}")
        for status, rows in payload["steps"].items():
            if not rows:
                continue
            ids = ", ".join(row["step_id"] for row in rows)
            lines.append(f"  {STATUS_LABEL[status]}：{ids}")
        if payload["alternatives"]:
            lines.append(f"  当班可继续：{', '.join(payload['alternatives'])}")
    return "\n".join(lines)


def render_audit_text(traces, authorized) -> str:
    lines = ["[课后追溯：学生实际看到的图与授权操作]"]
    for trace in traces:
        lines.append(
            f"- {trace.attempt_id} 教室{trace.classroom_id} 块{trace.block_id}"
            f" 归档={'是' if trace.archived else '否'}"
        )
        for number, version in trace.figure_versions.items():
            lines.append(f"    {number}：{version}；有效视角：{trace.effective_viewpoint}")
        for warning in trace.warnings:
            lines.append(f"    风险：{warning}")
        lines.append(f"    仍可核对：{'；'.join(trace.usable_for)}")
    lines.append("\n[按角色授权操作]")
    for classroom_id, by_recipient in authorized.items():
        lines.append(f"- 教室 {classroom_id}")
        for recipient, rows in by_recipient.items():
            lines.append(f"  {recipient}")
            for row in rows:
                state = "授权完整" if row["authorized"] else f"缺参照 {row['missing_companions']}"
                lines.append(f"    {row['step_id']}（{row['version']}）{state}")
    return "\n".join(lines)


def render_revision_text(decision) -> str:
    lines = [
        f"[改图决策] {decision.classroom_id} / {decision.figure_number}",
        f"结论：{decision.action}",
    ]
    for recipient, row in decision.recipient_actions.items():
        lines.append(f"- {recipient}：{row['action']}（{row['detail']}）")
    lines.append(f"暂停工步：{', '.join(decision.blocked_step_ids) or '无'}")
    lines.append(f"可继续练习：{', '.join(decision.continuable_step_ids) or '无'}")
    return "\n".join(lines)


def write_json(path: str | Path, payload) -> None:
    import json

    Path(path).write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
