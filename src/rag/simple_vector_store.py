from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.database import execute, fetch_all, fetch_one, get_connection, now_iso
from src.rag.document_hierarchy import build_document_hierarchy
from src.rag.text_splitter import split_text


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
        document = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?",
            (document_id, user_id),
        ).fetchone()
        if not document:
            raise ValueError("Document does not exist or is not owned by this user.")

        hierarchy = build_document_hierarchy(processed_markdown, document["title"], page_count)
        if hierarchy:
            _publish_document_hierarchy(
                conn,
                dict(document),
                hierarchy,
                original_text,
                page_count,
                structure_json,
            )
            return

        child_ids = _child_document_ids(conn, document_id)
        _delete_document_relations(conn, child_ids)
        _replace_document_chunks(conn, dict(document), chunks)
        conn.execute(
            """
            UPDATE documents
            SET original_text = ?, processed_markdown = ?, processing_status = 'ready',
                processing_error = NULL, page_count = ?, structure_json = ?, updated_at = ?,
                parent_document_id = NULL, document_role = 'standalone', group_title = NULL,
                section_key = NULL, sort_order = 0, source_start_page = NULL, source_end_page = NULL
            WHERE id = ? AND user_id = ?
            """,
            (original_text, processed_markdown, page_count, structure_json, now_iso(), document_id, user_id),
        )


def _publish_document_hierarchy(
    conn,
    document: dict,
    hierarchy,
    original_text: str,
    page_count: int,
    structure_json: str,
) -> None:
    """Atomically replace a collection's generated children while preserving stable IDs."""
    document_id = int(document["id"])
    user_id = int(document["user_id"])
    timestamp = now_iso()
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    conn.execute(
        """
        UPDATE documents
        SET original_text = ?, processed_markdown = ?, processing_status = 'ready',
            processing_error = NULL, page_count = ?, structure_json = ?, updated_at = ?,
            parent_document_id = NULL, document_role = 'collection', group_title = NULL,
            section_key = NULL, sort_order = 0, source_start_page = 1, source_end_page = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            original_text,
            hierarchy.toc_markdown,
            page_count,
            structure_json,
            timestamp,
            page_count or None,
            document_id,
            user_id,
        ),
    )

    existing_rows = conn.execute(
        "SELECT * FROM documents WHERE parent_document_id = ? ORDER BY sort_order, id",
        (document_id,),
    ).fetchall()
    existing = {str(row["section_key"]): dict(row) for row in existing_rows if row["section_key"]}
    retained_ids: set[int] = set()

    for section in hierarchy.sections:
        child = existing.get(section.section_key)
        child_page_count = (
            section.source_end_page - section.source_start_page + 1
            if section.source_start_page is not None and section.source_end_page is not None
            else 0
        )
        if child:
            child_id = int(child["id"])
            conn.execute(
                """
                UPDATE documents
                SET title = ?, file_path = ?, folder_id = ?, source_format = ?, original_text = ?,
                    processed_markdown = ?, processing_status = 'ready', processing_error = NULL,
                    page_count = ?, structure_json = NULL, library_scope = ?, is_global = ?, updated_at = ?,
                    document_role = 'section', group_title = ?, sort_order = ?,
                    source_start_page = ?, source_end_page = ?
                WHERE id = ? AND parent_document_id = ?
                """,
                (
                    section.title,
                    document["file_path"],
                    document["folder_id"],
                    document["source_format"],
                    None,
                    section.markdown,
                    child_page_count,
                    document["library_scope"],
                    document["is_global"],
                    timestamp,
                    section.group_title,
                    section.sort_order,
                    section.source_start_page,
                    section.source_end_page,
                    child_id,
                    document_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO documents
                (user_id, doc_type, title, file_path, folder_id, source_format, original_text,
                 processed_markdown, processing_status, processing_error, page_count, structure_json,
                 library_scope, is_global, created_at, updated_at, parent_document_id, document_role,
                 group_title, section_key, sort_order, source_start_page, source_end_page)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, NULL, ?, ?, ?, ?, ?, 'section', ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    document["doc_type"],
                    section.title,
                    document["file_path"],
                    document["folder_id"],
                    document["source_format"],
                    None,
                    section.markdown,
                    child_page_count,
                    document["library_scope"],
                    document["is_global"],
                    timestamp,
                    timestamp,
                    document_id,
                    section.group_title,
                    section.section_key,
                    section.sort_order,
                    section.source_start_page,
                    section.source_end_page,
                ),
            )
            child_id = int(cursor.lastrowid)
        retained_ids.add(child_id)
        child_document = {
            "id": child_id,
            "user_id": user_id,
            "doc_type": document["doc_type"],
        }
        _replace_document_chunks(
            conn,
            child_document,
            split_text(section.markdown, chunk_size=1200, overlap=180),
        )

    stale_ids = [int(row["id"]) for row in existing_rows if int(row["id"]) not in retained_ids]
    _delete_document_relations(conn, stale_ids)


def _replace_document_chunks(conn, document: dict, chunks: list[str]) -> None:
    document_id = int(document["id"])
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    for index, chunk in enumerate(chunks):
        conn.execute(
            """
            INSERT INTO document_chunks (document_id, user_id, doc_type, chunk_index, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, document["user_id"], document["doc_type"], index, chunk, now_iso()),
        )


