import unittest
from unittest.mock import Mock, patch

import scrape


GOOD_HTML = """
<html>
<body>
<section>
<h2>Current competitions</h2>
<p>
Revenue invites applications for the following recruitment campaign.
Closing date: 30 September 2026.
</p>
<a href="/careers/competition-123.aspx">
Graduate Tax Specialist
</a>
</section>
</body>
</html>
"""

BAD_HTML = """
<html>
<body>
<a href="/corporate/information-about-revenue/careers/index.aspx">
Overview
</a>
<a href="/corporate/information-about-revenue/careers/candidate-data-protection-statement.aspx">
Candidate data protection statement
</a>
<a href="/corporate/information-about-revenue/careers/assignment-data-protection-statement.aspx">
Assignment data protection statement
</a>
<a href="/tax-education/index.aspx">
Tax education
</a>
<a href="/corporate/information-about-revenue/careers/career-opportunities.aspx">
Please rate how useful this page was to you
</a>
<a href="/corporate/information-about-revenue/careers/career-opportunities.aspx">
Back to top
</a>
<a href="/corporate/information-about-revenue/careers/career-opportunities.aspx">
Close
</a>
</body>
</html>
"""


class RevenueQualityTests(unittest.TestCase):

    def run_collector(self, body):
        response = Mock()
        response.status_code = 200
        response.text = body

        session = Mock()
        session.get.return_value = response

        with patch.object(scrape, "_session", return_value=session):
            scrape.CONNECTOR_HEALTH.clear()
            jobs = scrape.scrape_revenue_ie()

        return jobs, scrape.CONNECTOR_HEALTH.get("Revenue")

    def test_navigation_page_produces_no_fake_jobs(self):
        jobs, health = self.run_collector(BAD_HTML)

        self.assertEqual(jobs, [])
        self.assertIsNotNone(health)
        self.assertTrue(health["live"])

    def test_real_competition_survives(self):
        jobs, health = self.run_collector(GOOD_HTML)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            jobs[0]["title"],
            "Graduate Tax Specialist",
        )
        self.assertTrue(health["live"])

    def test_known_revenue_navigation_titles_are_generic(self):
        for title in (
            "Close",
            "Overview",
            "Back to top",
            "Candidate data protection statement",
            "Assignment data protection statement",
            "Tax education",
            "Irish",
            "Gaeilge",
            "Béarla",
        ):
            self.assertFalse(
                scrape.is_real_job_title(title),
                title,
            )


if __name__ == "__main__":
    unittest.main()
