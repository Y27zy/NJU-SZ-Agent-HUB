from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.auth.auth_service import login_user, register_user
from src.database import execute, init_db
from src.modules.course_agent import answer_course_question, ingest_course_document
from src.modules.food_agent import random_canteen_food, recommend_restaurants
from src.modules.todo_agent import generate_week_plan, list_subtasks, parse_and_save_todos


def cleanup_user(user_id: int) -> None:
    for table in [
        "todo_subtasks",
        "document_chunks",
        "documents",
        "todos",
        "memory_items",
        "user_model_configs",
    ]:
        execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    execute("DELETE FROM users WHERE id = ?", (user_id,))


def main() -> None:
    init_db()
    username = f"smoke_{int(time.time())}"
    password = "password123"
    ok, message = register_user(username, password)
    assert ok, message
    user = login_user(username, password)
    assert user, "login failed"
    user_id = user["id"]

    try:
        doc_id = ingest_course_document(user_id, ROOT / "data" / "sample_course.txt", "sample_course.txt")
        assert doc_id > 0
        answer = answer_course_question(user_id, "PCA and LDA difference?")
        assert answer

        todo_text = "Review machine learning chapters 3-6, submit database homework by Friday, read one Agent paper by Sunday."
        todos = parse_and_save_todos(user_id, todo_text)
        assert len(todos) >= 1
        subtasks = list_subtasks(user_id, todos[0]["id"])
        assert subtasks
        week_plan = generate_week_plan(user_id)
        assert week_plan["best"]["plan"]

        restaurants = recommend_restaurants(45, "清淡", "近一点", False, False, True)
        assert restaurants
        canteen = random_canteen_food("午餐", "清淡", "米饭")
        assert canteen["food_name"]

        print("Smoke test passed.")
    finally:
        cleanup_user(user_id)


if __name__ == "__main__":
    main()
