from pathlib import Path

from src.agent.prompts import COURSE_SYSTEM_PROMPT
from src.llm.gateway import chat_with_user_model
from src.memory.memory_service import build_context_with_memory
from src.rag.document_parser import parse_document
from src.rag.simple_vector_store import add_document_to_kb, get_document_chunks, search_chunks
from src.rag.text_splitter import split_text


def ingest_course_document(user_id: int, file_path: str | Path, title: str) -> int:
    text = parse_document(file_path)
    chunks = split_text(text)
    return add_document_to_kb(user_id, "course", title, chunks, str(file_path))


def search_course_material(user_id: int, query: str, top_k: int = 5) -> list[dict]:
    return search_chunks(user_id, query, doc_type="course", top_k=top_k)


def answer_course_question(user_id: int, query: str) -> str:
    chunks = search_course_material(user_id, query)
    context = "\n\n".join(c["content"] for c in chunks) or "暂无课程资料，请提醒用户先上传资料。"
    memory = build_context_with_memory(user_id, query)
    prompt = f"课程资料：\n{context}\n\n记忆上下文：\n{memory}\n\n问题：{query}"
    return chat_with_user_model(user_id, COURSE_SYSTEM_PROMPT, prompt)


def generate_course_summary(user_id: int, document_id: int) -> str:
    chunks = get_document_chunks(user_id, document_id=document_id)
    context = "\n\n".join(c["content"] for c in chunks[:12])
    return chat_with_user_model(user_id, COURSE_SYSTEM_PROMPT, f"请总结这份课程资料的考试重点：\n{context}")


def generate_quiz(user_id: int, topic: str) -> str:
    chunks = search_course_material(user_id, topic)
    context = "\n\n".join(c["content"] for c in chunks)
    prompt = (
        f"围绕主题“{topic}”生成 5 道练习题并给出参考答案。\n"
        "要求：\n"
        "1. 使用 Markdown 输出。\n"
        "2. 数学公式必须使用 Markdown 数学语法：行内公式用 $...$，独立公式用 $$...$$。\n"
        "3. 不要使用 \\[...\\]、\\(...\\) 或裸露的 LaTeX 公式。\n"
        "4. 每题包含“题目”和“参考答案”，不要要求学生再提交答案给系统批改。\n"
        f"\n资料：{context}"
    )
    return chat_with_user_model(user_id, COURSE_SYSTEM_PROMPT, prompt)
