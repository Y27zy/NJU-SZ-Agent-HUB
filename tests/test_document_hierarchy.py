import tempfile
import unittest
from pathlib import Path

from src import config
from src.database import execute, fetch_all, fetch_one, init_db, now_iso
from src.rag.document_hierarchy import (
    MAX_SECTION_CHARACTERS,
    build_document_hierarchy,
    should_publish_as_collection,
)
from src.rag.simple_vector_store import (
    add_document_to_kb,
    delete_document,
    finish_document_processing,
    list_document_sections,
    list_library_documents,
)


def _long_markdown() -> str:
    pages = 1
    chapters = ["第一章 极限", "第二章 导数", "第三章 积分"]
    parts = ["# 微积分 1", "课程导言：这是应保留的前言。"]
    for chapter_index, chapter in enumerate(chapters, 1):
        parts.append(f"## {chapter}")
        for section_index in range(1, 5):
            parts.append(f"### {chapter_index}.{section_index} 小节 {section_index}")
            for _ in range(2):
                parts.append(f"<!-- page:{pages} -->\n标记-{chapter_index}-{section_index}-{pages} " + ("内容" * 850))
                pages += 1
    return "\n\n".join(parts)


class DocumentHierarchyUnitTests(unittest.TestCase):
    def test_subheadings_are_kept_inside_their_complete_major_section(self):
        markdown = "\n\n".join(
            ["# 微积分"]
            + [
                block
                for chapter in range(1, 4)
                for block in (
                    f"## 第{chapter}章",
                    f"### {chapter}.1 基础",
                    "正文 " + "内容" * 1000,
                    f"### {chapter}.1.1 定义",
                    "定义内容 " + "内容" * 1000,
                    f"### {chapter}.1.2 例题",
                    "例题内容 " + "内容" * 1000,
                    f"### {chapter}.1 基础（续）",
                    "续页内容 " + "内容" * 1000,
                    f"### 习题 {chapter}.1",
                    "习题内容 " + "内容" * 1000,
                )
            ]
        )
        hierarchy = build_document_hierarchy(markdown, "微积分", 100)
        self.assertIsNotNone(hierarchy)
        self.assertEqual(
            [section.title for section in hierarchy.sections],
            ["1.1 基础", "习题 1.1", "2.1 基础", "习题 2.1", "3.1 基础", "习题 3.1"],
        )
        self.assertIn("### 1.1.1 定义", hierarchy.sections[0].markdown)
        self.assertIn("### 1.1.2 例题", hierarchy.sections[0].markdown)
        self.assertIn("### 1.1 基础（续）", hierarchy.sections[0].markdown)

    def test_chapter_exercises_are_separate_from_the_preceding_section(self):
        markdown = "\n\n".join(
            ["# 线性代数"]
            + [
                block
                for chapter, numeral in ((1, "一"), (2, "二"), (3, "三"))
                for block in (
                    f"## 第{chapter}章",
                    f"### {chapter}.1 基础",
                    "正文 " + "内容" * 2000,
                    f"### 习题{numeral}",
                    "习题 " + "内容" * 1000,
                )
            ]
        )
        hierarchy = build_document_hierarchy(markdown, "线性代数", 100)
        self.assertIsNotNone(hierarchy)
        self.assertEqual(
            [section.title for section in hierarchy.sections],
            ["1.1 基础", "习题一", "2.1 基础", "习题二", "3.1 基础", "习题三"],
        )

    def test_short_document_remains_standalone(self):
        markdown = "# 短资料\n\n## 第一章\n\n正文"
        self.assertFalse(should_publish_as_collection(markdown, 5))
        self.assertIsNone(build_document_hierarchy(markdown, "短资料", 5))

    def test_one_long_chapter_with_many_sections_can_still_split(self):
        markdown = "# 专题\n\n## 唯一章\n\n" + "\n\n".join(
            f"### 小节 {index}\n\n" + (f"段落 {index}。" * 1800)
            for index in range(1, 6)
        )
        hierarchy = build_document_hierarchy(markdown, "专题", 90)
        self.assertIsNotNone(hierarchy)
        self.assertGreaterEqual(len(hierarchy.sections), 2)

    def test_long_document_is_grouped_into_bounded_stable_sections(self):
        markdown = _long_markdown()
        first = build_document_hierarchy(markdown, "微积分 1", 120)
        second = build_document_hierarchy(markdown, "微积分 1", 120)
        self.assertIsNotNone(first)
        self.assertEqual([item.section_key for item in first.sections], [item.section_key for item in second.sections])
        self.assertEqual({item.group_title for item in first.sections}, {"第一章 极限", "第二章 导数", "第三章 积分"})
        self.assertEqual(len(first.sections), 12)
        self.assertEqual(first.sections[0].title, "1.1 小节 1")
        self.assertTrue(all(len(item.markdown) <= MAX_SECTION_CHARACTERS + 200 for item in first.sections))
        self.assertEqual(
            sum(item.markdown.count("<!-- page:") for item in first.sections),
            markdown.count("<!-- page:"),
        )
        for token in ("课程导言", "标记-1-1-1", "标记-3-4-24"):
            self.assertTrue(any(token in item.markdown for item in first.sections), token)


class DocumentHierarchyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_database_url = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{Path(self.temp.name) / 'hierarchy.db'}"
        init_db()
        self.user_id = execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("hierarchy-user", "hash", now_iso()),
        )

    def tearDown(self):
        config.DATABASE_URL = self.original_database_url
        self.temp.cleanup()

    def test_publish_is_idempotent_and_library_listing_is_lightweight(self):
        markdown = _long_markdown()
        document_id = add_document_to_kb(
            self.user_id,
            "course",
            "微积分 1.pdf",
            [],
            "micro-calculus.pdf",
            processing_status="processing",
            page_count=120,
        )
        finish_document_processing(self.user_id, document_id, "原始文本", markdown, [markdown], 120, "{}")

        root = fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        children = fetch_all(
            "SELECT * FROM documents WHERE parent_document_id = ? ORDER BY sort_order",
            (document_id,),
        )
        first_ids = [row["id"] for row in children]
        self.assertEqual(root["document_role"], "collection")
        self.assertGreaterEqual(len(children), 3)
        self.assertLess(len(root["processed_markdown"]), len(markdown) // 10)
        self.assertTrue(all(row["document_role"] == "section" for row in children))
        lightweight_sections = list_document_sections(self.user_id, document_id)
        self.assertEqual(len(lightweight_sections), len(children))
        self.assertNotIn("processed_markdown", lightweight_sections[0])

        finish_document_processing(self.user_id, document_id, "原始文本", markdown, [markdown], 120, "{}")
        second_ids = [
            row["id"]
            for row in fetch_all(
                "SELECT id FROM documents WHERE parent_document_id = ? ORDER BY sort_order",
                (document_id,),
            )
        ]
        self.assertEqual(first_ids, second_ids)

        listing = list_library_documents(self.user_id)
        self.assertEqual(len(listing), 1 + len(children))
        self.assertNotIn("processed_markdown", listing[0])
        self.assertNotIn("original_text", listing[0])

    def test_agent_publish_keeps_nested_headings_in_the_major_section(self):
        markdown = "\n\n".join(
            ["# 线性代数"]
            + [
                block
                for chapter, numeral in ((1, "一"), (2, "二"), (3, "三"))
                for block in (
                    f"## 第{chapter}章",
                    f"### {chapter}.1 基础",
                    "正文 " + "内容" * 2000,
                    f"### {chapter}.1.1 定义",
                    "定义 " + "内容" * 1000,
                    f"### 习题{numeral}",
                    "习题 " + "内容" * 1000,
                )
            ]
        )
        document_id = add_document_to_kb(
            self.user_id,
            "course",
            "线性代数.pdf",
            [],
            processing_status="processing",
            page_count=100,
        )
        finish_document_processing(self.user_id, document_id, "原始文本", markdown, [markdown], 100)
        children = fetch_all(
            "SELECT title, processed_markdown FROM documents WHERE parent_document_id = ? ORDER BY sort_order",
            (document_id,),
        )
        self.assertEqual(
            [row["title"] for row in children],
            ["1.1 基础", "习题一", "2.1 基础", "习题二", "3.1 基础", "习题三"],
        )
        self.assertIn("### 1.1.1 定义", children[0]["processed_markdown"])

    def test_deleting_collection_cascades_to_generated_sections(self):
        markdown = _long_markdown()
        document_id = add_document_to_kb(self.user_id, "course", "微积分.pdf", [], processing_status="processing")
        finish_document_processing(self.user_id, document_id, "原始文本", markdown, [markdown], 120)
        child_ids = [row["id"] for row in fetch_all("SELECT id FROM documents WHERE parent_document_id = ?", (document_id,))]
        self.assertTrue(child_ids)
        self.assertTrue(delete_document(self.user_id, document_id))
        placeholders = ",".join("?" for _ in child_ids)
        self.assertIsNone(fetch_one("SELECT id FROM documents WHERE id = ?", (document_id,)))
        self.assertEqual(fetch_all(f"SELECT id FROM documents WHERE id IN ({placeholders})", tuple(child_ids)), [])


if __name__ == "__main__":
    unittest.main()
