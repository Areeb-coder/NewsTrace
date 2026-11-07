"""API-level discovery job lifecycle integration tests.

The scraper itself is covered by discovery/parser tests; this module verifies
that FastAPI creates a background job, stores its progress/results, and returns
them through the status/result functions without requiring live publisher calls.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from starlette.requests import Request

import backend.main as api
from backend.jobs import JobStore


def fake_request(client_ip="198.51.100.25"):
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/discovery/start",
        "raw_path": b"/api/discovery/start",
        "query_string": b"",
        "headers": [],
        "client": (client_ip, 54321),
        "server": ("testserver", 80),
    })


class DiscoveryJobApiLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_runs_background_task_and_persists_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            test_store = JobStore(str(Path(temporary) / "api-jobs.sqlite3"))
            api.app.state.tasks = {}
            api.app.state.job_semaphore = asyncio.Semaphore(1)
            api._start_attempts.clear()

            async def fake_investigation(
                url,
                outlet_name,
                max_articles,
                enable_profiles=False,
                enable_google=False,
                discovery_url=None,
                progress_callback=None,
            ):
                if progress_callback:
                    progress_callback(
                        "Article extraction", 2, 2,
                        "Processed 2/2 article pages · 2 records retained · 0 failed",
                    )
                return (
                    pd.DataFrame([
                        {
                            "title": "A source-linked headline",
                            "author": "A Reporter",
                            "section": "World",
                            "date": "2026-11-06",
                            "url": "https://example.com/world/story",
                        },
                        {
                            "title": "A second source-linked headline",
                            "author": "Another Reporter",
                            "section": "Business",
                            "date": "2026-11-05",
                            "url": "https://example.com/business/story",
                        },
                    ]),
                    {
                        "urls_found": 2,
                        "articles_scraped": 2,
                        "article_failures": 0,
                        "unique_authors": 2,
                    },
                    [],
                )

            with (
                patch.object(api, "store", test_store),
                patch.object(api, "resolve_outlet", return_value=("https://example.com", "example.com")),
                patch.object(api, "run_investigation", side_effect=fake_investigation),
                patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_KEY": ""}),
            ):
                response = await api.start_discovery(
                    api.DiscoveryRequest(
                        outlet="https://example.com/world",
                        max_articles=50,
                        enable_profiles=False,
                        enable_google=False,
                    ),
                    fake_request(),
                )
                job_id = response["job_id"]
                self.assertEqual(response["status"], "queued")
                self.assertTrue(job_id)

                tasks = list(api.app.state.tasks.values())
                self.assertEqual(len(tasks), 1)
                await asyncio.gather(*tasks)

                current = await api.discovery_status(job_id)
                self.assertEqual(current["status"], "complete")
                self.assertEqual(current["stage"], "Complete")
                self.assertEqual(current["stats"]["articles_scraped"], 2)
                self.assertTrue(
                    any(event["stage"] == "Article extraction" for event in current["events"])
                )

                results = await api.discovery_results(job_id, limit=50, offset=0)
                self.assertEqual(results["total"], 2)
                self.assertEqual(results["articles"][0]["title"], "A source-linked headline")
                self.assertEqual(results["articles"][0]["outlet"], "example.com")
                self.assertEqual(results["articles"][0]["job_id"], job_id)

    async def test_unresolved_publication_name_becomes_terminal_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            test_store = JobStore(str(Path(temporary) / "resolver-failure.sqlite3"))
            api.app.state.tasks = {}
            api.app.state.job_semaphore = asyncio.Semaphore(1)
            api._start_attempts.clear()

            with (
                patch.object(api, "store", test_store),
                patch.object(api, "resolve_outlet", return_value=(None, None)),
            ):
                response = await api.start_discovery(
                    api.DiscoveryRequest(outlet="Unknown Local Gazette", max_articles=20),
                    fake_request("198.51.100.26"),
                )
                tasks = list(api.app.state.tasks.values())
                await asyncio.gather(*tasks)

                job = await api.discovery_status(response["job_id"])
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["stage"], "Failed")
                self.assertIn("full website URL", job["error"])
                self.assertTrue(any(
                    event["stage"] == "Failed" for event in job["events"]
                ))

    async def test_unknown_job_returns_not_found(self):
        with tempfile.TemporaryDirectory() as temporary:
            test_store = JobStore(str(Path(temporary) / "empty.sqlite3"))
            with patch.object(api, "store", test_store):
                with self.assertRaises(api.HTTPException) as raised:
                    await api.discovery_status("missing")
                self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
