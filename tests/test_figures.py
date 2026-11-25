"""图号登记与显式归属测试：不按距离归属，只认显式图号/模块标记。"""
import unittest

from pack_check import read_tables
from training_pack.figures import build_figure_registry, fig_mentions, module_mentions


class FigureRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = read_tables()
        cls.figures = build_figure_registry(
            cls.tables["blocks.tsv"],
            sheet_notes=cls.tables["sheet_notes.tsv"],
            aids=cls.tables["aids.tsv"],
        )

    def test_fig_mentions_bilingual(self):
        self.assertEqual(fig_mentions("如右图，见图 3 的箭头"), ["图 3"])
        self.assertEqual(fig_mentions("Fig. 2. Inside tab shown from rear."), ["图 2"])
        self.assertEqual(fig_mentions("没有图号的句子"), [])

    def test_module_mentions_are_explicit_only(self):
        self.assertEqual(module_mentions("For M1, leave the blue tab in place."), ["M1"])
        self.assertEqual(module_mentions("普通中文句没有模块号"), [])

    def test_fig2_links_explicit_blocks_only(self):
        fig2 = self.figures["图 2"]
        ids = {block["id"] for block in fig2.figure_blocks}
        caption_ids = {block["id"] for block in fig2.captions}
        erratum_ids = {block["id"] for block in fig2.errata}
        label_ids = {block["id"] for block in fig2.in_frame_labels}
        self.assertEqual(ids, {"B3"})
        self.assertEqual(caption_ids, {"B4"})
        self.assertEqual(erratum_ids, {"B8"})
        # 角注不带图号，但第 1 页只有图 2，按页面唯一图归入。
        self.assertEqual(label_ids, {"B11", "B12"})
        # 英文图注 B4 与图 B3 同栏相邻也必须靠图号，不靠距离。
        self.assertIn("M2", fig2.module_scope)

    def test_fig3_shared_by_two_modules(self):
        fig3 = self.figures["图 3"]
        self.assertEqual(fig3.module_scope, frozenset({"M1", "M2"}))
        self.assertFalse(fig3.viewpoint_conflict)
        self.assertEqual(fig3.occlusion_subjects, frozenset({"white_tab"}))
        self.assertIn("搭档视角", fig3.viewpoints)
        self.assertIn("操作者视角", fig3.viewpoints)

    def test_fig2_viewpoint_conflict_and_occlusion(self):
        fig2 = self.figures["图 2"]
        self.assertTrue(fig2.viewpoint_conflict)
        self.assertTrue(fig2.flipped_rear)
        self.assertTrue(fig2.front_view)
        self.assertIn("slot_label", fig2.occlusion_subjects)
        self.assertTrue(fig2.orientation_corrected)


if __name__ == "__main__":
    unittest.main()
