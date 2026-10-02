"""Small, offline checks for CV ranking. Run: python3 test_candidate_match.py."""
import scrape


def check():
    profile = scrape.load_candidate_profile()
    def rank(title, description=""):
        return scrape.candidate_match({"title": title, "location": "Dublin, Ireland"}, description, profile)
    assert rank("Business Intelligence Analyst")["role_family"] == "Data & BI"
    assert rank("Internal Communications Specialist")["role_family"] == "Other"
    assert rank("R&D Electrical Engineering Graduate")["role_family"] == "Other"
    assert rank("Business Analyst", "SQL, requirements gathering, UAT. 2 years experience")["best_cv"] == "business"
    assert rank("Data Analyst", "SQL, Python, Power BI")["best_cv"] == "technical"
    assert rank("Senior Data Analyst", "8+ years experience, 2 years SQL")["experience_fit"] == "Too Senior"
    assert rank("Senior Data Analyst")["experience_fit"] == "Stretch"
    assert rank("Data Analyst", "3 years experience with Python and Azure")["missing_skills"] == ["Azure"]
    assert rank("Data Analyst")["scoring_evidence"] == "title_only"
    assert rank("Power BI Analyst")["scoring_evidence"] == "title_only"
    assert rank("Data Scientist", "Python, SQL, scikit-learn")["experience_fit"] == "Stretch"
    assert rank("Business Analyst MBA Intern, 2027")["candidate_match_score"] <= 40
    job = {"title": "Data Analyst", "location": "Dublin", "experience_min": 8, "matched_skills": ["SQL"]}
    rescored = scrape.candidate_match(job, "", profile)
    assert rescored["experience_fit"] == "Too Senior" and rescored["ranking_skills"] == ["SQL"]
    title_only = {"title": "Power BI Analyst", **rank("Power BI Analyst")}
    assert scrape.candidate_match(title_only, "", profile)["scoring_evidence"] == "title_only"
    technical = rank("Data Analyst", "Python, Java, JavaScript, FinBERT, SQL, Docker")
    assert technical["cv_match_scores"]["technical"] > technical["cv_match_scores"]["business"]
    print("CV ranking regression checks passed")


if __name__ == "__main__":
    check()
