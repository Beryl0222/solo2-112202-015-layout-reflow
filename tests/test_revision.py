"""教师更正、换页/收卡决策与下一批讲义重走发放测试。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pack_check import DEFAULT_DATA, read_tables
from training_pack.distribution import build_context
from training_pack.figures import build_figure_registry
from training_pack.planning import plan_classroom
from training_pack.revision import (
    Correction,
    apply_corrections,
    change_decision,
    load_corrections,
)
from training_pack.steps import build_steps


class RevisionFixture:
    @classmethod
    def build(cls):
        cls.tables = read_tables()
        cls.figures = build_figure_registry(
            cls.tables["blocks.tsv"],
            sheet_notes=cls.tables["sheet_notes.tsv"],
            aids=cls.tables["aids.tsv"],
        )
        cls.steps = build_steps(cls.tables["blocks.tsv"], cls.figures)
        cls.contexts = build_context(
            cls.tables["classrooms.tsv"],
            cls.tables["issue_log.tsv"],
            cls.tables["blocks.tsv"],
            cls.figures,
        )


class CorrectionTest(RevisionFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_orientation_correction_only_benefits_holder_of_erratum(self):
        correction = Correction(
            correction_id="K1",
            kind="orientation",
            figure_number="图 2",
            note="正视重订",
            target_block_ids=("B8",),
            clear_reasons=frozenset({"VIEW_CONFLICT", "OLD_VIEW"}),
        )
        plan = apply_corrections(self.contexts["C2"], self.steps, [correction])
        operator = next(
            item for item in plan.by_recipient["操作者"] if item.step.step_id == "B2-2"
        )
        partner = next(
            item for item in plan.by_recipient["搭档"] if item.step.step_id == "B2-2"
        )
        self.assertNotIn("VIEW_CONFLICT", operator.reasons)
        # 搭档没拿到 B8，静态视角冲突不得被清除。
        self.assertIn("VIEW_CONFLICT", partner.reasons)

    def test_occlusion_correction_without_reprint_does_not_clear(self):
        correction = Correction(
            correction_id="K2",
            kind="occlusion",
            figure_number="图 2",
            note="右槽标签待重印",
            target_block_ids=("B3",),
            reprinted_block_ids=(),
            physical=True,
            clear_reasons=frozenset({"LABEL_OCCLUDED"}),
        )
        plan = apply_corrections(self.contexts["C2"], self.steps, [correction])
        operator = next(
            item for item in plan.by_recipient["操作者"] if item.step.step_id == "B2-2"
        )
        self.assertIn("LABEL_OCCLUDED", operator.reasons)

    def test_translation_correction_requires_issued_target_block(self):
        correction = Correction(
            correction_id="K3",
            kind="translation",
            figure_number="图 3",
            note="条件顺序校订",
            target_block_ids=("B5", "B7"),
            clear_reasons=frozenset({"TRANSLATION_SWAP"}),
        )
        plan = apply_corrections(self.contexts["C2"], self.steps, [correction])
        operator = next(
            item for item in plan.by_recipient["操作者"] if item.step.step_id == "B5-2"
        )
        self.assertNotIn("TRANSLATION_SWAP", operator.reasons)
        # C2 搭档签收了 B5，同样适用；C3 搭档 B5/B7 都没拿到，
        # 其工步上的翻译风险不得被清除。
        plan_c3 = apply_corrections(self.contexts["C3"], self.steps, [correction])
        c3_partner = next(
            item for item in plan_c3.by_recipient["搭档"] if item.step.step_id == "B5-2"
        )
        self.assertIn("TRANSLATION_SWAP", c3_partner.reasons)

    def test_load_corrections_rejects_unknown_kind(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text(
                json.dumps({"corrections": [{"id": "X", "kind": "nope", "figure_number": "图 2"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_corrections(path)


class ChangeDecisionTest(RevisionFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_flipped_rear_figure_requires_card_recall(self):
        decision = change_decision(self.contexts["C2"], self.steps, "图 2")
        self.assertTrue(decision.needs_recall)
        self.assertIn("收回", decision.action)
        self.assertIn("B2-2", decision.blocked_step_ids)
        # 不依赖图 2 的练习仍可继续。
        self.assertIn("B5-3", decision.continuable_step_ids)

    def test_dashed_figure_defaults_to_page_swap(self):
        decision = change_decision(self.contexts["C2"], self.steps, "图 3")
        self.assertFalse(decision.needs_recall)
        self.assertIn("换讲义页", decision.action)

    def test_physical_correction_forces_recall(self):
        correction = Correction(
            correction_id="K2",
            kind="occlusion",
            figure_number="图 3",
            note="白卡轮廓重印",
            target_block_ids=("B9",),
            reprinted_block_ids=("B9",),
            physical=True,
        )
        decision = change_decision(
            self.contexts["C2"], self.steps, "图 3", [correction]
        )
        self.assertTrue(decision.needs_recall)


class NextBatchRerunTest(unittest.TestCase):
    """用下一批讲义重走发放：合成资料放在独立临时目录，路径以参数传入。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.batch_dir = Path(self.temporary.name) / "next_materials"
        shutil.copytree(DEFAULT_DATA, self.batch_dir)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, name: str, content: str) -> None:
        (self.batch_dir / name).write_text(content, encoding="utf-8")

    def test_reprinted_card_releases_occlusion_hold_in_next_batch(self):
        # 下一批：搭档也收到正视勘误页与重印的 B13 实物卡（右槽标签已补印）。
        # 历史印务观察 SN1 保留，但新卡显式声明遮挡已解除。
        self._write(
            "blocks.tsv",
            (self.batch_dir / "blocks.tsv").read_text(encoding="utf-8")
            + "B13\t1\t图\t300,68,250,140\tzh\t图 2 正视重印卡，右槽标签已补印，用于 M2。\n",
        )
        self._write(
            "issue_log.tsv",
            (self.batch_dir / "issue_log.tsv").read_text(encoding="utf-8")
            + "G6\tC2\t搭档\t2026-11-02T09:00\t图 2 正视重印批\tB8|B13\n",
        )
        tables = read_tables(self.batch_dir)
        figures = build_figure_registry(
            tables["blocks.tsv"],
            sheet_notes=tables["sheet_notes.tsv"],
            aids=tables["aids.tsv"],
        )
        self.assertNotIn("slot_label", figures["图 2"].occlusion_subjects)
        steps = build_steps(tables["blocks.tsv"], figures)
        contexts = build_context(
            tables["classrooms.tsv"],
            tables["issue_log.tsv"],
            tables["blocks.tsv"],
            figures,
        )
        plan = plan_classroom(contexts["C2"], steps)
        # 搭档仍无 B2 正文页：工步本体不到手仍是 NOT_ISSUED，而不是视角/遮挡问题。
        partner = {item.step.step_id: item for item in plan.by_recipient["搭档"]}
        self.assertIn("NOT_ISSUED", partner["B2-2"].reasons)
        self.assertNotIn("OLD_VIEW", partner["B2-2"].reasons)
        self.assertNotIn("LABEL_OCCLUDED", partner["B2-2"].reasons)


if __name__ == "__main__":
    unittest.main()
