import inspect
import unittest
from unittest.mock import patch

import scrape


class CleanupFourTests(unittest.TestCase):
    def setUp(self):
        scrape.CONNECTOR_HEALTH.clear()

    def test_hcltech_has_explicit_health_reporting(self):
        source = inspect.getsource(scrape.scrape_hcltech)
        self.assertIn("_mark_connector_health", source)
        self.assertIn("Official HCLTech Ireland careers completed", source)

    def test_jacobs_title_location_has_precedence(self):
        source = inspect.getsource(scrape.scrape_jacobs)
        self.assertIn("title_cities", source)
        self.assertIn("if not title_cities:", source)
        self.assertIn('" / ".join(title_cities)', source)
        self.assertIn("_mark_connector_health", source)

    def test_musgrave_uses_canonical_company_name(self):
        source = inspect.getsource(scrape.scrape_musgrave)
        self.assertIn(
            'company = "Musgrave Group (SuperValu / Centra)"',
            source,
        )
        self.assertIn("Dungiven", source)
        self.assertIn("Northern Ireland", source)
        self.assertIn("_mark_connector_health", source)

    def test_tiktok_has_description_contamination_guard(self):
        source = inspect.getsource(scrape.scrape_tiktok)
        self.assertIn("title_tokens", source)
        self.assertIn('description = ""', source)

    def test_four_playwright_absence_reports_unhealthy(self):
        for company, fn in (
            ("HCLTech", scrape.scrape_hcltech),
            ("Jacobs", scrape.scrape_jacobs),
            (
                "Musgrave Group (SuperValu / Centra)",
                scrape.scrape_musgrave,
            ),
            ("TikTok", scrape.scrape_tiktok),
        ):
            scrape.CONNECTOR_HEALTH.clear()

            with patch.object(scrape, "HAS_PLAYWRIGHT", False):
                jobs = fn()

            self.assertIn(company, scrape.CONNECTOR_HEALTH)
            health = scrape.CONNECTOR_HEALTH[company]
            if company == "HCLTech" and jobs:
                self.assertTrue(health["live"])
                self.assertTrue(all("careers.hcltech.com" in j["url"] for j in jobs))
            else:
                self.assertEqual(jobs, [])
                self.assertFalse(health["live"])


if __name__ == "__main__":
    unittest.main()



class CleanupFourFalseZeroTests(unittest.TestCase):
    def test_jacobs_zero_dom_is_not_declared_healthy(self):
        source = inspect.getsource(scrape.scrape_jacobs)
        self.assertIn("if discovered:", source)
        self.assertIn("zero vacancies not trusted", source)
        self.assertIn("previous_job_links", source)

    def test_tiktok_does_not_trust_full_body_as_description(self):
        source = inspect.getsource(scrape.scrape_tiktok)
        self.assertIn('description = ""', source)
        self.assertIn('"main"', source)
        self.assertIn('"article"', source)
        self.assertIn(
            "known global LifeAtTikTok shell",
            source,
        )

class CleanupFourFinalSafetyTests(unittest.TestCase):
    def test_hcltech_does_not_trust_empty_render(self):
        source = inspect.getsource(scrape.scrape_hcltech)
        self.assertIn("if discovered:", source)
        self.assertIn("zero vacancies not trusted", source)

    def test_musgrave_rejects_known_ni_localities(self):
        source = inspect.getsource(scrape.scrape_musgrave)
        for locality in (
            "Downpatrick",
            "Moira",
            "Lurgan",
            "Cookstown",
        ):
            self.assertIn(locality, source)
