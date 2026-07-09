from pathlib import Path
from uuid import uuid4

from src.config import UPLOAD_DIR


def safe_upload_path(user_id: int, subdir: str, filename: str) -> Path:
    suffix = Path(filename).suffix
    stem = Path(filename).stem[:80] or "upload"
    target_dir = UPLOAD_DIR / str(user_id) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{stem}_{uuid4().hex[:8]}{suffix}"
