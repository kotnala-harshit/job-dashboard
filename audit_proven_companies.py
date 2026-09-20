#!/usr/bin/env python3

import argparse
import json
import re
import sys
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

    if NI_RE.search(f"{title} {location}"):
        issues.append("northern_ireland_leak")

    return issues


def identity(job):
    url = norm(job.get("url") or job.get("apply_url"))

    if url:
        return url.split("?")[0].rstrip("/").lower()

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

    proven_names = set()

    for batch in getattr(scrape, "PROVEN_REFRESH_BATCHES", []):
        for company in batch:
            try:
                display = scrape.company_display_name(company)
            except Exception:
                display = company

            proven_names.add(norm(display))

    for company in getattr(scrape, "KNOWN_HEALTHY_ZERO_COMPANIES", {}):
        proven_names.add(norm(company))

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
