from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import DATA_DIR


SCHEMA_VERSION = 2
FOOD_DATA_PATH = DATA_DIR / "campus_foods.json"
FOOD_META_PATH = DATA_DIR / "campus_food_update_meta.json"
FORMAL_COLLECTIONS = ("canteen_dishes", "restaurants", "takeaways")


def empty_food_database() -> dict[str, Any]:
    """Return a fresh schema-v2 food database."""
    return {
        "schema_version": SCHEMA_VERSION,
        "campus": "南京大学苏州校区",
        "updated_at": None,
        "refresh_interval_days": 7,
        "canteen_dishes": [],
        "restaurants": [],
        "takeaways": [],
        "pending_review": [],
        "sources": [],
    }


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _normalize_formal_record(item: dict[str, Any], record_type: str) -> dict[str, Any]:
    normalized = dict(item)
    prefix = {"canteen_dishes": "canteen", "restaurants": "restaurant", "takeaways": "takeaway"}[record_type]
    identity = normalized.get("food_name") or normalized.get("name") or normalized.get("restaurant")
    normalized.setdefault("id", _stable_id(prefix, identity, normalized.get("venue"), normalized.get("source_url")))
    normalized.setdefault("weight", 1)
    normalized.setdefault("enabled", True)
    normalized.setdefault("origin", "manual")
    normalized.setdefault("locked", normalized.get("origin") == "manual")
    normalized.setdefault("notes", "")
    return normalized


def migrate_food_database(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Migrate legacy food data without inventing missing dish details."""
    if not isinstance(raw, dict):
        return empty_food_database(), True
    if int(raw.get("schema_version") or 1) >= SCHEMA_VERSION:
        data = {**empty_food_database(), **raw}
        for key in (*FORMAL_COLLECTIONS, "pending_review", "sources"):
            data[key] = _list(data.get(key))
        for key in FORMAL_COLLECTIONS:
            data[key] = [_normalize_formal_record(item, key) for item in data[key] if isinstance(item, dict)]
        return data, data != raw

    data = empty_food_database()
    data["updated_at"] = raw.get("updated_at")
    data["sources"] = deepcopy(_list(raw.get("sources")))

    for dish in _list(raw.get("dishes")):
        if not isinstance(dish, dict) or not str(dish.get("food_name") or "").strip():
            continue
        converted = {
            **dish,
            "id": dish.get("id") or _stable_id("canteen", dish.get("venue"), dish.get("window"), dish.get("food_name")),
            "meal_times": dish.get("meal_times") or ([dish.get("meal_time")] if dish.get("meal_time") else []),
            "tastes": dish.get("tastes") or ([dish.get("taste")] if dish.get("taste") else []),
            "enabled": dish.get("enabled", True),
        }
        data["canteen_dishes"].append(_normalize_formal_record(converted, "canteen_dishes"))

    for restaurant in _list(raw.get("restaurants")):
        if not isinstance(restaurant, dict) or not str(restaurant.get("name") or "").strip():
            continue
        converted = {
            **restaurant,
            "id": restaurant.get("id") or _stable_id("restaurant", restaurant.get("name"), restaurant.get("source_url")),
            "area": restaurant.get("area") or restaurant.get("distance") or "",
            "distance_minutes": restaurant.get("distance_minutes"),
            "tastes": restaurant.get("tastes") or restaurant.get("tags") or [],
            "categories": restaurant.get("categories") or restaurant.get("tags") or [],
            "recommended_food": restaurant.get("recommended_food") or "",
            "enabled": restaurant.get("enabled", True),
        }
        data["restaurants"].append(_normalize_formal_record(converted, "restaurants"))

    # A legacy venue is evidence of a place, not evidence of a concrete dish.
    for venue in _list(raw.get("venues")):
        if not isinstance(venue, dict) or not str(venue.get("name") or "").strip():
            continue
        data["pending_review"].append(
            {
                "id": _stable_id("pending", "canteen_venue", venue.get("name"), venue.get("source_url")),
                "record_type": "canteen_venue",
                "name": venue.get("name"),
                "source_url": venue.get("source_url", ""),
                "source_title": venue.get("source_title", ""),
                "source_snippet": venue.get("evidence", ""),
                "discovered_at": venue.get("verified_at") or raw.get("updated_at"),
                "status": "pending",
                "origin": venue.get("origin", "legacy"),
                "locked": bool(venue.get("locked")),
            }
        )
    return data, True


class FoodDataStore:
    """Own schema migration, safe reads, and atomic writes for food data."""

    def __init__(self, path: Path | None = None, meta_path: Path | None = None):
        self.path = Path(path or FOOD_DATA_PATH)
        self.meta_path = Path(meta_path or FOOD_META_PATH)
        self.last_error = ""

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def load(self) -> dict[str, Any]:
        """Load and migrate data; back up corrupt JSON instead of crashing."""
        if not self.path.exists():
            data = empty_food_database()
            self.save(data)
            return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            data, changed = migrate_food_database(raw)
            if changed:
                self.save(data)
            self.last_error = ""
            return data
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_suffix(f".corrupt-{stamp}{self.path.suffix}")
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                pass
            self.last_error = f"数据文件损坏，已使用空数据库启动：{exc}"
            data = empty_food_database()
            self.save(data)
            return data

    def save(self, data: dict[str, Any]) -> None:
        """Atomically save normalized schema-v2 data."""
        normalized, _ = migrate_food_database({**data, "schema_version": SCHEMA_VERSION})
        self._atomic_write(self.path, normalized)

    def load_meta(self) -> dict[str, Any]:
        try:
            value = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def save_meta(self, meta: dict[str, Any]) -> None:
        """Atomically save refresh metadata."""
        self._atomic_write(self.meta_path, meta)

    def replace_collection(self, collection: str, records: list[dict[str, Any]]) -> None:
        """Replace one approved collection after maintenance edits."""
        if collection not in FORMAL_COLLECTIONS:
            raise ValueError(f"不支持的数据集合：{collection}")
        data = self.load()
        data[collection] = [_normalize_formal_record(item, collection) for item in records if isinstance(item, dict)]
        self.save(data)

