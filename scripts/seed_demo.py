from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.auth.auth_service import login_user, register_user
from src.database import fetch_all, init_db
from src.memory.memory_service import update_user_memory
from src.modules.course_agent import ingest_course_document
from src.modules.todo_agent import parse_and_save_todos


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "password123"


def main() -> None:
    init_db()
    register_user(DEMO_USERNAME, DEMO_PASSWORD)
    user = login_user(DEMO_USERNAME, DEMO_PASSWORD)
    if not user:
        raise RuntimeError("Demo user login failed.")

    user_id = user["id"]
    existing_docs = fetch_all("SELECT id FROM documents WHERE user_id = ? AND title = ?", (user_id, "sample_course.txt"))
    if not existing_docs:
        ingest_course_document(user_id, ROOT / "data" / "sample_course.txt", "sample_course.txt")

    existing_todos = fetch_all("SELECT id FROM todos WHERE user_id = ?", (user_id,))
    if not existing_todos:
        parse_and_save_todos(
            user_id,
            "我这周要复习机器学习第 3-6 章，周五交数据库作业，周日之前看完一篇 Agent 论文。",
        )

    existing_memories = fetch_all("SELECT id FROM memory_items WHERE user_id = ?", (user_id,))
    if not existing_memories:
        update_user_memory(user_id, "我喜欢用条理清晰、适合考试复习的方式解释机器学习概念。", "user", 4)
        update_user_memory(user_id, "晚餐偏好清淡，预算通常在 30 元以内。", "user", 3)

    print("Demo data ready.")
    print(f"Username: {DEMO_USERNAME}")
    print(f"Password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
