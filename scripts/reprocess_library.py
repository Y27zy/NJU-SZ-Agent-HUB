import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auth.auth_service import get_default_model_config
from src.database import fetch_all, fetch_one, init_db
from src.rag.document_processor import reprocess_document
from src.rag.simple_vector_store import get_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild library documents with the user's current model.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--document-id", type=int, action="append", dest="document_ids")
    args = parser.parse_args()

    init_db()
    user = fetch_one("SELECT id FROM users WHERE username = ?", (args.username,))
    if not user:
        raise SystemExit(f"Unknown user: {args.username}")
    user_id = int(user["id"])
    model = get_default_model_config(user_id)
    if not model:
        raise SystemExit("The user has no active model configuration.")
    print(f"Model: {model['provider']} / {model['model_name']}")

    if args.document_ids:
        document_ids = args.document_ids
    else:
        document_ids = [
            int(row["id"])
            for row in fetch_all("SELECT id FROM documents WHERE user_id = ? ORDER BY id", (user_id,))
        ]

    for document_id in document_ids:
        document = get_document(user_id, document_id)
        if not document:
            print(f"Skip missing document {document_id}")
            continue
        print(f"\n[{document_id}] {document['title']}")

        def progress(current: int, total: int, message: str) -> None:
            print(f"  {current}/{total} {message}", flush=True)

        reprocess_document(user_id, document_id, progress=progress)
        updated = get_document(user_id, document_id)
        print(
            f"  done: pages={updated['page_count']}, markdown={len(updated['processed_markdown'] or '')}, "
            f"structured={bool(updated.get('structure_json'))}"
        )


if __name__ == "__main__":
    main()
