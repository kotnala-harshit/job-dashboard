"""Collect audited employers through existing direct/ATS collectors."""
import json
import re
from pathlib import Path
import urllib.request

import scrape

OFFICIAL_PAGES = {
    "Riot Games": ("https://www.riotgames.com/en/work-with-us/offices/dublin", ".job-list__body a.js-job-url", ".job-row__col--primary", None),
    "Synopsys": ("https://careers.synopsys.com/location/ireland-jobs/44408/2963597/2", "a.sr-job-link", "h2", ".job-location"),
}

OFFICIAL_ZERO_PAGES = {
    "Quantexa": ("https://www.quantexa.com/careers/vacancies/", r"\b0 jobs in all departments\b"),
}


def official_page_jobs(company, html):
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    url, selector, title_selector, location_selector = OFFICIAL_PAGES[company]
    jobs = []
    for card in BeautifulSoup(html, "html.parser").select(selector):
        title = card.select_one(title_selector)
        location = card.select_one(location_selector) if location_selector else None
        location = location.get_text(" ", strip=True) if location else ("Dublin, Ireland" if company == "Riot Games" else "")
        if title and card.get("href") and scrape.region_ok(location):
            jobs.append({"company": company, "ats": "official", "title": title.get_text(" ", strip=True),
                         "location": location, "url": urljoin(url, card["href"]), "updated_at": None})
    return jobs


def complete_feed_zero(platform, data):
    """Only complete feeds with explicit locations can establish a zero."""
    if platform not in {"greenhouse", "ashby", "lever", "personio"} or not isinstance(data, (dict, list)):
        return False
    rows = data if platform == "lever" else data.get("jobs") if "jobs" in data else data.get("positions")
    if not isinstance(rows, list):
        return False
    for job in rows:
        if not isinstance(job, dict):
            return False
        location = job.get("location") or job.get("office") or (job.get("categories") or {}).get("location") or ""
        if platform == "greenhouse":
            location = location.get("name", "") if isinstance(location, dict) else ""
        elif platform == "lever":
            location = location.get("name", "") if isinstance(location, dict) else location
        elif platform == "personio":
            location = (job.get("office") or {}).get("name", "") if isinstance(job.get("office"), dict) else location
        locations = [location] + [x.get("location", "") for x in job.get("secondaryLocations", []) if isinstance(x, dict)]
        if not location or any(not isinstance(x, str) or scrape.region_ok(x) for x in locations):
            return False
        if job.get("isRemote") or any(re.search(r"remote|EMEA|Europe|global|worldwide", x, re.I) for x in locations):
            return False
    return True


def workday_country_zero(data):
    if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list) or not isinstance(data.get("total"), int):
        return False
    if data["total"] == 0:
        return True
    pending = list(data.get("facets") or [])
    while pending:
        facet = pending.pop()
        if not isinstance(facet, dict):
            continue
        values = facet.get("values") or []
        if facet.get("facetParameter") in {"locationCountry", "locationHierarchy1"} and values:
            return all(isinstance(v, dict) and v.get("descriptor") and v.get("id")
                       and not re.search(r"ireland|remote|global|EMEA|Europe", v["descriptor"], re.I) for v in values)
        pending.extend(values)
        pending.extend(facet.get("facets") or [])
    return False


