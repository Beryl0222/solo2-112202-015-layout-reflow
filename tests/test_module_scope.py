"""模块范围与按距离归属的反例测试。"""
import unittest

from pack_check import read_tables
from training_pack.figures import build_figure_registry
from training_pack.steps import build_steps


class ModuleScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = read_tables()
        cls.figures = build_figure_registry(
            cls.tables["blocks.tsv"],
            sheet_notes=cls.tables["sheet_notes.tsv"],
            aids=cls.tables["aids.tsv"],
        )
        cls.steps = build_steps(cls.tables["blocks.tsv"], cls.figures)
        cls.by_id = {step.step_id: step for step in cls.steps}

    def test_explicit_marker_clauses(self):
        self.assertEqual(self.by_id["B7-1"].module_scope, frozenset({"M1"}))
        self.assertEqual(self.by_id["B7-3"].module_scope, frozenset({"M2"}))

    def test_block_marker_scope_propagates_to_action_clauses(self):
        # For M1 / For M2 是独立小句，后续动作小句必须继承同块模块标记。
        self.assertEqual(self.by_id["B7-2"].module_scope, frozenset({"M1"}))
        self.assertEqual(self.by_id["B7-4"].module_scope, frozenset({"M2"}))

    def test_cross_language_alignment_backfills_chinese_scope(self):
        # 中文 B5-2 拔白卡本身没有 M 号，只能通过与英文同动作对齐获得 M2，
        # 不能因为它与图 3（M1/M2 共用）距离近就分给 M1。
        step = self.by_id["B5-2"]
        self.assertEqual(step.module_scope, frozenset({"M2"}))
        self.assertTrue(step.scope_basis.startswith("aligned:"))

    def test_no_geometry_attribution_for_shared_figure(self):
        fig3 = self.figures["图 3"]
        self.assertEqual(fig3.module_scope, frozenset({"M1", "M2"}))
        # 没有任何正文小句因靠近图 3 而被自动挂上图 3。
        for step in self.steps:
            self.assertNotIn(
                "图 3",
                step.figure_refs,
                f"{step.step_id} 不应按距离自动归属图 3",
            )


if __name__ == "__main__":
    unittest.main()
