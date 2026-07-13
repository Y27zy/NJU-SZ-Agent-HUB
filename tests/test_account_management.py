import tempfile
import unittest
from pathlib import Path

from src import config
from src.auth.auth_service import (
    delete_personal_account,
    hash_password,
    list_deletable_users,
)
from src.database import execute, fetch_one, init_db


class AccountManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_database_url = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{Path(self.temp.name) / 'accounts.db'}"
        init_db()
        self.admin_id = execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("test_admin", hash_password("password"), "2026-01-01T00:00:00"),
        )
        self.user_id = execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("student_one", hash_password("password"), "2026-01-01T00:00:00"),
        )

    def tearDown(self) -> None:
        config.DATABASE_URL = self.original_database_url
        self.temp.cleanup()

    def test_admin_can_list_and_delete_a_personal_account(self) -> None:
        users = list_deletable_users(self.admin_id)
        self.assertEqual([item["username"] for item in users], ["student_one"])
        success, _ = delete_personal_account(self.admin_id, self.user_id)
        self.assertTrue(success)
        self.assertIsNone(fetch_one("SELECT id FROM users WHERE id = ?", (self.user_id,)))

    def test_cannot_delete_an_administrator_or_self(self) -> None:
        success, _ = delete_personal_account(self.admin_id, self.admin_id)
        self.assertFalse(success)
        other_admin = execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
            ("other_admin", hash_password("password"), "2026-01-01T00:00:00"),
        )
        success, _ = delete_personal_account(self.admin_id, other_admin)
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
