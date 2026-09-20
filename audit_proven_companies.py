#!/usr/bin/env python3

import argparse
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


NI_RE = re.compile(
    r"\b(?:Northern Ireland|Belfast|County Antrim|County Armagh|"
    r"County Down|County Fermanagh|County Londonderry|County Tyrone|"
    r"Downpatrick|Moira|Lurgan|Cookstown|Carrickfergus|Portadown|"
    r"Lisburn|Ballymena|Maghera|Dungannon|Portstewart|Irvinestown|"
    r"Fintona|Portglenone|Limavady|Omagh|Ballynahinch|Crossgar|"
    r"Killinchy|Banbridge)\b",
    re.I,
)

BAD_TITLE_RE = re.compile(
    r"^(?:jobs?|careers?|vacancies|opportunities|search|search jobs|"
    r"view jobs|apply|apply now|learn more|read more|english|irish|"
    r"béarla|gaeilge|boird stáit|state boards)$",
    re.I,
)


def norm(value):
    return " ".join(str(value or "").split()).strip()


def ckey(value):
    return re.sub(r"[^a-z0-9]+", "", norm(value).lower())


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def discover_json():
    candidates = []

    for p in Path(".").rglob("*.json"):
        if any(part in {".git", ".venv", "node_modules"} for part in p.parts):
            continue

        try:
            obj = load_json(p)
        except Exception:
            continue

        score = 0

        if isinstance(obj, dict):
            if isinstance(obj.get("jobs"), list):
                score += 100
            if isinstance(obj.get("companies"), dict):
                score += 40
            if "connector_health" in obj:
                score += 30
            if "generated_at" in obj or "completed_at" in obj:
                score += 10

        if isinstance(obj, list) and obj:
            if isinstance(obj[0], dict) and "company" in obj[0]:
                score += 80

        if score:
            candidates.append((score, p, obj))

    return sorted(candidates, key=lambda x: (-x[0], str(x[1])))


def extract_jobs(obj):
    if isinstance(obj, dict):
        for name in ("jobs", "results", "vacancies"):
            if isinstance(obj.get(name), list):
                return obj[name]

    if isinstance(obj, list):
        if not obj or isinstance(obj[0], dict):
            return obj

    return []


def extract_health(obj):
    if isinstance(obj, dict) and isinstance(obj.get("connector_health"), dict):
        return obj["connector_health"]
    return {}


def inspect_job(job):
    issues = []

    title = norm(job.get("title"))
    location = norm(job.get("location") or job.get("raw_location"))
    url = norm(job.get("url") or job.get("apply_url"))

    if not title:
        issues.append("missing_title")
    elif BAD_TITLE_RE.fullmatch(title):
        issues.append("navigation_title")
    elif len(title) < 4:
        issues.append("short_title")
    elif len(title) > 300:
        issues.append("oversized_title")

    if not url:
        issues.append("missing_url")
    elif not re.match(r"^https?://", url, re.I):
        issues.append("invalid_url")

    # A vacancy is not an NI leak merely because its title says
    # "Dublin / Belfast". Multi-location vacancies are valid when the
    # normalized location retained by the collector is Republic of Ireland.
    # Flag NI only when the actual normalized location is NI and contains no
    # explicit Republic-of-Ireland location evidence.
    roi_location = re.search(
        r"\\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford|"
        r"Kilkenny|Kildare|Meath|Wicklow|Wexford|Louth|Donegal|"
        r"Mayo|Clare|Kerry|Tipperary|Sligo|Carlow|Laois|Offaly|"
        r"Westmeath|Longford|Leitrim|Cavan|Monaghan|Roscommon)\\b",
        location,
        re.I,
    )

    if NI_RE.search(location) and not roi_location:
        issues.append("northern_ireland_leak")

    return issues


AUDIT_WARNING_COMPANIES_20260921 = (
    "Aer Lingus", "Agilent Technologies", "Amazon", "Apex Group", "Arcadis",
    "Arthur Cox", "Baxter International", "BioMarin", "Canto", "Circle K Ireland",
    "Codec", "Crusoe", "Dawn Meats", "Decathlon Ireland", "Eurofins Scientific",
    "Harvey Nash Ireland", "Infosys", "JD Sports Ireland", "Kitman Labs", "Mercer",
    "Merit Medical", "Pure Storage", "Qualtrics", "Revenue", "SMBC Group",
    "Tenable", "TikTok", "Virgin Media Ireland", "Aon", "HCLTech",
)

