"""Tests for selecting a durable production job store or local SQLite fallback."""

import os
import unittest
from unittest.mock import patch

from backend.jobs import JobStore, create_job_store


class JobStoreSelectionTests(unittest.TestCase):
    def test_uses_supabase_when_project_url_and_service_role_key_are_configured(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SERVICE_ROLE_KEY": "server-only-test-key",
                    "NEWSTRACE_REQUIRE_DURABLE_STORE": "true",
                },
            ),
            patch("backend.jobs.SupabaseJobStore") as supabase_store,
        ):
            supabase_store.return_value = object()
            selected = create_job_store()

        self.assertIs(selected, supabase_store.return_value)
        supabase_store.assert_called_once_with(
            "https://example.supabase.co",
            "server-only-test-key",
        )

    def test_local_development_falls_back_to_sqlite(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "",
                "SUPABASE_SERVICE_ROLE_KEY": "",
                "NEWSTRACE_REQUIRE_DURABLE_STORE": "false",
                "NEWSTRACE_DB_PATH": ":memory:",
            },
        ):
            selected = create_job_store()

        self.assertIsInstance(selected, JobStore)
        self.assertEqual(selected.backend_name, "sqlite")
        self.assertFalse(selected.is_durable)

    def test_production_can_require_durable_store(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "",
                "SUPABASE_SERVICE_ROLE_KEY": "",
                "NEWSTRACE_REQUIRE_DURABLE_STORE": "true",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "Durable storage is required"):
                create_job_store()


if __name__ == "__main__":
    unittest.main()
