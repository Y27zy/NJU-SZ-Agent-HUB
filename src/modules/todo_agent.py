from src.agent.todo_planning_agent import TodoPlanningAgent
from src.database import execute, now_iso


def parse_and_save_todos(user_id: int, text: str) -> list[dict]:
    tasks, _run = TodoPlanningAgent(user_id).ingest(text)
    return tasks


def list_todos(user_id: int, include_done: bool = True, sort_by: str = "smart") -> list[dict]:
    return TodoPlanningAgent(user_id).list_todos(include_done, sort_by)


def list_subtasks(user_id: int, todo_id: int) -> list[dict]:
    return TodoPlanningAgent(user_id).list_subtasks(todo_id)


def mark_todo_done(user_id: int, todo_id: int) -> None:
    execute("UPDATE todos SET status = 'done', completed_at = ? WHERE id = ? AND user_id = ?", (now_iso(), todo_id, user_id))
    execute("UPDATE todo_subtasks SET status = 'done' WHERE todo_id = ? AND user_id = ?", (todo_id, user_id))


def mark_subtask_done(user_id: int, subtask_id: int) -> None:
    execute("UPDATE todo_subtasks SET status = 'done' WHERE id = ? AND user_id = ?", (subtask_id, user_id))


def generate_today_plan(user_id: int) -> str:
    return TodoPlanningAgent(user_id).plan_today().answer


def generate_week_plan(user_id: int) -> dict:
    run, tree = TodoPlanningAgent(user_id).plan_week()
    return {
        "task": "本周计划",
        "candidates": tree.get("candidates") or [],
        "best": {
            "plan": run.answer,
            "score": (tree.get("best") or {}).get("score", 0),
            "reason": (tree.get("best") or {}).get("reason", "由 TodoPlanningAgent 综合工具证据后选择。"),
        },
        "trace": run.trace,
    }
