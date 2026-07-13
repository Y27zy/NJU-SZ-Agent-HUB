import tempfile
import unittest
from pathlib import Path

from src import config
from src.database import init_db
from src.memory.memory_service import retrieve_user_memory, update_user_memory


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_database_url = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{Path(self.temp.name) / 'memory.db'}"
        init_db()
        self.user_id = 77

    def tearDown(self) -> None:
        config.DATABASE_URL = self.original_database_url
        self.temp.cleanup()

    def test_query_prefers_relevant_memory(self) -> None:
        update_user_memory(self.user_id, "我喜欢用条理清晰的方式解释机器学习概念。", "user", 3)
        update_user_memory(self.user_id, "饮食偏好：我不吃辣。", "food_preference", 5)
        memories = retrieve_user_memory(self.user_id, "机器学习概念的解释", limit=2)
        self.assertIn("机器学习", memories[0]["content"])

    def test_food_conflict_updates_one_preference(self) -> None:
        first_id = update_user_memory(self.user_id, "饮食偏好：我不吃辣。", "food_preference", 4)
        second_id = update_user_memory(self.user_id, "饮食偏好：我喜欢辣。", "food_preference", 4)
        self.assertEqual(first_id, second_id)
        memories = retrieve_user_memory(self.user_id, "饮食偏好", limit=10)
        spicy = [item for item in memories if item.get("memory_key") == "food:spicy"]
        self.assertEqual(len(spicy), 1)
        self.assertIn("喜欢辣", spicy[0]["content"])

    def test_exact_memory_is_not_duplicated(self) -> None:
        first_id = update_user_memory(self.user_id, "我偏好先给结论再给推导。", "user", 3)
        second_id = update_user_memory(self.user_id, "我偏好先给结论再给推导。", "user", 3)
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(retrieve_user_memory(self.user_id, "推导", limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
