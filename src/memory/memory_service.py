from src.database import execute, fetch_all, now_iso
from src.rag.simple_vector_store import search_chunks


def update_user_memory(user_id: int, content: str, memory_type: str = "user", importance: int = 3) -> int:
    return execute(
        """
        INSERT INTO memory_items (user_id, memory_type, content, importance, created_at, last_accessed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, memory_type, content.strip(), importance, now_iso(), now_iso()),
    )


def retrieve_user_memory(user_id: int, query: str = "", limit: int = 6) -> list[dict]:
    rows = fetch_all(
        """
        SELECT * FROM memory_items
        WHERE user_id = ?
        ORDER BY importance DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    memories = [dict(r) for r in rows]
    for memory in memories:
        execute("UPDATE memory_items SET last_accessed_at = ? WHERE id = ?", (now_iso(), memory["id"]))
    return memories


def list_memories(user_id: int) -> list[dict]:
    return [dict(r) for r in fetch_all("SELECT * FROM memory_items WHERE user_id = ? ORDER BY id DESC", (user_id,))]


def build_context_with_memory(user_id: int, query: str) -> str:
    user_memories = retrieve_user_memory(user_id, query, limit=5)
    knowledge = search_chunks(user_id, query, top_k=5)
    memory_text = "\n".join(f"- [{m['memory_type']}] {m['content']}" for m in user_memories)
    knowledge_text = "\n".join(f"- {k['content'][:500]}" for k in knowledge)
    return f"用户长期记忆：\n{memory_text or '暂无'}\n\n知识记忆检索结果：\n{knowledge_text or '暂无'}"
