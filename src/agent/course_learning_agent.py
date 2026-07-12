from src.agent.runtime import AgentRun, AgentTool, ToolUsingAgent
from src.memory.memory_service import retrieve_user_memory
from src.rag.simple_vector_store import get_document, get_document_chunks, search_chunks


class CourseLearningAgent:
    def __init__(self, user_id: int):
        self.user_id = user_id

    def _search(self, args: dict) -> list[dict]:
        query = str(args.get("query") or "课程重点")
        top_k = max(1, min(int(args.get("top_k") or 5), 8))
        return search_chunks(self.user_id, query, doc_type="course", top_k=top_k)

    def _document(self, document_id: int):
        def handler(_args: dict) -> dict:
            document = get_document(self.user_id, document_id)
            if not document:
                raise ValueError("课程资料不存在。")
            chunks = get_document_chunks(self.user_id, document_id=document_id)
            return {"title": document["title"], "content": "\n\n".join(item["content"] for item in chunks)[:60000]}

        return handler

    def _preferences(self, _args: dict) -> list[str]:
        return [item["content"] for item in retrieve_user_memory(self.user_id, "课程学习解释偏好", limit=5)]

    def _runtime(self, tools: list[AgentTool]) -> ToolUsingAgent:
        return ToolUsingAgent(
            self.user_id,
            "CourseLearningAgent",
            "你是南京大学苏州校区学生的课程学习 Agent。所有结论优先依据课程工具证据；解释要建立概念联系、给出推理步骤，并明确区分资料原文与补充说明。公式使用 $...$ 或 $$...$$。",
            tools,
        )

    def answer(self, query: str) -> AgentRun:
        runtime = self._runtime(
            [
                AgentTool("search_course_kb", "从用户课程资料中做 TF-IDF RAG 检索。", self._search),
                AgentTool("learning_preferences", "读取用户解释风格和学习偏好。", self._preferences),
            ]
        )
        return runtime.run(
            query,
            constraints={"ground_in_course_material": True},
            default_calls=[{"tool": "search_course_kb", "args": {"query": query, "top_k": 6}}, {"tool": "learning_preferences", "args": {}}],
            output_instruction="先直接回答，再列依据、推理过程和一个用于自检的小例子；资料不足时指出需要补充哪部分。",
        )

    def summarize(self, document_id: int) -> AgentRun:
        runtime = self._runtime([AgentTool("read_course_document", "读取指定课程资料的章节化全文。", self._document(document_id))])
        return runtime.run(
            "生成这份课程资料的复习重点",
            constraints={"document_id": document_id, "focus": "考试与理解"},
            default_calls=[{"tool": "read_course_document", "args": {}}],
            output_instruction="按章节输出核心概念、关键公式、典型题型、易错点和复习顺序；不得遗漏工具证据中的主章节。",
        )

    def quiz(self, topic: str) -> AgentRun:
        runtime = self._runtime([AgentTool("search_course_kb", "检索与练习主题相关的课程证据。", self._search)])
        return runtime.run(
            f"围绕“{topic}”生成练习题",
            constraints={"question_count": 5, "include_answers": True},
            default_calls=[{"tool": "search_course_kb", "args": {"query": topic, "top_k": 8}}],
            output_instruction="生成 5 道难度递进的题，每题紧跟参考答案和考察点。公式只使用 $...$ 或 $$...$$，不要要求系统批改。",
        )
