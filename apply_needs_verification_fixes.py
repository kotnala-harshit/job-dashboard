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
# Verified-zero companies below use live ATS/direct collectors; do not put
# them in KNOWN_HEALTHY_ZERO_COMPANIES, which synthesizes checked_at.

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

_NEEDS_VERIFICATION_ASHBY = {
    "cubic3": "Cubic³",
    "quantexa": "Quantexa",
    "trading212": "Trading 212",
}
for _slug in _NEEDS_VERIFICATION_ASHBY:
    if _slug not in ASHBY_COMPANIES:
        ASHBY_COMPANIES.append(_slug)

VERIFIED_LIVE_ZERO_COMPANIES.update({"Quantexa", "Trading 212"})

_needs_verification_previous_company_display_name = company_display_name
def company_display_name(raw: str) -> str:
    _key = _company_key(raw)
    for _slug, _name in {**_NEEDS_VERIFICATION_GREENHOUSE, **_NEEDS_VERIFICATION_ASHBY}.items():
        if _key == _company_key(_slug):
            return _name
    return _needs_verification_previous_company_display_name(raw)


def _nv_greenhouse_company(company: str, slug: str):
    jobs = scrape_greenhouse(slug)
    for _job in jobs:
        _job["company"] = company
    _health = CONNECTOR_HEALTH.get(company_display_name(slug))
    if _health and company not in CONNECTOR_HEALTH:
        CONNECTOR_HEALTH[company] = dict(_health)
    return jobs


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

_NEEDS_VERIFICATION_DIRECT["Teneo Ireland"] = lambda: _nv_greenhouse_company("Teneo Ireland", "teneolinkedin")
_NEEDS_VERIFICATION_DIRECT["Figma"] = lambda: _nv_greenhouse_company("Figma", "figma")
DIRECT_COMPANY_CONNECTORS["Teneo Ireland"] = "greenhouse_official_direct"
DIRECT_COMPANY_CONNECTORS["Figma"] = "greenhouse_official_direct"

_needs_verification_previous_direct = scrape_direct_company
def scrape_direct_company(company: str, *args, **kwargs):
    _fn = _NEEDS_VERIFICATION_DIRECT.get(company)
    if _fn is not None:
        return _fn()
    return _needs_verification_previous_direct(company, *args, **kwargs)

_NEEDS_VERIFICATION_BROWSER = {
    "Lam Research": (
        ["https://opportunities.lamresearch.com/search/?q=&locationsearch=Ireland"],
        ("/job/", "/jobs/", "job-detail", "jobdetail"),
    ),
    "Novartis": (
        ["https://www.novartis.com/ie-en/careers/career-search?country%5B0%5D=LOC_IE&field_alternative_country%5B0%5D=LOC_IE"],
        ("/careers/career-search/job/details/", "/job/", "/jobs/"),
    ),
    "Zurich Insurance": (
        ["https://www.careers.zurich.com/search/?q=&locationsearch=Ireland"],
        ("/job/", "/jobs/", "jobdetail"),
    ),
    "WuXi Biologics": (
        ["https://www.wuxibiologics.com/join-us/"],
        ("/job/", "/jobs/", "/career/", "/join-us/"),
    ),
    "LinkedIn": (
        ["https://www.linkedin.com/jobs/search/?f_C=1337&geoId=104738515"],
        ("/jobs/view/",),
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
        default_location="Dublin, Ireland" if company == "LinkedIn" else "Ireland",
        max_scrolls=25,
        require_ireland=True,
        source_tag="direct",
    )

for _company in _NEEDS_VERIFICATION_BROWSER:
    DIRECT_COMPANY_CONNECTORS[_company] = "needs_verification_browser_official"

_nv_batched_keys = {
    _company_key(company_display_name(name))
    for group in PROVEN_REFRESH_BATCHES
    for name in group
}
for _nv_company in ("Lam Research", "Nucleo", "Teneo Ireland", "Figma", "LinkedIn"):
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
