import hashlib
import hmac
import os
import shutil
from datetime import datetime
from pathlib import Path

from src.config import STORAGE_DIR, UPLOAD_DIR
from src.database import execute, fetch_all, fetch_one, get_connection, now_iso
from src.rag.document_assets import document_asset_dir


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash a local password with a random PBKDF2 salt."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        candidate = hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
        return hmac.compare_digest(candidate, digest_hex)
    except ValueError:
        return False


def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 3:
        return False, "用户名至少需要 3 个字符。"
    if len(password) < 6:
        return False, "密码至少需要 6 个字符。"
    if fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        return False, "用户名已存在。"
    execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, hash_password(password), datetime.now().isoformat(timespec="seconds")),
    )
    return True, "注册成功，请登录。"


def login_user(username: str, password: str) -> dict | None:
    row = fetch_one("SELECT * FROM users WHERE username = ?", (username.strip(),))
    if row and _verify_password(password, row["password_hash"]):
        return {
            "id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
        }
    return None


def is_admin(user_id: int) -> bool:
    """Return whether a local user may maintain shared library material."""
    row = fetch_one("SELECT is_admin FROM users WHERE id = ?", (user_id,))
    return bool(row and row["is_admin"])


def get_user_profile(user_id: int) -> dict | None:
    """Load current identity metadata so renamed/role-migrated accounts refresh in session."""
    row = fetch_one("SELECT id, username, is_admin, created_at FROM users WHERE id = ?", (user_id,))
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def set_default_model_config(user_id: int, provider: str, api_base: str, api_key: str, model_name: str) -> int:
    execute("UPDATE user_model_configs SET is_default = 0 WHERE user_id = ?", (user_id,))
    return execute(
        """
        INSERT INTO user_model_configs
        (user_id, provider, api_base, api_key, model_name, is_default, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (user_id, provider, api_base, api_key, model_name, now_iso()),
    )


def activate_model_config(user_id: int, config_id: int) -> bool:
    row = fetch_one("SELECT id FROM user_model_configs WHERE id = ? AND user_id = ?", (config_id, user_id))
    if not row:
        return False
    execute("UPDATE user_model_configs SET is_default = 0 WHERE user_id = ?", (user_id,))
    execute("UPDATE user_model_configs SET is_default = 1 WHERE id = ? AND user_id = ?", (config_id, user_id))
    return True


def delete_model_config(user_id: int, config_id: int) -> bool:
    row = fetch_one("SELECT id, is_default FROM user_model_configs WHERE id = ? AND user_id = ?", (config_id, user_id))
    if not row:
        return False
    was_default = bool(row["is_default"])
    execute("DELETE FROM user_model_configs WHERE id = ? AND user_id = ?", (config_id, user_id))
    if was_default:
        replacement = fetch_one(
            "SELECT id FROM user_model_configs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if replacement:
            execute(
                "UPDATE user_model_configs SET is_default = 1 WHERE id = ? AND user_id = ?",
                (replacement["id"], user_id),
            )
    return True


def get_default_model_config(user_id: int) -> dict | None:
    row = fetch_one(
        "SELECT * FROM user_model_configs WHERE user_id = ? AND is_default = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    return dict(row) if row else None


def list_model_configs(user_id: int) -> list[dict]:
    rows = fetch_one("SELECT COUNT(*) AS c FROM user_model_configs WHERE user_id = ?", (user_id,))
    if not rows or rows["c"] == 0:
        return []
    from src.database import fetch_all

    return [dict(r) for r in fetch_all("SELECT * FROM user_model_configs WHERE user_id = ? ORDER BY id DESC", (user_id,))]


def list_deletable_users(actor_user_id: int) -> list[dict]:
    """List non-admin accounts that an administrator may permanently remove."""
    if not is_admin(actor_user_id):
        return []
    rows = fetch_all(
        """
        SELECT id, username, created_at
        FROM users
        WHERE is_admin = 0 AND id != ?
        ORDER BY created_at DESC, id DESC
        """,
        (actor_user_id,),
    )
    return [dict(row) for row in rows]


def _remove_managed_tree(path: Path, root: Path) -> None:
    """Delete only generated user data that stays inside an approved storage root."""
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Refusing to delete unmanaged path: {path}") from exc
    if path.exists():
        shutil.rmtree(path)


def delete_personal_account(actor_user_id: int, target_user_id: int) -> tuple[bool, str]:
    """Permanently remove a normal account and all of its private persisted data."""
    if actor_user_id == target_user_id:
        return False, "管理员不能注销当前登录账户。"
    if not is_admin(actor_user_id):
        return False, "只有管理员可以注销其他账户。"

    with get_connection() as conn:
        target = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if not target:
            return False, "该账户已不存在。"
        if bool(target["is_admin"]):
            return False, "管理员账户不能在这里注销。"

        document_ids = [
            int(row["id"])
            for row in conn.execute("SELECT id FROM documents WHERE user_id = ?", (target_user_id,)).fetchall()
        ]
        if document_ids:
            marks = ",".join("?" for _ in document_ids)
            for table in ("document_jobs", "document_questions", "document_mindmaps", "document_highlights", "document_chunks"):
                conn.execute(f"DELETE FROM {table} WHERE document_id IN ({marks})", document_ids)

        conn.execute("DELETE FROM documents WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM todo_subtasks WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM todos WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM memory_items WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM agent_runs WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM library_folders WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM user_model_configs WHERE user_id = ?", (target_user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))

    for document_id in document_ids:
        _remove_managed_tree(document_asset_dir(document_id), STORAGE_DIR / "document_assets")
    _remove_managed_tree(UPLOAD_DIR / str(target_user_id), UPLOAD_DIR)
    return True, f"已永久注销账户 {target['username']}，并清理其个人数据。"
