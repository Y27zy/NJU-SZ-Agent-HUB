from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agent.food_models import FOOD_DATA_PATH, FOOD_META_PATH, FoodDataStore
from src.agent.web_search_tool import search_web
from src.database import now_iso


REFRESH_DAYS = 7
_refresh_lock = threading.Lock()
_refreshing_users: set[int] = set()


def load_food_database() -> dict[str, Any]:
    """Load the approved food database with automatic v1 migration."""
    return FoodDataStore().load()


def food_data_status(store: FoodDataStore | None = None) -> dict[str, Any]:
    """Return compact approved and pending data counts."""
    repository = store or FoodDataStore()
    data = repository.load()
    meta = repository.load_meta()
    return {
        "data_path": str(repository.path),
        "meta_path": str(repository.meta_path),
        "updated_at": data.get("updated_at"),
        "last_attempt_at": meta.get("last_attempt_at"),
        "last_success_at": meta.get("last_success_at"),
        "status": meta.get("status", "ready" if data.get("updated_at") else "not_updated"),
        "error": meta.get("error") or repository.last_error,
        "canteen_count": len(data.get("canteen_dishes") or []),
        "restaurant_count": len(data.get("restaurants") or []),
        "takeaway_count": len(data.get("takeaways") or []),
        "pending_count": len([item for item in data.get("pending_review") or [] if item.get("status") == "pending"]),
        "evidence_count": meta.get("evidence_count", len(data.get("sources") or [])),
    }


def food_data_is_stale(data: dict[str, Any] | None = None) -> bool:
    """Return whether public discovery is due."""
    value = (data or load_food_database()).get("updated_at")
    if not value:
        return True
    try:
        updated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated > timedelta(days=REFRESH_DAYS)
    except ValueError:
        return True


def _collect_evidence(query: str = "") -> list[dict[str, str]]:
    queries = [
        "site:njusz.nju.edu.cn 南京大学苏州校区 食堂 餐饮 通知",
        "南京大学苏州校区 附近 新店 餐厅",
        "南京大学苏州校区 附近 餐厅 外卖",
    ]
    if query.strip():
        queries.insert(0, f"南京大学苏州校区 {query.strip()}")
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    for search_query in queries:
        for item in search_web(search_query, max_results=8):
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            evidence.append({"query": search_query, **item})
    return evidence


def _pending_id(name: str, url: str) -> str:
    digest = hashlib.sha1(f"{name}|{url}".lower().encode("utf-8")).hexdigest()[:12]
    return f"pending_{digest}"


def _evidence_to_pending(evidence: list[dict[str, str]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {
        (str(item.get("name") or "").strip().lower(), str(item.get("source_url") or "").strip().lower())
        for item in existing
    }
    additions = []
    for item in evidence:
        name = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = (name.lower(), url.lower())
        if not name or not url or key in known:
            continue
        known.add(key)
        additions.append(
            {
                "id": _pending_id(name, url),
                "record_type": "restaurant" if "餐厅" in f"{name}{item.get('snippet', '')}" else "food_notice",
                "name": name,
                "source_url": url,
                "source_title": name,
                "source_snippet": str(item.get("snippet") or ""),
                "discovered_at": now_iso(),
                "status": "pending",
            }
        )
    return additions


def refresh_food_database(
    user_id: int,
    force: bool = False,
    *,
    query: str = "",
    store: FoodDataStore | None = None,
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Discover public clues and append them only to pending_review."""
    del user_id  # Kept in the public API for background-job compatibility.
    repository = store or FoodDataStore()
    existing = repository.load()
    if not force and not query and not food_data_is_stale(existing):
        return existing
    attempted_at = now_iso()
    try:
        discovered = evidence if evidence is not None else _collect_evidence(query)
        if not discovered:
            raise RuntimeError("公开搜索没有返回可用来源。")
        additions = _evidence_to_pending(discovered, existing.get("pending_review") or [])
        updated = {
            **existing,
            "updated_at": attempted_at,
            "pending_review": [*(existing.get("pending_review") or []), *additions],
            "sources": discovered,
        }
        # Approved collections are copied unchanged; weekly discovery can never overwrite them.
        repository.save(updated)
        repository.save_meta(
            {
                "status": "success",
                "last_attempt_at": attempted_at,
                "last_success_at": attempted_at,
                "error": "",
                "evidence_count": len(discovered),
                "pending_count": len([item for item in updated["pending_review"] if item.get("status") == "pending"]),
            }
        )
        return updated
    except Exception as exc:
        repository.save_meta(
            {
                **repository.load_meta(),
                "status": "failed",
                "last_attempt_at": attempted_at,
                "error": str(exc)[:1000],
            }
        )
        raise


def approve_pending_record(
    pending_id: str,
    collection: str,
    record: dict[str, Any],
    store: FoodDataStore | None = None,
) -> bool:
    """Move one reviewed clue into an approved collection."""
    if collection not in {"canteen_dishes", "restaurants", "takeaways"}:
        raise ValueError("待审核记录只能批准为食堂菜品、附近餐厅或外卖。")
    repository = store or FoodDataStore()
    data = repository.load()
    pending = next((item for item in data["pending_review"] if item.get("id") == pending_id), None)
    if not pending:
        return False
    approved = {**record, "origin": "manual", "locked": True, "enabled": True}
    data[collection].append(approved)
    pending["status"] = "approved"
    pending["reviewed_at"] = now_iso()
    repository.save(data)
    return True


def ignore_pending_record(pending_id: str, store: FoodDataStore | None = None) -> bool:
    """Mark one discovery clue as ignored."""
    repository = store or FoodDataStore()
    data = repository.load()
    pending = next((item for item in data["pending_review"] if item.get("id") == pending_id), None)
    if not pending:
        return False
    pending["status"] = "ignored"
    pending["reviewed_at"] = now_iso()
    repository.save(data)
    return True


def ensure_weekly_food_refresh(user_id: int) -> bool:
    """Start one non-blocking refresh and isolate all failures from the UI."""
    if not food_data_is_stale():
        return False
    with _refresh_lock:
        if user_id in _refreshing_users:
            return False
        _refreshing_users.add(user_id)

    def worker() -> None:
        try:
            refresh_food_database(user_id)
        except Exception:
            pass
        finally:
            with _refresh_lock:
                _refreshing_users.discard(user_id)

    threading.Thread(target=worker, name=f"food-data-{user_id}", daemon=True).start()
    return True


def search_new_food_places(user_id: int, query: str, store: FoodDataStore | None = None) -> dict[str, Any]:
    """Run an explicit discovery request and return only pending-review counts."""
    before = food_data_status(store)["pending_count"]
    refresh_food_database(user_id, force=True, query=query, store=store)
    status = food_data_status(store)
    return {"success": True, "pending_added": max(0, status["pending_count"] - before), "status": status}


__all__ = [
    "FOOD_DATA_PATH",
    "FOOD_META_PATH",
    "approve_pending_record",
    "ensure_weekly_food_refresh",
    "food_data_is_stale",
    "food_data_status",
    "ignore_pending_record",
    "load_food_database",
    "refresh_food_database",
    "search_new_food_places",
]
