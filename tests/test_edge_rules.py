"""合成边界规则测试：方向独占、同页多图不猜归属、未解析指代。"""
import unittest

from pack_check import read_tables
from training_pack.distribution import (
    ClassroomContext,
    IssuedBlock,
    evaluate_classroom,
)
from training_pack.figures import build_figure_registry
from training_pack.steps import (
    REASON_AMBIGUOUS_REFERENCE,
    REASON_MONOPOLY,
    Finding,
    WorkStep,
    build_steps,
)


class UnassociatedLabelTest(unittest.TestCase):
    def test_label_without_figure_number_on_multi_figure_page_is_guessed_neither(self):
        blocks = [
            {"id": "F1", "page": "5", "kind": "图", "box": "20,60,250,80", "lang": "zh", "text": "图 5 示意。"},
            {"id": "F2", "page": "5", "kind": "图", "box": "302,60,250,80", "lang": "zh", "text": "图 6 示意。"},
            {"id": "L1", "page": "5", "kind": "角注", "box": "100,90,80,18", "lang": "zh", "text": "无图号角注"},
        ]
        figures = build_figure_registry(blocks, sheet_notes=[], aids=[])
        self.assertTrue(all(record.unassociated_labels for record in figures.values()))
        self.assertFalse(any(record.in_frame_labels for record in figures.values()))


class AmbiguousReferenceTest(unittest.TestCase):
    def test_unresolved_deixis_marks_hold_but_keeps_other_steps(self):
        # 同页右栏没有任何图时，“右图”无法唯一解析，仅该小句挂起。
        blocks = [
            {"id": "X1", "page": "7", "kind": "正文", "box": "20,60,250,40", "lang": "zh", "text": "如右图，按下按钮。随后松开。"},
        ]
        figures = build_figure_registry(blocks, sheet_notes=[], aids=[])
        steps = build_steps(blocks, figures)
        deixis_step = next(step for step in steps if "右图" in step.text)
        self.assertIn(
            REASON_AMBIGUOUS_REFERENCE,
            {finding.reason for finding in deixis_step.findings},
        )
        other = [step for step in steps if step is not deixis_step]
        self.assertTrue(other)
        self.assertTrue(all(not step.findings for step in other))


class PartnerMonopolyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = read_tables()
        cls.figures = build_figure_registry(
            cls.tables["blocks.tsv"],
            sheet_notes=cls.tables["sheet_notes.tsv"],
            aids=cls.tables["aids.tsv"],
        )
        cls.steps = build_steps(cls.tables["blocks.tsv"], cls.figures)

    def _context_without_partner_caption(self) -> ClassroomContext:
        base = {
            row["id"]: row
            for row in self.tables["classrooms.tsv"]
            if row["id"] == "C2"
        }["C2"]
        issued = {
            "搭档": {
                # 有图 3 本体与操作者视角图注 B6，但缺搭档视角图注 B10。
                block_id: IssuedBlock(block_id, "合成批", "2026-11-01T09:00")
                for block_id in ("B5", "B9", "B6")
            }
        }
        return ClassroomContext(
            classroom=base,
            issues_by_recipient={"搭档": []},
            issued_by_recipient=issued,
            figures=self.figures,
            blocks_by_id={block["id"]: block for block in self.tables["blocks.tsv"]},
            model="M2",
            mode="双人",
            lesson="合成课",
        )

    def test_partner_without_own_view_caption_is_held(self):
        step = WorkStep(
            step_id="SYN-1",
            block_id="B5",
            page=2,
            lang="zh",
            clause_index=0,
            text="让搭档核对图 3 的方向",
            action="verify",
            objects=("slot",),
            actor="搭档",
            partner_verification=True,
            connector_roles=("搭档协同",),
            figure_refs=("图 3",),
            layout_deictic=(),
        )
        context = self._context_without_partner_caption()
        results = evaluate_classroom(context, [step])
        item = results["搭档"][0]
        self.assertEqual(item.status, "held")
        self.assertIn(REASON_MONOPOLY, {finding.reason for finding in item.findings})

    def test_own_view_caption_clears_monopoly(self):
        context = self._context_without_partner_caption()
        # 补发搭档视角图注 B10 后，同一工步不再有方向独占风险。
        context.issued_by_recipient["搭档"]["B10"] = IssuedBlock(
            "B10", "搭档视角批", "2026-11-01T10:00"
        )
        step = WorkStep(
            step_id="SYN-2",
            block_id="B5",
            page=2,
            lang="zh",
            clause_index=0,
            text="让搭档核对图 3 的方向",
            action="verify",
            objects=("slot",),
            actor="搭档",
            partner_verification=True,
            connector_roles=("搭档协同",),
            figure_refs=("图 3",),
            layout_deictic=(),
        )
        item = evaluate_classroom(context, [step])["搭档"][0]
        self.assertNotIn(
            REASON_MONOPOLY, {finding.reason for finding in item.findings}
        )
        self.assertEqual(item.status, "practicable")


if __name__ == "__main__":
    unittest.main()