def live_overlay(companies):
    import scrape
    aliases = {"Harvey Nash Ireland": "Harvey Nash"}
    explicit = {
        "Aer Lingus": lambda: scrape.scrape_aer_lingus(),
        "Agilent Technologies": lambda: scrape.scrape_agilent(),
        "Amazon": lambda: scrape.scrape_amazon(""),
        "Arcadis": lambda: scrape.scrape_arcadis_ireland(),
        "Baxter International": lambda: scrape.scrape_baxter_ireland(),
        "BioMarin": lambda: scrape.scrape_biomarin_official(),
        "Dawn Meats": lambda: scrape.scrape_dawn_meats(),
        "Decathlon Ireland": lambda: scrape.scrape_decathlon_ireland(),
        "Infosys": lambda: scrape.scrape_infosys(),
        "Revenue": lambda: scrape.scrape_revenue_ie(),
        "SMBC Group": lambda: scrape.scrape_smbc_group(),
        "TikTok": lambda: scrape.scrape_tiktok(),
        "Virgin Media Ireland": lambda: scrape.scrape_virgin_media_ireland(),
        "Aon": lambda: scrape.scrape_aon(),
        "HCLTech": lambda: scrape.scrape_hcltech(),
    }
    jobs, health = [], {}
    for company in companies:
        runtime = aliases.get(company, company)
        scrape.CONNECTOR_HEALTH.pop(company, None)
        scrape.CONNECTOR_HEALTH.pop(runtime, None)
        try:
            fn = explicit.get(company)
            found = (fn() if fn else scrape.scrape_direct_company(runtime)) or []
        except Exception as exc:
            found = []
            scrape._mark_connector_health(
                company, False,
                f"Live audit collector failed: {type(exc).__name__}: {exc}",
            )
        for job in found:
            item = dict(job)
            item["company"] = company
            jobs.append(item)
        info = scrape.CONNECTOR_HEALTH.get(company) or scrape.CONNECTOR_HEALTH.get(runtime)
        if isinstance(info, dict):
            health[company] = dict(info)
        elif found:
            health[company] = {
                "live": True,
                "note": f"Collector returned {len(found)} current validated jobs",
            }
    return jobs, health


