"""Shared vacancy identity and publication cleanup; never merge by title alone."""
from collections import Counter
from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PRIORITY = {"direct": 100, "workday": 95, "greenhouse": 95, "lever": 95, "ashby": 95, "smartrecruiters": 95, "workable": 94, "recruitee": 94, "personio": 94, "pinpoint": 94, "phenom": 93, "eightfold": 93, "oracle": 93, "jsonld": 90, "adzuna": 30, "jooble": 25, "careerjet": 20}
TRACKING = {"source", "src", "trackingid", "lang", "locale", "gh_src", "lever-source", "iis", "iisn"}


def canonical_url(url):
    parsed = urlsplit((url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    params = [(k.lower(), v) for k,v in parse_qsl(parsed.query) if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
    if "myworkdayjobs.com" in host:
        match = re.search(r"_((?:[A-Za-z]+[-_])?\d[\w-]*|[A-Za-z]+\d[\w-]*)(?:/apply)?$", path)
        if match:
            return f"workday:{host.split('.')[0]}:{match[1].lower()}"
    # Preserve query-based requisitions and meaningful hash-router URLs.
    fragment = parsed.fragment if re.search(r"job|position|requisition", parsed.fragment, re.I) else ""
    return urlunsplit((parsed.scheme.lower(), host, path, urlencode(sorted(params)), fragment))


def deduplicate(jobs, checks=None):
    checks = checks or {}
    seen_urls, seen_reqs, kept, duplicates = {}, {}, [], []
    def preference(j):
        return (j.get("company") == "Mercer", PRIORITY.get((j.get("ats") or "").lower(), 50), bool(j.get("requisition_id")))
    for job in sorted(jobs, key=preference, reverse=True):
        company = re.sub(r"[^a-z0-9]", "", job.get("company", "").lower().replace("&", "and"))
        url = canonical_url(job.get("url"))
        check = checks.get(job.get("url"), {})
        final = check.get("final_url", "")
        keys = {url} if url else set()
        if check.get("status") == "reachable" and re.search(r"/jobs?/|/positions?/|\d{4,}", urlsplit(final).path, re.I):
            keys.add(canonical_url(final))
        req = str(job.get("requisition_id") or "").strip().lower()
        req_key = (company, req) if req and re.search(r"\d", req) else None
        winner = next((seen_urls[k] for k in keys if k in seen_urls), None) or (seen_reqs.get(req_key) if req_key else None)
        if winner:
            duplicates.append({"url": job.get("url"), "kept_url": winner, "company": job.get("company"), "title": job.get("title")})
            continue
        kept.append(job)
        seen_urls.update({k:job.get("url") for k in keys})
        if req_key:
            seen_reqs[req_key] = job.get("url")
    order = {id(j): i for i, j in enumerate(jobs)}
    kept.sort(key=lambda j: order[id(j)])
    by_url = {j["url"]: j for j in kept}
    for duplicate in duplicates:
        winner = by_url.get(duplicate["kept_url"])
        if winner is not None and duplicate["url"] != winner["url"]:
            winner["duplicate_urls"] = sorted(set(winner.get("duplicate_urls", []) + [duplicate["url"]]))
    return kept, duplicates


def apply_quality(data, report):
    checks = report.get("urls", {})
    jobs, duplicates = deduplicate(data["jobs"], checks)
    removed, kept = [], []
    for job in jobs:
        check = checks.get(job.get("url"), {})
        # Require repeat failures. Challenges, throttling, and network errors stay visible.
        checked_at = datetime.fromisoformat(check["checked_at"]) if check.get("checked_at") else None
        recent = checked_at and (datetime.now(timezone.utc) - checked_at).total_seconds() < 86400
        if recent and check.get("status") == "unreachable" and check.get("failure_checks", 0) >= 2:
            removed.append({"url": job["url"], "company": job.get("company"), "title": job.get("title"), "reason": check["reason"]})
            continue
        job["link_check"] = {key: check[key] for key in ("status", "reason", "checked_at", "http_status") if key in check} if check else {"status": "unverified", "reason": "New listing; link check pending"}
        kept.append(job)
    data["jobs"] = kept
    by_url = {job["url"]:job for job in kept}
    graduate = data.get("graduate_early_careers", {})
    if "jobs" in graduate:
        graduate["jobs"] = [by_url[j["url"]] for j in graduate["jobs"] if j.get("url") in by_url]
        graduate.update(live_job_count=len(graduate["jobs"]), live_company_count=len({j["company"] for j in graduate["jobs"]}), live_companies=sorted({j["company"] for j in graduate["jobs"]}))
    counts = Counter(j["company"] for j in kept)
    data.update(total_matches=len(kept), company_job_counts=dict(counts), companies_with_live_jobs=len(counts), source_counts=dict(Counter(j.get("ats") or "unknown" for j in kept)), recency_counts=dict(Counter(j.get("recency") or "unknown" for j in kept)), new_since_last_check=sum(bool(j.get("new_since_last_check")) for j in kept))
    for company, history in data.get("company_history", {}).items():
        history["current_live_jobs"] = counts.get(company, 0)
    for item in data.get("coverage_diagnostics", []):
        if item["state"] == "working" and not counts.get(item["company"]):
            item.update(state="configured_zero", reason="Listed links unavailable; check employer for replacement vacancies")
    data["coverage_state_counts"] = dict(Counter(x["state"] for x in data.get("coverage_diagnostics", [])))
    data["job_link_audit"] = {"completed_at": report.get("completed_at"), "checked_urls": report.get("checked_urls", 0), "status_counts": report.get("status_counts", {}), "duplicates_removed": len(duplicates), "unreachable_removed": len(removed), "remaining_status_counts": dict(Counter(j["link_check"]["status"] for j in kept))}
    return duplicates, removed
