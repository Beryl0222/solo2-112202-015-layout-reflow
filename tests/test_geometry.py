"""双栏版面与几何判断测试。"""
import unittest

from training_pack.geometry import LEFT, RIGHT, SPANNING, block_column, parse_box
from pack_check import read_tables


class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.blocks = {row["id"]: row for row in read_tables()["blocks.tsv"]}

    def test_parse_box(self):
        box = parse_box("10,10,570,36")
        self.assertEqual((box.x, box.y, box.width, box.height), (10, 10, 570, 36))
        self.assertEqual(box.right, 580)
        with self.assertRaises(ValueError):
            parse_box("1,2,3")
        with self.assertRaises(ValueError):
            parse_box("1,2,-3,4")

    def test_spanning_title_and_caption_detected(self):
        # B1 横跨两栏标题；B6/B8 横跨两栏图注/勘误。
        self.assertEqual(block_column(self.blocks["B1"]), SPANNING)
        self.assertEqual(block_column(self.blocks["B6"]), SPANNING)
        self.assertEqual(block_column(self.blocks["B8"]), SPANNING)

    def test_left_and_right_columns(self):
        self.assertEqual(block_column(self.blocks["B2"]), LEFT)
        self.assertEqual(block_column(self.blocks["B3"]), RIGHT)
        # 跨页正文 B5 在左栏，B7 在右栏。
        self.assertEqual(block_column(self.blocks["B5"]), LEFT)
        self.assertEqual(block_column(self.blocks["B7"]), RIGHT)


if __name__ == "__main__":
    unittest.main()
