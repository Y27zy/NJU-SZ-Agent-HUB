import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src import database
from src.agent import document_jobs
from src.agent.document_processing_agent import DocumentProcessingAgent
from src.llm.providers import LLMProviderError


class DocumentJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "jobs.db"
        self.db_patch = patch("src.database.get_db_path", return_value=self.db_path)
        self.db_patch.start()
        database.init_db()
        self.user_id = database.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
            ("worker-test", "hash", database.now_iso()),
        )
        self.document_id = database.execute(
            """
            INSERT INTO documents
            (user_id, doc_type, title, file_path, processing_status, created_at, updated_at)
            VALUES (?, 'course', 'test', ?, 'processing', ?, ?)
            """,
            (self.user_id, str(Path(self.tempdir.name) / "test.pdf"), database.now_iso(), database.now_iso()),
        )
        self.worker_patch = patch("src.agent.document_jobs.ensure_document_job_worker")
        self.worker_patch.start()

    def tearDown(self) -> None:
        self.worker_patch.stop()
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_duplicate_clicks_return_one_active_job(self) -> None:
        first = document_jobs.enqueue_document_job(self.user_id, self.document_id)
        second = document_jobs.enqueue_document_job(self.user_id, self.document_id)

        self.assertEqual(first, second)
        self.assertEqual(len(document_jobs.list_document_jobs(self.user_id, active_only=True)), 1)

    def test_enqueue_preserves_failure_marker_needed_for_cache_resume(self) -> None:
        database.execute(
            "UPDATE documents SET processing_status = 'error', processing_error = 'timeout' WHERE id = ?",
            (self.document_id,),
        )

        document_jobs.enqueue_document_job(self.user_id, self.document_id)

        document = database.fetch_one(
            "SELECT processing_status, processing_error FROM documents WHERE id = ?", (self.document_id,)
        )
        self.assertEqual(document["processing_status"], "processing")
        self.assertEqual(document["processing_error"], "timeout")

    def test_concurrent_duplicate_clicks_are_atomically_deduplicated(self) -> None:
        import threading

        job_ids = []
        threads = [
            threading.Thread(
                target=lambda: job_ids.append(document_jobs.enqueue_document_job(self.user_id, self.document_id))
            )
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(set(job_ids)), 1)
        self.assertEqual(len(document_jobs.list_document_jobs(self.user_id, active_only=True)), 1)

    def test_cancelled_queued_job_allows_a_new_job(self) -> None:
        first = document_jobs.enqueue_document_job(self.user_id, self.document_id)
        self.assertTrue(document_jobs.cancel_document_job(first, self.user_id))
        self.assertEqual(document_jobs.get_document_job(first, self.user_id)["status"], "cancelled")
        document = database.fetch_one("SELECT processing_status FROM documents WHERE id = ?", (self.document_id,))
        self.assertEqual(document["processing_status"], "error")

        second = document_jobs.enqueue_document_job(self.user_id, self.document_id)
        self.assertNotEqual(first, second)

    def test_stale_running_job_is_requeued(self) -> None:
        job_id = document_jobs.enqueue_document_job(self.user_id, self.document_id)
        stale = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
        database.execute(
            "UPDATE document_jobs SET status = 'running', heartbeat_at = ?, updated_at = ? WHERE id = ?",
            (stale, stale, job_id),
        )

        document_jobs._recover_stale_jobs()

        self.assertEqual(document_jobs.get_document_job(job_id, self.user_id)["status"], "queued")

    @patch("src.agent.document_jobs.reprocess_document")
    def test_worker_completes_and_persists_progress(self, process) -> None:
        def run(user_id, document_id, progress, cancel_check):
            self.assertFalse(cancel_check())
            progress(2, 7, "chapter 2")

        process.side_effect = run
        job_id = document_jobs.enqueue_document_job(self.user_id, self.document_id)

        document_jobs._run_job(job_id)

        job = document_jobs.get_document_job(job_id, self.user_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual((job["progress_current"], job["progress_total"]), (2, 7))

    @patch("src.agent.document_jobs.reprocess_document")
    def test_transient_failure_waits_for_automatic_retry(self, process) -> None:
        process.side_effect = LLMProviderError("模型请求超时")
        job_id = document_jobs.enqueue_document_job(self.user_id, self.document_id)

        document_jobs._run_job(job_id)

        job = document_jobs.get_document_job(job_id, self.user_id)
        self.assertEqual(job["status"], "retry_wait")
        self.assertEqual(job["attempt_count"], 1)
        self.assertIn("自动继续", job["progress_message"])
        document = database.fetch_one("SELECT processing_status FROM documents WHERE id = ?", (self.document_id,))
        self.assertEqual(document["processing_status"], "processing")

    @patch("src.agent.document_jobs.reprocess_document")
    def test_configuration_failure_pauses_job(self, process) -> None:
        process.side_effect = LLMProviderError("模型配置不完整")
        job_id = document_jobs.enqueue_document_job(self.user_id, self.document_id)

        document_jobs._run_job(job_id)

        job = document_jobs.get_document_job(job_id, self.user_id)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempt_count"], 1)

    def test_retry_backoff_is_bounded(self) -> None:
        self.assertEqual(document_jobs._retry_delay(1), 5)
        self.assertEqual(document_jobs._retry_delay(2), 10)
        self.assertEqual(document_jobs._retry_delay(20), 300)


class CacheWriteTests(unittest.TestCase):
    def test_cache_write_uses_unique_atomic_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(b"pdf")
            agent = DocumentProcessingAgent.__new__(DocumentProcessingAgent)
            agent.model_config = {"model_name": "test-model"}

            import threading

            threads = [
                threading.Thread(target=agent._save_cache, args=(source, {"value": index}))
                for index in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            cache_path = agent._cache_path(source)
            self.assertTrue(cache_path.exists())
            self.assertFalse(list(Path(directory).glob("*.tmp")))
            import json

            self.assertIn("value", json.loads(cache_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
