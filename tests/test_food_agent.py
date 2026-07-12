from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.food_agent import FoodAgent, selected_result
from src.agent.food_data_agent import refresh_food_database
from src.agent.food_models import FoodDataStore
from src.agent.food_tools import choose_canteen_food, choose_nearby_restaurant


def no_preferences(_user_id: int, _query: str, _limit: int) -> list[dict]:
    return []


class FoodAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = FoodDataStore(root / "foods.json", root / "meta.json")
        data = self.store.load()
        data["canteen_dishes"] = [
            {"id": "c1", "venue": "审核食堂", "floor": "一楼", "window": "甲窗口", "food_name": "清淡饭", "meal_times": ["午餐"], "tastes": ["清淡"], "category": "米饭", "price": 12, "weight": 1, "enabled": True, "origin": "manual", "locked": True},
            {"id": "c2", "venue": "审核食堂", "floor": "二楼", "window": "乙窗口", "food_name": "香菜辣面", "meal_times": ["午餐"], "tastes": ["辣"], "category": "面食", "price": 18, "weight": 1, "enabled": True, "origin": "manual", "locked": True},
            {"id": "c3", "venue": "审核食堂", "floor": "一楼", "window": "停用窗口", "food_name": "停用饭", "meal_times": ["午餐"], "tastes": [], "category": "米饭", "price": 10, "weight": 1, "enabled": False, "origin": "manual", "locked": True},
        ]
        data["restaurants"] = [
            {"id": "r1", "name": "审核餐厅甲", "area": "附近", "recommended_food": "面", "avg_price": 25, "distance_minutes": 8, "tastes": ["清淡"], "categories": ["面食"], "suitable_for": ["一人食", "两人"], "weight": 1, "enabled": True, "origin": "manual", "locked": True},
            {"id": "r2", "name": "审核餐厅乙", "area": "附近", "recommended_food": "饭", "avg_price": 60, "distance_minutes": 12, "tastes": [], "categories": ["米饭"], "suitable_for": ["聚餐"], "weight": 1, "enabled": True, "origin": "manual", "locked": True},
        ]
        data["takeaways"] = [
            {"id": "t1", "restaurant": "审核外卖店", "food_name": "套餐", "platforms": ["平台"], "avg_price": 20, "delivery_minutes": 30, "meal_times": ["午餐"], "tastes": [], "category": "米饭", "weight": 1, "enabled": True, "origin": "manual", "locked": True}
        ]
        self.store.save(data)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def agent(self) -> FoodAgent:
        return FoodAgent(1, store=self.store, intent_parser=lambda _text: {}, preference_reader=no_preferences, persist_runs=False)

    def test_canteen_intent_selects_canteen_tool(self) -> None:
        run = self.agent().handle_request("午饭在食堂吃")
        self.assertEqual(run.trace[-1]["tool"], "choose_canteen_food")

    def test_restaurant_intent_selects_restaurant_tool(self) -> None:
        run = self.agent().handle_request("两个人出去堂食")
        self.assertEqual(run.trace[-1]["tool"], "choose_nearby_restaurant")

    def test_school_nearby_request_does_not_wait_for_llm(self) -> None:
        def should_not_run(_text: str) -> dict:
            raise AssertionError("明确的学校附近请求不应调用 LLM")
        agent = FoodAgent(1, store=self.store, intent_parser=should_not_run, preference_reader=no_preferences, persist_runs=False)
        run = agent.handle_request("今晚我想和女朋友去学校附近吃饭，预算100")
        self.assertEqual(run.trace[-1]["tool"], "choose_nearby_restaurant")
        self.assertIn(run.trace[-1]["output"]["status"], {"selected", "no_match"})

    def test_takeaway_intent_selects_takeaway_tool(self) -> None:
        run = self.agent().handle_request("不想出门，点外卖")
        self.assertEqual(run.trace[-1]["tool"], "choose_takeaway")

    def test_budget_is_strict(self) -> None:
        result = choose_nearby_restaurant(user_id=1, budget_per_person=30, store=self.store, preference_reader=no_preferences)
        self.assertEqual(result["record_id"], "r1")

    def test_avoid_keyword_is_strict(self) -> None:
        result = choose_canteen_food(user_id=1, meal_time="午餐", avoid_keywords=["香菜"], store=self.store, preference_reader=no_preferences)
        self.assertEqual(result["record_id"], "c1")

    def test_disabled_record_is_never_selected(self) -> None:
        result = choose_canteen_food(user_id=1, budget=10, store=self.store, preference_reader=no_preferences)
        self.assertFalse(result["success"])

    def test_change_excludes_previous_id(self) -> None:
        first = self.agent().handle_request("午饭在食堂吃")
        first_id = selected_result(first)["record_id"]
        second = self.agent().handle_request("换一个", {"last_mode": "canteen", "last_recommendation_id": first_id, "excluded_ids": [first_id]})
        self.assertNotEqual(selected_result(second)["record_id"], first_id)

    def test_no_match_does_not_fabricate(self) -> None:
        result = choose_canteen_food(user_id=1, budget=1, store=self.store, preference_reader=no_preferences)
        self.assertEqual(result["status"], "no_match")
        self.assertNotIn("record_id", result)

    def test_weekly_update_writes_pending_only(self) -> None:
        before = self.store.load()
        refresh_food_database(1, force=True, store=self.store, evidence=[{"title": "公开餐饮信息", "url": "https://example.test/food", "snippet": "餐厅线索"}])
        after = self.store.load()
        self.assertEqual(after["canteen_dishes"], before["canteen_dishes"])
        self.assertEqual(after["restaurants"], before["restaurants"])
        self.assertEqual(len(after["pending_review"]), 1)

    def test_weekly_update_preserves_manual_locked(self) -> None:
        refresh_food_database(1, force=True, store=self.store, evidence=[{"title": "另一个线索", "url": "https://example.test/new", "snippet": "新店"}])
        self.assertTrue(self.store.load()["restaurants"][0]["locked"])

    def test_legacy_json_migrates(self) -> None:
        legacy = FoodDataStore(Path(self.temp.name) / "legacy.json", Path(self.temp.name) / "legacy_meta.json")
        legacy.path.write_text('{"schema_version":1,"venues":[{"name":"旧食堂","origin":"manual","locked":true}],"dishes":[],"restaurants":[]}', encoding="utf-8")
        migrated = legacy.load()
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["pending_review"][0]["name"], "旧食堂")
        self.assertTrue(migrated["pending_review"][0]["locked"])

    def test_quick_form_works_without_llm(self) -> None:
        def unavailable(_text: str) -> dict:
            raise RuntimeError("LLM unavailable")
        agent = FoodAgent(1, store=self.store, intent_parser=unavailable, preference_reader=no_preferences, persist_runs=False)
        run = agent.handle_request("快捷筛选", {"mode": "canteen", "meal_time": "午餐"})
        self.assertIsNotNone(selected_result(run))


if __name__ == "__main__":
    unittest.main()
