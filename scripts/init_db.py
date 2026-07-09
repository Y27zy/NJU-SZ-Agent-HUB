from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database import init_db
from src.config import ensure_runtime_dirs, get_db_path


if __name__ == "__main__":
    ensure_runtime_dirs()
    init_db()
    print(f"Database initialized at: {get_db_path()}")
