from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.food_data_agent import FOOD_DATA_PATH, FOOD_META_PATH, refresh_food_database  # noqa: E402
from src.database import fetch_one, init_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="检索南京大学苏州校区饮食线索并写入待审核区。")
    parser.add_argument("--username", required=True, help="用于记录刷新任务的本地用户名")
    parser.add_argument("--force", action="store_true", help="忽略七天刷新间隔")
    args = parser.parse_args()
    init_db()
    user = fetch_one("SELECT id FROM users WHERE username = ?", (args.username,))
    if not user:
        raise SystemExit(f"用户不存在：{args.username}")
    data = refresh_food_database(int(user["id"]), force=args.force)
    print(f"更新完成：{FOOD_DATA_PATH}")
    print(f"更新状态：{FOOD_META_PATH}")
    print(
        f"正式食堂菜品 {len(data['canteen_dishes'])}，附近餐厅 {len(data['restaurants'])}，"
        f"外卖 {len(data['takeaways'])}，待审核 {len(data['pending_review'])}"
    )


if __name__ == "__main__":
    main()
