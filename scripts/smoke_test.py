from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.document_processing_agent import DocumentProcessingAgent
from src.auth.auth_service import login_user, register_user, set_default_model_config
from src.database import execute, init_db
from src.llm.gateway import build_provider
from src.llm.providers import LLMProviderError
from src.modules.library_agent import (
    add_canvas_note,
    add_highlight,
    build_reading_context,
    create_folder,
    delete_canvas_node,
    delete_highlight,
    list_document_questions,
    list_highlights,
    update_canvas_node,
)
from src.modules.todo_agent import list_subtasks, parse_and_save_todos
from src.rag.simple_vector_store import add_document_to_kb, get_document
from src.rag.text_splitter import split_text


def cleanup_user(user_id: int) -> None:
    for table in [
        "document_highlights", "document_questions", "document_mindmaps", "todo_subtasks", "document_chunks",
        "documents", "library_folders", "todos", "memory_items", "user_model_configs",
    ]:
        execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    execute("DELETE FROM users WHERE id = ?", (user_id,))


def main() -> None:
    init_db()
    username = f"smoke_{int(time.time())}"
    ok, message = register_user(username, "password123")
    assert ok, message
    user = login_user(username, "password123")
    assert user
    user_id = user["id"]

    try:
        try:
            build_provider(None)
            raise AssertionError("Missing model configuration must fail")
        except LLMProviderError:
            pass

        set_default_model_config(user_id, "qwen", "https://example.com/v1", "test-key", "qwen-test")
        assert DocumentProcessingAgent(user_id).model_name == "qwen-test"

        folder_id = create_folder(user_id, "机器学习")
        sample = "# 机器学习\n\n## 降维\n\nPCA 保留最大方差方向。\n\n## 分类\n\nLDA 使用类别标签。"
        doc_id = add_document_to_kb(
            user_id, "course", "sample_course.txt", split_text(sample),
            str(ROOT / "data" / "sample_course.txt"), folder_id=folder_id,
            source_format="txt", original_text=sample, processed_markdown=sample,
        )
        assert get_document(user_id, doc_id)["folder_id"] == folder_id
        assert "PCA" in build_reading_context(user_id, doc_id, "PCA", "paragraph")
        assert "降维" in build_reading_context(user_id, doc_id, "PCA", "section")
        assert "分类" not in build_reading_context(user_id, doc_id, "PCA", "section")

        highlight_id = add_highlight(user_id, doc_id, "PCA 保留最大方差方向")
        assert len(list_highlights(user_id, doc_id)) == 1
        note_id = add_canvas_note(user_id, doc_id, "测试节点", "公式 $x^2$", "note")
        update_canvas_node(user_id, "question", note_id, x=120, y=80, width=460, height=320, content="修改后的内容")
        note = list_document_questions(user_id, doc_id)[0]
        assert note["canvas_x"] == 120 and note["answer"] == "修改后的内容"
        delete_canvas_node(user_id, "question", note_id)
        delete_highlight(user_id, highlight_id)
        assert not list_document_questions(user_id, doc_id) and not list_highlights(user_id, doc_id)

        todos = parse_and_save_todos(user_id, "复习机器学习第 3-6 章；周五提交数据库作业")
        assert todos and list_subtasks(user_id, todos[0]["id"])
        print("Smoke test passed: auth, document agent binding, chapter context, canvas, highlights and todo storage.")
    finally:
        cleanup_user(user_id)


if __name__ == "__main__":
    main()