def _child_document_ids(conn, document_id: int) -> list[int]:
    return [
        int(row["id"])
        for row in conn.execute("SELECT id FROM documents WHERE parent_document_id = ?", (document_id,)).fetchall()
    ]


def _delete_document_relations(conn, document_ids: list[int]) -> None:
    if not document_ids:
        return
    placeholders = ",".join("?" for _ in document_ids)
    for table in (
        "document_jobs",
        "document_questions",
        "document_mindmaps",
        "document_highlights",
        "document_chunks",
    ):
        conn.execute(f"DELETE FROM {table} WHERE document_id IN ({placeholders})", tuple(document_ids))
    conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", tuple(document_ids))


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
        ids = [document_id, *_child_document_ids(conn, document_id)]
        _delete_document_relations(conn, ids)
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
    columns = """
        id, user_id, doc_type, title, file_path, folder_id, source_format,
        processing_status, processing_error, page_count, library_scope, is_global,
        created_at, updated_at, parent_document_id, document_role, group_title,
        section_key, sort_order, source_start_page, source_end_page
    """
    if admin:
        rows = fetch_all(
            f"""
            SELECT {columns} FROM documents
            WHERE is_global = 1 AND library_scope != 'custom'
            ORDER BY COALESCE(parent_document_id, id) DESC, sort_order, id
            """
        )
        return [dict(row) for row in rows]
    rows = fetch_all(
        f"""
        SELECT {columns} FROM documents
        WHERE user_id = ? OR is_global = 1
        ORDER BY COALESCE(parent_document_id, id) DESC, sort_order, id
        """,
        (viewer_id,),
    )
    return [dict(row) for row in rows]


def list_document_sections(viewer_id: int, parent_document_id: int) -> list[dict]:
    """List lightweight internal Markdown parts for one accessible collection."""
    rows = fetch_all(
        """
        SELECT id, user_id, doc_type, title, file_path, folder_id, source_format,
               processing_status, processing_error, page_count, library_scope, is_global,
               created_at, updated_at, parent_document_id, document_role, group_title,
               section_key, sort_order, source_start_page, source_end_page
        FROM documents
        WHERE parent_document_id = ? AND document_role = 'section'
          AND (user_id = ? OR is_global = 1)
        ORDER BY sort_order, id
        """,
        (parent_document_id, viewer_id),
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
    with get_connection() as conn:
        ids = [document_id, *_child_document_ids(conn, document_id)]
        _delete_document_relations(conn, ids)
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
