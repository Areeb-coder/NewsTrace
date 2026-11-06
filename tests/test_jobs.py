"""Regression tests for the NewsTrace job store."""

import tempfile
import unittest
from pathlib import Path

from backend.jobs import JobStore, ProgressThrottle


class ProgressThrottleTests(unittest.TestCase):
    def test_stage_changes_and_completion_are_never_throttled(self):
        throttle = ProgressThrottle(min_interval_seconds=0.3)
        self.assertTrue(throttle.should_report("API discovery", 0, 7, now=10.0))
        self.assertFalse(throttle.should_report("API discovery", 1, 7, now=10.1))
        self.assertTrue(throttle.should_report("HTML discovery", 0, 18, now=10.12))
        self.assertTrue(throttle.should_report("HTML discovery", 18, 18, now=10.13))

    def test_repetitive_progress_resumes_after_interval(self):
        throttle = ProgressThrottle(min_interval_seconds=0.3)
        self.assertTrue(throttle.should_report("Article extraction", 0, 10, now=5.0))
        self.assertFalse(throttle.should_report("Article extraction", 1, 10, now=5.2))
        self.assertTrue(throttle.should_report("Article extraction", 2, 10, now=5.31))


class DiscoveryJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(str(Path(self.temp_dir.name) / "jobs.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_job_reports_real_stage_counts_and_result_payload(self):
        job = self.store.create_job("Example News", {"max_articles": 25})
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["outlet"], "Example News")

        self.store.update_progress(
            job["job_id"], "Article extraction", 7, 25,
            "Processed 7/25 · 6 article records retained · 1 failed",
        )
        running = self.store.get_job(job["job_id"])
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["stage"], "Article extraction")
        self.assertEqual(running["current"], 7)
        self.assertEqual(running["total"], 25)
        self.assertTrue(any(event["stage"] == "Article extraction" for event in running["events"]))

        articles = [{
            "title": "A source-linked headline",
            "author": "A Reporter",
            "section": "World",
            "url": "https://example.com/world/report",
        }]
        self.store.complete_job(
            job["job_id"],
            articles,
            {"urls_found": 25, "articles_scraped": 1, "article_failures": 24},
            ["Some publisher pages were unavailable."],
            partial=True,
        )

        result = self.store.get_results(job["job_id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["articles"][0]["title"], "A source-linked headline")
        self.assertEqual(result["stats"]["urls_found"], 25)
        self.assertEqual(len(result["warnings"]), 1)

    def test_restart_marks_queued_and_running_jobs_as_interrupted(self):
        queued = self.store.create_job("Queued Paper", {})
        running = self.store.create_job("Running Paper", {})
        self.store.update_progress(running["job_id"], "HTML discovery", 2, 18, "Visited 2/18 pages.")

        recovered = self.store.recover_interrupted_jobs()
        self.assertEqual(recovered, 2)
        self.assertEqual(self.store.get_job(queued["job_id"])["status"], "interrupted")
        interrupted = self.store.get_job(running["job_id"])
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertIn("restarted", interrupted["error"].lower())

    def test_archive_records_keep_their_investigation_provenance(self):
        job = self.store.create_job("The Example", {})
        self.store.complete_job(
            job["job_id"],
            [{"title": "One report", "url": "https://example.com/story"}],
            {"articles_scraped": 1},
        )
        records = self.store.all_articles()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["job_id"], job["job_id"])
        self.assertEqual(records[0]["outlet"], "The Example")
        self.assertEqual(records[0]["article_index"], 0)

    def test_unknown_job_returns_none(self):
        self.assertIsNone(self.store.get_job("not-a-real-job"))
        self.assertIsNone(self.store.get_results("not-a-real-job"))


if __name__ == "__main__":
    unittest.main()
