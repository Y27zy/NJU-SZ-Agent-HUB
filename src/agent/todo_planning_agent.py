import json
import re
from datetime import datetime, timedelta
from typing import Any

from src.agent.runtime import AgentRun, AgentTool, ToolUsingAgent
from src.agent.thought_tree import dynamic_thought_tree
from src.database import execute, fetch_all, now_iso
from src.llm.gateway import get_llm_for_user
from src.memory.memory_service import retrieve_user_memory


class TodoPlanningAgent:
    def __init__(self, user_id: int):
        self.user_id = user_id

    def list_todos(self, include_done: bool = True, sort_by: str = "smart") -> list[dict]:
        condition = "" if include_done else "AND status != 'done'"
        rows = fetch_all(
            f"SELECT * FROM todos WHERE user_id = ? {condition}",
            (self.user_id,),
        )
        todos = [dict(row) for row in rows]
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        if sort_by == "priority":
            return sorted(todos, key=lambda item: (item["status"] == "done", priority_rank.get(item["priority"], 1), self._deadline_rank(item["deadline"]), -item["id"]))
        if sort_by == "deadline":
            return sorted(todos, key=lambda item: (item["status"] == "done", self._deadline_rank(item["deadline"]), priority_rank.get(item["priority"], 1), -item["id"]))
        if sort_by == "completed":
            return sorted(todos, key=lambda item: (item["status"] != "done", item.get("completed_at") or "", item["id"]), reverse=True)
        if sort_by == "created":
            return sorted(todos, key=lambda item: item["id"], reverse=True)
        return sorted(todos, key=lambda item: (item["status"] == "done", self._deadline_rank(item["deadline"]), priority_rank.get(item["priority"], 1), -item["id"]))

    @staticmethod
    def _deadline_rank(value: str | None) -> tuple[int, str]:
        text = (value or "").strip()
        if not text:
            return (1, "9999-12-31")
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if match:
            return (0, match.group(0))
        weekdays = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6}
        today = datetime.now()
        for label, weekday in weekdays.items():
            if label in text:
                offset = weekday - today.weekday()
                return (0, (today + timedelta(days=offset)).strftime("%Y-%m-%d"))
        return (1, text)

    def list_subtasks(self, todo_id: int) -> list[dict]:
        return [
            dict(row)
            for row in fetch_all(
                "SELECT * FROM todo_subtasks WHERE user_id = ? AND todo_id = ? ORDER BY id",
                (self.user_id, todo_id),
            )
        ]

    def _task_context(self, _args: dict) -> list[dict]:
        return [
            {**todo, "subtasks": self.list_subtasks(todo["id"])}
            for todo in self.list_todos(include_done=False)
        ]

    def _preferences(self, _args: dict) -> list[str]:
        return [item["content"] for item in retrieve_user_memory(self.user_id, "学习时间与规划偏好", limit=6)]

    @staticmethod
    def _normalize_task(item: dict[str, Any]) -> dict:
        title = str(item.get("title") or "").strip()[:80]
        if not title:
            raise ValueError("Agent 返回了空任务标题。")
        priority = str(item.get("priority") or "medium").lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        subtasks = [str(value).strip()[:100] for value in (item.get("subtasks") or []) if str(value).strip()][:8]
        return {
            "title": title,
            "description": str(item.get("description") or title).strip()[:500],
            "deadline": str(item.get("deadline") or "").strip()[:80],
            "priority": priority,
            "status": "open",
            "subtasks": subtasks or [f"准备完成“{title}”所需材料", f"执行“{title}”并记录进度", "检查结果并完成提交或复盘"],
        }

    def _save_task(self, task: dict) -> int:
        todo_id = execute(
            """
            INSERT INTO todos (user_id, title, description, deadline, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (self.user_id, task["title"], task["description"], task["deadline"], task["priority"], now_iso()),
        )
        for subtask in task["subtasks"]:
            execute(
                "INSERT INTO todo_subtasks (todo_id, user_id, title, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (todo_id, self.user_id, subtask, now_iso()),
            )
        return todo_id

    def ingest(self, text: str) -> tuple[list[dict], AgentRun]:
        runtime = ToolUsingAgent(
            self.user_id,
            "TodoPlanningAgent",
            "你是大学生任务拆解与执行顺序 Agent。识别独立目标、截止时间、依赖和工作量。"
            "同一成果只建立一个父任务，并生成按先后依赖排列的具体步骤；禁止把同一句话重复保存成多个任务。"
            "标题删除‘我这周要’等口语前缀，使用动词和明确成果。不得编造用户未给出的截止日期。",
            [
                AgentTool("existing_open_tasks", "读取当前未完成任务，用于避免重复保存。", self._task_context),
                AgentTool("planning_preferences", "读取用户学习时间和规划偏好。", self._preferences),
            ],
        )
        run = runtime.run(
            f"把以下输入拆成待办任务：{text}",
            constraints={"source_text": text, "max_tasks": 8, "today": datetime.now().strftime("%Y-%m-%d")},
            default_calls=[{"tool": "existing_open_tasks", "args": {}}, {"tool": "planning_preferences", "args": {}}],
            output_instruction=(
                '只输出合法 JSON，不要代码围栏：{"tasks":[{"title":"动词开头的成果","description":"完成标准和范围",'
                '"deadline":"可确定时用 YYYY-MM-DD，否则保留用户原话或空字符串","priority":"high|medium|low",'
                '"subtasks":["按顺序排列的第1步","第2步","第3步"]}]}。'
                "每个父任务生成 3-6 个可在一次学习时段内完成的步骤；先准备和理解，再执行，再检查提交。独立截止成果才拆成不同父任务。"
            ),
        )
        data = ToolUsingAgent._extract_json(run.answer)
        tasks = self.save_validated_tasks(data.get("tasks") or [])
        if not tasks:
            raise ValueError("TodoPlanningAgent 没有生成可保存的任务。")
        return tasks, run

    def save_validated_tasks(self, raw_tasks: list[dict]) -> list[dict]:
        """Validate Agent output before crossing the database boundary."""
        tasks = [self._normalize_task(item) for item in raw_tasks if isinstance(item, dict)][:8]
        tasks = [task for task in tasks if task["title"]]
        existing = {self._canonical_title(item["title"]) for item in self.list_todos(include_done=False)}
        unique_tasks = []
        for task in tasks:
            canonical = self._canonical_title(task["title"])
            if not canonical or canonical in existing:
                continue
            task["id"] = self._save_task(task)
            existing.add(canonical)
            unique_tasks.append(task)
        return unique_tasks

    @staticmethod
    def _canonical_title(value: str) -> str:
        text = re.sub(r"^(我|我们)?(这周|本周|今天|近期)?(要|需要|准备|计划)?", "", value.strip())
        return re.sub(r"[\s，。！？、,:：;；]+", "", text).lower()

    def plan_today(self) -> AgentRun:
        runtime = ToolUsingAgent(
            self.user_id,
            "TodoPlanningAgent",
            "你是大学生时间管理 Agent。基于真实任务、截止时间和子任务安排计划，优先保证截止任务并保留休息与缓冲。",
            [
                AgentTool("open_tasks", "读取全部未完成任务及子任务。", self._task_context),
                AgentTool("planning_preferences", "读取用户长期规划偏好。", self._preferences),
            ],
        )
        return runtime.run(
            "生成今天的可执行安排",
            constraints={"periods": ["上午", "下午", "晚上"], "include_buffer": True},
            default_calls=[{"tool": "open_tasks", "args": {}}, {"tool": "planning_preferences", "args": {}}],
            output_instruction="按上午、下午、晚上列出时间块、对应任务、完成标准和一个缓冲时间；没有截止信息时不要编造具体日期。",
        )

    def plan_week(self) -> tuple[AgentRun, dict]:
        tree_result: dict = {}

        def thought_tree_tool(_args: dict) -> dict:
            nonlocal tree_result
            context = json.dumps(self._task_context({}), ensure_ascii=False)
            tree_result = dynamic_thought_tree("生成本周学习、作业与论文阅读计划", context, get_llm_for_user(self.user_id))
            return tree_result

        runtime = ToolUsingAgent(
            self.user_id,
            "TodoPlanningAgent",
            "你是大学生周计划 Agent。你需要比较多个候选方案，选择理由必须对应截止时间、工作量、依赖关系和恢复时间。",
            [
                AgentTool("open_tasks", "读取全部未完成任务及子任务。", self._task_context),
                AgentTool("dynamic_thought_tree", "生成三个不同策略的候选周计划并进行轻量评分。", thought_tree_tool),
                AgentTool("planning_preferences", "读取用户长期规划偏好。", self._preferences),
            ],
        )
        run = runtime.run(
            "生成并选择本周最佳计划",
            constraints={"must_compare_candidates": True, "include_review": True},
            default_calls=[
                {"tool": "open_tasks", "args": {}},
                {"tool": "planning_preferences", "args": {}},
                {"tool": "dynamic_thought_tree", "args": {}},
            ],
            output_instruction="输出最终周计划、选择该方案的理由、每天的重点和周末复盘；不要重复完整候选文本。",
        )
        return run, tree_result
