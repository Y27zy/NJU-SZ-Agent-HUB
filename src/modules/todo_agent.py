import re

from src.agent.prompts import TODO_SYSTEM_PROMPT
from src.agent.thought_tree import dynamic_thought_tree
from src.database import execute, fetch_all, now_iso
from src.llm.gateway import chat_with_user_model, get_llm_for_user


def infer_subtasks(title: str) -> list[str]:
    if any(word in title for word in ["复习", "考试", "章节"]):
        return ["整理知识点", "完成练习题", "复盘错题与薄弱点"]
    if any(word in title for word in ["作业", "提交", "交"]):
        return ["确认作业要求", "完成初稿", "检查格式并提交"]
    if any(word in title for word in ["论文", "paper", "Paper", "阅读", "看完"]):
        return ["阅读摘要和引言", "梳理方法与实验", "记录问题和可复现要点"]
    return ["拆分目标", "安排时间块", "完成后复盘"]


def parse_todos_from_text(text: str) -> list[dict]:
    parts = re.split(r"[，,。；;\n]+", text.strip())
    todos = []
    for part in [p.strip() for p in parts if p.strip()]:
        priority = "high" if any(w in part for w in ["周五", "明天", "今晚", "ddl", "截止", "交"]) else "medium"
        deadline = ""
        for token in ["周一", "周二", "周三", "周四", "周五", "周六", "周日", "明天", "今晚", "今天"]:
            if token in part:
                deadline = token
                break
        todos.append(
            {
                "title": part[:60],
                "description": part,
                "deadline": deadline,
                "priority": priority,
                "status": "open",
                "subtasks": infer_subtasks(part),
            }
        )
    return todos or [
        {
            "title": text[:60],
            "description": text,
            "deadline": "",
            "priority": "medium",
            "status": "open",
            "subtasks": infer_subtasks(text),
        }
    ]


def save_todo(user_id: int, todo: dict) -> int:
    todo_id = execute(
        """
        INSERT INTO todos (user_id, title, description, deadline, priority, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            todo["title"],
            todo.get("description", ""),
            todo.get("deadline", ""),
            todo.get("priority", "medium"),
            todo.get("status", "open"),
            now_iso(),
        ),
    )
    for subtask in todo.get("subtasks", []):
        execute(
            """
            INSERT INTO todo_subtasks (todo_id, user_id, title, status, created_at)
            VALUES (?, ?, ?, 'open', ?)
            """,
            (todo_id, user_id, subtask, now_iso()),
        )
    return todo_id


def parse_and_save_todos(user_id: int, text: str) -> list[dict]:
    todos = parse_todos_from_text(text)
    for todo in todos:
        todo["id"] = save_todo(user_id, todo)
    return todos


def list_todos(user_id: int, include_done: bool = True) -> list[dict]:
    if include_done:
        rows = fetch_all("SELECT * FROM todos WHERE user_id = ? ORDER BY status, id DESC", (user_id,))
    else:
        rows = fetch_all("SELECT * FROM todos WHERE user_id = ? AND status != 'done' ORDER BY id DESC", (user_id,))
    return [dict(r) for r in rows]


def mark_todo_done(user_id: int, todo_id: int) -> None:
    execute("UPDATE todos SET status = 'done' WHERE id = ? AND user_id = ?", (todo_id, user_id))
    execute("UPDATE todo_subtasks SET status = 'done' WHERE todo_id = ? AND user_id = ?", (todo_id, user_id))


def list_subtasks(user_id: int, todo_id: int) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM todo_subtasks WHERE user_id = ? AND todo_id = ? ORDER BY id",
        (user_id, todo_id),
    )
    return [dict(r) for r in rows]


def mark_subtask_done(user_id: int, subtask_id: int) -> None:
    execute("UPDATE todo_subtasks SET status = 'done' WHERE id = ? AND user_id = ?", (subtask_id, user_id))


def _todo_context(user_id: int) -> str:
    todos = list_todos(user_id, include_done=False)
    return "\n".join(f"- {t['title']} | deadline={t['deadline']} | priority={t['priority']}" for t in todos) or "暂无未完成任务。"


def generate_today_plan(user_id: int) -> str:
    context = _todo_context(user_id)
    return chat_with_user_model(user_id, TODO_SYSTEM_PROMPT, f"请根据以下 todo-list 生成今日计划，按上午/下午/晚上输出。\n{context}")


def generate_week_plan(user_id: int) -> dict:
    context = _todo_context(user_id)
    return dynamic_thought_tree("根据 todo-list 生成本周学习与作业计划", context, get_llm_for_user(user_id))
