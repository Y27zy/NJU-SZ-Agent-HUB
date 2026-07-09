from pathlib import Path

from src.agent.prompts import PAPER_SYSTEM_PROMPT
from src.llm.gateway import chat_with_user_model
from src.rag.document_parser import parse_document
from src.rag.simple_vector_store import add_document_to_kb, get_document_chunks, search_chunks
from src.rag.text_splitter import split_text


def ingest_paper(user_id: int, file_path: str | Path, title: str) -> int:
    text = parse_document(file_path)
    chunks = split_text(text, chunk_size=900, overlap=150)
    return add_document_to_kb(user_id, "paper", title, chunks, str(file_path))


def _paper_context(user_id: int, document_id: int | None = None, limit: int = 12) -> str:
    if document_id:
        chunks = get_document_chunks(user_id, document_id=document_id)
    else:
        chunks = search_chunks(user_id, "abstract introduction method experiment contribution limitation", "paper", limit)
    return "\n\n".join(c["content"] for c in chunks[:limit])


def summarize_paper(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(
        user_id,
        PAPER_SYSTEM_PROMPT,
        f"请做论文 5 分钟速读：研究问题、方法、创新点、实验、局限、适合组会讲的亮点。\n论文内容：{_paper_context(user_id, document_id)}",
    )


def extract_research_question(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(
        user_id,
        PAPER_SYSTEM_PROMPT,
        f"请提取论文要解决的研究问题，说明问题背景、挑战和为什么重要。\n{_paper_context(user_id, document_id)}",
    )


def extract_contributions(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(user_id, PAPER_SYSTEM_PROMPT, f"请提取论文创新点，并区分方法创新、实验创新和应用价值。\n{_paper_context(user_id, document_id)}")


def extract_method(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(user_id, PAPER_SYSTEM_PROMPT, f"请解释论文方法流程，尽量用步骤和输入输出描述。\n{_paper_context(user_id, document_id)}")


def extract_experiment_setup(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(
        user_id,
        PAPER_SYSTEM_PROMPT,
        f"请提取论文实验设置：数据集、baseline、评价指标、主要结果和消融实验。\n{_paper_context(user_id, document_id)}",
    )


def extract_limitations(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(
        user_id,
        PAPER_SYSTEM_PROMPT,
        f"请提取论文局限性，并给出可能的改进方向和复现风险。\n{_paper_context(user_id, document_id)}",
    )


def translate_text(user_id: int, text: str, target_language: str = "中文") -> str:
    return chat_with_user_model(user_id, PAPER_SYSTEM_PROMPT, f"请把下面文本翻译成{target_language}，保留学术含义：\n{text}")


def generate_presentation_outline(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(user_id, PAPER_SYSTEM_PROMPT, f"请生成 10 分钟组会汇报大纲，包含每页标题和要点。\n{_paper_context(user_id, document_id)}")


def generate_reproduction_checklist(user_id: int, document_id: int | None = None) -> str:
    return chat_with_user_model(user_id, PAPER_SYSTEM_PROMPT, f"请生成论文复现 checklist：数据、环境、模型、指标、实验表格和风险。\n{_paper_context(user_id, document_id)}")
