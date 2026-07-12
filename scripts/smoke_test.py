from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.document_processing_agent import DocumentProcessingAgent
from src.agent.food_models import FoodDataStore
from src.agent.todo_planning_agent import TodoPlanningAgent
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
    toggle_highlight,
    toggle_highlight_anchor,
    update_canvas_node,
)
from src.modules.todo_agent import list_subtasks
from src.rag.simple_vector_store import add_document_to_kb, get_document
from src.rag.text_splitter import split_text


def cleanup_user(user_id: int) -> None:
    for table in [
        "document_highlights", "document_questions", "document_mindmaps", "todo_subtasks", "document_chunks",
        "agent_runs", "documents", "library_folders", "todos", "memory_items", "user_model_configs",
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
        assert toggle_highlight(user_id, doc_id, "PCA 保留最大方差方向") is False
        assert not list_highlights(user_id, doc_id)
        assert toggle_highlight(user_id, doc_id, "PCA 保留最大方差方向") is True
        highlight_id = list_highlights(user_id, doc_id)[0]["id"]
        added, anchored_id = toggle_highlight_anchor(user_id, doc_id, "重复名称", 12, 16, "前文", "后文")
        assert added and anchored_id
        anchored = next(item for item in list_highlights(user_id, doc_id) if item["id"] == anchored_id)
        assert anchored["anchor_start"] == 12 and anchored["anchor_end"] == 16
        assert toggle_highlight_anchor(user_id, doc_id, "重复名称", 12, 16)[0] is False
        note_id = add_canvas_note(user_id, doc_id, "测试节点", "公式 $x^2$", "note")
        update_canvas_node(user_id, "question", note_id, x=120, y=80, width=460, height=320, content="修改后的内容")
        note = list_document_questions(user_id, doc_id)[0]
        assert note["canvas_x"] == 120 and note["answer"] == "修改后的内容"
        delete_canvas_node(user_id, "question", note_id)
        delete_highlight(user_id, highlight_id)
        assert not list_document_questions(user_id, doc_id) and not list_highlights(user_id, doc_id)

        todos = TodoPlanningAgent(user_id).save_validated_tasks(
            [{"title": "复习机器学习第 3-6 章", "priority": "high", "subtasks": ["第 3-4 章", "第 5-6 章"]}]
        )
        assert todos and list_subtasks(user_id, todos[0]["id"])
        assert TodoPlanningAgent(user_id).save_validated_tasks([{"title": "我这周要复习机器学习第 3-6 章"}]) == []
        TodoPlanningAgent(user_id).save_validated_tasks(
            [{"title": "提交数据库作业", "deadline": "2026-07-15", "priority": "medium", "subtasks": ["检查 SQL", "提交"]}]
        )
        assert TodoPlanningAgent(user_id).list_todos(sort_by="deadline")[0]["title"] == "提交数据库作业"
        assert TodoPlanningAgent(user_id).list_todos(sort_by="priority")[0]["priority"] == "high"
        assert TodoPlanningAgent._deadline_rank("周五") < TodoPlanningAgent._deadline_rank("周日")
        food_data = FoodDataStore().load()
        assert food_data["schema_version"] == 2
        assert all(key in food_data for key in ("canteen_dishes", "restaurants", "takeaways", "pending_review"))
        print("Smoke test passed: auth, agent binding, reading context, canvas, todo tools and food tools.")
    finally:
        cleanup_user(user_id)


if __name__ == "__main__":
    main()
