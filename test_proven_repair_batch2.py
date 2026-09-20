import unittest
from unittest.mock import Mock, patch

import audit_proven_companies as audit
import scrape


class ProvenRepairBatch2Tests(unittest.TestCase):

    def test_greenhouse_gh_jid_is_identity(self):
        a = {
            "company": "Stripe",
            "title": "Engineer",
            "location": "Dublin, Ireland",
            "url": "https://stripe.com/jobs/search?gh_jid=111&utm_source=x",
        }
        b = {
            "company": "Stripe",
            "title": "Engineer",
            "location": "Dublin, Ireland",
            "url": "https://stripe.com/jobs/search?gh_jid=222&utm_source=x",
        }

        self.assertNotEqual(audit.identity(a), audit.identity(b))

    def test_candidate_manager_jid_is_identity(self):
        a = {
            "company": "TCS",
            "title": "Engineer",
            "location": "Dublin, Ireland",
            "url": (
                "https://www.candidatemanager.net/cm/p/"
                "pJobDetails.aspx?jid=111&mid=x"
            ),
        }
        b = {
            "company": "TCS",
            "title": "Engineer",
            "location": "Dublin, Ireland",
            "url": (
                "https://www.candidatemanager.net/cm/p/"
                "pJobDetails.aspx?jid=222&mid=x"
            ),
        }

        self.assertNotEqual(audit.identity(a), audit.identity(b))

    def test_tracking_params_do_not_create_identity(self):
        a = {
            "company": "Example",
            "title": "Engineer",
            "location": "Dublin",
            "url": "https://example.com/jobs/123?utm_source=a",
        }
        b = {
            "company": "Example",
            "title": "Engineer",
            "location": "Dublin",
            "url": "https://example.com/jobs/123?utm_source=b",
        }

        self.assertEqual(audit.identity(a), audit.identity(b))

    def test_navigation_titles_include_revenue_language_labels(self):
        for title in (
            "Irish",
            "Gaeilge",
            "Béarla",
            "English",
            "State Boards",
            "Boird Stáit",
        ):
            self.assertTrue(scrape._is_navigation_job_title(title))


if __name__ == "__main__":
    unittest.main()
