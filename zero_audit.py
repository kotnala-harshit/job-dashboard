"""Collect audited employers through existing direct/ATS collectors."""
import json
import re
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

import scrape

OFFICIAL_PAGES = {
    "CACEIS": ("https://jobs.caceis.com/offre-de-emploi/liste-offres.aspx", ".ts-offer-list-item", ".ts-offer-list-item__title-link", ".ts-offer-list-item__description"),
    "ASL Aviation Holdings": ("https://cezanneondemand.intervieweb.it/aslaviationgroup/en/career", ".vacancy__header", ".vacancy__title a", "[title=Location]"),
    "Storm Technology": ("https://careers.storm.ie/", ".job-card", ".card-header a", ".card-body p"),
    "WuXi Biologics": ("https://www.wuxibiologics.com/join-us/", "tr:has(td.td_width02 a)", "td.td_width02 a", "td.td_width03 .title"),
    "Rippling": ("https://www.rippling.com/careers/open-roles", "a[href*='ats.rippling.com/rippling/jobs/']", "div:first-child > span:first-child", "div:first-child > div > span:last-child"),
    "SAP legacy": ("https://careers.sap.com/go/Ireland/9053801/", "tr.data-row", "a.jobTitle-link", ".jobLocation"),
    "SAP": ("https://jobs.sap.com/en/jobs/?locations=Dublin", "article.card-job", "h2 a", "li:has(span.sr-only):-soup-contains(Locations)"),
    "Novartis": ("https://www.novartis.com/careers/career-search?country%5B1%5D=LOC_IE", "tr:has(.views-field-field-job-title)", ".views-field-field-job-title a", ".views-field-field-job-country"),
    "Willis Towers Watson (WTW)": ("https://careers.wtwco.com/jobs/search?cities%5B%5D=Dublin", "tr[data-job-url]", ".job-search-results-title a", ".job-search-results-location"),
    "AirNav Ireland": ("https://www.airnav.ie/careers/current-vacancies", "li:has(a.title[href*='/careers/current-vacancies/'])", "a.title", "p.highlight"),
    "ARYZTA Ireland": ("https://careers.aryzta.com/go/Ireland-Jobs/1345801/", "tr.data-row", "a.jobTitle-link", ".jobLocation"),
    "Expleo Ireland": ("https://expleo-jobs-ie-en.icims.com/jobs/search?ss=1&in_iframe=1", ".iCIMS_JobCardItem", ".title a", ".iCIMS_JobHeaderData"),
    "Noesis": ("https://opportunities.noesis.pt/jobs", "a.job-card", ".title", ".details span"),
    "Riot Games": ("https://www.riotgames.com/en/work-with-us/offices/dublin", ".job-list__body a.js-job-url", ".job-row__col--primary", None),
    "Synopsys": ("https://careers.synopsys.com/location/ireland-jobs/44408/2963597/2", "a.sr-job-link", "h2", ".job-location"),
}



def official_page_jobs(company, html):
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    url, selector, title_selector, location_selector = OFFICIAL_PAGES[company]
    jobs = []
    for card in BeautifulSoup(html, "html.parser").select(selector):
        title = card.select_one(title_selector)
        location = card.select_one(location_selector) if location_selector else None
        location = location.get_text(" ", strip=True) if location else ("Ireland" if company in {"AirNav Ireland", "ARYZTA Ireland", "Riot Games"} else "")
        location = re.sub(r",\s*IE(?=,|$)", ", Ireland", location, flags=re.I)
        if company == "Storm Technology":
            location = location.split("Business Area:")[0].replace("Location:", "").strip()
        link = card.get("href") or (title.get("href") if title else None)
        if company == "Expleo Ireland":
            location = re.sub(r"^IE-", "Ireland - ", location)
            title = title.select_one("h3") if title else None
        if title and link and scrape.region_ok(location):
            jobs.append({"company": company, "ats": "direct", "title": title.get_text(" ", strip=True),
                         "location": location, "url": urljoin(url, link), "updated_at": (card.select_one("time").get("datetime") if card.select_one("time") else card.select_one(".views-field-field-job-posted-date").get_text(strip=True) if card.select_one(".views-field-field-job-posted-date") else None)})
    return jobs


