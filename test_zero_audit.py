"""Run with python3 test_zero_audit.py; no network requests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from types import SimpleNamespace

import scrape
import zero_audit


def check():
    rows = [{"company": "empty", "status": "verified_zero"}, {"company": "repaired", "status": "jobs_found"}, {"company": "unknown", "status": "needs_attention"}]
    assert [r["company"] for r in scrape.audit_refresh_rows(rows, {"repaired"}, [])] == ["empty"]
    assert len(scrape.audit_refresh_rows(rows, set(), rows[:1])) == 2
    assert scrape.oracle_complete_zero([{"PrimaryLocation": "Germany"}], 1)
    for entries, total in [([{"PrimaryLocation": "Ireland"}], 1), ([{"PrimaryLocation": "Germany"}], 2), ([{}], 1), ([{"PrimaryLocation": "Germany", "secondaryLocations": [{"Name": "Dublin"}]}], 1), ([{"PrimaryLocation": "Remote EMEA"}], 1)]:
        assert not scrape.oracle_complete_zero(entries, total)
    now = datetime.now(timezone.utc)
    evidence = {"live": True, "verified_zero": True, "checked_at": now.isoformat()}
    assert scrape.has_current_zero_evidence(evidence)
    for change in ({"live": False}, {"verified_zero": False},
                   {"checked_at": (now - timedelta(days=2)).isoformat()},
                   {"checked_at": "bad timestamp"}, {"checked_at": None}):
        assert not scrape.has_current_zero_evidence({**evidence, **change})
    assert not scrape.has_current_zero_evidence({"live": True})

    assert zero_audit.foreign_location("USA - Remote")
    assert zero_audit.foreign_location("Remote, California, USA")
    for location in ("Remote", "Remote EMEA", "Remote Europe / Germany", "Remote, Ireland", "Remote, UK / Ireland", "Dublin"):
        assert not zero_audit.foreign_location(location)
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
    overlap = {**board, "facets": [{"facetParameter": "Location_Country", "values": [{"id": "us", "descriptor": "United States", "count": 3}, {"id": "uk", "descriptor": "United Kingdom", "count": 1}]}]}
    assert zero_audit.workday_country_zero(overlap)
    overlap["facets"][0]["values"].append({"id": "ie", "descriptor": "Ireland", "count": 1})
    assert not zero_audit.workday_country_zero(overlap)
    for document, expected in ((b"<workzag-jobs/>", True), (b"<html>Blocked</html>", False), (b"not xml", False)):
        with patch.object(scrape, "_session", return_value=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(text=document.decode(), raise_for_status=lambda: None))):
            assert zero_audit.personio_feed_zero("test") is expected

    aryzta = '<tr class="data-row"><td><a class="jobTitle-link" href="/job/123">Key Account Manager</a></td><td class="jobLocation">Clondalkin, IE</td></tr>'
    jobs = zero_audit.official_page_jobs("ARYZTA Ireland", aryzta)
    assert len(jobs) == 1 and jobs[0]["location"] == "Clondalkin, Ireland"
    airnav = '<li><a class="title" href="/careers/current-vacancies/ict">ICT Infrastructure Analyst</a><p class="highlight">Dublin</p><a class="cta" href="/careers/current-vacancies/ict">View Vacancy</a></li>'
    assert zero_audit.official_page_jobs("AirNav Ireland", airnav)[0]["title"] == "ICT Infrastructure Analyst"

    sap = aryzta.replace("Clondalkin, IE", "Dublin 24, IE, D24WA02")
    assert zero_audit.official_page_jobs("SAP legacy", sap)[0]["location"] == "Dublin 24, Ireland, D24WA02"
    wtw = '<tr data-job-url="1"><td class="job-search-results-title"><a href="/jobs/1">Property Underwriter</a></td><td class="job-search-results-location">Dublin, Ireland</td></tr>'
    assert len(zero_audit.official_page_jobs("Willis Towers Watson (WTW)", wtw)) == 1

    # Shared MMC feed must not relabel Marsh jobs as Mercer.
    route = {"platform": "workday", "slug": "test|wd1|careers"}
    with patch.object(scrape, "_workday_session", return_value=None), patch.object(scrape, "build_company_registry", return_value=[{"company": "Test Empty", "careers_url": "https://example.com"}]), patch.object(zero_audit, "configured_routes", return_value=[route]), patch.object(scrape, "_workday_post", return_value=SimpleNamespace(json=lambda: board)), patch.object(scrape, "_careers_page_ats_candidates", return_value=[("workday", route["slug"])]), patch.object(scrape, "_scrape_cached_mapping") as full_scan:
        assert zero_audit.collect("Test Empty") == []
        assert scrape.has_current_zero_evidence(scrape.CONNECTOR_HEALTH["Test Empty"])
        full_scan.assert_not_called()
    postings = [{"title": "Data Analyst", "locationsText": "Dublin", "externalPath": "/job/1"}]
    response = SimpleNamespace(json=lambda: {"jobPostings": postings, "facets": [{"facetParameter": "country", "values": [{"id": "IE", "descriptor": "Ireland"}]}]})
    session = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"hiringOrganization": {"name": "Marsh"}, "jobPostingInfo": {"location": "Dublin"}}))
    with patch.object(scrape, "_workday_session", return_value=session), patch.object(scrape, "_workday_post", return_value=response), patch.object(scrape.time, "sleep"):
        assert scrape.scrape_workday("Mercer", "mmc", "wd1", "MMC", max_pages=1) == []

    country_html = '<div class="ts-ol-pagination__title">Nombre de résultats : 3 offre(s)</div><select id="GeographicalAreaCollection"><option value="0">Choose</option><option value="29">Allemagne (1)</option><optgroup label="France (2)"><option value="79">France (2)</option><option value="208">Paris (2)</option></optgroup></select>'
    assert zero_audit.caceis_country_zero(country_html) == 3
    assert zero_audit.caceis_country_zero(country_html.replace("Allemagne", "Irlande")) is None
    assert zero_audit.caceis_country_zero(country_html.replace("3 offre", "4 offre")) is None
    storm = '<div class="job-card"><div class="card-header"><a href="job-detail.php?jobid=1">Support Analyst</a></div><div class="card-body"><p>Location: Dublin Business Area: IT</p></div></div>'
    assert zero_audit.official_page_jobs("Storm Technology", storm)[0]["location"] == "Dublin"
    from unittest.mock import Mock
    session = Mock()
    session.get.side_effect = [SimpleNamespace(status_code=403), SimpleNamespace(status_code=200)]
    assert scrape._eightfold_search(session, "careers.example.com", "example.com", 0).status_code == 200
    assert session.get.call_args.args[0] == "https://careers.example.com/api/apply/v2/jobs"

    row = {"response": {"id": "1", "unifiedUrlTitle": "Analyst", "unifiedStandardTitle": "Analyst", "jobLocationShort": ["Belfast, Northern Ireland", "Dublin, Ireland"], "brandUrl": "default"}}
    session = Mock()
    session.post.return_value.json.return_value = {"jobSearchResult": [row], "totalJobs": 1}
    with patch.object(scrape, "_session", return_value=session):
        jobs = zero_audit.collect_successfactors("CRH", "https://jobs.crh.com")
        assert len(jobs) == 1 and jobs[0]["location"] == "Dublin, Ireland"
        assert jobs[0]["url"].endswith("/default/job/Analyst/1-en_US")
        assert session.post.call_count == 1

    # Current API collectors must reject non-Irish and inactive results.
    session = Mock()
    row = {"id": 1, "title": "Claims Administrator", "status": "ACTIVE", "siteCountry": "IE", "siteCity": "Dublin", "jobPublicUrl": "https://aviva.talent-community.com/projects/claims/1"}
    session.post.return_value.json.return_value = {"results": [row, {**row, "siteCountry": "GB"}, {**row, "archived": True}], "totalResults": 3}
    with patch.object(scrape, "_session", return_value=session):
        assert len(zero_audit.collect_aviva()) == 1
        assert session.post.call_count == 1
    session.get.return_value.text = 'window.AG_ID = "APP"; window.AG_KEY = "public-search-key"; window.AG_INDEX = {"default":"jobs"};'
    session.post.return_value.json.return_value = {"results": [{"hits": [{"title": "Analyst", "town_city_country": "Dublin | Ireland", "jd_url": "/job/1"}], "nbHits": 1}]}
    with patch.object(scrape, "_session", return_value=session):
        assert len(zero_audit.collect_msci()) == 1
    session.get.return_value.json.return_value = {"SearchResult": {"SearchResultCountAll": 1, "SearchResultItems": [{"MatchedObjectDescriptor": {"PositionLocation": [{"CountryName": "Irland", "CityName": "Dublin"}]}}]}}
    scrape.CONNECTOR_HEALTH.pop("Deutsche Bank", None)
    with patch.object(scrape, "_session", return_value=session):
        zero_audit.check_deutsche_bank_zero()
        assert not scrape.has_current_zero_evidence(scrape.CONNECTOR_HEALTH.get("Deutsche Bank", {}))
    session.get.return_value.text = '<a href="https://my.greenhouse.io/users/sign_in?job_board=veeamsoftware">Job alerts</a>'
    session.get.return_value.status_code = 200
    session.get.return_value.url = "https://careers.veeam.com"
    assert ("greenhouse", "veeamsoftware") in scrape._careers_page_ats_candidates("Veeam", "https://careers.veeam.com", session)
    dps = '<div class="boxstyle-info__copy"><div class="boxstyle-info__copy--info"><a href="/job/1">QC Analyst</a><div><div class="info--list__item">Location: Kerry</div></div></div></div>'
    assert zero_audit.official_page_jobs("DPS Group (Arcadis)", dps)[0]["location"] == "Kerry"
    asml = '<a class="search-results__item" href="/en/careers/find-your-job/1"><h3>Field Service Engineer</h3><ul class="search-results__fields"><li>Leixlip, Ireland</li></ul></a>'
    assert len(zero_audit.official_page_jobs("ASML", asml)) == 1

    def caceis_page(title, city, more=""):
        return f'<div>Nombre de résultats : 2</div><li class="ts-offer-list-item"><a class="ts-offer-list-item__title-link" href="/{title}">{title}</a><ul class="ts-offer-list-item__description"><li>CDI</li><li></li><li>{city}</li></ul></li>{more}'
    pages = [caceis_page("Analyst", "Paris", '<a class="ts-ol-pagination-list-item__link--next" href="?page=2">Next</a>'), caceis_page("Manager", "Putrajaya")]
    session.get.side_effect = [SimpleNamespace(text=text, raise_for_status=lambda: None) for text in pages]
    with patch.object(scrape, "_session", return_value=session):
        assert zero_audit.collect_official_page("CACEIS") == []
        assert scrape.has_current_zero_evidence(scrape.CONNECTOR_HEALTH["CACEIS"])
    scrape.CONNECTOR_HEALTH.pop("CACEIS")
    session.get.side_effect = [SimpleNamespace(text=pages[1], raise_for_status=lambda: None)]
    with patch.object(scrape, "_session", return_value=session):
        assert zero_audit.collect_official_page("CACEIS") == []
        assert not scrape.has_current_zero_evidence(scrape.CONNECTOR_HEALTH.get("CACEIS", {}))

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
