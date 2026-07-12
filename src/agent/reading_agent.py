from collections.abc import Callable

from src.agent.runtime import AgentRun, AgentTool, ToolUsingAgent
from src.memory.memory_service import retrieve_user_memory


class ReadingAgent:
    """Selection-aware reading Agent with explicit tools and persisted traces."""

    def __init__(self, user_id: int, document_id: int, context_loader: Callable[[dict], dict], document_loader: Callable[[dict], dict]):
        self.user_id = user_id
        self.document_id = document_id
        self.context_loader = context_loader
        self.document_loader = document_loader

    def _preferences(self, _args: dict) -> list[str]:
        return [item["content"] for item in retrieve_user_memory(self.user_id, "阅读解释风格与学习偏好", limit=5)]

    def _runtime(self, tools: list[AgentTool]) -> ToolUsingAgent:
        return ToolUsingAgent(
            self.user_id,
            "ReadingAgent",
            "你是学术资料阅读 Agent。必须先调用上下文工具取证，再回答问题。区分原文事实、必要推导和补充例子；"
            "不得编造页码、定义或实验结果。数学内容使用规范 Markdown LaTeX。",
            tools,
        )

    def answer(self, task: str, context_mode: str) -> AgentRun:
        runtime = self._runtime([
            AgentTool("read_selected_context", "按选区、段落、章节、RAG 或全文读取上下文。", self.context_loader),
            AgentTool("reading_preferences", "读取用户长期保存的阅读与解释偏好。", self._preferences),
        ])
        return runtime.run(
            task,
            constraints={"document_id": self.document_id, "context_mode": context_mode},
            default_calls=[
                {"tool": "read_selected_context", "args": {"mode": context_mode}},
                {"tool": "reading_preferences", "args": {}},
            ],
            output_instruction="先给结论，再给原文依据和必要推导。Markdown 从三级标题开始；资料不足时明确指出。",
        )

    def mindmap(self) -> AgentRun:
        runtime = self._runtime([AgentTool("read_document", "读取结构化全文及章节信息。", self.document_loader)])
        return runtime.run(
            "为当前资料生成用于复习的层级知识地图。",
            constraints={"document_id": self.document_id, "format": "markdown_outline"},
            default_calls=[{"tool": "read_document", "args": {}}],
            output_instruction=(
                "只输出 Markdown 层级结构。第一行使用 # 根主题，后续仅用 ##、###、####；"
                "节点必须是短语，并体现章节关系、核心概念、方法步骤、公式依赖与应用。"
            ),
        )
