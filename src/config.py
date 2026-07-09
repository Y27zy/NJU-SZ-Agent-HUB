import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"

load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "NJU-SZ Agent Hub")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/app.db")
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "mock")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "mock-agent")
USE_SYSTEM_PROXY = os.getenv("USE_SYSTEM_PROXY", "false").lower() in {"1", "true", "yes", "on"}


def get_db_path() -> Path:
    if DATABASE_URL.startswith("sqlite:///"):
        raw_path = DATABASE_URL.replace("sqlite:///", "", 1)
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = BASE_DIR / db_path
        return db_path
    return STORAGE_DIR / "app.db"


def ensure_runtime_dirs() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
