from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.database import execute, fetch_all, fetch_one, get_connection, now_iso


def add_document_to_kb(
    user_id: int,
    doc_type: str,
    title: str,
    chunks: list[str],
    file_path: str = "",
    *,
    folder_id: int | None = None,
    source_format: str = "",
    original_text: str = "",
    processed_markdown: str = "",
    processing_status: str = "ready",
    page_count: int = 0,
    library_scope: str = "custom",
    is_global: bool = False,
) -> int:
    doc_id = execute(
        """
        INSERT INTO documents
        (user_id, doc_type, title, file_path, folder_id, source_format, original_text,
         processed_markdown, processing_status, page_count, library_scope, is_global, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            doc_type,
            title,
            file_path,
            folder_id,
            source_format,
            original_text,
            processed_markdown,
            processing_status,
            page_count,
            library_scope,
            int(is_global),
            now_iso(),
            now_iso(),
        ),
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


def create_document_record(
    user_id: int,
    doc_type: str,
    title: str,
    file_path: str,
    folder_id: int | None,
    source_format: str,
    library_scope: str = "custom",
    is_global: bool = False,
) -> int:
    return add_document_to_kb(
        user_id,
        doc_type,
        title,
        [],
        file_path,
        folder_id=folder_id,
        source_format=source_format,
        processing_status="processing",
        library_scope=library_scope,
        is_global=is_global,
    )


def finish_document_processing(
    user_id: int,
    document_id: int,
    original_text: str,
    processed_markdown: str,
    chunks: list[str],
    page_count: int,
    structure_json: str = "",
) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM document_chunks WHERE user_id = ? AND document_id = ?",
            (user_id, document_id),
        )
        for index, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO document_chunks
                (document_id, user_id, doc_type, chunk_index, content, created_at)
                SELECT id, user_id, doc_type, ?, ?, ? FROM documents
                WHERE id = ? AND user_id = ?
                """,
                (index, chunk, now_iso(), document_id, user_id),
            )
        conn.execute(
            """
            UPDATE documents
            SET original_text = ?, processed_markdown = ?, processing_status = 'ready',
                processing_error = NULL, page_count = ?, structure_json = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (original_text, processed_markdown, page_count, structure_json, now_iso(), document_id, user_id),
        )


def fail_document_processing(user_id: int, document_id: int, error: str) -> None:
    execute(
        """
        UPDATE documents SET processing_status = 'error', processing_error = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (error[:1000], now_iso(), document_id, user_id),
    )


def update_document_assets_markdown(document_id: int, markdown: str) -> bool:
    """Persist a system-generated asset binding without changing document ownership."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE documents SET processed_markdown = ?, updated_at = ? WHERE id = ?",
            (markdown, now_iso(), document_id),
        )
        return cursor.rowcount > 0


def get_document(user_id: int, document_id: int) -> dict | None:
    row = fetch_one("SELECT * FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id))
    return dict(row) if row else None


def get_library_document(viewer_id: int, document_id: int) -> dict | None:
    """Return private material owned by the viewer or material published by an admin."""
    row = fetch_one(
        """
        SELECT * FROM documents
        WHERE id = ? AND (user_id = ? OR is_global = 1)
        """,
        (document_id, viewer_id),
    )
    return dict(row) if row else None


def delete_document(user_id: int, document_id: int) -> bool:
    row = get_document(user_id, document_id)
    if not row:
        return False
    with get_connection() as conn:
        conn.execute("DELETE FROM document_questions WHERE document_id = ? AND user_id = ?", (document_id, user_id))
        conn.execute("DELETE FROM document_mindmaps WHERE document_id = ? AND user_id = ?", (document_id, user_id))
        conn.execute("DELETE FROM document_highlights WHERE document_id = ? AND user_id = ?", (document_id, user_id))
        conn.execute("DELETE FROM document_chunks WHERE document_id = ? AND user_id = ?", (document_id, user_id))
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id))
    return True


def list_documents(user_id: int, doc_type: str | None = None) -> list[dict]:
    if doc_type:
        rows = fetch_all(
            "SELECT * FROM documents WHERE user_id = ? AND doc_type = ? ORDER BY id DESC",
            (user_id, doc_type),
        )
    else:
        rows = fetch_all("SELECT * FROM documents WHERE user_id = ? ORDER BY id DESC", (user_id,))
    return [dict(r) for r in rows]


def list_library_documents(viewer_id: int, admin: bool = False) -> list[dict]:
    """List a student's personal/public material or an administrator's shared-library material."""
    if admin:
        rows = fetch_all(
            """
            SELECT * FROM documents
            WHERE is_global = 1 AND library_scope != 'custom'
            ORDER BY updated_at DESC, id DESC
            """
        )
        return [dict(row) for row in rows]
    rows = fetch_all(
        """
        SELECT * FROM documents
        WHERE user_id = ? OR is_global = 1
        ORDER BY updated_at DESC, id DESC
        """,
        (viewer_id,),
    )
    return [dict(row) for row in rows]


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
    return _rank_chunks(chunks, query, top_k)


def search_document_chunks(user_id: int, document_id: int, query: str, top_k: int = 5) -> list[dict]:
    return _rank_chunks(get_document_chunks(user_id, document_id=document_id), query, top_k)


def delete_library_document(actor_user_id: int, document_id: int, admin: bool = False) -> bool:
    """Delete custom material only for its owner, while shared scopes require an admin."""
    document = get_library_document(actor_user_id, document_id)
    if not document:
        return False
    owned_local = not bool(document["is_global"]) and int(document["user_id"]) == actor_user_id
    if not (owned_local or (admin and bool(document["is_global"]))):
        return False
    owner_id = int(document["user_id"])
    with get_connection() as conn:
        conn.execute("DELETE FROM document_questions WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_mindmaps WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_highlights WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, owner_id))
    return True


def can_edit_library_document(actor_user_id: int, document: dict, admin: bool = False) -> bool:
    """Return whether an actor may change the rendered Markdown of a document."""
    return (not bool(document.get("is_global")) and int(document["user_id"]) == actor_user_id) or (
        admin and bool(document.get("is_global"))
    )


def update_document_markdown(actor_user_id: int, document_id: int, markdown: str, admin: bool = False) -> bool:
    """Persist a permitted manual Markdown correction and rebuild that document's local RAG chunks."""
    document = get_library_document(actor_user_id, document_id)
    cleaned = markdown.strip()
    if not document or not cleaned or not can_edit_library_document(actor_user_id, document, admin):
        return False
    from src.rag.text_splitter import split_text

    chunks = split_text(cleaned, chunk_size=1200, overlap=180)
    owner_id = int(document["user_id"])
    with get_connection() as conn:
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        for index, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO document_chunks (document_id, user_id, doc_type, chunk_index, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (document_id, owner_id, document["doc_type"], index, chunk, now_iso()),
            )
        conn.execute(
            "UPDATE documents SET processed_markdown = ?, updated_at = ? WHERE id = ?",
            (cleaned, now_iso(), document_id),
        )
    return True


def _rank_chunks(chunks: list[dict], query: str, top_k: int) -> list[dict]:
    if not chunks:
        return []
    corpus = [c["content"] for c in chunks]
    # Character n-grams work for Chinese text without requiring an extra tokenizer.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(corpus + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for idx, score in ranked:
        item = dict(chunks[idx])
        item["score"] = float(score)
        results.append(item)
    return results
