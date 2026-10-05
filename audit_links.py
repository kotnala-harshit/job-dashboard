"""Check dashboard URLs. HTTP blocks/timeouts are unknown, never proof of closure."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

_LOCKS = {}
_LOCAL = threading.local()


def classify_response(status, html, url, final_url):
    result = {"http_status": status, "final_url": final_url}
    if status in (404, 410):
        return {**result, "status": "unreachable", "reason": f"HTTP {status}"}
    if status in (401, 403, 429):
        return {**result, "status": "blocked", "reason": f"Automated check blocked (HTTP {status})"}
    if not 200 <= status < 300:
        return {**result, "status": "error", "reason": f"HTTP {status}"}
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if re.search(r"access denied|just a moment|human verification|attention required|security check|captcha|robot check", title, re.I):
        return {**result, "status": "blocked", "reason": "Browser verification required"}
    for el in soup.select("script, style, noscript, template, nav, footer, header"):
        el.decompose()
    text = soup.get_text(" ", strip=True)
    closed = r"(?:this (?:job|position|vacancy|opportunity) (?:is no longer available|has been (?:filled|closed)|is no longer accepting applications)|(?:job|position|vacancy) (?:not found|no longer available)|the job you (?:are looking for|requested) (?:is no longer|has been)|we(?:'re| are) sorry.{0,60}(?:job|position).{0,30}no longer available)"
    # Only an explicit page message counts; boilerplate inside scripts does not.
    if re.search(closed, text[:1800], re.I):
        return {**result, "status": "unreachable", "reason": "Employer page explicitly reports job unavailable"}
    final_path = urlsplit(final_url).path.rstrip("/").lower()
    if urlsplit(url).path.rstrip("/").lower() != final_path and re.fullmatch(r"(?:/[a-z]{2}(?:-[a-z]{2})?)?/(?:careers|jobs|search-jobs|search-results)?", final_path + ("/" if not final_path else "")):
        return {**result, "status": "unverified", "reason": "Redirected to a general careers page"}
    if not text and len(html) < 100:
        return {**result, "status": "unverified", "reason": "Empty response"}
    return {**result, "status": "reachable", "reason": "HTTP success; vacancy availability may require the employer page"}


def check_url(url, deadline=float("inf")):
    if time.monotonic() > deadline:
        return None
    checked = datetime.now(timezone.utc).isoformat()
    if urlsplit(url).scheme == "mailto":
        return {"status": "unverified", "reason": "Email application; no web page to check", "checked_at": checked}
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
        return {"status": "unreachable", "reason": "Invalid job URL", "checked_at": checked}
    if not hasattr(_LOCAL, "session"):
        _LOCAL.session = requests.Session()
        _LOCAL.session.headers["User-Agent"] = "Mozilla/5.0 (compatible; JobDashboardLinkCheck/1.0)"
    try:
        with _LOCKS[urlsplit(url).netloc]:
            with _LOCAL.session.get(url, timeout=(8, 18), allow_redirects=True, stream=True) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= 2_000_000:
                        break
                html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                result = classify_response(response.status_code, html, url, response.url)
    except requests.RequestException as exc:
        result = {"status": "error", "reason": type(exc).__name__}
    return {**result, "checked_at": checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry", action="store_true", help="Recheck provisional failures")
    parser.add_argument("--max-age-hours", type=float, default=0, help="Reuse recent checks for scheduled runs")
    parser.add_argument("--apply", action="store_true", help="Publish deduplicated jobs and repeat-confirmed link failures")
    parser.add_argument("--budget-seconds", type=float, default=3600)
    args = parser.parse_args()
    data = json.loads(Path("data.json").read_text())
    path = Path("job_link_audit.json")
    report = json.loads(path.read_text()) if path.exists() else {"urls": {}}
    urls = sorted({j["url"] for j in data["jobs"]})
    now = datetime.now(timezone.utc)
    due = []
    for url in urls:
        old = report["urls"].get(url, {})
        age = (now - datetime.fromisoformat(old["checked_at"])).total_seconds() / 3600 if old.get("checked_at") else float("inf")
        if args.retry:
            if old.get("status") in {"unreachable", "error", "unverified"}:
                due.append(url)
        elif age >= args.max_age_hours:
            due.append(url)
    # Spread work across employers; at most two simultaneous requests per host.
    due.sort(key=lambda u: (len(urlsplit(u).path), urlsplit(u).netloc))
    _LOCKS.update({urlsplit(u).netloc: threading.Semaphore(2) for u in due})
    with ThreadPoolExecutor(max_workers=28) as pool:
        futures = {pool.submit(check_url, url, time.monotonic() + args.budget_seconds): url for url in due}
        for n, future in enumerate(as_completed(futures), 1):
            url = futures[future]
            old = report["urls"].get(url, {})
            result = future.result()
            if result is None:
                continue
            result["failure_checks"] = old.get("failure_checks", 0) + 1 if result["status"] == "unreachable" else 0
            report["urls"][url] = result
            if n % 100 == 0:
                path.write_text(json.dumps(report, indent=2))
                print(f"Checked {n}/{len(due)} URLs", flush=True)
    report.update(completed_at=datetime.now(timezone.utc).isoformat(), checked_urls=sum(u in report["urls"] for u in urls), status_counts=dict(Counter(report["urls"].get(u, {}).get("status", "unverified") for u in urls)))
    path.write_text(json.dumps(report, indent=2))
    if args.apply:
        from job_quality import apply_quality
        duplicates, removed = apply_quality(data, report)
        report["last_cleanup"] = {"at": report["completed_at"], "duplicates": duplicates, "unavailable": removed}
        path.write_text(json.dumps(report, indent=2))
        history_path = Path("company_history.json")
        if history_path.exists():
            history = json.loads(history_path.read_text())
            for company, entry in history.get("companies", {}).items():
                entry["current_live_jobs"] = data["company_job_counts"].get(company, 0)
            history_path.write_text(json.dumps(history, indent=2))
        seen_path = Path("seen_jobs.json")
        if seen_path.exists():
            seen = json.loads(seen_path.read_text())
            unavailable = {u for u, check in report["urls"].items() if check.get("status") == "unreachable" and check.get("failure_checks", 0) >= 2}
            for entry in seen.values():
                if isinstance(entry, dict) and entry.get("url") in unavailable:
                    entry["active"] = False
            seen_path.write_text(json.dumps(seen, indent=2))
        Path("data.json").write_text(json.dumps(data, indent=2))
        print(f"Removed {len(duplicates)} duplicates and {len(removed)} confirmed unavailable links", flush=True)
    print(json.dumps({k:v for k,v in report.items() if k not in {"urls", "last_cleanup"}}), flush=True)


if __name__ == "__main__":
    main()