def caceis_country_zero(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    total = soup.select_one(".ts-ol-pagination__title")
    countries = soup.select_one("select[id$=GeographicalAreaCollection]")
    if not total or not countries:
        return None
    count = re.search(r"Nombre de résultats\s*:\s*(\d+)", total.get_text(" ", strip=True))
    labels = [x.get_text(" ", strip=True) for x in countries.select(":scope > option") if x.get("value") != "0"]
    labels += [x.get("label", "") for x in countries.select(":scope > optgroup")]
    if not count or not labels or any(re.search(r"Ireland|Irlande|remote|global|Europe", label, re.I) for label in labels):
        return None
    counts = [re.search(r"\((\d+)\)$", label) for label in labels]
    if all(counts) and sum(int(n[1]) for n in counts) == int(count[1]):
        return int(count[1])
    return None


def collect_official_page(company):
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse
    url = OFFICIAL_PAGES[company][0]
    if company == "Rippling":
        with scrape.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                search = page.get_by_placeholder("Search roles")
                search.fill("Ireland")
                page.wait_for_timeout(3500)
                return list({job["url"]: job for job in official_page_jobs(company, page.content())}.values())
            finally:
                browser.close()
    host = urlparse(url).netloc
    session = scrape._session()
    visited, jobs = set(), {}
    # ponytail: bounded pagination; raise the cap if an official board exceeds 20 pages.
    while url and url not in visited and len(visited) < 20:
        visited.add(url)
        response = session.get(url, timeout=25)
        response.raise_for_status()
        if company == "CACEIS":
            total = caceis_country_zero(response.text)
            if total is not None:
                scrape._mark_connector_health(company, True, f"Complete official country filters: {total} postings, no Ireland locations", url)
                scrape.CONNECTOR_HEALTH[company].update(verified_zero=True, official_total=total)
        for job in official_page_jobs(company, response.text):
            jobs[job["url"]] = job
        next_link = BeautifulSoup(response.text, "html.parser").select_one('a[rel="next"][href], a[title="Next page"][href]')
        url = urljoin(url, next_link["href"]) if next_link else None
        if url and urlparse(url).netloc != host:
            break
    if company == "SAP":
        for job in collect_official_page("SAP legacy"):
            job["company"] = "SAP"
            jobs[job["url"]] = job
    return list(jobs.values())


def complete_feed_zero(platform, data):
    """Only complete feeds with explicit locations can establish a zero."""
    if platform not in {"greenhouse", "ashby", "lever", "personio"}:
        return False
    if not isinstance(data, list if platform == "lever" else dict):
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
        return not data["jobPostings"]
    pending = list(data.get("facets") or [])
    while pending:
        facet = pending.pop()
        if not isinstance(facet, dict):
            continue
        values = facet.get("values") or []
        if re.sub(r"[^a-z]", "", str(facet.get("facetParameter", "")).lower()) in {"locationcountry", "country"} and values:
            # A posting can appear in several country buckets, so counts can exceed total.
            return all(isinstance(v, dict) and v.get("descriptor") and v.get("id")
                       and isinstance(v.get("count"), int)
                       and not re.search(r"ireland|remote|global|EMEA|Europe", v["descriptor"], re.I) for v in values) and sum(v["count"] for v in values) >= data["total"]
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
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    if root.tag != "workzag-jobs":
        return False
    positions = root.findall("position")
    if not positions:
        return True
    for block in positions:
        fields = " ".join(block.findtext(field) or "" for field in ("office", "city"))
        if not fields or scrape.region_ok(fields) or re.search(r"remote|EMEA|Europe|global|worldwide", fields, re.I):
            return False
    return True



def collect_bamboohr(company, slug):
    source = f"https://{slug}.bamboohr.com/careers"
    response = scrape._session().get(source + "/list", timeout=25)
    response.raise_for_status()
    data = response.json()
    jobs = []
    for row in data.get("result", []):
        loc = row.get("atsLocation") or {}
        fallback = row.get("location") or {}
        location = ", ".join(str(x) for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x)
        location = location or ", ".join(str(x) for x in fallback.values() if x)
        if scrape.region_ok(location):
            jobs.append({"company": company, "ats": "bamboohr", "title": row["jobOpeningName"].strip(), "location": location, "url": source + "/" + str(row["id"]), "updated_at": None})
    return jobs


def collect_successfactors(company, base):
    session = scrape._session()
    session.get(base, timeout=25).raise_for_status()
    jobs = {}
    rows_seen = 0
    for page in range(20):
        response = session.post(base + "/services/recruiting/v1/jobs", json={
            "locale": "en_US", "pageNumber": page, "sortBy": "", "keywords": "", "location": "Ireland",
            "facetFilters": {}, "brand": "", "skills": [], "categoryId": 0, "alertId": "", "rcmCandidateId": "",
        }, timeout=25)
        response.raise_for_status()
        data = response.json()
        rows = data.get("jobSearchResult")
        if not isinstance(rows, list):
            raise ValueError("Missing SuccessFactors jobSearchResult")
        for item in rows:
            row = item["response"]
            locations = [loc.strip() for loc in row.get("jobLocationShort", []) if scrape.region_ok(loc)]
            if not locations:
                continue
            url = f"{base}/{row.get('brandUrl') or 'default'}/job/{row['unifiedUrlTitle']}/{row['id']}-en_US"
            jobs[url] = {"company": company, "ats": "successfactors", "title": row["unifiedStandardTitle"], "location": "; ".join(locations), "url": url, "updated_at": row.get("unifiedStandardStart")}
        rows_seen += len(rows)
        if not rows or rows_seen >= data.get("totalJobs", 0):
            break
    return list(jobs.values())


def collect_transfermate():
    session = scrape._session()
    source = "https://www.transfermate.com/company/career-page"
    page = session.get(source, timeout=25)
    page.raise_for_status()
    # Read the public job-search configuration from the employer, not a saved credential.
    key = re.search(r"TEAMTAILOR_KEY\s*=\s*['\"]([^'\"]+)", page.text)
    division = re.search(r"divisionId\s*=\s*(\d+)", page.text)
    version = re.search(r"API_VERSION\s*=\s*['\"]([^'\"]+)", page.text)
    if not all((key, division, version)):
        raise ValueError("Missing official Teamtailor search configuration")
    url = f"https://api.teamtailor.com/v1/jobs?include=location&page[size]=30&filter[division]={division[1]}"
    jobs = []
    for _ in range(20):
        response = session.get(url, headers={"Authorization": "Token token=" + key[1], "X-Api-Version": version[1]}, timeout=25)
        response.raise_for_status()
        data = response.json()
        locations = {x["id"]: x["attributes"].get("name", "") for x in data.get("included", []) if x["type"] == "locations"}
        for row in data.get("data", []):
            loc_id = ((row.get("relationships", {}).get("location", {}).get("data")) or {}).get("id")
            location = locations.get(loc_id, "")
            if scrape.region_ok(location):
                jobs.append({"company": "TransferMate", "ats": "teamtailor", "title": row["attributes"]["title"], "location": location, "url": row["links"]["careersite-job-url"], "description_text": scrape._strip_html(row["attributes"].get("body", "")), "updated_at": row["attributes"].get("created-at")})
        url = (data.get("links") or {}).get("next")
        if not url or not url.startswith("https://api.teamtailor.com/v1/jobs?"):
            break
    return jobs


CORRECTED_ROUTES = {
    "Teva Pharmaceuticals": {"platform": "eightfold", "slug": "www.careers.teva|tevapharm.com"},
    "CRH": {"platform": "successfactors", "slug": "https://jobs.crh.com"},
    "GridBeyond": {"platform": "bamboohr", "slug": "gridbeyond"},
    "TransferMate": {"platform": "teamtailor", "slug": "TransferMate"},
}


def configured_routes(company):
    key = scrape._company_key(company)
    routes = [CORRECTED_ROUTES[company]] if company in CORRECTED_ROUTES else []
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
    verified_routes = set()
    # An audit may discover a corrected route; reuse it on subsequent refreshes.
    audit_path = Path(__file__).with_name("zero_audit.json")
    if audit_path.exists():
        previous = next((r for r in json.loads(audit_path.read_text())["companies"] if r["company"] == company), {})
        if previous.get("route"):
            routes.insert(0, previous["route"])

    def run(route):
        nonlocal empty_route
        platform, slug = route["platform"], route["slug"]
        if (platform, slug) in tried:
            return []
        tried.add((platform, slug))
        if platform == "successfactors":
            jobs = collect_successfactors(company, slug)
        elif platform == "bamboohr":
            jobs = collect_bamboohr(company, slug)
        elif platform == "teamtailor":
            jobs = collect_transfermate()
        elif platform == "official_page":
            jobs = collect_official_page(company)
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
        elif platform == "official_page" and scrape.has_current_zero_evidence(scrape.CONNECTOR_HEALTH.get(company, {})):
            empty_route = (route, OFFICIAL_PAGES[company][0], scrape.CONNECTOR_HEALTH[company]["official_total"])
            verified_routes.add((platform, slug))
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
                verified_routes.add((platform, slug))
        elif platform == "workday":
            tenant, host, site = slug.split("|")
            url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            response = scrape._workday_post(scrape._workday_session(), url, scrape._workday_headers(tenant, host, site), {}, 20, 0, "")
            data = response.json() if response is not None else None
            if workday_country_zero(data):
                empty_route = (route, url, data["total"])
                verified_routes.add((platform, slug))
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
    # One empty board (e.g. early careers) cannot clear a second unchecked board.
    if empty_route and empty_route[0]["platform"] != "official_page" and (not discovered or not set(discovered).issubset(verified_routes)):
        attempts.append("Not every current official board has complete zero evidence; zero unconfirmed")
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
