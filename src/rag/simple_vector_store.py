from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.database import execute, fetch_all, now_iso


def add_document_to_kb(user_id: int, doc_type: str, title: str, chunks: list[str], file_path: str = "") -> int:
    doc_id = execute(
        "INSERT INTO documents (user_id, doc_type, title, file_path, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, doc_type, title, file_path, now_iso()),
    )
    for idx, chunk in enumerate(chunks):
        execute(
            """
            INSERT INTO document_chunks (document_id, user_id, doc_type, chunk_index, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (doc_id, user_id, doc_type, idx, chunk, now_iso()),
        )
    return doc_id


def list_documents(user_id: int, doc_type: str | None = None) -> list[dict]:
    if doc_type:
        rows = fetch_all(
            "SELECT * FROM documents WHERE user_id = ? AND doc_type = ? ORDER BY id DESC",
            (user_id, doc_type),
        )
    else:
        rows = fetch_all("SELECT * FROM documents WHERE user_id = ? ORDER BY id DESC", (user_id,))
    return [dict(r) for r in rows]


def get_document_chunks(user_id: int, document_id: int | None = None, doc_type: str | None = None) -> list[dict]:
    if document_id is not None:
        rows = fetch_all(
            "SELECT * FROM document_chunks WHERE user_id = ? AND document_id = ? ORDER BY chunk_index",
            (user_id, document_id),
        )
    elif doc_type:
        rows = fetch_all(
            "SELECT * FROM document_chunks WHERE user_id = ? AND doc_type = ? ORDER BY id DESC",
            (user_id, doc_type),
        )
    else:
        rows = fetch_all("SELECT * FROM document_chunks WHERE user_id = ? ORDER BY id DESC", (user_id,))
    return [dict(r) for r in rows]


def search_chunks(user_id: int, query: str, doc_type: str | None = None, top_k: int = 5) -> list[dict]:
    chunks = get_document_chunks(user_id, doc_type=doc_type)
    if not chunks:
        return []
    corpus = [c["content"] for c in chunks]
    vectorizer = TfidfVectorizer()
    matrix = vectorizer.fit_transform(corpus + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for idx, score in ranked:
        item = dict(chunks[idx])
        item["score"] = float(score)
        results.append(item)
    return results
