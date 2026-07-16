import unittest

from src.rag.markdown_quality import optimize_scanned_page_markdown


class MarkdownQualityTests(unittest.TestCase):
    def test_redundant_full_page_scan_and_quote_markers_are_removed(self):
        source = """# 章节

<!-- page:3 -->
> **定义** 普通正文。
> $$x=1$$

![整页截图](asset://page-003-figure-1.png)
"""
        cleaned = optimize_scanned_page_markdown(source, {3})
        self.assertIn("**定义** 普通正文。", cleaned)
        self.assertNotIn("> **定义**", cleaned)
        self.assertNotIn("asset://", cleaned)

    def test_unresolved_formula_keeps_one_collapsed_source_page(self):
        source = """<!-- page:8 -->
矩阵 $A=$ [待核对]。

![矩阵数据](asset://page-008-figure-1.png)
"""
        cleaned = optimize_scanned_page_markdown(source, {8})
        self.assertIn("<details", cleaned)
        self.assertIn("asset://page-008-figure-1.png", cleaned)
        self.assertEqual(cleaned.count("asset://"), 1)
        self.assertEqual(optimize_scanned_page_markdown(cleaned, {8}), cleaned)

    def test_real_figure_on_non_scan_page_is_untouched(self):
        source = "<!-- page:4 -->\n![几何图](asset://page-004-figure-1.png)"
        self.assertEqual(optimize_scanned_page_markdown(source, {3}), source)

    def test_unanchored_inline_scan_is_moved_into_a_collapsed_disclosure(self):
        source = "说明矩阵 ![矩阵A](asset://page-121-figure-1.png) 不可对角化。"
        cleaned = optimize_scanned_page_markdown(source, {121})
        self.assertIn("矩阵或公式见文末原页核对", cleaned)
        self.assertIn("<details", cleaned)
        self.assertEqual(cleaned.count("asset://"), 1)


if __name__ == "__main__":
    unittest.main()
