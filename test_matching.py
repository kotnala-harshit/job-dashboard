import unittest

from scrape import candidate_match, smartrecruiters_public_url


PROFILE = {
    "experience_years": 3,
    "preferred_locations": ["Ireland", "Dublin"],
    "role_families": {
        "Data & BI": {"tier": "A", "weight": 40, "titles": ["data analyst", "power bi"]},
        "Technology Consulting": {"tier": "A", "weight": 36, "titles": ["implementation consultant"]},
    },
    "skills": {"core": ["SQL", "Python", "Power BI", "AWS"]},
    "negative_title_terms": ["software engineer", "account executive"],
    "seniority_penalties": {"principal": 22},
}


class CandidateMatchTest(unittest.TestCase):
    def score(self, title, description="SQL Python Power BI AWS"):
        return candidate_match(
            {"title": title, "location": "Dublin, Ireland", "country": "Ireland"},
            description,
            PROFILE,
        )

    def test_description_cannot_invent_role_family(self):
        result = self.score("Account Executive", "Works with the data analyst and Power BI teams. SQL AWS")
        self.assertEqual(result["role_family"], "Other")
        self.assertLess(result["candidate_match_score"], 55)

    def test_target_title_remains_relevant(self):
        result = self.score("Data Analyst")
        self.assertEqual(result["role_family"], "Data & BI")
        self.assertGreaterEqual(result["candidate_match_score"], 55)

    def test_version1_public_route_uses_correct_company_id(self):
        self.assertEqual(
            "https://jobs.smartrecruiters.com/Version1/744000145976699-backend-developer",
            smartrecruiters_public_url("version1", "744000145976699", "Backend Developer"),
        )


if __name__ == "__main__":
    unittest.main()