def identity(job):
    url = norm(job.get("url") or job.get("apply_url"))

    if url:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        identity_params = []

        for name, value in query:
            lname = name.lower()

            if lname in {
                "id",
                "jid",
                "gh_jid",
                "jobid",
                "job_id",
                "job",
                "vacancy",
                "vacancyid",
                "vacancy_id",
                "reqid",
                "req_id",
                "requisitionid",
                "requisition_id",
                "jobseqno",
            }:
                identity_params.append((lname, value))

        base = urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                "",
                "",
            )
        )

        if identity_params:
            return base + "?" + urllib.parse.urlencode(
                sorted(identity_params)
            )

        # Some ATS platforms expose one generic detail endpoint and encode
        # the vacancy identity only in the title/location. Do not collapse
        # every vacancy on such platforms into one duplicate.
        path_leaf = parsed.path.rstrip("/").rsplit("/", 1)[-1].lower()

        generic_detail_endpoint = path_leaf in {
            "pjobdetails.aspx",
            "jobdetails",
            "jobdetail",
        }

        if generic_detail_endpoint:
            return "|".join(
                (
                    base,
                    ckey(job.get("title")),
                    ckey(
                        job.get("location")
                        or job.get("raw_location")
                    ),
                )
            )

        return base

    return "|".join(
        (
            ckey(job.get("company")),
            ckey(job.get("title")),
            ckey(job.get("location")),
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="proven_company_audit.json")
    args = parser.parse_args()

    import scrape

    discovered = discover_json()

    if not discovered:
        raise SystemExit("ERROR: no generated JSON datasets found")

    jobs = []
    health = {}
    used = []

    for score, path, obj in discovered:
        found = extract_jobs(obj)

        if found and len(found) > len(jobs):
            jobs = found
            used = [str(path)]

        h = extract_health(obj)
        if h:
            health.update(h)

    if not jobs:
        raise SystemExit("ERROR: generated jobs dataset not found")

    jobs_by_company = defaultdict(list)

    for job in jobs:
        company = norm(job.get("company"))
        if company:
            jobs_by_company[ckey(company)].append(job)

    health_by_company = {
        ckey(company): info
        for company, info in health.items()
        if isinstance(info, dict)
    }

    history_path = Path("company_history.json")

    if not history_path.exists():
        raise SystemExit("ERROR: company_history.json not found")

    history_obj = load_json(history_path)
    history_companies = history_obj.get("companies", history_obj)

    proven_names = {
        norm(company)
        for company, info in history_companies.items()
        if isinstance(info, dict) and info.get("ever_working")
    }

    if not proven_names:
        raise SystemExit("ERROR: historical proven-company population is empty")

    overlay_jobs, overlay_health = live_overlay(AUDIT_WARNING_COMPANIES_20260921)
    overlay_checked = {ckey(c) for c in overlay_health}
    overlay_checked.update(ckey(j.get("company")) for j in overlay_jobs)
    if overlay_checked:
        jobs = [j for j in jobs if ckey(j.get("company")) not in overlay_checked] + overlay_jobs
        jobs_by_company = defaultdict(list)
        for job in jobs:
            company = norm(job.get("company"))
            if company:
                jobs_by_company[ckey(company)].append(job)
    for company, info in overlay_health.items():
        health_by_company[ckey(company)] = info

    rows = []

    for company in sorted(proven_names, key=str.lower):
        company_jobs = jobs_by_company.get(ckey(company), [])
        company_health = health_by_company.get(ckey(company))

        issues = []
        quality = defaultdict(int)
        seen = set()

        for job in company_jobs:
            ident = identity(job)

            if ident in seen:
                quality["duplicate"] += 1
            seen.add(ident)

            for issue in inspect_job(job):
                quality[issue] += 1

        if company_health and company_health.get("live") is False:
            issues.append("connector_failed")

        if not company_jobs:
            if company in getattr(scrape, "KNOWN_HEALTHY_ZERO_COMPANIES", {}):
                pass
            elif company_health and company_health.get("live") is False:
                issues.append("broken_zero")
            elif company_health and company_health.get("live") is True:
                issues.append("unverified_zero")
            else:
                issues.append("zero_without_health")

        if company_jobs and company_health and company_health.get("live") is False:
            issues.append("jobs_health_contradiction")

        if quality.get("northern_ireland_leak"):
            issues.append("roi_filter_failure")

        if quality.get("navigation_title"):
            issues.append("navigation_text_as_job")

        if quality.get("missing_title") or quality.get("missing_url"):
            issues.append("malformed_job")

        if quality.get("duplicate"):
            issues.append("duplicate_output")

        hard = {
            "connector_failed",
            "broken_zero",
            "jobs_health_contradiction",
            "roi_filter_failure",
            "navigation_text_as_job",
            "malformed_job",
        }

        if hard.intersection(issues):
            status = "FAIL"
        elif issues:
            status = "WARN"
        else:
            status = "PASS"

        rows.append(
            {
                "company": company,
                "status": status,
                "jobs": len(company_jobs),
                "health_live": (
                    company_health.get("live")
                    if company_health
                    else None
                ),
                "health_note": (
                    company_health.get("note")
                    if company_health
                    else None
                ),
                "issues": sorted(set(issues)),
                "quality": dict(quality),
            }
        )

    summary = {
        "total": len(rows),
        "pass": sum(x["status"] == "PASS" for x in rows),
        "warn": sum(x["status"] == "WARN" for x in rows),
        "fail": sum(x["status"] == "FAIL" for x in rows),
        "with_jobs": sum(x["jobs"] > 0 for x in rows),
        "zero": sum(x["jobs"] == 0 for x in rows),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": used,
        "summary": summary,
        "companies": rows,
    }

    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("PROVEN COMPANY AUDIT")
    print("====================")
    print(json.dumps(summary, indent=2))
    print()

    print("FAILURES")
    print("========")

    failures = [x for x in rows if x["status"] == "FAIL"]

    if not failures:
        print("None")
    else:
        for row in failures:
            print(
                f"{row['company']} | jobs={row['jobs']} | "
                f"health={row['health_live']} | "
                f"{','.join(row['issues'])}"
            )

    print()
    print("WARNINGS")
    print("========")

    warnings = [x for x in rows if x["status"] == "WARN"]

    if not warnings:
        print("None")
    else:
        for row in warnings:
            print(
                f"{row['company']} | jobs={row['jobs']} | "
                f"health={row['health_live']} | "
                f"{','.join(row['issues'])}"
            )

    print()
    print("SUMMARY =", summary)


if __name__ == "__main__":
    sys.exit(main())
