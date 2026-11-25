"""课后追溯与授权操作测试。"""
import unittest

from pack_check import read_tables
from training_pack.audit import authorization_trace, trace_attempts
from training_pack.distribution import build_context
from training_pack.figures import build_figure_registry
from training_pack.steps import build_steps


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        cls.traces = trace_attempts(
            cls.tables["attempts.tsv"], cls.contexts, cls.figures, cls.tables["blocks.tsv"]
        )

    def test_e1_used_old_rear_view_even_though_erratum_issued_later(self):
        e1 = next(trace for trace in self.traces if trace.attempt_id == "E1")
        self.assertIn("背面翻转", e1.effective_viewpoint)
        self.assertTrue(any("旧版" in warning for warning in e1.warnings))

    def test_e2_partner_does_not_inherit_operator_erratum(self):
        e2 = next(trace for trace in self.traces if trace.attempt_id == "E2")
        self.assertEqual(e2.figure_versions["图 2"], "供应商原稿")
        self.assertIn("背面翻转", e2.effective_viewpoint)
        self.assertTrue(e2.archived)

    def test_trace_states_what_still_can_be_checked(self):
        e2 = next(trace for trace in self.traces if trace.attempt_id == "E2")
        # 英文图注留档可用，但左右方向不能用来核对共同操作。
        self.assertTrue(any("留档" in item for item in e2.usable_for))

    def test_authorization_trace_uses_actual_issued_pages(self):
        authorized = authorization_trace(self.contexts["C2"], self.steps)
        operator_ids = {row["step_id"] for row in authorized["操作者"]}
        partner_ids = {row["step_id"] for row in authorized["搭档"]}
        self.assertIn("B2-3", operator_ids)
        self.assertNotIn("B2-3", partner_ids)
        incomplete = next(
            row for row in authorized["操作者"] if row["step_id"] == "B2-2"
        )
        self.assertFalse(incomplete["authorized"])
        self.assertIn("B4", incomplete["missing_companions"])


if __name__ == "__main__":
    unittest.main()
