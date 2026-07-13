import unittest

from src.rag.document_assets import bind_document_images


class DocumentAssetTests(unittest.TestCase):
    def test_only_explicitly_retained_figures_are_bound(self) -> None:
        source = (
            "# 资料\n\n<!-- page:3 -->\n\n### 回归 vs. 分类\n"
            "![任务对比](placeholder_regression.png)\n\n<!-- page:4 -->\n\n### 线性回归"
        )
        bound = bind_document_images(
            source,
            {3: ["asset://page-003-figure-1.png", "asset://page-003-figure-2.png"], 4: ["asset://page-004-figure-1.png"]},
        )
        self.assertIn("![任务对比](asset://page-003-figure-1.png)", bound)
        self.assertNotIn("page-003-figure-2.png", bound)
        self.assertNotIn("page-004-figure-1.png", bound)

    def test_editorial_figure_marker_is_bound_without_auto_appending(self) -> None:
        source = "<!-- page:2 -->\n\n[图：朴素贝叶斯分类流程图]"
        bound = bind_document_images(
            source,
            {2: ["asset://page-002-figure-1.png", "asset://page-002-figure-2.png"]},
        )
        self.assertIn("![朴素贝叶斯分类流程图](asset://page-002-figure-1.png)", bound)
        self.assertNotIn("page-002-figure-2.png", bound)

    def test_external_image_links_are_not_rewritten(self) -> None:
        source = "<!-- page:1 -->\n\n![外部图](https://example.test/image.png)"
        bound = bind_document_images(source, {1: ["asset://page-001-figure-1.png"]})
        self.assertIn("https://example.test/image.png", bound)


if __name__ == "__main__":
    unittest.main()
