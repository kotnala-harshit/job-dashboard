import inspect
import unittest
from unittest.mock import patch

import scrape


class CurrentSourceTests(unittest.TestCase):
    def setUp(self):
        scrape.CONNECTOR_HEALTH.clear()

    def test_aon_current_source(self):
        source = inspect.getsource(scrape.scrape_aon)
        self.assertIn("jobs.aon.com/jobs", source)
        self.assertNotIn("aon.wd1.myworkdayjobs.com", source)
        self.assertNotIn("AonCareers", source)
        self.assertIn("zero vacancies not trusted", source)

    def test_aon_missing_browser_allows_validated_http_fallback(self):
        with patch.object(scrape, "HAS_PLAYWRIGHT", False):
            jobs = scrape.scrape_aon()
        health = scrape.CONNECTOR_HEALTH["Aon"]
        if jobs:
            self.assertTrue(health["live"])
            self.assertTrue(all("jobs.aon.com" in j["url"] for j in jobs))
        else:
            self.assertFalse(health["live"])
            self.assertIn("zero vacancies not trusted", health["note"])

    def test_zscaler_greenhouse_source(self):
        source = inspect.getsource(scrape.scrape_zscaler)
        self.assertIn(
            'scrape_greenhouse("zscaler")',
            source,
        )
        self.assertNotIn("sync_playwright", source)

    def test_zscaler_canonical_company(self):
        sample = [{
            "company": "zscaler",
            "ats": "greenhouse",
            "title": "Sales Account Executive, Public Sector",
            "location": "Remote - Ireland",
            "url": (
                "https://job-boards.greenhouse.io/"
                "zscaler/jobs/5193258007"
            ),
            "description_text": "Ireland",
        }]

        with patch.object(
            scrape,
            "scrape_greenhouse",
            return_value=sample,
        ):
            jobs = scrape.scrape_zscaler()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Zscaler")
        self.assertEqual(jobs[0]["ats"], "greenhouse")
        self.assertTrue(
            scrape.CONNECTOR_HEALTH["Zscaler"]["live"]
        )


if __name__ == "__main__":
    unittest.main()
