import json
import unittest

import scrape


class ProfileAlignmentTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open("profile.json", encoding="utf-8") as f:
            cls.profile = json.load(f)

    def match(self, title, description, location="Dublin, Ireland"):
        return scrape.candidate_match(
            {
                "title": title,
                "location": location,
                "country": "Ireland",
            },
            description,
            self.profile,
        )

    def test_data_role_selects_technical_cv(self):
        result = self.match(
            "Data Analyst",
            "Requires SQL, Python, Power BI and ETL.",
        )

        self.assertEqual(result["best_cv"], "technical")
        self.assertIn("SQL", result["matched_skills"])
        self.assertIn("Python", result["matched_skills"])
        self.assertIn("Power BI", result["matched_skills"])

    def test_business_role_selects_business_cv(self):
        result = self.match(
            "Business Analyst",
            (
                "Requirements gathering, stakeholder management, "
                "UAT and process improvement."
            ),
        )

        self.assertEqual(result["best_cv"], "business")
        self.assertIn(
            "Requirements Gathering",
            result["matched_skills"],
        )
        self.assertIn(
            "Stakeholder Management",
            result["matched_skills"],
        )

    def test_missing_skills_are_job_requirements_not_candidate_extras(self):
        result = self.match(
            "Data Analyst",
            "Requires SQL and Power BI.",
        )

        self.assertNotIn("Python", result["missing_skills"])
        self.assertNotIn("ERP", result["missing_skills"])

    def test_unsubstantiated_profile_skill_cannot_create_match(self):
        result = self.match(
            "Data Analyst",
            "Requires Snowflake and SQL.",
        )

        self.assertIn("SQL", result["matched_skills"])

        self.assertNotIn(
            "Snowflake",
            result["matched_skills"],
        )

    def test_irrelevant_software_role_remains_capped(self):
        result = self.match(
            "Software Engineer",
            "Python SQL Git AWS",
        )

        self.assertLessEqual(
            result["candidate_match_score"],
            40,
        )

    def test_cv_specific_coverage_is_exposed(self):
        result = self.match(
            "Technology Consultant",
            (
                "ERP implementation, UAT, requirements gathering "
                "and stakeholder management."
            ),
        )

        self.assertEqual(result["best_cv"], "business")
        self.assertTrue(result["cv_coverage_skills"])

    def test_evidence_sources_are_exposed(self):
        result = self.match(
            "Data Analyst",
            "SQL Python Power BI",
        )

        self.assertIn(
            "technical_cv",
            result["candidate_evidence"]["SQL"],
        )


if __name__ == "__main__":
    unittest.main()
