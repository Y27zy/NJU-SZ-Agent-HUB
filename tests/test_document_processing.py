import unittest
from unittest.mock import patch

from src.rag.document_processor import (
    _clean_complete_document,
    _deduplicate_markdown,
    _document_profile,
    _normalize_structure,
    _remove_repeated_page_noise,
)


class DocumentProcessingTests(unittest.TestCase):
    def test_short_course_uses_one_complete_reconstruction(self) -> None:
        pages = ["期末复习重点\n线性模型", "决策树\n支持向量机", "神经网络"]
        profile = _document_profile(pages, "复习重点", "课程")
        self.assertEqual(profile["strategy"], "compact_complete")

    def test_academic_paper_uses_chapter_reconstruction(self) -> None:
        pages = [
            "Abstract\nIntroduction\nThis paper proposes a method.",
            "Related Work\nPrior studies.",
            "References\n[1] Example.",
        ]
        profile = _document_profile(pages, "Paper", "论文")
        self.assertEqual(profile["kind"], "paper")
        self.assertEqual(profile["strategy"], "chapter_reconstruction")

    def test_same_page_outline_items_do_not_create_overlapping_chapters(self) -> None:
        raw = {
            "document_title": "复习重点",
            "chapters": [
                {"title": "概论", "start_page": 1, "end_page": 1},
                {"title": "线性模型", "start_page": 1, "end_page": 2},
                {"title": "决策树", "start_page": 1, "end_page": 3},
                {"title": "神经网络", "start_page": 4, "end_page": 4},
            ],
        }
        structure = _normalize_structure(raw, "复习重点", 4, "课程")
        self.assertEqual(len(structure["chapters"]), 2)
        self.assertEqual(structure["chapters"][0]["title"], "概论")
        self.assertEqual(structure["chapters"][0]["start_page"], 1)
        self.assertEqual(structure["chapters"][0]["end_page"], 3)
        self.assertIn("线性模型", structure["chapters"][0]["key_terms"])

    def test_repeated_page_noise_is_kept_once(self) -> None:
        pages = [
            "课程名称\n第一章正文\n第 1 页",
            "课程名称\n第二章正文\n第 2 页",
            "课程名称\n第三章正文\n第 3 页",
        ]
        cleaned = _remove_repeated_page_noise(pages)
        self.assertEqual(sum(page.count("课程名称") for page in cleaned), 1)
        self.assertTrue(all("正文" in page for page in cleaned))

    def test_duplicate_long_markdown_block_is_removed(self) -> None:
        repeated = "考试说明：选择题二十八分，简答题七十二分，不需要精确计算，只需要进行相对比较。"
        markdown = f"# 标题\n\n{repeated}\n\n## 第一章\n\n正文内容。\n\n{repeated}\n"
        cleaned = _deduplicate_markdown(markdown)
        self.assertEqual(cleaned.count(repeated), 1)

    def test_math_delimiters_are_normalized_locally(self) -> None:
        markdown = r"公式 \(x + y\) 与 \[z = 1\]。"
        cleaned = _deduplicate_markdown(markdown)
        self.assertIn("$x + y$", cleaned)
        self.assertIn("$$z = 1$$", cleaned)

    @patch("src.rag.document_processor.chat_with_user_model")
    def test_complete_reconstruction_uses_one_call_and_normalizes_wrapper(self, chat) -> None:
        chat.return_value = "```markdown\n# 复习重点\n\n考试说明。\n```"

        markdown = _clean_complete_document(1, "复习重点", ["第一页", "第二页"])

        self.assertEqual(chat.call_count, 1)
        self.assertTrue(markdown.startswith("# 复习重点\n\n## 正文"))
        self.assertEqual(markdown.count("# 复习重点"), 1)


if __name__ == "__main__":
    unittest.main()
