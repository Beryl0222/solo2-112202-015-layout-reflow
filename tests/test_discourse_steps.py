"""句段恢复、连接词与跨页指代测试。"""
import unittest

from pack_check import read_tables
from training_pack.discourse import build_paragraphs, classify_connectors, split_sentences
from training_pack.figures import build_figure_registry
from training_pack.steps import build_steps


class DiscourseTest(unittest.TestCase):
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

    def test_sentence_split_protects_fig_abbreviation(self):
        sentences = split_sentences("Fig. 2. Inside tab. Next move.")
        self.assertEqual(sentences, ["Fig. 2. Inside tab.", "Next move."])

    def test_paragraphs_group_same_page_column_language(self):
        paragraphs = build_paragraphs(self.tables["blocks.tsv"])
        keys = {(p.page, p.column, p.lang) for p in paragraphs}
        # 第 1 页左栏中文、第 2 页左栏中文、第 2 页右栏英文各一段。
        self.assertIn((1, "左栏", "zh"), keys)
        self.assertIn((2, "左栏", "zh"), keys)
        self.assertIn((2, "右栏", "en"), keys)

    def test_connector_roles(self):
        self.assertIn("时序", classify_connectors("随后拔掉该卡"))
        self.assertIn("指代", classify_connectors("随后拔掉该卡"))
        self.assertIn("版面指示", classify_connectors("如右图所示"))
        self.assertIn("搭档协同", classify_connectors("让搭档核对槽号"))

    def test_right_figure_is_layout_not_stance(self):
        step = self.by_id["B2-2"]
        self.assertEqual(step.figure_refs, ("图 2",))
        self.assertIn("右图", step.layout_deictic)
        reasons = {finding.reason for finding in step.findings}
        self.assertIn("LAYOUT_DEICTIC", reasons)
        # 版面指示词记录的是双栏右栏，不产生任何站位方向结论。
        self.assertTrue(all(finding.reason != "OLD_VIEW" for finding in step.findings))

    def test_cross_page_anaphora_points_to_page_one_white_tab(self):
        # “随后拔掉该卡”只能回溯阅读顺序更早的 B2 白卡，不能指向后出现的英文 B7。
        step = self.by_id["B5-2"]
        targets = {link["target_block"] for link in step.anaphora}
        self.assertEqual(targets, {"B2"})
        self.assertTrue(all(link["cross_page"] for link in step.anaphora))

    def test_previous_page_link_is_scoped_to_earlier_pages(self):
        step = self.by_id["B5-1"]
        self.assertTrue(step.anaphora)
        self.assertTrue(all(link["target_page"] < step.page for link in step.anaphora))

    def test_partner_verification_actor(self):
        self.assertEqual(self.by_id["B5-3"].actor, "搭档")
        self.assertTrue(self.by_id["B5-3"].partner_verification)

    def test_translation_swap_flagged_language_only(self):
        # 调换标记挂在拔卡工步（中文 B5-2）与英文条件句（B7-4）上；
        # 搭档核对工步 B5-3 本身保留可练，不被语言风险连带。
        for step_id in ("B5-2", "B7-4"):
            reasons = {finding.reason: finding.severity for finding in self.by_id[step_id].findings}
            self.assertEqual(reasons.get("TRANSLATION_SWAP"), "language")
        self.assertFalse(
            any(
                finding.reason == "TRANSLATION_SWAP"
                for finding in self.by_id["B5-3"].findings
            )
        )

    def test_other_segments_kept_when_one_is_uncertain(self):
        # B2-2 因遮挡/视角暂停，同块其他小句不被连带。
        self.assertEqual(
            {finding.reason for finding in self.by_id["B2-1"].findings},
            set(),
        )
        self.assertTrue(self.by_id["B2-3"].findings == [])


if __name__ == "__main__":
    unittest.main()