def personio_feed_zero(slug):
    xml = ""
    for domain in ("de", "com"):
        req = urllib.request.Request(
            f"https://{slug}.jobs.personio.{domain}/xml?language=en",
            headers={"User-Agent": "Mozilla/5.0 (job-dashboard-bot)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml = resp.read().decode("utf-8", "ignore")
            break
        except Exception:
            pass
    if not xml:
        return False
    positions = re.findall(r"<position>(.*?)</position>", xml, re.DOTALL)
    if not positions:
        return True
    for block in positions:
        fields = " ".join(re.findall(r"<(?:office|city)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:office|city)>", block, re.DOTALL))
        if not fields or scrape.region_ok(fields) or re.search(r"remote|EMEA|Europe|global|worldwide", fields, re.I):
            return False
    return True


def configured_routes(company):
    key = scrape._company_key(company)
    routes = []
    if company in OFFICIAL_PAGES:
        routes.append({"platform": "official_page", "slug": company})
    if company in scrape.DIRECT_COMPANY_CONNECTORS:
        routes.append({"platform": "direct", "slug": company})
    for platform, names in (
        ("greenhouse", scrape.GREENHOUSE_COMPANIES), ("lever", scrape.LEVER_COMPANIES),
        ("ashby", scrape.ASHBY_COMPANIES), ("smartrecruiters", scrape.SMARTRECRUITERS_COMPANIES),
        ("workable", scrape.WORKABLE_COMPANIES), ("recruitee", scrape.RECRUITEE_COMPANIES),
        ("personio", scrape.PERSONIO_COMPANIES), ("pinpoint", scrape.PINPOINT_COMPANIES),
    ):
        for slug in names:
            if scrape._company_key(scrape.company_display_name(slug)) == key:
                routes.append({"platform": platform, "slug": slug})
    for name, tenant, host, site in scrape.WORKDAY_COMPANIES:
        if scrape._company_key(scrape.company_display_name(name)) == key:
            routes.append({"platform": "workday", "slug": f"{tenant}|{host}|{site}"})
    for platform, mapping in (("eightfold", scrape.KNOWN_EIGHTFOLD_MAPPINGS), ("phenom", scrape.KNOWN_PHENOM_MAPPINGS)):
        if company in mapping:
            routes.append({"platform": platform, "slug": mapping[company]})
    cache = Path(__file__).with_name("ats_platform_cache.json")
    saved = json.loads(cache.read_text()).get(company, {}) if cache.exists() else {}
    if saved.get("slug") and (company, saved.get("platform"), saved["slug"]) not in scrape.REJECTED_DYNAMIC_MAPPINGS:
        routes.append({"platform": saved["platform"], "slug": saved["slug"]})
    return routes


def collect(company):
    registry = {r["company"]: r for r in scrape.build_company_registry(include_cache=True)}
    source = registry[company].get("careers_url") or ""
    session = scrape._session()
    routes = configured_routes(company)
    tried = set()
    attempts = []
    empty_route = None
    # An audit may discover a corrected route; reuse it on subsequent refreshes.
    audit_path = Path(__file__).with_name("zero_audit.json")
    if audit_path.exists():
        previous = next((r for r in json.loads(audit_path.read_text())["companies"] if r["company"] == company), {})
        if previous.get("route"):
            routes.insert(0, previous["route"])
    if company in OFFICIAL_ZERO_PAGES:
        url, pattern = OFFICIAL_ZERO_PAGES[company]
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            if re.search(pattern, response.text, re.I):
                scrape._mark_connector_health(company, True, "Official vacancies page reports 0 open roles", url)
                scrape.CONNECTOR_HEALTH[company].update(verified_zero=True, audit_route={"platform": "official_zero_page", "slug": company})
                return []
        except Exception as exc:
            attempts.append(f"official_zero_page/{company}: {type(exc).__name__}")

    def run(route):
        nonlocal empty_route
        platform, slug = route["platform"], route["slug"]
        if (platform, slug) in tried:
            return []
        tried.add((platform, slug))
        if platform == "official_page":
            response = session.get(OFFICIAL_PAGES[company][0], timeout=25)
            response.raise_for_status()
            jobs = official_page_jobs(company, response.text)
        elif platform == "direct":
            jobs = scrape.scrape_direct_company(slug) or []
        elif platform == "workable" or scrape._probe_platform(platform, slug, session, allow_empty=True):
            jobs = scrape._scrape_cached_mapping(company, platform, slug, session)
        else:
            attempts.append(f"{platform}/{slug}: endpoint validation failed")
            return []
        jobs = [j for j in jobs if scrape.is_real_job_title(j.get("title")) and scrape.region_ok(j.get("location") or "")]
        attempts.append(f"{platform}/{slug}: {len(jobs)} candidate Ireland jobs")
        if jobs:
            for j in jobs:
                j["company"] = company
            scrape._mark_connector_health(company, True, attempts[-1], source)
            scrape.CONNECTOR_HEALTH[company]["audit_route"] = route
        elif platform in {"greenhouse", "ashby", "lever", "personio"}:
            url = {
                "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
                "personio": f"https://{slug}.jobs.personio.com/xml?language=en",
            }[platform]
            data = None if platform == "personio" else scrape.fetch_json(url)
            if personio_feed_zero(slug) if platform == "personio" else complete_feed_zero(platform, data):
                empty_route = (route, url, 0 if platform == "personio" else len(data if platform == "lever" else data["jobs"]))
        elif platform == "workday":
            tenant, host, site = slug.split("|")
            url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            response = scrape._workday_post(scrape._workday_session(), url, scrape._workday_headers(tenant, host, site), {}, 20, 0, "")
            data = response.json() if response is not None else None
            if workday_country_zero(data):
                empty_route = (route, url, data["total"])
        return jobs

    def safe_run(route):
        try:
            return run(route)
        except Exception as exc:
            attempts.append(f"{route['platform']}/{route['slug']}: {type(exc).__name__}")
            return []

    for route in routes:
        jobs = safe_run(route)
        if jobs:
            return jobs
    # Follow identifiers published by the actual employer, never guessed slugs.
    discovered = scrape._careers_page_ats_candidates(company, source, session)
    for platform, slug in discovered:
        if (company, platform, slug) in scrape.REJECTED_DYNAMIC_MAPPINGS:
            continue
        jobs = safe_run({"platform": platform, "slug": slug})
        if jobs:
            return jobs
    if empty_route and empty_route[0]["platform"] in {"greenhouse", "ashby", "lever", "personio"}:
        route = empty_route[0]
        if (route["platform"], route["slug"]) not in discovered:
            attempts.append("Empty cached board is not linked from the current official careers page; zero unconfirmed")
            empty_route = None
    health = scrape.CONNECTOR_HEALTH.get(company, {})
    if empty_route:
        route, url, total = empty_route
        evidence = "Official country filters" if route["platform"] == "workday" else "Complete official feed"
        scrape._mark_connector_health(company, True, f"{evidence} checked: {total} postings, no eligible Ireland locations", url)
        scrape.CONNECTOR_HEALTH[company].update(verified_zero=True, audit_route=route)
    elif company == "Infosys" and health.get("live") and "explicitly reports zero" in health.get("note", ""):
        health["verified_zero"] = True
        health["audit_route"] = {"platform": "direct", "slug": company}
    else:
        scrape._mark_connector_health(company, False, "; ".join(attempts) or "No validated collector discovered from official careers page", source)
    return []
