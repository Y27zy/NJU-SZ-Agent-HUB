from pathlib import Path

from src.agent.course_learning_agent import CourseLearningAgent
from src.rag.document_processor import process_document
from src.rag.simple_vector_store import search_chunks


def ingest_course_document(user_id: int, file_path: str | Path, title: str) -> int:
    return process_document(user_id, file_path, title, "course")


def search_course_material(user_id: int, query: str, top_k: int = 5) -> list[dict]:
    return search_chunks(user_id, query, doc_type="course", top_k=top_k)


def answer_course_question(user_id: int, query: str) -> str:
    return CourseLearningAgent(user_id).answer(query).answer


def generate_course_summary(user_id: int, document_id: int) -> str:
    return CourseLearningAgent(user_id).summarize(document_id).answer


def generate_quiz(user_id: int, topic: str) -> str:
    return CourseLearningAgent(user_id).quiz(topic).answer
