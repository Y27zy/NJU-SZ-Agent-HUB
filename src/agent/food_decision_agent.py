"""Compatibility layer for callers from earlier project versions."""

from src.agent.food_agent import FoodAgent
from src.agent.food_tools import choose_canteen_food, choose_nearby_restaurant


class FoodDecisionAgent(FoodAgent):
    """Deprecated alias; new code should import FoodAgent."""

    def recommend_restaurants(self, constraints: dict, allow_web: bool = False):
        del allow_web
        return self.handle_request("附近堂食", {**constraints, "mode": "restaurant"})

    def choose_canteen(self, constraints: dict):
        return self.handle_request("校内食堂", {**constraints, "mode": "canteen"})


def local_restaurant_candidates(constraints: dict) -> list[dict]:
    """Return at most one approved Python-selected restaurant for compatibility."""
    result = choose_nearby_restaurant(user_id=int(constraints.get("user_id") or 0), budget_per_person=constraints.get("budget"))
    return [result["record"]] if result.get("success") else []


def local_canteen_candidates(constraints: dict) -> list[dict]:
    """Return at most one approved Python-selected dish for compatibility."""
    result = choose_canteen_food(user_id=int(constraints.get("user_id") or 0), meal_time=constraints.get("meal_time"))
    return [result["record"]] if result.get("success") else []
