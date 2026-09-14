#!/usr/bin/env python3
"""Merge bounded scraper slices into the dashboard dataset."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def key(job):
    return str(job.get("url") or "").strip().lower() or "|".join(
        str(job.get(name) or "").strip().lower()
        for name in ("company", "title", "location")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("core")
    parser.add_argument("slices", nargs="+")
    parser.add_argument("--output", default="data.json")
    parser.add_argument("--seen", default="seen_jobs.json")
    args = parser.parse_args()

    output = json.loads(Path(args.core).read_text(encoding="utf-8"))
    jobs = {key(job): job for job in output.get("jobs", [])}
    health = dict(output.get("connector_health") or {})
    errors = list(output.get("errors") or [])

    for path in args.slices:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        jobs.update({key(job): job for job in data.get("jobs", [])})
        health.update(data.get("connector_health") or {})
        errors.extend(data.get("errors") or [])

    merged = list(jobs.values())
    output.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scrape_mode": "full",
        "scrape_phase": "merged",
        "jobs": merged,
        "total_matches": len(merged),
        "companies_with_live_jobs": len({job.get("company") for job in merged if job.get("company")}),
        "company_job_counts": {
            company: sum(1 for job in merged if job.get("company") == company)
            for company in sorted({job.get("company") for job in merged if job.get("company")})
        },
        "source_counts": {
            source: sum(1 for job in merged if (job.get("ats") or "unknown") == source)
            for source in sorted({job.get("ats") or "unknown" for job in merged})
        },
        "connector_health": health,
        "errors": errors,
    })
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    seen_path = Path(args.seen)
    try:
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        seen = {}
    now = datetime.now(timezone.utc).isoformat()
    for job in merged:
        identity = key(job)
        prior = seen.get(identity) if isinstance(seen.get(identity), dict) else {}
        seen[identity] = {
            **prior,
            "first_seen": job.get("first_seen_at") or prior.get("first_seen") or now,
            "last_seen": now,
            "last_verified": now,
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "url": job.get("url"),
            "ats": job.get("ats"),
            "active": True,
            "missing_runs": 0,
        }
    seen_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    print(f"Merged {len(merged)} jobs from {len(args.slices)} bounded slices")


if __name__ == "__main__":
    main()
