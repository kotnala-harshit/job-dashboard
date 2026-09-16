#!/usr/bin/env python3
from pathlib import Path

PATH = Path("scrape.py")
if not PATH.exists():
    raise SystemExit("ERROR: run from the job-dashboard repository root")

text = PATH.read_text(encoding="utf-8")
MARKER = "# BEGIN NEEDS_VERIFICATION_2026_09_16"
if MARKER in text:
    print("✓ Needs Verification patch already present")
    raise SystemExit(0)

anchor = 'if __name__ == "__main__":'
pos = text.rfind(anchor)
if pos < 0:
    raise SystemExit("ERROR: could not find final scrape.py __main__ guard")

block = r'''
# BEGIN NEEDS_VERIFICATION_2026_09_16
# Official-source audit performed 2026-09-16.

# The 2026-09-16 audit found Quantexa, Trading 212, Indeed, and
# Heineken Ireland at zero jobs. Do NOT add them to
# KNOWN_HEALTHY_ZERO_COMPANIES: that structure stamps a fresh
# checked_at without performing a live verification.

_NEEDS_VERIFICATION_GREENHOUSE = {
    "esw": "ESW",
    "smartling": "Smartling",
    "sumup": "SumUp",
    "teneolinkedin": "Teneo Ireland",
    "figma": "Figma",
}
for _slug in _NEEDS_VERIFICATION_GREENHOUSE:
    if _slug not in GREENHOUSE_COMPANIES:
        GREENHOUSE_COMPANIES.append(_slug)

_NEEDS_VERIFICATION_ASHBY = {"cubic3": "Cubic³"}
for _slug in _NEEDS_VERIFICATION_ASHBY:
    if _slug not in ASHBY_COMPANIES:
        ASHBY_COMPANIES.append(_slug)

_needs_verification_previous_company_display_name = company_display_name
def company_display_name(raw: str) -> str:
    _key = _company_key(raw)
    for _slug, _name in {
        **_NEEDS_VERIFICATION_GREENHOUSE,
        **_NEEDS_VERIFICATION_ASHBY,
    }.items():
        if _key == _company_key(_slug):
            return _name
    return _needs_verification_previous_company_display_name(raw)

_NEEDS_VERIFICATION_DIRECT = {}
for _company, _fn_name in {
    "CRH": "scrape_crh",
    "FBD Insurance": "scrape_fbd_insurance_official",
    "Waystone": "scrape_waystone_official",
    "Amgen": "scrape_amgen_official",
    "Fidelity Investments": "scrape_fidelity_investments_official",
    "Nucleo": "scrape_nucleo_official",
}.items():
    _fn = globals().get(_fn_name)
    if callable(_fn):
        _NEEDS_VERIFICATION_DIRECT[_company] = _fn
        DIRECT_COMPANY_CONNECTORS[_company] = "needs_verification_official"

_needs_verification_previous_direct = scrape_direct_company
def scrape_direct_company(company: str, *args, **kwargs):
    _fn = _NEEDS_VERIFICATION_DIRECT.get(company)
    if _fn is not None:
        return _fn()
    return _needs_verification_previous_direct(company, *args, **kwargs)

_NEEDS_VERIFICATION_BROWSER = {
    "Lam Research": (
        ["https://www.lamresearch.com/careers/"],
        ("/job/", "/jobs/", "job-detail", "jobdetail"),
    ),
    "Novartis": (
        ["https://www.novartis.com/careers/career-search?country%5B0%5D=IE"],
        ("/careers/career-search/job/details/", "/job/", "/jobs/"),
    ),
    "Macquarie Group": (
        ["https://www.macquarie.com/au/en/careers/graduates-and-interns.html"],
        ("/careers/", "/job/", "/jobs/"),
    ),
    "Zurich Insurance": (
        ["https://www.zurich.ie/about-us/careers/"],
        ("/job/", "/jobs/", "jobdetail"),
    ),
    "WuXi Biologics": (
        ["https://www.wuxibiologics.com/join-us/"],
        ("/job/", "/jobs/", "/career/"),
    ),
}

_needs_verification_browser_previous_direct = scrape_direct_company
def scrape_direct_company(company: str, *args, **kwargs):
    jobs = _needs_verification_browser_previous_direct(company, *args, **kwargs)
    if jobs or company not in _NEEDS_VERIFICATION_BROWSER:
        return jobs
    urls, patterns = _NEEDS_VERIFICATION_BROWSER[company]
    return _browser_board_collect(
        company,
        urls,
        patterns,
        default_location="Ireland",
        max_scrolls=25,
        require_ireland=True,
        source_tag="direct",
    )

for _company in _NEEDS_VERIFICATION_BROWSER:
    DIRECT_COMPANY_CONNECTORS[_company] = "needs_verification_browser_official"


# Keep every active direct connector represented in the proven refresh batches.
_nv_batched_keys = {
    _company_key(company_display_name(name))
    for group in PROVEN_REFRESH_BATCHES
    for name in group
}

for _nv_company in ("Lam Research", "Nucleo"):
    _nv_key = _company_key(company_display_name(_nv_company))
    if _nv_key not in _nv_batched_keys:
        if len(PROVEN_REFRESH_BATCHES[-1]) >= 10:
            PROVEN_REFRESH_BATCHES.append([])
        PROVEN_REFRESH_BATCHES[-1].append(_nv_company)
        _nv_batched_keys.add(_nv_key)

# END NEEDS_VERIFICATION_2026_09_16

'''
PATH.write_text(text[:pos] + block + text[pos:], encoding="utf-8")
print("✓ Applied Needs Verification connector fixes")
