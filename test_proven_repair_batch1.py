import unittest

import audit_proven_companies as audit
import scrape


class ProvenRepairBatch1Tests(unittest.TestCase):

    def test_dublin_belfast_multilocation_is_valid_roi(self):
        job = {
            "company": "Example",
            "title": "Manager - Dublin / Belfast",
            "location": "Dublin, Ireland",
            "url": "https://example.com/jobs/1",
        }

        self.assertNotIn(
            "northern_ireland_leak",
            audit.inspect_job(job),
        )

    def test_actual_belfast_location_is_rejected(self):
        job = {
            "company": "Example",
            "title": "Manager",
            "location": "Belfast, Northern Ireland",
            "url": "https://example.com/jobs/1",
        }

        self.assertIn(
            "northern_ireland_leak",
            audit.inspect_job(job),
        )

    def test_navigation_titles_are_blocked(self):
        for title in (
            "State Boards",
            "Boird Stáit",
            "Irish",
            "Gaeilge",
            "Béarla",
        ):
            self.assertTrue(
                scrape._is_navigation_job_title(title),
                title,
            )

    def test_generic_ats_query_job_ids_are_distinct(self):
        a = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin",
            "url": (
                "https://example.com/pjobdetails.aspx?"
                "jobid=123&utm_source=x"
            ),
        }

        b = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin",
            "url": (
                "https://example.com/pjobdetails.aspx?"
                "jobid=456&utm_source=x"
            ),
        }

        self.assertNotEqual(
            audit.identity(a),
            audit.identity(b),
        )

    def test_distinct_generic_ats_jobs_are_not_duplicates(self):
        a = {
            "company": "Example",
            "title": "Data Analyst",
            "location": "Dublin",
            "url": "https://example.com/cm/p/pjobdetails.aspx",
        }

        b = {
            "company": "Example",
            "title": "Data Engineer",
            "location": "Dublin",
            "url": "https://example.com/cm/p/pjobdetails.aspx",
        }

        self.assertNotEqual(
            audit.identity(a),
            audit.identity(b),
        )


if __name__ == "__main__":
    unittest.main()
