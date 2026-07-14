import unittest
from unittest.mock import patch

from src.rag.document_processor import (
    _clean_chapter,
    _clean_complete_document,
    _classify_document_pages,
    _deduplicate_markdown,
    _document_profile,
    _normalize_structure,
    _remove_non_learning_markdown,
    _structure_from_page_headings,
    _remove_repeated_page_noise,
    _retry_attempts_for_part,
    _should_resume_processing,
)
from src.llm.providers import LLMProviderError


class DocumentProcessingTests(unittest.TestCase):
    def test_reprocess_mode_distinguishes_clean_ready_from_failed_run(self) -> None:
        self.assertFalse(_should_resume_processing({"processing_status": "ready", "processing_error": None}))
        self.assertTrue(_should_resume_processing({"processing_status": "error", "processing_error": "timeout"}))
        self.assertTrue(_should_resume_processing({"processing_status": "ready", "processing_error": "last retry failed"}))

    def test_retry_budget_scales_with_part_workload(self) -> None:
        self.assertEqual(_retry_attempts_for_part(4000, 2), 4)
        self.assertEqual(_retry_attempts_for_part(10000, 4), 5)
        self.assertEqual(_retry_attempts_for_part(15000, 9), 6)

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

    def test_isolated_thank_you_page_is_removed(self) -> None:
        markdown = "# 标题\n\n<!-- page:1 -->\n\n## 贝叶斯分类器\n\n正文。\n\n<!-- page:2 -->\n\n# Thank You\n\n![致谢页](asset://page-002-figure-1.png)"
        cleaned = _remove_non_learning_markdown(markdown)
        self.assertIn("贝叶斯分类器", cleaned)
        self.assertNotIn("Thank You", cleaned)
        self.assertNotIn("page-002-figure-1.png", cleaned)

    def test_closing_line_is_removed_but_teaching_page_stays(self) -> None:
        markdown = "<!-- page:4 -->\n\n## 贝叶斯公式\n\n这是推导正文。\n\n欢迎提问"
        cleaned = _remove_non_learning_markdown(markdown)
        self.assertIn("这是推导正文", cleaned)
        self.assertNotIn("欢迎提问", cleaned)

    def test_front_matter_is_not_sent_to_learning_body(self) -> None:
        pages = [
            "微积分 I\n张三 编\n高等教育出版社\nISBN 978-7-0000",
            "目录\n第一章 函数与极限 ........ 1\n第二章 导数 ........ 25",
            "第一章 函数与极限\n函数是两个集合之间的对应关系。",
        ]
        roles = _classify_document_pages(pages)
        self.assertEqual(roles[1], "skip")
        self.assertEqual(roles[2], "outline")
        self.assertEqual(roles[3], "content")

    def test_page_chapter_headings_create_a_book_scale_plan(self) -> None:
        pages = [
            "书名\n出版社",
            "第1章 极限与连续性\n函数的概念。",
            "极限的基本性质。",
            "第2章 导数与微分\n导数的定义。",
        ]
        roles = _classify_document_pages(pages)
        structure = _structure_from_page_headings("微积分", "课程", pages, roles)
        self.assertIsNotNone(structure)
        self.assertEqual([item["title"] for item in structure["chapters"]], ["第1章 极限与连续性", "第2章 导数与微分"])

    def test_repeated_running_chapter_header_does_not_split_every_page(self) -> None:
        pages = [
            "Chapter 1 Basics\nDefinition one.",
            "Chapter 1 Basics\nDefinition two.",
            "Chapter 1 Basics\nDefinition three.",
            "Chapter 2 Relations\nRelation definition.",
            "Chapter 2 Exercises Answers\nAnswer key.",
        ]
        structure = _structure_from_page_headings(
            "Discrete Mathematics", "course", pages, {index: "content" for index in range(1, 6)}
        )
        self.assertIsNotNone(structure)
        self.assertEqual([item["title"] for item in structure["chapters"]], ["Chapter 1 Basics", "Chapter 2 Relations"])
        self.assertEqual(structure["chapters"][0]["end_page"], 3)

    @patch("src.rag.document_processor.chat_with_user_model")
    def test_long_chapter_resumes_after_the_failed_part(self, chat) -> None:
        pages = ["A" * 10000, "B" * 10000]
        chapter = {"title": "长章节", "start_page": 1, "end_page": 2, "summary": "", "key_terms": []}
        cached_parts: dict[str, str] = {}

        def save_part(key: str, output: str) -> None:
            cached_parts[key] = output

        chat.side_effect = ["第一分片已整理", LLMProviderError("模型请求超时")]
        with self.assertRaises(LLMProviderError):
            _clean_chapter(1, chapter, pages, "长章节", part_cache=cached_parts, on_part_complete=save_part)

        self.assertEqual(len(cached_parts), 1)
        chat.reset_mock()
        chat.side_effect = None
        chat.return_value = "第二分片已整理"

        markdown = _clean_chapter(
            1,
            chapter,
            pages,
            "长章节",
            part_cache=cached_parts,
            on_part_complete=save_part,
        )

        self.assertEqual(chat.call_count, 1)
        self.assertIn("第一分片已整理", markdown)
        self.assertIn("第二分片已整理", markdown)

    @patch("src.rag.document_processor.chat_with_user_model")
    def test_failed_part_reports_its_resumable_checkpoint(self, chat) -> None:
        pages = ["A" * 10000]
        chapter = {"title": "长章节", "start_page": 1, "end_page": 1, "summary": "", "key_terms": []}
        failures = []
        chat.side_effect = LLMProviderError("模型请求超时")

        with self.assertRaises(LLMProviderError):
            _clean_chapter(1, chapter, pages, "长章节", on_part_error=lambda *args: failures.append(args))

        self.assertEqual(len(failures), 1)
        part_key, part_index, part_total, error = failures[0]
        self.assertTrue(part_key.startswith("1:"))
        self.assertEqual((part_index, part_total), (1, 1))
        self.assertIsInstance(error, LLMProviderError)

    @patch("src.rag.document_processor.chat_with_user_model")
    def test_complete_reconstruction_uses_one_call_and_normalizes_wrapper(self, chat) -> None:
        chat.return_value = "```markdown\n# 复习重点\n\n考试说明。\n```"

        markdown = _clean_complete_document(1, "复习重点", ["第一页", "第二页"])

        self.assertEqual(chat.call_count, 1)
        self.assertTrue(markdown.startswith("# 复习重点\n\n## 正文"))
        self.assertEqual(markdown.count("# 复习重点"), 1)


if __name__ == "__main__":
    unittest.main()
