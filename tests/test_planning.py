"""按实际发放评估工步、模型门槛与双人方向独占测试。"""
import unittest

from pack_check import read_tables
from training_pack.distribution import build_context, evaluate_classroom
from training_pack.figures import build_figure_registry
from training_pack.planning import GROUPINGS, plan_classroom, station_report
from training_pack.steps import build_steps


class PlanningFixture:
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

    def status_map(self, classroom_id):
        plan = plan_classroom(self.contexts[classroom_id], self.steps)
        return {
            recipient: {item.step.step_id: item for item in planned}
            for recipient, planned in plan.by_recipient.items()
        }, plan


class C2TwoPersonTest(PlanningFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_operator_old_view_cleared_by_erratum_but_occlusion_holds(self):
        mapping, _ = self.status_map("C2")
        item = mapping["操作者"]["B2-2"]
        reasons = set(item.reasons)
        # 操作者拿到 B8 勘误：OLD_VIEW 不再出现；右槽标签未重印，遮挡仍暂停。
        self.assertNotIn("OLD_VIEW", reasons)
        self.assertIn("LABEL_OCCLUDED", reasons)
        self.assertEqual(item.status, "held")

    def test_partner_keeps_old_view_without_erratum(self):
        mapping, _ = self.status_map("C2")
        item = mapping["搭档"]["B2-2"]
        self.assertIn("NOT_ISSUED", item.reasons)
        # 搭档没有 B2 页本身；一旦补页而仍无勘误，OLD_VIEW 由静态视角冲突保留。
        self.assertIn("VIEW_CONFLICT", item.reasons)

    def test_cross_page_antecedent_lost_for_partner(self):
        mapping, _ = self.status_map("C2")
        item = mapping["搭档"]["B5-2"]
        self.assertIn("MISSING_ANTECEDENT", item.reasons)
        self.assertIn("B2", item.missing_block_ids)
        self.assertEqual(item.status, "held")

    def test_operator_has_antecedent_and_can_practice_with_language_note(self):
        mapping, _ = self.status_map("C2")
        item = mapping["操作者"]["B5-2"]
        self.assertEqual(item.status, "teacher_required")
        self.assertIn("TRANSLATION_SWAP", item.reasons)

    def test_partner_slot_check_remains_practicable(self):
        mapping, _ = self.status_map("C2")
        item = mapping["搭档"]["B5-3"]
        self.assertEqual(item.status, "practicable")

    def test_alternatives_keep_class_running(self):
        _, plan = self.status_map("C2")
        self.assertIn("B5-3", plan.alternatives["搭档"])
        self.assertIn("B2-1", plan.alternatives["操作者"])

    def test_three_groupings_are_all_legal(self):
        context = self.contexts["C2"]
        plans = {
            grouping: plan_classroom(context, self.steps, grouping=grouping)
            for grouping in GROUPINGS
        }
        # 任何合法组织方式都不得改变工步状态与原因，只改变呈现顺序。
        signatures = {
            grouping: sorted(
                (item.step.step_id, item.status, tuple(item.reasons))
                for planned in plan.by_recipient.values()
                for item in planned
            )
            for grouping, plan in plans.items()
        }
        baseline = signatures["by_step"]
        self.assertTrue(all(signature == baseline for signature in signatures.values()))
        # 按图组织确实把带图工步排到了最前，与按工步顺序不同。
        by_figure_order = [
            item.step.step_id for item in plans["by_figure"].by_recipient["操作者"]
        ]
        self.assertEqual(by_figure_order[0], "B2-2")
        with self.assertRaises(ValueError):
            plan_classroom(context, self.steps, grouping="not_a_grouping")


class C3ModelGatingTest(PlanningFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_m2_steps_never_enter_m1_pack(self):
        mapping, plan = self.status_map("C3")
        for step_id in ("B7-3", "B7-4", "B5-2"):
            self.assertEqual(mapping["操作者"][step_id].status, "gated")
        gated = {
            item.step.step_id
            for item in plan.by_recipient["操作者"]
            if item.status == "gated"
        }
        # B7-3 是 M2 标记小句，B7-4 与中文 B5-2 都经显式模块信息对齐为 M2；
        # M1 台上三者都不得入旧版练习包。
        self.assertEqual(gated, {"B7-3", "B7-4", "B5-2"})

    def test_m1_blue_tab_step_practicable(self):
        mapping, _ = self.status_map("C3")
        self.assertEqual(mapping["操作者"]["B7-2"].status, "practicable")

    def test_station_verdict_distinguishes_hold_from_language(self):
        report = station_report(plan_classroom(self.contexts["C3"], self.steps))
        operator = report["recipients"]["操作者"]
        self.assertIn("还不能练", operator["verdict"])
        # M1 台上的蓝卡保留工步不受 M2 拔卡工步牵连。
        ids = {row["step_id"] for row in operator["steps"]["practicable"]}
        self.assertIn("B7-2", ids)


class C1TabletBundleTest(PlanningFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build()

    def test_unissued_classroom_everything_not_issued(self):
        plan = plan_classroom(self.contexts["C1"], self.steps)
        for planned in plan.by_recipient.values():
            self.assertTrue(all("NOT_ISSUED" in item.reasons for item in planned))

    def test_bundle_lists_nearby_figure_antecedent_and_terms(self):
        # 未发教室没有 bundle；用就绪性逻辑核对必需项组成。
        plan = plan_classroom(self.contexts["C2"], self.steps)
        bundle = next(
            bundle
            for bundle in plan.tablet_bundles
            if bundle["step_id"] == "B5-2" and bundle["recipient"] == "操作者"
        )
        roles = {need["block_id"]: need["role"] for need in bundle["nearby_requirements"]}
        self.assertIn("B2", roles)
        self.assertEqual(roles["B2"], "上一步状态")


if __name__ == "__main__":
    unittest.main()
