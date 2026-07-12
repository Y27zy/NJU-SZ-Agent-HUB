from src.agent.food_agent import FoodAgent
from src.agent.food_tools import save_user_food_preference


def run_food_agent(user_id: int, request: str, constraints: dict | None = None):
    """Run the unified FoodAgent."""
    return FoodAgent(user_id).handle_request(request, constraints)


def run_restaurant_agent(user_id: int, constraints: dict, allow_web: bool = False):
    """Compatibility wrapper for nearby dining."""
    del allow_web
    return run_food_agent(user_id, "附近堂食", {**constraints, "mode": "restaurant"})


def run_canteen_agent(user_id: int, constraints: dict):
    """Compatibility wrapper for campus dining."""
    return run_food_agent(user_id, "校内食堂", {**constraints, "mode": "canteen"})


def save_food_preference(user_id: int, content: str) -> int:
    """Compatibility wrapper returning the created memory id."""
    return int(save_user_food_preference(user_id, content).get("memory_id") or 0)
