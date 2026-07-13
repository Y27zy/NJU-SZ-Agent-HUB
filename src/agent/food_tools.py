from __future__ import annotations

import random
import re
from typing import Any, Callable

from src.agent.food_data_agent import food_data_status, search_new_food_places
from src.agent.food_models import FoodDataStore
from src.memory.memory_service import retrieve_user_memory, update_user_memory


PreferenceReader = Callable[[int, str, int], list[dict[str, Any]]]
PreferenceWriter = Callable[[int, str, str, int], int]


def _text_values(record: dict[str, Any]) -> str:
    values = [
        record.get("name"), record.get("restaurant"), record.get("venue"), record.get("window"),
        record.get("food_name"), record.get("recommended_food"), record.get("category"),
        *(record.get("categories") or []), *(record.get("tastes") or []),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _parse_preferences(memories: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"avoid": [], "like": [], "spicy": None, "budget": None, "raw": []}
    for memory in memories:
        content = str(memory.get("content") or "").strip()
        if not content or "饮食" not in content:
            continue
        result["raw"].append(content)
        lowered = content.lower()
        for pattern in (r"(?:不吃|不要|别推荐|忌口)\s*([^，。；,;]+)",):
            match = re.search(pattern, content)
            if match:
                result["avoid"].append(match.group(1).strip())
        match = re.search(r"(?:喜欢|偏好)\s*([^，。；,;]+)", content)
        if match:
            result["like"].append(match.group(1).strip())
        if "不吃辣" in lowered or "不要辣" in lowered:
            result["spicy"] = False
        elif "喜欢辣" in lowered or "想吃辣" in lowered:
            result["spicy"] = True
        budget = re.search(r"(?:预算|以内|不超过)[^\d]{0,8}(\d{1,3})", content)
        if budget:
            result["budget"] = int(budget.group(1))
    return result


def get_user_food_preferences(
    user_id: int,
    *,
    reader: PreferenceReader = retrieve_user_memory,
) -> dict[str, Any]:
    """Read and normalize long-term food preferences from memory."""
    return _parse_preferences(reader(user_id, "饮食偏好", 30))


def save_user_food_preference(
    user_id: int,
    content: str,
    *,
    writer: PreferenceWriter = update_user_memory,
) -> dict[str, Any]:
    """Persist one explicit food preference through the shared memory service."""
    clean = content.strip()
    if not clean:
        return {"success": False, "status": "invalid", "message": "偏好内容不能为空。"}
    memory_id = writer(user_id, f"饮食偏好：{clean}", "food_preference", 4)
    return {"success": True, "status": "saved", "memory_id": memory_id, "preference": clean}


def _weighted_pick(records: list[dict[str, Any]], rng: random.Random | Any) -> dict[str, Any]:
    weights = [max(0.01, float(item.get("weight") or 1)) for item in records]
    if hasattr(rng, "choices"):
        return rng.choices(records, weights=weights, k=1)[0]
    return random.choices(records, weights=weights, k=1)[0]


def _no_match(filters: list[str]) -> dict[str, Any]:
    key = filters[0] if filters else "当前条件"
    return {
        "success": False,
        "status": "no_match",
        "result_type": "none",
        "blocking_conditions": filters,
        "message": f"本地已审核数据中没有符合{key}的记录，可以只放宽这一项再试。",
    }


def _preference_constraints(user_id: int, explicit: dict[str, Any], reader: PreferenceReader) -> dict[str, Any]:
    preferences = get_user_food_preferences(user_id, reader=reader)
    merged = dict(explicit)
    merged["avoid_keywords"] = list(dict.fromkeys([*(preferences.get("avoid") or []), *(explicit.get("avoid_keywords") or [])]))
    merged["liked_keywords"] = preferences.get("like") or []
    if not merged.get("budget") and preferences.get("budget"):
        merged["budget"] = preferences["budget"]
    if merged.get("taste") in {None, "", "随便", "随机"} and preferences.get("spicy") is False:
        merged["taste"] = "不吃辣"
    return merged


def choose_canteen_food(
    *,
    user_id: int,
    meal_time: str | None = None,
    budget: float | None = None,
    taste: str | None = None,
    category: str | None = None,
    excluded_ids: list[str] | None = None,
    avoid_keywords: list[str] | None = None,
    store: FoodDataStore | None = None,
    rng: random.Random | Any = random,
    preference_reader: PreferenceReader = retrieve_user_memory,
) -> dict[str, Any]:
    """Strictly filter approved canteen dishes, then perform weighted random choice."""
    constraints = _preference_constraints(user_id, locals(), preference_reader)
    records = (store or FoodDataStore()).load().get("canteen_dishes") or []
    excluded = set(excluded_ids or [])
    blockers: list[str] = []
    candidates = [item for item in records if item.get("enabled", True) and item.get("id") not in excluded]
    if budget is not None:
        before = candidates
        candidates = [item for item in candidates if item.get("price") is not None and float(item["price"]) <= float(budget)]
        if before and not candidates:
            blockers.append(f"预算 {budget:g} 元以内")
    if meal_time and meal_time not in {"随机", "随便"}:
        before = candidates
        candidates = [item for item in candidates if meal_time in (item.get("meal_times") or [])]
        if before and not candidates:
            blockers.append(meal_time)
    if category and category not in {"随机", "随便"}:
        before = candidates
        candidates = [item for item in candidates if str(item.get("category") or "") == category]
        if before and not candidates:
            blockers.append(category)
    if taste and taste not in {"随机", "随便", "不吃辣"}:
        before = candidates
        candidates = [item for item in candidates if taste in (item.get("tastes") or [])]
        if before and not candidates:
            blockers.append(taste)
    avoid = constraints.get("avoid_keywords") or []
    if avoid:
        before = candidates
        candidates = [item for item in candidates if not any(word.lower() in _text_values(item) for word in avoid)]
        if before and not candidates:
            blockers.append("忌口")
    if taste == "不吃辣":
        before = candidates
        candidates = [item for item in candidates if "辣" not in _text_values(item)]
        if before and not candidates:
            blockers.append("不吃辣")
    if not candidates:
        return _no_match(blockers or ["当前食堂筛选条件"])
    soft = []
    for item in candidates:
        score = float(item.get("weight") or 1)
        text = _text_values(item)
        if category and category not in {"随机", "随便"} and category.lower() in text:
            score += 2
        if taste and taste not in {"随机", "随便"}:
            if taste == "不吃辣":
                score += 1 if "辣" not in text else -0.9
            elif taste.replace("想吃", "") in text:
                score += 2
        if any(word.lower() in text for word in constraints.get("liked_keywords") or []):
            score += 1.5
        soft.append({**item, "weight": max(0.01, score)})
    selected = _weighted_pick(soft, rng)
    title = "".join(part for part in [selected.get("venue", ""), selected.get("floor", ""), selected.get("window", "")] if part)
    return {
        "success": True, "status": "selected", "result_type": "canteen", "record_id": selected["id"],
        "title": title or selected.get("venue", "校内食堂"), "food_name": selected.get("food_name", ""),
        "price_text": f"约 {selected['price']:g} 元" if selected.get("price") is not None else "",
        "distance_text": "", "reason": _reason(meal_time, taste, category, budget), "record": selected,
    }


def choose_nearby_restaurant(
    *,
    user_id: int,
    budget_per_person: float | None = None,
    taste: str | None = None,
    category: str | None = None,
    max_distance_minutes: int | None = None,
    group_size: int | None = None,
    excluded_ids: list[str] | None = None,
    avoid_keywords: list[str] | None = None,
    store: FoodDataStore | None = None,
    rng: random.Random | Any = random,
    preference_reader: PreferenceReader = retrieve_user_memory,
) -> dict[str, Any]:
    """Strictly filter approved nearby restaurants, then choose one in Python."""
    explicit = dict(locals())
    explicit["budget"] = budget_per_person
    constraints = _preference_constraints(user_id, explicit, preference_reader)
    budget_per_person = budget_per_person or constraints.get("budget")
    records = (store or FoodDataStore()).load().get("restaurants") or []
    excluded = set(excluded_ids or [])
    blockers: list[str] = []
    candidates = [item for item in records if item.get("enabled", True) and item.get("id") not in excluded]
    if budget_per_person is not None:
        before = candidates
        candidates = [item for item in candidates if item.get("avg_price") is not None and float(item["avg_price"]) <= float(budget_per_person)]
        if before and not candidates:
            blockers.append(f"人均 {budget_per_person:g} 元以内")
    if max_distance_minutes is not None:
        before = candidates
        candidates = [item for item in candidates if item.get("distance_minutes") is not None and int(item["distance_minutes"]) <= int(max_distance_minutes)]
        if before and not candidates:
            blockers.append(f"骑行 {max_distance_minutes} 分钟以内")
    if category and category not in {"随机", "随便"}:
        before = candidates
        candidates = [item for item in candidates if category in (item.get("categories") or [])]
        if before and not candidates:
            blockers.append(category)
    if taste and taste not in {"随机", "随便", "不吃辣"}:
        before = candidates
        candidates = [item for item in candidates if taste in (item.get("tastes") or [])]
        if before and not candidates:
            blockers.append(taste)
    if group_size:
        expected = "一人食" if group_size == 1 else "两人" if group_size == 2 else "聚餐"
        before = candidates
        candidates = [item for item in candidates if not item.get("suitable_for") or expected in item.get("suitable_for", [])]
        if before and not candidates:
            blockers.append(f"{group_size} 人用餐")
    avoid = constraints.get("avoid_keywords") or []
    if avoid:
        candidates = [item for item in candidates if not any(word.lower() in _text_values(item) for word in avoid)]
    if taste == "不吃辣":
        candidates = [item for item in candidates if "辣" not in _text_values(item)]
    if not candidates:
        return _no_match(blockers or ["当前堂食筛选条件"])
    scored = _score_soft(candidates, taste, category, constraints.get("liked_keywords") or [])
    selected = _weighted_pick(scored, rng)
    return {
        "success": True, "status": "selected", "result_type": "restaurant", "record_id": selected["id"],
        "title": selected.get("name", ""), "food_name": selected.get("recommended_food", ""),
        "price_text": f"约 {selected['avg_price']:g} 元" if selected.get("avg_price") is not None else "",
        "distance_text": f"骑行约 {selected['distance_minutes']} 分钟" if selected.get("distance_minutes") is not None else selected.get("area", ""),
        "reason": _reason(None, taste, category, budget_per_person), "record": selected,
    }


def choose_takeaway(
    *,
    user_id: int,
    budget: float | None = None,
    taste: str | None = None,
    category: str | None = None,
    meal_time: str | None = None,
    excluded_ids: list[str] | None = None,
    avoid_keywords: list[str] | None = None,
    store: FoodDataStore | None = None,
    rng: random.Random | Any = random,
    preference_reader: PreferenceReader = retrieve_user_memory,
) -> dict[str, Any]:
    """Strictly filter approved takeaway entries, then choose one in Python."""
    constraints = _preference_constraints(user_id, locals(), preference_reader)
    budget = budget or constraints.get("budget")
    records = (store or FoodDataStore()).load().get("takeaways") or []
    excluded = set(excluded_ids or [])
    blockers: list[str] = []
    candidates = [item for item in records if item.get("enabled", True) and item.get("id") not in excluded]
    if budget is not None:
        before = candidates
        candidates = [item for item in candidates if item.get("avg_price") is not None and float(item["avg_price"]) <= float(budget)]
        if before and not candidates:
            blockers.append(f"预算 {budget:g} 元以内")
    if meal_time and meal_time not in {"随机", "随便"}:
        before = candidates
        candidates = [item for item in candidates if meal_time in (item.get("meal_times") or [])]
        if before and not candidates:
            blockers.append(meal_time)
    if category and category not in {"随机", "随便"}:
        before = candidates
        candidates = [item for item in candidates if str(item.get("category") or "") == category]
        if before and not candidates:
            blockers.append(category)
    if taste and taste not in {"随机", "随便", "不吃辣"}:
        before = candidates
        candidates = [item for item in candidates if taste in (item.get("tastes") or [])]
        if before and not candidates:
            blockers.append(taste)
    avoid = constraints.get("avoid_keywords") or []
    if avoid:
        candidates = [item for item in candidates if not any(word.lower() in _text_values(item) for word in avoid)]
    if taste == "不吃辣":
        candidates = [item for item in candidates if "辣" not in _text_values(item)]
    if not candidates:
        return _no_match(blockers or ["当前外卖筛选条件"])
    selected = _weighted_pick(_score_soft(candidates, taste, category, constraints.get("liked_keywords") or []), rng)
    platforms = " / ".join(selected.get("platforms") or [])
    return {
        "success": True, "status": "selected", "result_type": "takeaway", "record_id": selected["id"],
        "title": selected.get("restaurant", ""), "food_name": selected.get("food_name", ""),
        "price_text": f"预计 {selected['avg_price']:g} 元" if selected.get("avg_price") is not None else "",
        "distance_text": f"配送约 {selected['delivery_minutes']} 分钟" if selected.get("delivery_minutes") is not None else platforms,
        "reason": _reason(meal_time, taste, category, budget), "record": selected,
    }


def exclude_recommendation(record_id: str, excluded_ids: list[str] | None = None) -> dict[str, Any]:
    """Return a session-only exclusion list containing the current result."""
    values = list(dict.fromkeys([*(excluded_ids or []), record_id]))
    return {"success": True, "status": "excluded", "record_id": record_id, "excluded_ids": values}


def get_food_data_status(store: FoodDataStore | None = None) -> dict[str, Any]:
    """Expose compact data status to Agent and maintenance UI."""
    return food_data_status(store)


def _score_soft(records: list[dict[str, Any]], taste: str | None, category: str | None, liked: list[str]) -> list[dict[str, Any]]:
    output = []
    for item in records:
        score = float(item.get("weight") or 1)
        text = _text_values(item)
        if taste and taste not in {"随机", "随便"}:
            if taste == "不吃辣":
                score += 1 if "辣" not in text else -0.9
            elif taste.replace("想吃", "") in text:
                score += 2
        if category and category not in {"随机", "随便"} and category.lower() in text:
            score += 2
        if any(word.lower() in text for word in liked):
            score += 1.5
        output.append({**item, "weight": max(0.01, score)})
    return output


def _reason(meal: str | None, taste: str | None, category: str | None, budget: float | None) -> str:
    parts = [value for value in (meal, taste, category) if value and value not in {"随机", "随便"}]
    if budget is not None:
        parts.append(f"{budget:g} 元以内")
    return "符合" + "、".join(parts) + "要求" if parts else "从已审核数据中随机选出"


__all__ = [
    "choose_canteen_food", "choose_nearby_restaurant", "choose_takeaway", "exclude_recommendation",
    "get_food_data_status", "get_user_food_preferences", "save_user_food_preference", "search_new_food_places",
]
