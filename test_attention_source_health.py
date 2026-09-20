import inspect
import unittest
from unittest.mock import patch, MagicMock
import scrape


class AttentionSourceHealthTests(unittest.TestCase):

    def setUp(self):
        scrape.CONNECTOR_HEALTH.clear()

    def test_aon_failed_workday_probe_is_not_healthy_zero(self):
        with patch.object(scrape, "_workday_session", return_value=MagicMock()), \
             patch.object(scrape, "_workday_post", return_value=None):
            jobs = scrape.scrape_aon()

        self.assertEqual(jobs, [])
        health = scrape.CONNECTOR_HEALTH.get("Aon")
        self.assertIsNotNone(health)
        self.assertFalse(health["live"])

    def test_aon_does_not_use_stale_seed_ids(self):
        source = inspect.getsource(scrape.scrape_aon)
        for stale_id in (
            "93353", "99173", "99565", "102116", "103488",
            "105297", "94666", "100234", "104230", "99495",
        ):
            self.assertNotIn(stale_id, source)

    def test_dps_uses_current_arcadis_source(self):
        source = inspect.getsource(scrape.scrape_dps_group)
        self.assertIn("scrape_arcadis_ireland", source)
        self.assertNotIn("dpsgroupglobal.com", source)

    def test_tiktok_marks_playwright_absence_unhealthy(self):
        with patch.object(scrape, "HAS_PLAYWRIGHT", False):
            jobs = scrape.scrape_tiktok()

        self.assertEqual(jobs, [])
        self.assertFalse(scrape.CONNECTOR_HEALTH["TikTok"]["live"])

    def test_agilent_has_explicit_health_reporting(self):
        source = inspect.getsource(scrape.scrape_agilent)
        self.assertIn("_mark_connector_health", source)


if __name__ == "__main__":
    unittest.main()


class IsolatedHealthSemanticsTests(unittest.TestCase):

    def test_empty_unreported_connector_is_not_auto_healthy(self):
        source = inspect.getsource(scrape._parallel_collect_isolated)
        self.assertIn(
            'company not in payload["connector_health"] and found',
            source,
        )

    def test_nonempty_unreported_connector_can_prove_health(self):
        source = inspect.getsource(scrape._parallel_collect_isolated)
        self.assertIn(
            'f"Official connector returned {len(found)} jobs"',
            source,
        )
