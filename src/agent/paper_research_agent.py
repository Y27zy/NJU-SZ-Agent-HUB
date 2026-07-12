import re

from src.agent.runtime import AgentRun, AgentTool, ToolUsingAgent
from src.agent.web_search_tool import search_web
from src.memory.memory_service import retrieve_user_memory
from src.rag.simple_vector_store import get_document, get_document_chunks, search_chunks, search_document_chunks


class PaperResearchAgent:
    def __init__(self, user_id: int, document_id: int | None = None):
        self.user_id = user_id
        self.document_id = document_id

    def _document(self, _args: dict) -> dict:
        if self.document_id:
            document = get_document(self.user_id, self.document_id)
            if not document:
                raise ValueError("论文不存在。")
            chunks = get_document_chunks(self.user_id, document_id=self.document_id)
            return {"title": document["title"], "content": "\n\n".join(item["content"] for item in chunks)[:70000]}
        chunks = search_chunks(self.user_id, "abstract introduction method experiment contribution limitation", "paper", 16)
        return {"title": "论文资料", "content": "\n\n".join(item["content"] for item in chunks)}

    def _search_inside(self, args: dict) -> list[dict]:
        query = str(args.get("query") or "method experiment contribution limitation")
        if self.document_id:
            return search_document_chunks(self.user_id, self.document_id, query, top_k=8)
        return search_chunks(self.user_id, query, "paper", 8)

    def _preferences(self, _args: dict) -> list[str]:
        return [item["content"] for item in retrieve_user_memory(self.user_id, "研究兴趣与论文阅读偏好", limit=5)]

    def run(self, task: str, output_instruction: str, *, allow_web: bool = False, web_query: str = "") -> AgentRun:
        tools = [
            AgentTool("read_paper", "读取指定论文的章节化全文。", self._document),
            AgentTool("search_inside_paper", "在论文 chunks 中检索特定方法、实验或结论。", self._search_inside),
            AgentTool("research_preferences", "读取用户研究兴趣和论文阅读偏好。", self._preferences),
        ]
        defaults = [{"tool": "read_paper", "args": {}}, {"tool": "research_preferences", "args": {}}]
        if allow_web:
            tools.append(
                AgentTool(
                    "search_related_web",
                    "联网检索公开的相关工作或项目线索，必须保留链接并标注未核验。",
                    lambda args: search_web(str(args.get("query") or web_query or task), 6),
                )
            )
            defaults.append({"tool": "search_related_web", "args": {"query": web_query or task}})
        runtime = ToolUsingAgent(
            self.user_id,
            "PaperResearchAgent",
            "你是科研论文研读 Agent。忠于论文证据，区分作者主张、实验事实、你的推断和联网线索；禁止编造数值、数据集、引用或实现细节。公式使用规范 LaTeX。",
            tools,
        )
        return runtime.run(
            task,
            constraints={"document_id": self.document_id, "allow_web": allow_web},
            default_calls=defaults,
            output_instruction=output_instruction,
        )

    def translate(self, text: str, target_language: str = "中文") -> AgentRun:
        def protected_tokens(_args: dict) -> dict:
            formulas = re.findall(r"\$\$.*?\$\$|\$.*?\$", text, flags=re.DOTALL)
            citations = re.findall(r"\[[0-9,\-\s]+\]|\([^)]*\b(?:19|20)\d{2}[^)]*\)", text)
            technical_terms = sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9+\-]{1,30}\b", text)))[:80]
            return {"formulas": formulas[:40], "citations": citations[:40], "technical_terms": technical_terms}

        runtime = ToolUsingAgent(
            self.user_id,
            "PaperResearchAgent",
            "你是学术翻译 Agent。保持事实、段落、术语、公式和引用不变，不总结、不扩写、不解释。",
            [
                AgentTool("extract_protected_tokens", "提取翻译时必须原样保护的公式、引用和技术术语。", protected_tokens),
                AgentTool("research_preferences", "读取用户的术语与论文阅读偏好。", self._preferences),
            ],
        )
        return runtime.run(
            f"把以下论文片段翻译为{target_language}：\n{text}",
            constraints={"target_language": target_language, "preserve_structure": True},
            default_calls=[{"tool": "extract_protected_tokens", "args": {}}, {"tool": "research_preferences", "args": {}}],
            output_instruction="只输出译文；公式与引用必须原样保留，术语首次出现可保留英文括注。",
        )
