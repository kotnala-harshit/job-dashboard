"""Run with python3 test_zero_audit.py; no network requests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from io import BytesIO

import scrape
import zero_audit


def check():
    now = datetime.now(timezone.utc)
    evidence = {"live": True, "verified_zero": True, "checked_at": now.isoformat()}
    assert scrape.has_current_zero_evidence(evidence)
    for change in ({"live": False}, {"verified_zero": False},
                   {"checked_at": (now - timedelta(days=2)).isoformat()},
                   {"checked_at": "bad timestamp"}, {"checked_at": None}):
        assert not scrape.has_current_zero_evidence({**evidence, **change})
    assert not scrape.has_current_zero_evidence({"live": True})

    assert zero_audit.complete_feed_zero("greenhouse", {"jobs": []})
    assert not zero_audit.complete_feed_zero("greenhouse", [])
    assert not zero_audit.complete_feed_zero("greenhouse", {"jobs": [{"location": {"name": "Dublin"}}]})
    assert not zero_audit.complete_feed_zero("ashby", {"jobs": [{"location": "Remote EMEA"}]})
    assert not zero_audit.workday_country_zero({"total": 0, "jobPostings": [{}]})
    assert zero_audit.workday_country_zero({"total": 0, "jobPostings": []})
    board = {"total": 3, "jobPostings": [{}], "facets": [{
        "facetParameter": "locationCountry",
        "values": [{"id": "us", "descriptor": "United States", "count": 3}],
    }]}
    assert zero_audit.workday_country_zero(board)
    assert not zero_audit.workday_country_zero({**board, "total": 4})
    for document, expected in ((b"<workzag-jobs/>", True), (b"<html>Blocked</html>", False), (b"not xml", False)):
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: BytesIO(document)):
            assert zero_audit.personio_feed_zero("test") is expected

    aryzta = '<tr class="data-row"><td><a class="jobTitle-link" href="/job/123">Key Account Manager</a></td><td class="jobLocation">Clondalkin, IE</td></tr>'
    jobs = zero_audit.official_page_jobs("ARYZTA Ireland", aryzta)
    assert len(jobs) == 1 and jobs[0]["location"] == "Clondalkin, Ireland"
    airnav = '<li><a class="title" href="/careers/current-vacancies/ict">ICT Infrastructure Analyst</a><p class="highlight">Dublin</p><a class="cta" href="/careers/current-vacancies/ict">View Vacancy</a></li>'
    assert zero_audit.official_page_jobs("AirNav Ireland", airnav)[0]["title"] == "ICT Infrastructure Analyst"

    scrape.CONNECTOR_HEALTH.clear()
    def failed():
        scrape._mark_connector_health("Visa", False, "HTTP 403")
        return []
    with patch.dict(scrape._PRIORITY_OFFICIAL_CONNECTORS, {"Visa": (failed, "https://example.com")}):
        assert scrape.scrape_direct_company("Visa") == []
    assert scrape.CONNECTOR_HEALTH["Visa"]["live"] is False
    print("Zero-source regression checks passed")


if __name__ == "__main__":
    check()
