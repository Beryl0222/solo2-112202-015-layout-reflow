"""命令行入口（从仓库根目录运行：python3 cli.py ...）。

所有输入路径均通过参数传入；读取外部资料目录的命令建议用 -I 运行，
避免资料目录里的同名模块污染导入。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pack_check import read_tables  # noqa: E402

from training_pack.audit import authorization_trace, trace_attempts  # noqa: E402
from training_pack.distribution import build_context  # noqa: E402
from training_pack.figures import build_figure_registry  # noqa: E402
from training_pack.planning import GROUPINGS, plan_classroom, station_report  # noqa: E402
from training_pack.report import (  # noqa: E402
    render_audit_text,
    render_plan_text,
    render_revision_text,
    render_station_text,
    to_jsonable,
)
from training_pack.revision import change_decision, load_corrections, apply_corrections  # noqa: E402
from training_pack.steps import build_steps  # noqa: E402


def load_pipeline(directory: Path):
    tables = read_tables(directory)
    figures = build_figure_registry(
        tables["blocks.tsv"],
        sheet_notes=tables["sheet_notes.tsv"],
        aids=tables["aids.tsv"],
    )
    steps = build_steps(tables["blocks.tsv"], figures)
    contexts = build_context(
        tables["classrooms.tsv"],
        tables["issue_log.tsv"],
        tables["blocks.tsv"],
        figures,
    )
    return tables, figures, steps, contexts


def _pick(contexts: dict, classroom_id: str | None):
    if classroom_id is None:
        return next(iter(contexts.values()))
    if classroom_id not in contexts:
        raise SystemExit(f"未知教室：{classroom_id}，可选 {sorted(contexts)}")
    return contexts[classroom_id]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "materials", help="资料目录")
    parser.add_argument("--json", type=Path, help="同时把结构化结果写入该 JSON 文件")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="按台位生成练习计划")
    plan_parser.add_argument("--classroom")
    plan_parser.add_argument("--grouping", choices=GROUPINGS, default="by_step")
    plan_parser.add_argument("--corrections", type=Path)

    sub.add_parser("station", help="按台位回答不能练还是仅待语言校订").add_argument("--classroom")
    sub.add_parser("audit", help="课后追溯实际看到的图与授权操作")
    revision_parser = sub.add_parser("revision", help="改图后的换页/收卡决策")
    revision_parser.add_argument("--classroom")
    revision_parser.add_argument("--figure", required=True)
    revision_parser.add_argument("--corrections", type=Path)

    args = parser.parse_args(argv)
    tables, figures, steps, contexts = load_pipeline(args.directory)

    if args.command == "plan":
        context = _pick(contexts, args.classroom)
        corrections = load_corrections(args.corrections) if args.corrections else []
        plan = (
            apply_corrections(context, steps, corrections, grouping=args.grouping)
            if corrections
            else plan_classroom(context, steps, grouping=args.grouping)
        )
        text = render_plan_text(plan)
        payload = to_jsonable(plan)
    elif args.command == "station":
        context = _pick(contexts, args.classroom)
        plan = plan_classroom(context, steps)
        text = render_station_text(plan)
        payload = station_report(plan)
    elif args.command == "audit":
        traces = trace_attempts(
            tables["attempts.tsv"], contexts, figures, tables["blocks.tsv"]
        )
        authorized = {
            room_id: authorization_trace(context, steps)
            for room_id, context in contexts.items()
        }
        text = render_audit_text(traces, authorized)
        payload = {"traces": to_jsonable(traces), "authorized": to_jsonable(authorized)}
    else:
        context = _pick(contexts, args.classroom)
        corrections = load_corrections(args.corrections) if args.corrections else []
        decision = change_decision(context, steps, args.figure, corrections)
        text = render_revision_text(decision)
        payload = to_jsonable(decision)

    print(text)
    if args.json:
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
