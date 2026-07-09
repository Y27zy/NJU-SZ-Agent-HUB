import json
import random
from pathlib import Path

from src.config import DATA_DIR
from src.memory.memory_service import update_user_memory


def _load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def recommend_restaurants(budget: int, taste: str, distance_preference: str, is_group: bool, spicy: bool, light: bool) -> list[dict]:
    restaurants = _load_json(DATA_DIR / "restaurants.json")
    scored = []
    for item in restaurants:
        score = 0
        if item["avg_price"] <= budget:
            score += 3
        if taste and any(taste in tag for tag in item["tags"]):
            score += 2
        if spicy and any("辣" in tag for tag in item["tags"]):
            score += 2
        if light and any("清淡" in tag for tag in item["tags"]):
            score += 2
        if is_group and any("聚餐" in s for s in item["suitable_for"]):
            score += 2
        if distance_preference == "近一点" and item["distance"].startswith(("700", "900", "1.")):
            score += 1
        scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:3]]


def random_canteen_food(meal_time: str, taste: str, category: str) -> dict:
    foods = _load_json(DATA_DIR / "canteen_foods.json")
    candidates = [
        f
        for f in foods
        if (meal_time == "随机" or f["meal_time"] == meal_time)
        and (taste == "随便" or f["taste"] == taste)
        and (category == "随机" or f["category"] == category)
    ]
    return random.choice(candidates or foods)


def save_food_preference(user_id: int, content: str) -> int:
    return update_user_memory(user_id, f"饮食偏好：{content}", "user", importance=4)
