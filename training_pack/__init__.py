"""设备培训讲义工步拆分与发放核对包。

输入是供应商来件的文本块/图框标记（materials/*.tsv），输出以工人实际
拿到的一页或一叠为准的工步练习计划：哪些工步可练、哪些必须暂停由老师
解释、哪些只是待语言校订、哪些限新模型不得进旧版练习包。

本包只消费资料中已有的文本块与检测位置，不猜测图面内容；图号归属只认
显式的“图 N / Fig. N”标记与显式模块标记，不按几何距离归属。
"""
from __future__ import annotations

from .geometry import Box, block_column, parse_box, page_width
from .figures import FigureRecord, build_figure_registry, fig_mentions, module_mentions
from .discourse import (
    Paragraph,
    build_paragraphs,
    split_clauses,
    split_sentences,
)
from .steps import (
    STEP_STATUSES,
    WorkStep,
    build_steps,
    reading_order,
    resolve_scopes,
)
from .distribution import (
    ClassroomContext,
    build_context,
    evaluate_classroom,
    visible_blocks,
)
from .planning import GROUPINGS, plan_classroom, station_report
from .audit import trace_attempts, authorization_trace
from .revision import (
    Correction,
    apply_corrections,
    change_decision,
    load_corrections,
)
from .report import render_plan_text, render_station_text, to_jsonable

__all__ = [
    "Box",
    "parse_box",
    "block_column",
    "page_width",
    "FigureRecord",
    "build_figure_registry",
    "fig_mentions",
    "module_mentions",
    "Paragraph",
    "build_paragraphs",
    "split_clauses",
    "split_sentences",
    "STEP_STATUSES",
    "WorkStep",
    "build_steps",
    "reading_order",
    "resolve_scopes",
    "ClassroomContext",
    "build_context",
    "evaluate_classroom",
    "visible_blocks",
    "GROUPINGS",
    "plan_classroom",
    "station_report",
    "trace_attempts",
    "authorization_trace",
    "Correction",
    "apply_corrections",
    "change_decision",
    "load_corrections",
    "render_plan_text",
    "render_station_text",
    "to_jsonable",
]
