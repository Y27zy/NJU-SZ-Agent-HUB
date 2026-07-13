"""Durable user preferences and lightweight semantic memory retrieval."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.database import fetch_all, get_connection, now_iso
from src.rag.simple_vector_store import search_chunks


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _food_preference_key(content: str) -> str | None:
    """Return a stable key for explicit food preferences that can conflict."""
    text = content.replace("饮食偏好：", "").replace("饮食偏好:", "").strip()
    compact = _normalize_text(text)
    if any(token in compact for token in ("不吃辣", "不要辣", "喜欢辣", "想吃辣")):
        return "food:spicy"
    if re.search(r"(?:预算|以内|不超过)[^\d]{0,8}\d{1,3}", text):
        return "food:budget"
    avoid = re.search(r"(?:不吃|不要|别推荐|忌口)\s*([^，。；,;]+)", text)
    if avoid:
        return f"food:avoid:{_normalize_text(avoid.group(1))[:48]}"
    liked = re.search(r"(?:喜欢|偏好)\s*([^，。；,;]+)", text)
    if liked:
        return f"food:like:{_normalize_text(liked.group(1))[:48]}"
    return None


def infer_memory_key(memory_type: str, content: str) -> str | None:
    """Infer a replacement key only for preferences that have a clear meaning."""
    if memory_type == "food_preference" or "饮食偏好" in content:
        return _food_preference_key(content)
    return None


def _parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _rank_memories(memories: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Rank memories by query relevance, then importance and freshness."""
    if not memories:
        return []
    relevance = [0.0] * len(memories)
    clean_query = (query or "").strip()
    if clean_query:
        try:
            corpus = [str(item.get("content") or "") for item in memories]
            matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1).fit_transform(corpus + [clean_query])
            relevance = cosine_similarity(matrix[-1], matrix[:-1]).flatten().tolist()
        except ValueError:
            pass
    latest = max((_parse_time(item.get("updated_at") or item.get("created_at")) for item in memories), default=0.0) or 1.0
    ranked: list[dict[str, Any]] = []
    for item, semantic in zip(memories, relevance):
        importance = max(0, min(5, int(item.get("importance") or 0))) / 5
        freshness = _parse_time(item.get("updated_at") or item.get("created_at")) / latest
        # Relevance leads when a query is supplied; otherwise use stable preference importance.
        score = (0.78 * semantic + 0.16 * importance + 0.06 * freshness) if clean_query else (0.75 * importance + 0.25 * freshness)
        ranked.append({**item, "relevance_score": round(float(score), 4)})
    return sorted(ranked, key=lambda item: (item["relevance_score"], item["id"]), reverse=True)


def update_user_memory(user_id: int, content: str, memory_type: str = "user", importance: int = 3) -> int:
    """Create or update an explicit durable preference without duplicate rows."""
    cleaned = content.strip()
    if not cleaned:
        raise ValueError("记忆内容不能为空。")
    importance = max(1, min(int(importance), 5))
    memory_key = infer_memory_key(memory_type, cleaned)
    normalized = _normalize_text(cleaned)
    now = now_iso()
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM memory_items WHERE user_id = ? ORDER BY id DESC", (user_id,))]
        matching = [
            row for row in rows
            if (memory_key and (row.get("memory_key") or infer_memory_key(row["memory_type"], row["content"])) == memory_key)
            or (not memory_key and _normalize_text(row["content"]) == normalized)
        ]
        if matching:
            target = matching[0]
            conn.execute(
                """
                UPDATE memory_items
                SET memory_type = ?, memory_key = ?, content = ?, importance = ?, updated_at = ?, last_accessed_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (memory_type, memory_key, cleaned, max(importance, int(target.get("importance") or 0)), now, now, target["id"], user_id),
            )
            duplicate_ids = [row["id"] for row in matching[1:]]
            if duplicate_ids:
                placeholders = ", ".join("?" for _ in duplicate_ids)
                conn.execute(f"DELETE FROM memory_items WHERE user_id = ? AND id IN ({placeholders})", (user_id, *duplicate_ids))
            return int(target["id"])
        cursor = conn.execute(
            """
            INSERT INTO memory_items (user_id, memory_type, memory_key, content, importance, created_at, updated_at, last_accessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, memory_type, memory_key, cleaned, importance, now, now, now),
        )
        return int(cursor.lastrowid)


def retrieve_user_memory(user_id: int, query: str = "", limit: int = 6) -> list[dict[str, Any]]:
    """Return only the most relevant durable preferences for the current task."""
    rows = fetch_all("SELECT * FROM memory_items WHERE user_id = ?", (user_id,))
    memories = _rank_memories([dict(row) for row in rows], query)[: max(1, limit)]
    if memories:
        now = now_iso()
        with get_connection() as conn:
            conn.executemany("UPDATE memory_items SET last_accessed_at = ? WHERE id = ?", [(now, item["id"]) for item in memories])
    return memories


def list_memories(user_id: int) -> list[dict[str, Any]]:
    """List all durable preferences, newest updates first, for future management UI."""
    return [dict(row) for row in fetch_all("SELECT * FROM memory_items WHERE user_id = ? ORDER BY updated_at DESC, id DESC", (user_id,))]


def delete_user_memory(user_id: int, memory_id: int) -> bool:
    """Remove one durable memory owned by the current user."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM memory_items WHERE id = ? AND user_id = ?", (memory_id, user_id))
        return cursor.rowcount > 0


def build_context_with_memory(user_id: int, query: str) -> str:
    """Combine task-relevant user memory with RAG knowledge evidence."""
    user_memories = retrieve_user_memory(user_id, query, limit=5)
    knowledge = search_chunks(user_id, query, top_k=5)
    memory_text = "\n".join(f"- [{m['memory_type']}] {m['content']}" for m in user_memories)
    knowledge_text = "\n".join(f"- {k['content'][:500]}" for k in knowledge)
    return f"用户长期记忆：\n{memory_text or '暂无'}\n\n知识记忆检索结果：\n{knowledge_text or '暂无'}"
