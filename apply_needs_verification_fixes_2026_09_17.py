#!/usr/bin/env python3
from pathlib import Path

PATH = Path("scrape.py")
if not PATH.exists():
    raise SystemExit("ERROR: run from the job-dashboard repository root")

text = PATH.read_text(encoding="utf-8")
MARKER = "# BEGIN NEEDS_VERIFICATION_2026_09_17"
if MARKER in text:
    print("✓ 2026-09-17 verification patch already present")
    raise SystemExit(0)

anchor = 'if __name__ == "__main__":'
pos = text.rfind(anchor)
if pos < 0:
    raise SystemExit("ERROR: could not find final scrape.py __main__ guard")

block = r"""
# BEGIN NEEDS_VERIFICATION_2026_09_17

_NV17_GREENHOUSE = {"teneolinkedin": "Teneo Ireland", "figma": "Figma"}
for _slug in _NV17_GREENHOUSE:
    if _slug not in GREENHOUSE_COMPANIES:
        GREENHOUSE_COMPANIES.append(_slug)

_NV17_ASHBY = {"quantexa": "Quantexa", "trading212": "Trading 212"}
for _slug in _NV17_ASHBY:
    if _slug not in ASHBY_COMPANIES:
        ASHBY_COMPANIES.append(_slug)

_nv17_prev_display = company_display_name
def company_display_name(raw: str) -> str:
    _key = _company_key(raw)
    for _slug, _name in {**_NV17_GREENHOUSE, **_NV17_ASHBY}.items():
        if _key == _company_key(_slug):
            return _name
    return _nv17_prev_display(raw)

def _nv17_greenhouse_company(company: str, slug: str):
    jobs = scrape_greenhouse(slug)
    for _job in jobs:
        _job["company"] = company
    _health = CONNECTOR_HEALTH.get(company_display_name(slug))
    if _health:
        CONNECTOR_HEALTH[company] = dict(_health)
    return jobs

def _nv17_workable_company(company: str, slug: str):
    jobs = scrape_workable(slug)
    for _job in jobs:
        _job["company"] = company
    _mark_connector_health(
        company, True,
        f"Official Workable board loaded; returned {len(jobs)} qualifying Ireland jobs",
        f"https://apply.workable.com/{slug}/",
    )
    return jobs

_NV17_DIRECT = {
    "Teneo Ireland": lambda: _nv17_greenhouse_company("Teneo Ireland", "teneolinkedin"),
    "Figma": lambda: _nv17_greenhouse_company("Figma", "figma"),
    "Nucleo": lambda: _nv17_workable_company("Nucleo", "nucleo-consulting"),
}

_nv17_prev_direct = scrape_direct_company
def scrape_direct_company(company: str, *args, **kwargs):
    _fn = _NV17_DIRECT.get(company)
    if _fn is not None:
        return _fn()
    return _nv17_prev_direct(company, *args, **kwargs)

DIRECT_COMPANY_CONNECTORS["Teneo Ireland"] = "greenhouse_official_direct"
DIRECT_COMPANY_CONNECTORS["Figma"] = "greenhouse_official_direct"
DIRECT_COMPANY_CONNECTORS["Nucleo"] = "workable_official_direct"

_NV17_BROWSER = {
    "WuXi Biologics": (
        ["https://www.wuxibiologics.com/join-us/"],
        ("/join-us-", "/job/", "/jobs/", "/career/"),
    ),
}

_nv17_prev_direct_2 = scrape_direct_company
def scrape_direct_company(company: str, *args, **kwargs):
    jobs = _nv17_prev_direct_2(company, *args, **kwargs)
    if jobs or company not in _NV17_BROWSER:
        return jobs
    urls, patterns = _NV17_BROWSER[company]
    return _browser_board_collect(
        company, urls, patterns, default_location="Ireland",
        max_scrolls=25, require_ireland=True, source_tag="direct",
    )

for _company in _NV17_BROWSER:
    DIRECT_COMPANY_CONNECTORS[_company] = "needs_verification_browser_official"

# Verified-zero classification is owned exclusively by KNOWN_HEALTHY_ZERO_COMPANIES.

_nv17_batched = {
    _company_key(company_display_name(name))
    for group in PROVEN_REFRESH_BATCHES
    for name in group
}
for _company in ("Teneo Ireland", "Figma", "Nucleo", "WuXi Biologics"):
    _key = _company_key(_company)
    if _key not in _nv17_batched:
        if len(PROVEN_REFRESH_BATCHES[-1]) >= 10:
            PROVEN_REFRESH_BATCHES.append([])
        PROVEN_REFRESH_BATCHES[-1].append(_company)
        _nv17_batched.add(_key)

# END NEEDS_VERIFICATION_2026_09_17

"""
PATH.write_text(text[:pos] + block + text[pos:], encoding="utf-8")
print("✓ Applied 2026-09-17 zero/verification connector fixes")
