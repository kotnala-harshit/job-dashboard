import unittest

from audit_proven_companies import inspect_job, identity, live_overlay


class ProvenAuditTests(unittest.TestCase):

    def test_good_roi_job(self):
        job = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin, Ireland",
            "url": "https://example.com/jobs/123",
        }
        self.assertEqual(inspect_job(job), [])

    def test_ni_leak(self):
        job = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Belfast, Northern Ireland",
            "url": "https://example.com/jobs/123",
        }
        self.assertIn(
            "northern_ireland_leak",
            inspect_job(job),
        )

    def test_navigation_title(self):
        job = {
            "company": "Example",
            "title": "Béarla",
            "location": "Dublin, Ireland",
            "url": "https://example.com/jobs/123",
        }
        self.assertIn(
            "navigation_title",
            inspect_job(job),
        )

    def test_live_overlay_returns_current_repaired_sources(self):
        jobs, health = live_overlay(("Aon", "HCLTech"))
        by_company = {j.get("company") for j in jobs}
        self.assertNotIn("Aon", by_company)
        self.assertNotIn("HCLTech", by_company)
        self.assertFalse(health["Aon"]["live"])
        self.assertFalse(health["HCLTech"]["live"])

    def test_url_identity_ignores_tracking(self):
        a = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin",
            "url": "https://example.com/jobs/123?ref=a",
        }
        b = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin",
            "url": "https://example.com/jobs/123?ref=b",
        }
        self.assertEqual(identity(a), identity(b))


if __name__ == "__main__":
    unittest.main()
