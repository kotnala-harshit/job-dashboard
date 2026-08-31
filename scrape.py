#!/usr/bin/env python3
"""
General Ireland job-search scraper.
Hits public ATS JSON APIs (Greenhouse, Lever, Ashby, …) and JSON-LD career pages.
Run by GitHub Actions hourly. Writes data.json for index.html.
"""

import json
import re
import time
import os
import html
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    requests = None

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    sync_playwright = None
    HAS_PLAYWRIGHT = False

# ---------------------------------------------------------------------------
# Company list: (slug, ats) -- expand this over time as we confirm more boards
# ---------------------------------------------------------------------------

GREENHOUSE_COMPANIES = ['stripe', 'airbnb', 'doordash', 'pinterest', 'squarespace', 'twilio', 'docusign', 'robinhood', 'reddit', 'coinbase', 'gitlab', 'github', 'hubspotjobs', 'indeed', 'zendesk', 'trustpilot', 'workhuman', 'wayflyer', 'intercom', 'wise', 'asana', 'cloudflare', 'datadog', 'snowflake', 'instacart', 'lyft', 'fenergo', 'affirm', 'airtable', 'algolia', 'amplitude', 'betterup', 'buffer', 'calendly', 'carta', 'chime', 'classpass', 'coursera', 'discord', 'doximity', 'elastic', 'envoy', 'faire', 'flexport', 'gusto', 'handshake', 'hashicorp', 'honeycomb', 'justworks', 'klaviyo', 'lattice', 'mixpanel', 'mongodb', 'qualtrics', 'mural', 'okta', 'opendoor', 'patreon', 'peloton', 'pilot', 'postman', 'procore', 'quora', 'rippling', 'samsara', 'segment', 'sendgrid', 'sourcegraph', 'sprinklr', 'strava', 'tanium', 'thumbtack', 'toast', 'turo', 'udemy', 'verkada', 'webflow', 'wework', 'yelp', 'zapier', 'zoominfo', 'getyourguide', 'trivago', 'deliveryhero', 'babbel', 'contentful', 'celonis', 'flixbus', 'tiermobility', 'gorillas', 'typeform', 'glovo', 'cabify', 'blablacar', 'backmarket', 'doctolib', 'qonto', 'alan', 'payfit', 'gocardless', 'truelayer', 'thoughtmachine', 'cazoo', 'octopusenergy', 'farfetch', 'starlingbank', 'revolut', 'darktrace', 'graphcore', 'onfido', 'fundingcircle', 'tines', 'flipdish', 'letsgetchecked', 'genesys', 'grab', 'sea', 'carousell', 'razer', 'lazada', 'careem', 'noon', 'talabat', 'propertyfinder', 'razorpay', 'swiggy', 'freshworks', 'browserstack', 'meesho', 'cred', 'groww', 'urbancompany', 'chargebee', 'clevertap', 'cultureamp', 'safetyculture', 'employmenthero', 'airwallex', 'deputy', 'linktree', 'go1', 'halter', 'judobank', 'figma', 'zscaler']

LEVER_COMPANIES = ['spotify', 'plaid', 'brex', 'checkout', 'deliveroo', 'monzo', 'wolt', 'bolt', 'pipedrive', 'zopa', 'gojek', 'traveloka']

ASHBY_COMPANIES = ['notion', 'linear', 'ramp', 'elevenlabs', 'openai', 'anthropic', 'vercel', 'scale', 'deel', 'partly', 'clickup', 'snowflake', 'wayflyer']

# ---------------------------------------------------------------------------
# Workday-hosted career sites (*.myworkdayjobs.com). Workday has no official
# public jobs API, but every tenant's own career-site JSON endpoint --
# https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs --
# is unauthenticated and freely queryable via POST, the same class of access
# already used for Greenhouse/Lever/Ashby above. Workday hard-caps each page
# at 20 results, so this paginates.
#
# (tenant, wd_host, site) -- verified working as of this build. Find more by
# opening any company's careers.<company>.com page, opening browser dev tools
# -> Network tab, and looking for a request to a "/wday/cxs/.../jobs" URL --
# the tenant/wd_host/site values are all in that URL.
# ---------------------------------------------------------------------------

WORKDAY_COMPANIES = [('Abbott', 'abbott', 'wd5', 'abbottcareers'), ('Salesforce', 'salesforce', 'wd12', 'External_Career_Site'), ('Workday', 'workday', 'wd5', 'Workday'), ('Genesys', 'genesys', 'wd1', 'Genesys'), ('Slack', 'salesforce', 'wd12', 'Slack'), ('Mastercard', 'mastercard', 'wd1', 'CorporateCareers'), ('PayPal', 'paypal', 'wd1', 'jobs'), ('Adobe', 'adobe', 'wd5', 'external_experienced'), ('Autodesk', 'autodesk', 'wd1', 'Ext'), ('Cadence Design Systems', 'cadence', 'wd1', 'External_Careers'), ('Analog Devices', 'analogdevices', 'wd1', 'External'), ('NVIDIA', 'nvidia', 'wd5', 'NVIDIAExternalCareerSite'), ('Broadcom', 'broadcom', 'wd1', 'External_Career'), ('NXP Semiconductors', 'nxp', 'wd3', 'careers'), ('Rockwell Automation', 'rockwellautomation', 'wd1', 'External_Rockwell_Automation'), ('Eaton', 'eaton', 'wd5', 'Eaton'), ('Pfizer', 'pfizer', 'wd1', 'PfizerCareers'), ('Sanofi', 'sanofi', 'wd3', 'SanofiCareers'), ('MSD (Merck Sharp & Dohme)', 'msd', 'wd5', 'SearchJobs'), ('Bausch + Lomb', 'bauschhealth', 'wd1', 'BauschHealthCareers'), ('Takeda', 'takeda', 'wd3', 'External'), ('Gilead Sciences', 'gilead', 'wd1', 'gileadcareers'), ('Edwards Lifesciences', 'edwards', 'wd1', 'EdwardsCareers'), ('Teleflex', 'teleflex', 'wd1', 'TeleflexCareers'), ('Zimmer Biomet', 'zimmerbiomet', 'wd1', 'Zimmer_Biomet_Careers'), ('Viatris', 'viatris', 'wd5', 'external'), ('Teva Pharmaceuticals', 'teva', 'wd1', 'Teva_Careers'), ('Jazz Pharmaceuticals', 'jazzpharma', 'wd5', 'Jazz_Careers'), ('ResMed', 'resmed', 'wd1', 'ResMed_External_Careers'), ('Becton Dickinson (BD)', 'bdx', 'wd1', 'EXTERNAL_CAREER_SITE_IRELAND'), ('Illumina', 'illumina', 'wd1', 'illumina-careers'), ('Catalent', 'catalent', 'wd1', 'External'), ('State Street', 'statestreet', 'wd1', 'Global'), ('Elavon', 'usbank', 'wd1', 'Elavon_Careers'), ('Northern Trust', 'ntrs', 'wd1', 'northerntrust'), ('Deloitte Ireland', 'deloitteie', 'wd3', 'experienced_professionals'), ('PwC Ireland', 'pwc', 'wd3', 'Global_Experienced_Careers'), ('Grant Thornton Ireland', 'iegt', 'wd3', 'GTI_External_Careers_Experienced_Hires_ROI'), ('Aon', 'aon', 'wd1', 'AonCareers'), ('Willis Towers Watson (WTW)', 'wtw', 'wd1', 'WTWCareers'), ('Mercer', 'mmc', 'wd1', 'MMC'), ('Marsh McLennan', 'mmc', 'wd1', 'MMC'), ('Diageo Ireland', 'diageo', 'wd3', 'Diageo_Careers'), ('PIMCO', 'pimco', 'wd1', 'pimco-careers'), ('Intel', 'intel', 'wd1', 'External'), ('Aptiv', 'aptiv', 'wd5', 'APTIV_CAREERS')]

# ---------------------------------------------------------------------------
# SmartRecruiters has a genuinely documented public Postings API --
# https://api.smartrecruiters.com/v1/companies/{companyId}/postings -- but
# it's a per-customer toggle, so not every SmartRecruiters customer has it
# switched on. "smartrecruiters" itself (their own careers page) is
# SmartRecruiters' own documented example and confirmed working. Add more by
# checking https://api.smartrecruiters.com/v1/companies/{guess}/postings
# directly in a browser -- a 200 with JSON means it's enabled for that company.
# ---------------------------------------------------------------------------

SMARTRECRUITERS_COMPANIES = ['smartrecruiters', 'aristanetworks', 'abbvie', 'eurofins', 'version1']
SMARTRECRUITERS_PUBLIC_IDS = {
    "aristanetworks": "AristaNetworks",
    "abbvie": "AbbVie",
    "eurofins": "Eurofins",
    "smartrecruiters": "SmartRecruiters",
    "version1": "Version1",
}

# ---------------------------------------------------------------------------
# Three more genuinely free, unauthenticated ATS APIs. These skew toward
# SMB/mid-market and European scale-ups rather than Fortune-500-scale firms
# (that's who tends to run them) -- useful breadth, but don't expect them to
# unlock the big banks/telcos/national champions still marked "manual" in the
# company list. Ceiling for those: most run either a fully custom in-house
# platform (confirmed for Deutsche Bank -- careers.db.com has no ATS
# fingerprint at all) or an enterprise ATS (SAP SuccessFactors, Oracle
# Taleo/Recruiting Cloud, Phenom, Eightfold) that requires signed/session-
# based requests -- the same class of difficulty as Google/Apple/Meta, which
# is exactly why those three stayed on Apify instead of being reverse-
# engineered. For that remaining bucket the realistic options are: manual
# checking, an Apify actor per company (pay-per-result, browser automation
# handles the hard cases), or a paid cross-ATS aggregator (e.g. fantastic.jobs,
# jobspipe.dev) -- there is no free universal answer for them.
# ---------------------------------------------------------------------------

WORKABLE_COMPANIES = [
    # https://apply.workable.com/api/v1/widget/accounts/{slug} -- add slugs here
]

RECRUITEE_COMPANIES = [
    # https://{slug}.recruitee.com/api/offers/ -- add slugs here
]

PERSONIO_COMPANIES = [
    "dilloneustace",
]

PINPOINT_COMPANIES = ['ericsson', 'kpmg', 'greencore', 'arcadis', 'zendesk', 'synopsys', 'nutanix', 'virgin', 'terumo', 'smith']

# ---------------------------------------------------------------------------
# JSON-LD structured-data scraper -- universal fallback for the ~500-company
# "manual-check" bucket (big banks, telcos, national champions, most Big 4
# outside Accenture) that don't run any of the ATS platforms above.
#
# Most large-company career pages, regardless of ATS, embed a
# schema.org/JobPosting block as JSON-LD in their HTML specifically so
# Google for Jobs can index them -- this includes Workday, SuccessFactors,
# Taleo, and even fully custom sites. Instead of reverse-engineering each
# platform's internal API, this fetches the plain HTML of each career page
# and pulls the embedded structured job data straight out.
#
# This is genuinely free (just an HTTP GET) but NOT guaranteed coverage --
# it only works if the site bothered to add the markup. Expect a mixed hit
# rate: some companies will return real results, many will return zero.
# That's still strictly better than "manual-check only" at zero extra cost.
# List sourced from the "Career Page URL" column of company_shortlist_by_
# region.xlsx, limited to companies not already covered by a dedicated
# scraper above.
# ---------------------------------------------------------------------------

MASTER_COMPANY_CSV = "ireland_job_radar_HARSHIT_MASTER.csv"

UNIVERSITY_CAREER_PAGES = {
    'Trinity College Dublin': {'url': 'https://jobs.tcd.ie', 'location': 'Dublin, Ireland'},
    'University College Cork (UCC)': {'url': 'https://www.ucc.ie/en/hr/work-at-ucc/', 'location': 'Cork, Ireland'},
    'University College Dublin (UCD)': {'url': 'https://www.ucd.ie/workatucd/jobs/', 'location': 'Dublin, Ireland'},
    'Dublin City University (DCU)': {'url': 'https://www.dcu.ie/people/jobs', 'location': 'Dublin, Ireland'},
    'University of Galway': {'url': 'https://www.universityofgalway.ie/about-us/jobs/', 'location': 'Galway, Ireland'},
    'University of Limerick (UL)': {'url': 'https://www.ul.ie/hr/careers', 'location': 'Limerick, Ireland'},
    'Maynooth University': {'url': 'https://www.maynoothuniversity.ie/human-resources/vacancies', 'location': 'Maynooth, Ireland'},
    'Munster Technological University (MTU)': {'url': 'https://www.mtu.ie/vacancies/', 'location': 'Cork / Kerry, Ireland'},
    'RCSI University of Medicine and Health Sciences': {'url': 'https://www.rcsi.com/careers/ireland', 'location': 'Dublin, Ireland'},
    'Technological University Dublin (TU Dublin)': {'url': 'https://www.tudublin.ie/explore/jobs/current-vacancies/', 'location': 'Dublin, Ireland'},
    'Atlantic Technological University (ATU)': {'url': 'https://www.atu.ie/jobs', 'location': 'Ireland'},
    'South East Technological University (SETU)': {'url': 'https://www.setu.ie/about/vacancies', 'location': 'South East, Ireland'},
    'Technological University of the Shannon (TUS)': {'url': 'https://tus.ie/hr/vacancies/', 'location': 'Midlands / Midwest, Ireland'},
}

CAREERS_URL_OVERRIDES = {
    "Apple": "https://jobs.apple.com/en-ie/search",
    "EY Ireland": "https://careers.ey.com/ey",
    "Accenture": "https://www.accenture.com/ie-en/careers/jobsearch",
    "Citi": "https://jobs.citi.com/location/dublin-jobs/287/2963597/2",
}

def _company_key(value: str) -> str:
    value = (value or "").lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)

def _load_company_master_rows():
    """Single source of truth for the Ireland employer universe."""
    import csv
    try:
        with open(MASTER_COMPANY_CSV, encoding="utf-8-sig", newline="") as f:
            return [r for r in csv.DictReader(f) if (r.get("company_name") or "").strip()]
    except Exception as exc:
        print(f"  ! {MASTER_COMPANY_CSV} unavailable: {exc}")
        return []


def _load_company_master():
    return [
        (
            (r.get("company_name") or "").strip(),
            (r.get("career_url") or "").strip(),
            ("university" if (r.get("sector") or "") == "Higher Education / Research" else (r.get("source_type") or "employer")).strip(),
            (r.get("sector") or r.get("category") or "").strip(),
        )
        for r in _load_company_master_rows()
        if str(r.get("include_in_scrape_registry", "yes")).strip().lower() in {"", "yes", "true", "1"}
    ]


def _load_company_master_metadata():
    return {_company_key(r.get("company_name")): r for r in _load_company_master_rows()}


def _registry_url_map():
    out = {
        _company_key(r.get("company_name")): (r.get("career_url") or "").strip()
        for r in _load_company_master_rows()
        if (r.get("company_name") or "").strip() and (r.get("career_url") or "").strip()
    }
    for company, url in CAREERS_URL_OVERRIDES.items():
        out[_company_key(company)] = url
    return out


def build_company_registry(include_cache: bool = False):
    url_map = _registry_url_map()
    master_metadata = _load_company_master_metadata()
    connector_maps = [
        ({_company_key(x): "greenhouse" for x in GREENHOUSE_COMPANIES}),
        ({_company_key(x): "lever" for x in LEVER_COMPANIES}),
        ({_company_key(x): "ashby" for x in ASHBY_COMPANIES}),
        ({_company_key(x[0]): "workday" for x in WORKDAY_COMPANIES}),
        ({_company_key(x): "smartrecruiters" for x in SMARTRECRUITERS_COMPANIES}),
        ({_company_key(x): "workable" for x in WORKABLE_COMPANIES}),
        ({_company_key(x): "recruitee" for x in RECRUITEE_COMPANIES}),
        ({_company_key(x): "personio" for x in PERSONIO_COMPANIES}),
        ({_company_key(x): "pinpoint" for x in PINPOINT_COMPANIES}),
        ({_company_key(x): "direct" for x in DIRECT_COMPANY_CONNECTORS}),
        ({_company_key(x): "phenom" for x in KNOWN_PHENOM_MAPPINGS}),
        ({_company_key(x): "eightfold" for x in KNOWN_EIGHTFOLD_MAPPINGS}),
    ]
    status_by_key = {}

    # High-priority Ireland employers with known connector families. These aliases
    # prevent display-name differences such as "Meta" vs "Meta (Ireland)" from
    # incorrectly placing an employer in Manual Search Needed.
    explicit_status_aliases = {
        "Accenture": "direct",
        "Citi": "direct",
        "Citigroup": "direct",
        "HSBC Ireland": "direct",
        "KPMG Ireland": "direct",
        "Grant Thornton Ireland": "workday",
        "HSBC Ireland": "direct",
        "Version 1": "direct",
        "Meta": "direct",
        "Google": "direct",
        "TikTok": "direct",
        "NetApp": "eightfold",
        "EY Ireland": "direct",
    }
    status_by_key.update({_company_key(k): v for k, v in explicit_status_aliases.items()})
    for mapping in connector_maps:
        status_by_key.update(mapping)

    # Confirmed dynamic ATS mappings discovered in previous runs. Hard-coded
    # mappings remain authoritative; cache only fills companies that otherwise
    # would be manual-check.
    if include_cache:
        try:
            with open("ats_platform_cache.json", encoding="utf-8") as f:
                ats_cache = json.load(f)
            for company_name, info in ats_cache.items():
                if company_name.startswith("__") or not isinstance(info, dict):
                    continue
                platform = info.get("platform")
                key = _company_key(company_name)
                if platform and platform != "none" and key not in status_by_key:
                    status_by_key[key] = platform
        except Exception:
            pass

    registry = []
    for name, master_url, source_type, category in _load_company_master():
        if not name:
            continue
        key = _company_key(name)
        platform = status_by_key.get(key, "manual-check")
        url = CAREERS_URL_OVERRIDES.get(name) or master_url or url_map.get(key)

        # IMPORTANT: do not use substring matching here.
        # "Ergo" must not inherit Fenergo's connector, "Eir" must not inherit
        # another company containing "eir", etc. Dynamic ATS discovery below
        # validates real career-page/ATS endpoints instead.
        meta = master_metadata.get(key, {})
        registry.append({
            "company": name,
            "country": "Ireland",
            "platform": platform,
            "careers_url": url,
            "automatic": platform != "manual-check",
            "source_type": source_type,
            "category": category,
            "dashboard_rank": meta.get("dashboard_rank", ""),
            "harshit_priority_score": meta.get("harshit_priority_score", ""),
            "priority_tier": meta.get("priority_tier", ""),
            "profile_priority": meta.get("profile_priority", ""),
            "best_fit_role_families": meta.get("best_fit_role_families", ""),
            "secondary_finance_score": meta.get("secondary_finance_score", ""),
            "dashboard_default_visibility": meta.get("dashboard_default_visibility", "visible"),
            "dashboard_optional_group": meta.get("dashboard_optional_group", "core_harshit"),
            "source_status": meta.get("source_status", ""),
            "ireland_relevance_basis": meta.get("ireland_relevance_basis", ""),
            "evidence_status": meta.get("evidence_status", ""),
        })
    return registry

def curated_company_key_set():
    keys = {
        _company_key(name)
        for name, _url, _source_type, _category in _load_company_master()
    }

    # Explicit validated employer that is distinct from
    # "SMBC Aviation Capital" in the master CSV.
    keys.add(_company_key("SMBC Group"))

    return keys

def is_curated_company_name(name: str) -> bool:
    key = _company_key(company_display_name(name))
    return key in curated_company_key_set()

def company_display_name(raw: str) -> str:
    key = _company_key(raw)
    for name, _url, _source_type, _category in _load_company_master():
        if _company_key(name) == key:
            return name
    aliases = {
        "nvidia": "NVIDIA",
        "docusign": "DocuSign",
        "microsoft": "Microsoft",
        "linkedin": "LinkedIn",
        "meta": "Meta",
        "google": "Google",
        "apple": "Apple",
        "ey": "EY Ireland",
        "kpmg": "KPMG Ireland",
        "aib": "AIB (Allied Irish Banks)",
        "opentext": "OpenText",
        "quantexa": "Quantexa",
        "klaviyo": "Klaviyo",
        "tines": "Tines",
        "flipdish": "Flipdish",
        "letsgetchecked": "LetsGetChecked",
        "chargebee": "Chargebee",
        "monzo": "Monzo",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "hubspotjobs": "HubSpot",
        "qualtrics": "Qualtrics",
        "huawei": "Huawei Ireland",
        "revenueie": "Revenue",
        "irishrevenue": "Revenue",
        "publicjobsie": "Public Jobs / Civil Service",
        "publicjobs": "Public Jobs / Civil Service",
        "publicjobscivilservice": "Public Jobs / Civil Service",
        "cocacola": "Coca-Cola HBC Ireland",
        "cocacolahbc": "Coca-Cola HBC Ireland",
        "musgrave": "Musgrave Group (SuperValu / Centra)",
        "musgravegroup": "Musgrave Group (SuperValu / Centra)",
        "allianz": "Allianz Ireland",
        "susquehanna": "Susquehanna International Group (SIG)",
        "sig": "Susquehanna International Group (SIG)",
        "susquehannainternationalgroup": "Susquehanna International Group (SIG)",
        "heineken": "Heineken Ireland",
        "iarnrdireann": "Irish Rail (Iarnród Éireann)",
        "irishrail": "Irish Rail (Iarnród Éireann)",
        "irishrailiarnrdireann": "Irish Rail (Iarnród Éireann)",
        "forvismazars": "Forvis Mazars Ireland",
        "forvismazarsireland": "Forvis Mazars Ireland",
        "dpsgroup": "DPS Group (Arcadis)",
        "dpsgrouparcadis": "DPS Group (Arcadis)",

        # Canonical names required by the master Ireland company universe.
        "iarnrdireann": "Irish Rail (Iarnród Éireann)",
        "irishrail": "Irish Rail (Iarnród Éireann)",
        "forvismazars": "Forvis Mazars Ireland",
        "dpsgroup": "DPS Group (Arcadis)",
    }

    # SMBC Group is a separately validated Ireland employer from
    # SMBC Aviation Capital. Keep its official dashboard name.
    if key == "smbcgroup":
        return "SMBC Group"

    return aliases.get(key, raw)


# ---------------------------------------------------------------------------
# External job aggregator APIs -- optional, free, but need YOUR OWN key
# (I can't sign up on your behalf). These cover the "other well-known job
# posting websites" ground -- Indeed and LinkedIn don't offer free public
# search APIs anymore (Indeed closed its Publisher program to new
# applicants; LinkedIn requires a partnership), and scraping their HTML
# directly violates their terms of service and is aggressively bot-blocked,
# so they're not legitimate free options. These three are the real
# free equivalent: documented APIs, free tiers, no ToS violation.
#
# Important honest caveat from earlier: these aggregators crawl the same
# primary ATS sources this scraper already hits, just later -- they add
# BREADTH (companies/regions we don't otherwise cover), not SPEED. Left
# empty/inactive by default; each function is a no-op until you fill in a key.
#
#   Adzuna:    developer.adzuna.com            -- ADZUNA_APP_ID / ADZUNA_APP_KEY
#   Careerjet: careerjet.com/partners           -- CAREERJET_AFFID
#   Jooble:    jooble.org/api/about             -- JOOBLE_API_KEY
# ---------------------------------------------------------------------------

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "").strip()

# Careerjet's API calls this value "affid". Keep both environment names for compatibility.
CAREERJET_AFFID = (
    os.environ.get("CAREERJET_API_KEY", "").strip()
    or os.environ.get("CAREERJET_AFFID", "").strip()
)

JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# Direct-from-company-site sources, attempted with plain HTTP (no proxy).
# These use each company's own internal search API -- the same ones the
# Apify FAANG actor calls. GitHub Actions runners have full outbound internet
# access (unlike a restricted sandbox), so plain requests may well succeed
# here even though they failed when tested from a locked-down environment.
#
# Amazon and Netflix have simple, well-documented JSON search APIs and are
# implemented below. Google, Apple and Meta use heavier client-side
# rendering / GraphQL / session-signed requests that are genuinely fragile
# to reverse-engineer -- they are intentionally NOT attempted here. Keep
# pulling those three from the Apify FAANG actor (still free) rather than
# risk silently-wrong or empty data from a guessed integration.
# ---------------------------------------------------------------------------


# Runtime health for official/direct career sources. A source is marked live when
# its official board loads successfully, even if it currently has zero Ireland jobs.
# This lets the dashboard distinguish a healthy zero-vacancy company from a broken scraper.
CONNECTOR_HEALTH = {}

# A company enters "Live source · 0 jobs" only after the official board has
# been manually/independently verified as healthy and genuinely empty.
# Do NOT infer healthy-zero merely from an HTTP 200 response.
VERIFIED_LIVE_ZERO_COMPANIES = {
    "ASL Aviation Holdings",
    "Central Bank of Ireland",
    "LetsGetChecked",
    "Bayer",
    "BT Ireland",
    "Catalent",
    "Charles River Laboratories",
    "Cloudflare",
    "Eaton",
    "Fenergo",
    "Qualcomm",
    "HSBC Ireland",
    "DXC Technology",
}

def _mark_connector_health(company, live=True, note=None, url=None):
    CONNECTOR_HEALTH[company] = {
        "live": bool(live),
        "note": note or ("Official careers source reachable" if live else "Official careers source failed"),
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

# Direct company career-site connectors. These are intentionally separate from
# ATS discovery because the sites use proprietary/public search surfaces rather
# than a reusable third-party ATS board. A connector is allowed to return zero
# without failing the whole run; the dashboard then exposes it under
# "Zero jobs scraped" for diagnosis.
DIRECT_COMPANY_CONNECTORS = {
    "Irish Rail (Iarnród Éireann)": "irish_rail",
    "Irish Life": "irish_life",
    "Forvis Mazars Ireland": "forvis_mazars",
    "ESB": "esb",
    "DPS Group (Arcadis)": "dps_group",
    "S&P Global": "sp_global",
    "JPMorgan Chase": "jpmorgan",
    "BlackRock": "blackrock",
    "Accenture": "accenture",
    "Citi": "citi",
    "Apple": "apple",
    "Google": "google",
    "Microsoft": "microsoft",
    "Meta": "meta",
    "TikTok": "tiktok",
    "Oracle": "oracle",
    "Red Hat": "redhat",
    "Amazon": "amazon",
    "Netflix": "netflix",
    "EY Ireland": "ey",
    "KPMG Ireland": "kpmg",
    "NetApp": "netapp_browser",
    "Version 1": "version1_browser",
    "HSBC Ireland": "hsbc_browser",
    "EXL": "exl_oracle",
    "Dell Technologies": "dell_oracle_api",
    "Tata Consultancy Services (TCS)": "tcs_candidate_manager",
    "Infosys": "infosys_ireland",
    "Wells Fargo": "wells_fargo_detail_crawl",
    "Vodafone": "vodafone_successfactors",
    "Wipro": "wipro_successfactors",
    "Grant Thornton Ireland": "grant_thornton_oracle",
    "RSM Ireland": "rsm_candidate_manager",
    "KPMG Ireland": "kpmg_avature",
    "Deutsche Bank": "deutsche_bank_workday",
    "DXC Technology": "dxc_cws_api",
    "Capgemini": "capgemini_successfactors_detail",
    "Cognizant": "cognizant_detail_crawl",
    "IBM": "ibm_detail_crawl",
    "Hitachi Energy": "hitachi_detail_crawl",
    "Aon": "aon_detail_crawl",
    "GE HealthCare": "ge_healthcare_phenom",
    "Huawei": "huawei_teamtailor",
    "Becton Dickinson (BD)": "bd_workday_ireland",
    "Becton Dickinson (BD)": "bd_official",
    "AstraZeneca": "astrazeneca_official",
    "Bank of America": "bank_of_america_official",
    "Aiven": "aiven_official",
    "A&L Goodbody": "alg_official",
    "Agilent Technologies": "agilent_workday",
    "Jacobs": "jacobs_official",
    "HP (Hewlett-Packard)": "hp_official",
    "Arup": "arup_official",
    "Deutsche Bank": "deutsche_bank_official",
    "SMBC Group": "smbc_successfactors",
    "Fidelity International": "fidelity_workday",
    "Bloomberg": "bloomberg_avature",
    "Bank of Ireland": "bank_of_ireland_official",
    "Harvey Nash": "harvey_nash_official",
    "ING": "ing_official",
    "Bank of America": "bank_of_america_browser",
    "AIB (Allied Irish Banks)": "aib_browser",
    "Central Bank of Ireland": "central_bank_browser",
    "BNP Paribas": "bnp_paribas_browser",
    "ServiceNow": "servicenow_official",
    "Boston Scientific": "boston_scientific_browser",
    "Johnson & Johnson": "jnj_browser",
    "Johnson Controls": "johnson_controls_browser",
    "Dropbox": "dropbox_browser",
    "Zscaler": "zscaler",
    "Huawei Ireland": "huawei_teamtailor",
    "Honeywell": "honeywell_oracle",
    "Revenue": "revenue_direct",
    "Public Jobs / Civil Service": "publicjobs_oleeo",
    "NTT DATA": "nttdata_successfactors",
    "Ryanair": "ryanair_direct",
    "Coca-Cola HBC Ireland": "cocacola_hbc",
    "PepsiCo": "pepsico_direct",
    "Musgrave Group (SuperValu / Centra)": "musgrave_direct",
    "SAP": "sap_successfactors",
    "Allianz Ireland": "allianz_direct",
    "Susquehanna International Group (SIG)": "sig_direct",
    "Schneider Electric": "schneider_direct",
    "Heineken Ireland": "heineken_successfactors",

    "AECOM": "aecom_official",
    "ABB": "abb_official",
    "AXA Ireland": "axa_official",
    "BNP Paribas Ireland": "bnp_paribas_official",
    "AIG": "aig_workday",
    "Barclays": "barclays_workday",
    "PM Group": "pmgroup_official",
    "Motorola Solutions": "motorola_workday",
    "PTSB": "ptsb_corehr",
    "AMCS Group": "amcs_official",
    "Avolon": "avolon_official",
    "ASL Aviation Holdings": "asl_aviation_official",
    "Alexion Pharmaceuticals": "alexion_astrazeneca_official",
    "Arcadis": "arcadis_eightfold_official",
    "Baker Tilly Ireland": "baker_tilly_official",
    "DocuSign": "docusign_official",
    "Broadcom": "broadcom_verified_details",
    "BT Ireland": "bt_successfactors_official",
    "Fenergo": "fenergo_workable_official",
    "Palo Alto Networks": "palo_alto_official",
    "Guidewire": "guidewire_official",
    "Hewlett Packard Enterprise (HPE)": "hpe_official",
    "IQVIA": "iqvia_official",
    "Proofpoint": "proofpoint_workday",
    "Willis Towers Watson (WTW)": "wtw_official",
    "Auxilion": "auxilion_official",
    "BioMarin": "biomarin_official",
    "CGI": "njoyn_official",
    "Dawn Meats": "icims_official",
    "Decathlon Ireland": "successfactors_official",
    "Alter Domus": "alter_domus_official",
    "Baxter International": "baxter_official",
    "Aer Lingus": "aer_lingus_talentsoft",
}

# Official Irish university vacancy boards use a shared collector.
DIRECT_COMPANY_CONNECTORS.update({name: "university_official" for name in UNIVERSITY_CAREER_PAGES})

# Exact enterprise-platform mappings learned from validated public career-site
# hosts. Unlike guessed ATS slugs, these are revalidated at runtime before use.
KNOWN_EIGHTFOLD_MAPPINGS = {
    "NetApp": "netapp",
    "STMicroelectronics": "stmicroelectronics",
    "Bayer": "bayer",
    "Eaton": "eaton",
}

KNOWN_PHENOM_MAPPINGS = {
    "Hewlett Packard Enterprise (HPE)": "careers.hpe.com|HPE1US",
    "GE HealthCare": "careers.gehealthcare.com|GEVGHLGLOBAL",
    "Cisco": "careers.cisco.com|CISCISGLOBAL",
    "Fiserv": "careers.fiserv.com|FFFYJUS",
    "Roche": "careers.roche.com|ROCHGLOBAL",
    "Merck Group": "jobs.merck.com|MERCUS",
    "Zimmer Biomet": "careers.zimmerbiomet.com|ZBUZBRUS",
    "Convatec": "careers.convatec.com|CONVGLOBAL",
    "Labcorp": "careers.labcorp.com|COVAGLOBAL",
    "Danaher Corporation": "jobs.danaher.com|DANAGLOBAL",
    "Catalent": "careers.catalent.com|CATAUS",
    "Kerry Group": "jobs.kerry.com|KGUKGRGLOBAL",
    "DHL Ireland": "careers.dhl.com|DPDHGLOBAL",
    "Marsh McLennan": "careers.marsh.com|MAMCGLOBAL",
    "Kuehne+Nagel Ireland": "jobs.kuehne-nagel.com|KUNAGLOBAL",
    "State Street": "careers.statestreet.com|STSTGLOBAL",
    "Thermo Fisher Scientific": "jobs.thermofisher.com|TFSCGLOBAL",
}

DIRECT_QUERIES = [""]  # general search engine: retrieve all jobs; filter in the dashboard

# ---------------------------------------------------------------------------
# Role keyword filter (title must contain at least one of these)
# ---------------------------------------------------------------------------

TITLE_KEYWORDS = [
    "data analyst", "data scientist", "business intelligence",
    "business analyst", "consultant", "erp", "retail sales",
    "customer service", "store assistant",
    # Part-time / internship track, matching the Part Time CV's 3 target
    # categories (retail sales / customer service / store & stock assistant,
    # already covered above) plus general part-time and internship phrasing
    # so genuinely part-time or intern postings get caught even when the
    # title doesn't literally say "retail" or "customer service".
    "intern", "internship", "working student", "student job", "placement",
    "graduate", "graduate programme", "graduate program", "trainee",
    "part time", "part-time", "sales assistant", "stock assistant",
    "seasonal", "temporary staff", "christmas temp", "weekend staff",
]

# Used to tag each matched job's employment_type after scraping (see main()).
# Order matters: internship is checked before part-time so "part-time
# internship" style titles land as "internship".
INTERNSHIP_KEYWORDS = ["intern", "internship", "working student", "student job", "placement", "co-op", "co op"]
PART_TIME_KEYWORDS = ["part time", "part-time", "seasonal", "temporary staff", "christmas temp", "weekend staff"]


def employment_type(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in INTERNSHIP_KEYWORDS):
        return "internship"
    if re.search(r"\b(graduate|graduate programme|graduate program|trainee)\b", t):
        return "graduate"
    if re.search(r"\b(contract|fixed[\s-]?term|ftc|agency contract|maternity cover)\b", t):
        return "contract"
    if re.search(r"\b(temporary|seasonal|temp)\b", t):
        return "temporary"
    if any(k in t for k in PART_TIME_KEYWORDS):
        return "part_time"
    return "full_time"


# ---------------------------------------------------------------------------
# Location filter — Ireland-only pipeline (roles in IE or IE-remote/hybrid).
# ---------------------------------------------------------------------------

IRELAND_ONLY = True

IRELAND_LOCATION_KEYWORDS = [
    "ireland", "éire", "eire", "dublin", "cork", "galway", "limerick",
    "waterford", "kildare", "kilkenny", "wexford", "sligo", "mayo",
    "donegal", "kerry", "tipperary", "meath", "louth", "wicklow", "carlow",
    "laois", "offaly", "westmeath", "longford", "roscommon", "cavan",
    "monaghan", "clare", "ennis", "shannon", "athlone", "dundalk", "bray",
    "naas", "tralee", "letterkenny", "drogheda", "swords", "blanchardstown",
    "dún laoghaire", "dun laoghaire", "tallaght", "cork city", "dublin city",
    "irL",  # typo guard — removed below via normalized check
]
# Drop accidental typo token
IRELAND_LOCATION_KEYWORDS = [k for k in IRELAND_LOCATION_KEYWORDS if k != "irL"]

IRELAND_REMOTE_HINTS = [
    # Explicit Ireland-remote forms
    "remote, ireland",
    "remote ireland",
    "remote - ireland",
    "remote – ireland",
    "remote — ireland",
    "ireland remote",
    "ireland - remote",
    "ireland – remote",
    "ireland — remote",
    "remote (ireland)",
    "ireland (remote",
    "remote/ireland",
    "ireland/remote",

    # Hybrid / home-office Ireland
    "remote/hybrid ireland",
    "hybrid ireland",
    "hybrid - ireland",
    "hybrid, ireland",
    "home office - ireland",
    "home office ireland",
    "ireland - home office",
    "ireland home office",

    # Eligibility wording commonly used by remote-first employers
    "based in ireland",
    "located in ireland",
    "residing in ireland",
    "resident in ireland",
    "work from ireland",
    "working from ireland",
    "remote within ireland",
    "remote in ireland",
    "ireland-based",
    "ireland based",
]

# Canonical county/city bucket for the dashboard location filter.
IRELAND_AREA_KEYWORDS = [
    ("dublin", "Dublin"),
    ("cork", "Cork"),
    ("galway", "Galway"),
    ("limerick", "Limerick"),
    ("waterford", "Waterford"),
    ("kildare", "Kildare"),
    ("remote", "Remote / Hybrid"),
    ("hybrid", "Remote / Hybrid"),
]

_REGION_TAG_RE = re.compile(r"\(([^)]+)\)")

IRISH_DOMESTIC_CAREER_PAGES = {
    "aib", "an post", "ryanair", "aer lingus", "eir", "version 1",
    "dunnes stores", "supervalu / musgrave", "musgrave",
    "penneys / primark ireland", "bank of ireland", "ibm ireland", "sap ireland",
}

# Visa / employment-permit language. Negative patterns are evaluated first so
# phrases such as "no visa sponsorship" cannot be misclassified as positive.
VISA_SPONSOR_PATTERNS = [
    r"visa sponsorship (?:is |will be )?available",
    r"will sponsor",
    r"we (?:can|do|are able to) sponsor",
    r"eligible for (?:visa |work permit )?sponsorship",
    r"sponsorship (?:is )?available for (?:this|eligible) (?:role|candidates)",
    r"provide(?:s)? immigration sponsorship",
    r"support (?:a |an )?(?:critical skills )?employment permit",
    r"open to sponsoring",
    r"sponsor(?:ship)? (?:work permit|visa)s? for (?:this|the) role",
    r"critical skills employment permit",
    r"general employment permit",
]
VISA_NO_SPONSOR_PATTERNS = [
    r"unable to (?:offer|provide) (?:visa )?sponsorship",
    r"(?:does not|do not|won't|will not|no) (?:currently )?(?:offer|provide) (?:visa )?sponsorship",
    r"cannot sponsor",
    r"without (?:the need for )?(?:visa )?sponsorship",
    r"must (?:be|already be) (?:legally )?eligible to work .{0,50}without sponsorship",
    r"no visa sponsorship (?:is )?available",
    r"not able to sponsor",
    r"sponsorship (?:is )?not (?:available|offered|provided)",
    r"right to work in ireland without restriction",
]
VISA_SPONSOR_RE = re.compile("|".join(VISA_SPONSOR_PATTERNS), re.IGNORECASE)
VISA_NO_SPONSOR_RE = re.compile("|".join(VISA_NO_SPONSOR_PATTERNS), re.IGNORECASE)

ADZUNA_COUNTRIES = ["ie"] if IRELAND_ONLY else ["gb", "ie", "de", "nl", "at", "es", "pl", "in", "sg", "au", "nz", "ca"]
CAREERJET_LOCALES = ["en_IE"] if IRELAND_ONLY else ["en_GB", "en_IE", "en_US", "en_AU", "en_CA", "en_SG", "en_IN"]

# ---------------------------------------------------------------------------
# Recency filter. Aggregators (Adzuna/Careerjet/Jooble) mostly buy you
# breadth, not speed -- they crawl the same primary ATS sources we do, just
# later. The actual lever for "earliest" is how often THIS scrapes (see
# scrape.yml's cron) plus being able to see, at a glance, how fresh each
# listing is. MAX_AGE_DAYS optionally drops stale postings entirely at
# scrape time; set to None to keep everything and just rely on the
# recency tag + dashboard filter instead.
# ---------------------------------------------------------------------------

MAX_AGE_DAYS = None  # e.g. 30 to auto-drop postings older than a month; None = keep all


def parse_posted_date(value):
    """Best-effort parse of a posting date/recency string into a UTC datetime.
    Handles ISO8601 (Greenhouse/Lever/Ashby/SmartRecruiters/Workable/Recruitee/
    Personio/Amazon/Netflix all return this) and Workday's human-readable
    relative strings ("Posted Today", "Posted 3 Days Ago", "Posted 30+ Days Ago").
    """
    if not value:
        return None
    s = str(value).strip()

    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    sl = s.lower()
    now = datetime.now(timezone.utc)
    if "today" in sl:
        return now
    if "yesterday" in sl:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", sl)
    if m:
        return now - timedelta(days=int(m.group(1)))
    return None


def recency_bucket(posted_dt):
    if not posted_dt:
        return "unknown"
    age = datetime.now(timezone.utc) - posted_dt
    if age <= timedelta(hours=24):
        return "24h"
    if age <= timedelta(days=7):
        return "7d"
    if age <= timedelta(days=30):
        return "30d"
    return "older"


def title_matches(title: str) -> bool:
    """Preference tag only. Never use this to decide whether a job is ingested."""
    t = (title or "").lower()
    return any(k in t for k in TITLE_KEYWORDS)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", str(text))


def ireland_area(location: str) -> str:
    loc = (location or "").lower()
    for keyword, label in IRELAND_AREA_KEYWORDS:
        if keyword in loc:
            return label
    if any(k in loc for k in IRELAND_LOCATION_KEYWORDS):
        return "Ireland (other)"
    return "Ireland (other)"


def classify_visa_sponsorship(*parts: str):
    """Return (status, evidence_snippet) from job text.

    Status is one of sponsors / no_sponsorship / not_mentioned.  The snippet
    gives the dashboard a short auditable explanation instead of a black-box
    flag. Silence remains neutral and is never treated as a rejection signal.
    """
    text = " ".join(_strip_html(p) for p in parts if p)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "not_mentioned", None

    neg = VISA_NO_SPONSOR_RE.search(text)
    if neg:
        start = max(0, neg.start() - 55)
        end = min(len(text), neg.end() + 70)
        return "no_sponsorship", text[start:end].strip()

    pos = VISA_SPONSOR_RE.search(text)
    if pos:
        start = max(0, pos.start() - 55)
        end = min(len(text), pos.end() + 70)
        return "sponsors", text[start:end].strip()

    return "not_mentioned", None


def visa_sponsorship_from_text(*parts: str) -> str:
    return classify_visa_sponsorship(*parts)[0]



def notify_github_issue(jobs):
    """Open one GitHub issue for high-value newly discovered jobs.

    Local runs are a no-op because GITHUB_TOKEN/GITHUB_REPOSITORY are absent.
    Notifications are selective: new + profile match >=55 + sponsorship signal.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return 0

    positive_history = {"rare_positive", "occasional_positive", "frequent_positive"}
    selected = []
    for job in jobs or []:
        if not job.get("new_since_last_check"):
            continue
        try:
            score = int(job.get("candidate_match_score") or 0)
        except Exception:
            score = 0
        if score < 55:
            continue
        hist = job.get("employer_sponsorship_history") or {}
        if not (
            job.get("visa_sponsorship") == "sponsors"
            or int(job.get("official_permits_total") or 0) > 0
            or hist.get("category") in positive_history
        ):
            continue
        selected.append(job)

    if not selected:
        return 0

    lines = []
    for job in selected[:40]:
        permit_total = int(job.get("official_permits_total") or 0)
        hist = job.get("employer_sponsorship_history") or {}
        visa_bits = []
        if job.get("visa_sponsorship") == "sponsors":
            visa_bits.append("posting mentions sponsorship")
        if permit_total:
            visa_bits.append(f"DETE permits: {permit_total}")
        if hist.get("label"):
            visa_bits.append(str(hist.get("label")))
        lines.append(
            f"- **{job.get('company','')}** — "
            f"[{job.get('title','Untitled role')}]({job.get('url','')}) "
            f"({job.get('location','Ireland')}) — "
            f"match {score if False else int(job.get('candidate_match_score') or 0)}% — "
            + ("; ".join(visa_bits) or "sponsorship signal")
        )

    body = "High-value new Ireland jobs found by Job Radar.\n\n" + "\n".join(lines)
    if len(selected) > 40:
        body += f"\n\n…and {len(selected) - 40} more qualifying jobs."

    payload = json.dumps({
        "title": "High-value Ireland job alert — " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + f" ({len(selected)})",
        "body": body,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ireland-job-radar",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if getattr(resp, "status", 201) >= 300:
                print(f"  ! GitHub issue notification HTTP {resp.status}")
                return 0
        print(f"GitHub issue notification: {len(selected)} high-value new jobs")
        return len(selected)
    except Exception as exc:
        print(f"  ! GitHub issue notification failed: {exc}")
        return 0

def load_official_permit_stats(path="official_permit_stats.json"):
    """Load monthly DETE permits-issued-to-companies evidence when present."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sponsorship_history_label(stats):
    """Summarize employer-level evidence without treating silence as negative."""
    total = int(stats.get("total", 0) or 0)
    sponsors = int(stats.get("sponsors", 0) or 0)
    no_sponsorship = int(stats.get("no_sponsorship", 0) or 0)
    if total < 5:
        return {"label": f"Not enough history yet ({total} postings)", "category": "no_data"}
    if sponsors == 0 and no_sponsorship == 0:
        return {"label": f"No sponsorship language found ({total} postings)", "category": "no_data"}
    if sponsors == 0 and no_sponsorship > 0:
        return {"label": f"Explicitly rules out sponsorship in {no_sponsorship} of {total}", "category": "explicit_negative"}
    ratio = sponsors / total
    if ratio < 0.10:
        return {"label": f"Rare sponsorship mentions ({sponsors} of {total})", "category": "rare_positive"}
    if ratio < 0.40:
        return {"label": f"Occasional sponsorship mentions ({sponsors} of {total})", "category": "occasional_positive"}
    return {"label": f"Frequent sponsorship mentions ({sponsors} of {total})", "category": "frequent_positive"}


def jsonld_page_is_ireland(company: str, url: str) -> bool:
    """Keep JSON-LD career pages that target Ireland (skip other regions)."""
    u = (url or "").lower()
    c = (company or "").lower()
    if ".ie/" in u or "/ie/" in u or "en-ie" in u or "en_ie" in u:
        return True
    if "bankofireland" in u or "dublin-ireland" in u:
        return True
    if " ireland" in c or c.endswith(" ireland"):
        return True
    tags = [t.lower() for t in _REGION_TAG_RE.findall(company or "")]
    if tags:
        return any("ireland" in t for t in tags)
    if c in IRISH_DOMESTIC_CAREER_PAGES:
        return True
    return False


def region_ok(location: str) -> bool:
    """Return True only when a vacancy is genuinely available in Republic of Ireland.

    Remote-first employers ARE allowed. A physical Irish office is not required.

    Accepted examples:
        Dublin
        Cork, Ireland
        Ireland
        Remote - Ireland
        Ireland (Remote)
        Home Office - Ireland
        Remote within Ireland

    Rejected examples:
        Remote
        Worldwide Remote
        Europe Remote
        EMEA
        UK / Ireland   # ambiguous multi-country listing
        Northern Ireland
        Dublin, Ohio
    """
    loc = re.sub(r"\\s+", " ", (location or "").strip().lower())

    if IRELAND_ONLY:
        if not loc:
            return False

        # Republic-of-Ireland only.
        foreign_markers = (
            "northern ireland",
            "united states",
            "u.s.a",
            "u.s.",
            " usa",
            "dublin, oh",
            "dublin, ohio",
            "canada",
            "australia",
            "india",
            "singapore",
        )
        if any(marker in loc for marker in foreign_markers):
            return False

        # Avoid ambiguous two-country advertisements unless the location text
        # separately establishes a Republic-of-Ireland base.
        ambiguous_cross_border = (
            "uk / ireland",
            "uk & ireland",
            "uk and ireland",
            "ireland / uk",
            "ireland & uk",
            "ireland and uk",
        )
        if any(marker in loc for marker in ambiguous_cross_border):
            return False

        # Explicit Ireland remote/hybrid/home-office roles are valid.
        if any(hint in loc for hint in IRELAND_REMOTE_HINTS):
            return True

        # Explicit Republic-of-Ireland country wording.
        if "ireland" in loc:
            return True

        # Irish city/county names are valid where no foreign marker exists.
        if any(keyword in loc for keyword in IRELAND_LOCATION_KEYWORDS):
            return True

        # A bare Remote / Europe / EMEA / Worldwide label is NOT sufficient.
        if any(x in loc for x in (
            "remote",
            "hybrid",
            "emea",
            "europe",
            "worldwide",
            "global",
        )):
            return False

        return False

    # Legacy multi-region mode.
    REGION_KEYWORDS = [
        "ireland", "dublin", "cork", "uk", "united kingdom", "london", "europe",
        "eu", "germany", "berlin", "france", "paris", "netherlands", "amsterdam",
        "spain", "madrid", "barcelona", "italy", "milan", "sweden", "stockholm",
        "denmark", "copenhagen", "finland", "helsinki", "norway", "oslo",
        "poland", "warsaw", "portugal", "lisbon", "belgium", "brussels",
        "austria", "vienna", "switzerland", "zurich", "singapore", "dubai",
        "uae", "united arab emirates", "india", "bangalore", "bengaluru",
        "mumbai", "delhi", "hyderabad", "pune", "chennai", "gurgaon", "gurugram",
        "australia", "sydney", "melbourne", "brisbane", "nsw", "queensland",
        "victoria", "new zealand", "auckland", "wellington", "nz",
        "saudi arabia", "riyadh", "jeddah", "qatar", "doha",
    ]
    US_KEYWORDS = ["usa", "united states", "u.s.a", "u.s."]

    if any(k in loc for k in REGION_KEYWORDS):
        return True
    if any(k in loc for k in US_KEYWORDS):
        return "remote" in loc
    if "remote" in loc:
        return True
    return False

# ---------------------------------------------------------------------------
# Sector + country tagging. SECTOR_BY_COMPANY is built from the 'Sector'
# column of company_shortlist_by_region.xlsx (704 companies) so the dashboard
# can filter by industry. Keys are lowercase company names as they appear in
# that spreadsheet -- JSON-LD entries carry a '(Region)' suffix (e.g.
# 'google (ireland)') which matches the ATS-scraper 'company' field for those
# rows exactly; bare-slug entries (greenhouse/lever/ashby/etc., e.g. 'stripe')
# match directly too. sector_for() falls back to stripping any '(...)' suffix
# so a company can still resolve even if the two names drift slightly.
# ---------------------------------------------------------------------------

SECTOR_BY_COMPANY = {
    "a1 telekom austria": "Telecom",
    "ab inbev": "Consumer",
    "abn amro": "Bank",
    "accenture (india)": "Consulting",
    "accenture australia": "Consulting",
    "accenture austria": "Consulting",
    "accenture belgium": "Consulting",
    "accenture canada": "Consulting",
    "accenture finland": "Consulting",
    "accenture germany": "Consulting",
    "accenture hong kong": "Consulting",
    "accenture ireland": "Consulting",
    "accenture malaysia": "Consulting/GBS",
    "accenture netherlands": "Consulting",
    "accenture new zealand": "Consulting",
    "accenture poland": "Consulting/GBS",
    "accenture portugal": "Consulting/GBS",
    "accenture qatar": "Consulting",
    "accenture saudi arabia": "Consulting",
    "accenture singapore": "Consulting",
    "accenture spain": "Consulting",
    "accenture sweden": "Consulting",
    "accenture uae": "Consulting",
    "accenture uk": "Consulting",
    "acs group": "Construction",
    "adani group": "Conglomerate",
    "adidas": "Sports Apparel",
    "adnoc": "Energy",
    "adyen": "Fintech",
    "aegon": "Insurance",
    "aeon malaysia": "Retail",
    "aer lingus": "Airline",
    "ahold delhaize": "Retail",
    "aia group": "Insurance",
    "aia malaysia": "Insurance",
    "aib": "Bank",
    "air canada": "Airline",
    "air india": "Airline",
    "air new zealand": "Airline",
    "airasia": "Airline",
    "airwallex": "Fintech",
    "al meera": "Retail",
    "al othaim": "Retail",
    "al rajhi bank": "Bank",
    "aldar properties": "Real Estate",
    "aldi": "Retail",
    "aldi ireland": "Retail",
    "allegro": "E-commerce",
    "allianz": "Insurance",
    "almarai": "Consumer/FMCG",
    "amadeus": "Travel Tech",
    "amadeus (spain)": "Travel Tech",
    "amazon (germany)": "Tech/Retail/Logistics",
    "amazon (hong kong)": "Tech/Retail",
    "amazon (india)": "Tech/Retail",
    "amazon (ireland)": "Tech/Retail",
    "amazon (saudi arabia)": "Tech/AWS",
    "amazon (singapore)": "Tech/Retail",
    "amazon (spain)": "Tech/Retail/Logistics",
    "amazon (sweden)": "Tech/Retail",
    "amazon (uk)": "Tech/Retail",
    "amazon australia": "Tech/Retail",
    "amazon canada": "Tech/Retail",
    "amazon poland": "Tech/Retail/Logistics",
    "amazon uae": "Tech/Retail",
    "an post": "Postal/Semi-state",
    "andritz": "Industrial/Engineering",
    "anz bank": "Bank",
    "anz new zealand": "Bank",
    "apple (germany)": "Tech",
    "apple (india)": "Tech",
    "apple (ireland)": "Tech",
    "apple (singapore)": "Tech",
    "apple (uk)": "Tech",
    "applegreen": "Retail/Convenience",
    "articulate": "Tech",
    "asb bank": "Bank",
    "asda": "Retail",
    "ashghal (public works authority)": "Government/Semi-state",
    "asml": "Tech/Semiconductor",
    "astrazeneca": "Pharma",
    "atlassian": "Tech",
    "auckland airport": "Aviation/Semi-state",
    "australia post": "Logistics",
    "automattic (wordpress.com)": "Tech",
    "aviva": "Insurance",
    "axel springer": "Media",
    "bae systems": "Defence",
    "bajaj auto": "Automotive",
    "bam group": "Construction",
    "bank of china (hong kong)": "Bank",
    "bank of ireland": "Bank",
    "barclays": "Bank",
    "barclays (singapore)": "Bank",
    "barratt developments": "Construction",
    "base company": "Telecom",
    "basecamp": "Tech",
    "basf": "Chemicals",
    "bawag group": "Bank",
    "bayer": "Pharma",
    "bbc": "Media",
    "bbva": "Bank",
    "belfius": "Bank",
    "bell canada": "Telecom",
    "bhp": "Mining",
    "bloomberg (london)": "Fintech/Data",
    "bmo financial group": "Bank",
    "bmw group": "Automotive",
    "bol.com": "E-commerce",
    "booking.com": "Travel Tech",
    "boots ireland": "Retail",
    "bosch": "Industrial",
    "bpost": "Logistics",
    "brookfield": "Real Estate/Infrastructure",
    "bt group": "Telecom",
    "bt openreach": "Telecom",
    "budimex": "Construction",
    "buffer": "Tech",
    "bunnings (wesfarmers)": "Retail",
    "byju's": "Edtech",
    "bytedance / tiktok (apac)": "Tech",
    "cabify": "Tech",
    "caixabank": "Bank",
    "canada post": "Postal/Semi-state",
    "canadian tire": "Retail",
    "canva": "Tech",
    "capgemini germany": "Consulting/ERP",
    "capgemini india": "Consulting/GBS",
    "capgemini netherlands": "Consulting/ERP",
    "capgemini poland": "Consulting/GBS",
    "capgemini portugal": "Consulting/GBS",
    "capgemini spain": "Consulting/ERP",
    "capgemini uk": "Consulting/ERP",
    "capita": "BPO/Outsourcing",
    "capitaland": "Real Estate",
    "careem": "Tech",
    "cathay pacific": "Airline",
    "ccc": "Shoe Retail",
    "cd projekt": "Gaming",
    "celonis": "Tech/Process Mining",
    "centra / spar (bwg foods)": "Retail/Convenience",
    "centrica / british gas": "Energy",
    "cgi group": "IT Consulting",
    "chalhoub group": "Retail",
    "cibc": "Bank",
    "cimb group": "Bank",
    "cipla": "Pharma",
    "circle k ireland": "Retail/Convenience",
    "cisco poland": "Tech",
    "cisco portugal": "Tech",
    "citi (ireland)": "Bank",
    "city developments limited (cdl)": "Real Estate",
    "close": "Tech",
    "clp group": "Energy",
    "cn rail": "Transport",
    "cofinimmo": "Real Estate",
    "cognizant (india)": "IT Services",
    "coles group": "Retail",
    "colruyt group": "Retail",
    "comarch": "IT/ERP",
    "commercial bank of qatar": "Bank",
    "commerzbank": "Bank",
    "commonwealth bank": "Bank",
    "concentrix (ireland)": "BPO/Call Centre",
    "concentrix india": "BPO/Call Centre",
    "concentrix portugal": "BPO/Call Centre",
    "continental": "Automotive",
    "coolblue": "E-commerce",
    "correos": "Postal",
    "costa coffee": "Hospitality/Food Service",
    "countdown/woolworths nz": "Retail",
    "cred": "Fintech",
    "credit suisse/ubs (krakow gbs)": "Bank/GBS",
    "crh": "Construction Materials",
    "critical techworks (bmw)": "Automotive/Tech",
    "crown resorts": "Hospitality",
    "ctt correios": "Postal",
    "culture amp": "Tech",
    "daa (dublin airport authority)": "Aviation/Semi-state",
    "dalata hotel group": "Hospitality",
    "damac properties": "Real Estate",
    "datacom": "IT Services",
    "dbs (hong kong)": "Bank",
    "dbs bank": "Bank",
    "deel": "HR Tech/EOR",
    "delhaize belgium": "Retail",
    "deliveroo": "Tech",
    "delivery hero": "Tech",
    "deloitte australia": "Consulting",
    "deloitte austria": "Consulting",
    "deloitte belgium": "Consulting",
    "deloitte canada": "Consulting",
    "deloitte finland": "Consulting",
    "deloitte germany": "Consulting",
    "deloitte hong kong": "Consulting",
    "deloitte india": "Consulting",
    "deloitte ireland": "Consulting",
    "deloitte malaysia": "Consulting",
    "deloitte netherlands": "Consulting",
    "deloitte new zealand": "Consulting",
    "deloitte poland": "Consulting",
    "deloitte portugal": "Consulting",
    "deloitte qatar": "Consulting",
    "deloitte saudi arabia": "Consulting",
    "deloitte singapore": "Consulting",
    "deloitte spain": "Consulting",
    "deloitte sweden": "Consulting",
    "deloitte uae": "Consulting",
    "deloitte uk": "Consulting",
    "deutsche bahn": "Transport",
    "deutsche bank": "Bank",
    "deutsche telekom": "Telecom",
    "dhl / deutsche post": "Logistics",
    "dino polska": "Retail",
    "dlf": "Real Estate",
    "doha bank": "Bank",
    "doist": "Tech",
    "dp world": "Logistics",
    "dr. reddy's laboratories": "Pharma",
    "dropbox": "Tech",
    "du (eitc)": "Telecom",
    "dubai duty free": "Retail",
    "dunnes stores": "Retail",
    "dxc technology malaysia": "IT/GBS",
    "e& (etisalat)": "Telecom",
    "e.on": "Energy",
    "ebay/paypal ireland ops": "Tech/Retail",
    "edp": "Energy",
    "eir": "Telecom",
    "el corte ingles": "Retail",
    "elastic": "Tech",
    "ellisdon": "Construction",
    "emaar properties": "Real Estate",
    "emirates group": "Airline",
    "emirates nbd": "Bank",
    "employment hero": "Tech",
    "ericsson": "Telecom/Tech",
    "erste group": "Bank",
    "esb": "Energy/Semi-state",
    "etihad airways": "Airline",
    "etihad rail": "Transport/Semi-state",
    "euroclear": "Fintech",
    "experian": "Data/Analytics",
    "extra (united electronics)": "Retail",
    "ey australia": "Consulting",
    "ey austria": "Consulting",
    "ey belgium": "Consulting",
    "ey canada": "Consulting",
    "ey finland": "Consulting",
    "ey germany": "Consulting",
    "ey hong kong": "Consulting",
    "ey india": "Consulting",
    "ey ireland": "Consulting",
    "ey malaysia": "Consulting",
    "ey netherlands": "Consulting",
    "ey new zealand": "Consulting",
    "ey poland": "Consulting",
    "ey portugal": "Consulting",
    "ey qatar": "Consulting",
    "ey saudi arabia": "Consulting",
    "ey singapore": "Consulting",
    "ey spain": "Consulting",
    "ey sweden": "Consulting",
    "ey uae": "Consulting",
    "ey uk": "Consulting",
    "farfetch": "E-commerce",
    "feedzai": "Fintech",
    "fenergo": "Fintech",
    "ferrovial": "Construction/Infrastructure",
    "finnair": "Airline",
    "first abu dhabi bank (fab)": "Bank",
    "fisher & paykel healthcare": "Health Tech",
    "fletcher building": "Construction",
    "flipkart": "E-commerce",
    "flynas": "Airline",
    "fonterra": "Consumer/FMCG",
    "foodstuffs nz": "Retail",
    "fortum": "Energy",
    "fresenius": "Healthcare",
    "freshworks": "Tech",
    "galp energia": "Energy",
    "genpact": "BPO/GBS",
    "genting group": "Conglomerate/Hospitality",
    "gitlab": "Tech",
    "glanbia": "FMCG",
    "glenveagh properties": "Real Estate",
    "glovo": "Tech",
    "goldman sachs (singapore)": "Bank",
    "goldman sachs (uk)": "Bank",
    "google (apac hq)": "Tech",
    "google (australia)": "Tech",
    "google (canada)": "Tech",
    "google (germany)": "Tech",
    "google (hong kong)": "Tech",
    "google (india)": "Tech",
    "google (ireland)": "Tech",
    "google (uae)": "Tech",
    "google (uk)": "Tech",
    "google malaysia": "Tech",
    "google poland": "Tech",
    "grab": "Tech",
    "grab malaysia": "Tech",
    "great eastern": "Insurance",
    "great-west lifeco": "Insurance",
    "greggs": "Food Retail",
    "grifols": "Pharma",
    "groww": "Fintech",
    "gsk": "Pharma",
    "h&m group": "Retail",
    "halter": "Tech",
    "hamad international airport (matar)": "Aviation/Ops",
    "hang seng bank": "Bank",
    "hashicorp": "Tech",
    "hcltech": "IT Services",
    "hdfc bank": "Bank",
    "heineken": "Consumer",
    "hellofresh": "Consumer/Tech",
    "help scout": "Tech",
    "hema": "Retail",
    "hindustan unilever": "FMCG",
    "hsbc": "Bank",
    "hsbc (hong kong)": "Bank",
    "hsbc electronic data processing (malaysia)": "Bank/GBS",
    "hsbc gsc krakow": "Bank/GBS",
    "hugo boss": "Fashion Retail",
    "iag insurance": "Insurance",
    "iberdrola": "Energy",
    "ibm canada": "Tech",
    "ibm india": "Tech",
    "ibm ireland": "Tech",
    "ibm malaysia": "Tech/GBS",
    "ibm poland": "Tech/GBS",
    "ibm uk": "Tech",
    "ica gruppen": "Retail",
    "icici bank": "Bank",
    "ihg hotels & resorts": "Hospitality",
    "ijm corporation": "Construction",
    "ikea (sweden)": "Retail",
    "indeed (ireland)": "Tech",
    "indian hotels company (taj hotels)": "Hospitality",
    "indigo": "Airline",
    "inditex (zara)": "Retail",
    "indra": "IT/Defense",
    "infineon": "Semiconductor",
    "infosys": "IT Services",
    "ing": "Bank",
    "ing belgium": "Bank",
    "ing poland": "Bank",
    "inpost": "Logistics",
    "intact financial": "Insurance",
    "intercom": "Tech",
    "irish life": "Insurance",
    "irish rail (iarnrod eireann)": "Transport/Semi-state",
    "itc limited": "FMCG",
    "itv": "Media",
    "j.p. morgan (ireland)": "Bank",
    "jahez": "Tech",
    "jardine matheson": "Conglomerate",
    "jarir bookstore": "Retail",
    "jd sports": "Sports Retail",
    "jeronimo martins": "Retail",
    "john lewis partnership": "Retail",
    "jpmorgan chase (india)": "Bank",
    "jpmorgan chase (uk)": "Bank",
    "judo bank": "Bank",
    "jumbo supermarkten": "Retail",
    "kbc group": "Bank",
    "keppel corporation": "Conglomerate",
    "kerry group": "FMCG",
    "kesko": "Retail",
    "king (activision blizzard)": "Gaming",
    "kingspan group": "Construction",
    "klarna": "Fintech",
    "klm": "Airline",
    "kone": "Industrial",
    "kpmg australia": "Consulting",
    "kpmg austria": "Consulting",
    "kpmg belgium": "Consulting",
    "kpmg canada": "Consulting",
    "kpmg finland": "Consulting",
    "kpmg germany": "Consulting",
    "kpmg hong kong": "Consulting",
    "kpmg india": "Consulting",
    "kpmg ireland": "Consulting",
    "kpmg malaysia": "Consulting",
    "kpmg netherlands": "Consulting",
    "kpmg new zealand": "Consulting",
    "kpmg poland": "Consulting",
    "kpmg portugal": "Consulting",
    "kpmg qatar": "Consulting",
    "kpmg saudi arabia": "Consulting",
    "kpmg singapore": "Consulting",
    "kpmg spain": "Consulting",
    "kpmg sweden": "Consulting",
    "kpmg uae": "Consulting",
    "kpmg uk": "Consulting",
    "kpn": "Telecom",
    "larsen & toubro": "Construction/Engineering",
    "legal & general": "Insurance",
    "lendlease": "Construction/Real Estate",
    "lidl / schwarz group": "Retail",
    "lidl ireland": "Retail",
    "lightspeed commerce": "Tech",
    "linkedin (ireland)": "Tech",
    "lloyds banking group": "Bank",
    "loblaw companies": "Retail",
    "lpp (reserved)": "Fashion Retail",
    "lufthansa": "Airline",
    "lulu group (uae)": "Retail",
    "lulu hypermarket qatar": "Retail",
    "luxoft (dxc)": "IT/GBS",
    "mahindra group": "Automotive/Conglomerate",
    "mahle": "Automotive",
    "majid al futtaim": "Retail/Real Estate",
    "manulife": "Insurance",
    "manulife hong kong": "Insurance",
    "mapfre": "Insurance",
    "marina bay sands": "Hospitality",
    "marks & spencer": "Retail",
    "mashreq bank": "Bank",
    "mastercard (ireland)": "Fintech",
    "mastercard (uk)": "Fintech",
    "maybank": "Bank",
    "mbank": "Bank",
    "mcdonald's ireland": "Hospitality/Food Service",
    "mcdonald's uk": "Hospitality/Food Service",
    "meesho": "E-commerce",
    "melia hotels international": "Hospitality",
    "mercadona": "Retail",
    "mercedes-benz group": "Automotive",
    "mercedes-benz.io": "Automotive/Tech",
    "merck kgaa": "Pharma",
    "meta (ireland)": "Tech",
    "meta (singapore)": "Tech",
    "meta (uae)": "Tech",
    "meta (uk)": "Tech",
    "metro ag": "Retail/Wholesale",
    "metro inc.": "Retail",
    "microsoft (apac hq)": "Tech",
    "microsoft (hong kong)": "Tech",
    "microsoft (india)": "Tech",
    "microsoft (ireland)": "Tech",
    "microsoft (uk)": "Tech",
    "microsoft australia": "Tech",
    "microsoft canada": "Tech",
    "microsoft germany": "Tech",
    "microsoft malaysia": "Tech",
    "microsoft netherlands": "Tech",
    "microsoft poland": "Tech",
    "microsoft saudi arabia": "Tech",
    "microsoft uae": "Tech",
    "mirvac": "Real Estate",
    "mollie": "Fintech",
    "monzo": "Fintech",
    "morrisons": "Retail",
    "mota-engil": "Construction",
    "msheireb properties": "Real Estate",
    "mtr corporation": "Transport/Semi-state",
    "munich re": "Insurance",
    "myntra": "E-commerce",
    "n26": "Fintech",
    "nab": "Bank",
    "national grid": "Energy",
    "natixis (porto gbs)": "Bank/GBS",
    "natwest group": "Bank",
    "ncc": "Construction",
    "neom": "Giga-project",
    "neste": "Energy",
    "new world development": "Real Estate",
    "next plc": "Retail",
    "nh hotel group": "Hospitality",
    "nn group": "Insurance",
    "nokia": "Tech/Telecom",
    "noon": "E-commerce",
    "nordea (finland)": "Bank",
    "nordea (sweden)": "Bank",
    "nordea poland (gbs)": "Bank/GBS",
    "ntuc fairprice": "Retail",
    "nvidia (india)": "Tech",
    "nz post": "Postal/Semi-state",
    "obb (austrian federal railways)": "Transport/Semi-state",
    "ocado": "Retail/Tech",
    "ocbc bank": "Bank",
    "ola": "Tech",
    "omv": "Energy",
    "ooredoo": "Telecom",
    "op financial group": "Bank/Insurance",
    "optus": "Telecom",
    "oracle (india)": "Tech/ERP",
    "oracle (ireland)": "Tech/ERP",
    "oracle (uk)": "Tech/ERP",
    "orange polska": "Telecom",
    "outsystems": "Tech",
    "panda retail company": "Retail",
    "parknshop / as watson group": "Retail",
    "paypal (ireland)": "Fintech",
    "pccw": "Telecom",
    "pcl construction": "Construction",
    "penneys / primark ireland": "Retail",
    "permanent tsb": "Bank",
    "persimmon homes": "Construction",
    "personio": "HR Tech",
    "pestana hotel group": "Hospitality",
    "petronas": "Energy",
    "pge polska grupa energetyczna": "Energy",
    "philips": "Tech/Health",
    "phonepe": "Fintech",
    "pkn orlen": "Energy",
    "pko bank polski": "Bank",
    "poczta polska": "Postal",
    "porr": "Construction",
    "pos malaysia": "Postal",
    "posti group": "Postal",
    "postnl": "Postal/Logistics",
    "postnord": "Postal/Logistics",
    "primark": "Retail",
    "propertyguru": "Tech",
    "proximus": "Telecom",
    "prudential hong kong": "Insurance",
    "public bank": "Bank",
    "puma": "Sports Apparel",
    "pwc australia": "Consulting",
    "pwc austria": "Consulting",
    "pwc belgium": "Consulting",
    "pwc canada": "Consulting",
    "pwc finland": "Consulting",
    "pwc germany": "Consulting",
    "pwc hong kong": "Consulting",
    "pwc india": "Consulting",
    "pwc ireland": "Consulting",
    "pwc malaysia": "Consulting",
    "pwc netherlands": "Consulting",
    "pwc new zealand": "Consulting",
    "pwc poland": "Consulting",
    "pwc portugal": "Consulting",
    "pwc qatar": "Consulting",
    "pwc saudi arabia": "Consulting",
    "pwc singapore": "Consulting",
    "pwc spain": "Consulting",
    "pwc sweden": "Consulting",
    "pwc uae": "Consulting",
    "pwc uk": "Consulting",
    "pzu": "Insurance",
    "qantas": "Airline",
    "qatar airways": "Airline",
    "qatar islamic bank": "Bank",
    "qatarenergy": "Energy",
    "qiddiya": "Giga-project",
    "qnb group": "Bank",
    "rabobank": "Bank",
    "radisson hotel group (ireland)": "Hospitality",
    "raiffeisen bank international": "Bank",
    "randstad": "Staffing/HR",
    "razorpay": "Fintech",
    "rbc (royal bank of canada)": "Bank",
    "red bull": "Consumer",
    "red sea global": "Giga-project",
    "reliance retail": "Retail",
    "repsol": "Energy",
    "revolut": "Fintech",
    "rewe austria (billa/merkur)": "Retail",
    "rewe group": "Retail",
    "rio tinto": "Mining",
    "riyad bank": "Bank",
    "rogers communications": "Telecom",
    "rolls-royce": "Industrial",
    "roshn": "Real Estate/Giga-project",
    "royal mail": "Postal/Logistics",
    "ryanair": "Airline",
    "s group (s-ryhma)": "Retail",
    "sabic": "Chemicals",
    "safetyculture": "Tech",
    "sainsbury's": "Retail",
    "salesforce (india)": "Tech",
    "salesforce (ireland)": "Tech",
    "salesforce (uae)": "Tech",
    "salesforce (uk)": "Tech",
    "salesforce australia": "Tech",
    "salesforce canada": "Tech",
    "salesforce germany": "Tech",
    "salesforce singapore": "Tech",
    "santander": "Bank",
    "santander bank polska": "Bank",
    "sap": "Tech/ERP",
    "sap ireland": "Tech/ERP",
    "sap labs india": "Tech/ERP",
    "sas airlines": "Airline",
    "saudi aramco": "Energy",
    "saudi electricity company": "Utility/Semi-state",
    "saudi national bank (snb)": "Bank",
    "saudia (airline)": "Airline",
    "scandic hotels": "Hospitality",
    "schiphol group": "Aviation/Semi-state",
    "scotiabank": "Bank",
    "sea limited (shopee/garena)": "Tech",
    "seb": "Bank",
    "shell (nl)": "Energy",
    "shell business operations krakow": "Energy/GBS",
    "shopee malaysia": "E-commerce",
    "shopify": "Tech/E-commerce",
    "siemens": "Industrial/Tech",
    "sime darby": "Conglomerate",
    "sinch": "Tech",
    "singtel": "Telecom",
    "skanska": "Construction",
    "sky city": "Hospitality",
    "sobeys / empire company": "Retail",
    "softcat": "IT Reseller",
    "software ag": "Tech/ERP",
    "solvay": "Chemicals",
    "sonae": "Retail/Conglomerate",
    "spar austria": "Retail",
    "spark new zealand": "Telecom",
    "spotify": "Tech",
    "standard chartered (hk)": "Bank",
    "starbucks ireland": "Hospitality/Food Service",
    "state street (ireland)": "Fintech/GBS",
    "state street (krakow gbs)": "GBS/Fintech",
    "stc (saudi telecom)": "Telecom",
    "stockland": "Real Estate",
    "stora enso": "Forestry/Materials",
    "strabag": "Construction",
    "stripe": "Fintech",
    "sun hung kai properties": "Real Estate",
    "sun life": "Insurance",
    "sun pharma": "Pharma",
    "suncorp": "Insurance/Bank",
    "sunway group": "Construction/Property",
    "supercell": "Gaming",
    "supervalu / musgrave": "Retail",
    "swedbank": "Bank",
    "swift": "Fintech",
    "swiggy": "Tech",
    "talabat": "Tech",
    "talkdesk": "Tech",
    "tap air portugal": "Airline",
    "tata motors": "Automotive",
    "tata steel": "Manufacturing",
    "taylor wimpey": "Construction",
    "tcs": "IT Services",
    "td bank group": "Bank",
    "telefonica": "Telecom",
    "teleperformance (ireland)": "BPO/Call Centre",
    "teleperformance india": "BPO/Call Centre",
    "teleperformance portugal": "BPO/Call Centre",
    "teleperformance spain": "BPO/Call Centre",
    "teleperformance uk": "BPO/Call Centre",
    "telia company": "Telecom",
    "telstra": "Telecom",
    "telus": "Telecom",
    "tesco": "Retail",
    "tesco ireland": "Retail",
    "three ireland": "Telecom",
    "tiktok (ireland)": "Tech",
    "titan company": "Retail/Consumer",
    "tomtom": "Tech",
    "toptal": "Tech/Staffing",
    "trade me": "Tech",
    "trade republic": "Fintech",
    "tui group": "Travel/Hospitality",
    "twilio": "Tech",
    "uber (netherlands ops)": "Tech",
    "ucb": "Pharma",
    "umicore": "Materials",
    "union coop": "Retail",
    "uniqa insurance group": "Insurance",
    "uob": "Bank",
    "upm": "Forestry/Materials",
    "van der valk": "Hospitality",
    "verbund": "Energy",
    "version 1": "IT Consulting/ERP",
    "vienna insurance group": "Insurance",
    "vodafone portugal": "Telecom",
    "vodafone qatar": "Telecom",
    "vodafone uk": "Telecom",
    "voestalpine": "Industrial",
    "volkerwessels": "Construction",
    "volkswagen group": "Automotive",
    "volvo group": "Automotive/Industrial",
    "vonovia": "Real Estate",
    "wartsila": "Industrial",
    "wayflyer": "Fintech",
    "wealthsimple": "Fintech",
    "wesfarmers": "Retail/Conglomerate",
    "westpac": "Bank",
    "whitbread / premier inn": "Hospitality",
    "wipro": "IT Services",
    "wise": "Fintech",
    "wolt (doordash)": "Tech",
    "wolters kluwer": "Info Services",
    "woolworths group": "Retail",
    "workday (ireland)": "Tech/ERP",
    "xero": "Tech/ERP",
    "yit": "Construction",
    "zabka": "Retail",
    "zalando": "E-commerce",
    "zapier": "Tech",
    "zendesk (ireland)": "Tech",
    "zf friedrichshafen": "Automotive",
    "zoho": "Tech/ERP",
    "zomato": "Tech",
    "zurich insurance ireland": "Insurance"
}

# Secondary lookup keyed by company name with any trailing "(Region)" suffix
# stripped, e.g. "google (ireland)" -> "google". Built once at import time.
_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")
BASE_SECTOR_BY_COMPANY = {}
for _k, _v in SECTOR_BY_COMPANY.items():
    _base = _SUFFIX_RE.sub("", _k).strip()
    BASE_SECTOR_BY_COMPANY.setdefault(_base, _v)


def sector_for(company: str) -> str:
    """Best-effort industry sector for a company, used to tag/filter jobs."""
    if not company:
        return "Other"
    key = company.strip().lower()
    if key in SECTOR_BY_COMPANY:
        return SECTOR_BY_COMPANY[key]
    base = _SUFFIX_RE.sub("", key).strip()
    if base in BASE_SECTOR_BY_COMPANY:
        return BASE_SECTOR_BY_COMPANY[base]
    return "Other"


# ISO alpha-3 country codes some ATSs (mostly Workday) append after a comma,
# e.g. "Dubai, ARE" -- checked before the keyword scan below since it's exact.
ISO3_TO_COUNTRY = {
    "ARE": "UAE", "GBR": "UK", "DEU": "Germany", "IRL": "Ireland",
    "IND": "India", "SGP": "Singapore", "AUS": "Australia", "NZL": "New Zealand",
    "CAN": "Canada", "USA": "United States", "SAU": "Saudi Arabia", "QAT": "Qatar",
    "MYS": "Malaysia", "HKG": "Hong Kong", "POL": "Poland", "PRT": "Portugal",
    "NLD": "Netherlands", "AUT": "Austria", "BEL": "Belgium", "ESP": "Spain",
    "SWE": "Sweden", "FIN": "Finland", "FRA": "France", "ITA": "Italy",
    "DNK": "Denmark", "NOR": "Norway", "CHE": "Switzerland",
}

# Keyword -> canonical country name, checked in order (first match wins) if
# the ISO3 check above doesn't hit. Mirrors REGION_KEYWORDS but resolves to a
# single display name per country instead of a yes/no.
COUNTRY_KEYWORDS = [
    ("ireland", "Ireland"), ("dublin", "Ireland"), ("cork", "Ireland"),
    ("united kingdom", "UK"), ("london", "UK"), ("england", "UK"),
    ("scotland", "UK"), ("wales", "UK"), ("uk", "UK"),
    ("germany", "Germany"), ("berlin", "Germany"), ("munich", "Germany"),
    ("frankfurt", "Germany"), ("hamburg", "Germany"), ("cologne", "Germany"),
    ("netherlands", "Netherlands"), ("amsterdam", "Netherlands"),
    ("france", "France"), ("paris", "France"),
    ("spain", "Spain"), ("madrid", "Spain"), ("barcelona", "Spain"),
    ("italy", "Italy"), ("milan", "Italy"), ("milano", "Italy"), ("rome", "Italy"),
    ("roma", "Italy"), ("florence", "Italy"), ("firenze", "Italy"),
    ("sweden", "Sweden"), ("stockholm", "Sweden"),
    ("denmark", "Denmark"), ("copenhagen", "Denmark"),
    ("finland", "Finland"), ("helsinki", "Finland"),
    ("norway", "Norway"), ("oslo", "Norway"),
    ("poland", "Poland"), ("warsaw", "Poland"), ("krakow", "Poland"), ("kraków", "Poland"),
    ("portugal", "Portugal"), ("lisbon", "Portugal"), ("lisboa", "Portugal"), ("porto", "Portugal"),
    ("belgium", "Belgium"), ("brussels", "Belgium"),
    ("austria", "Austria"), ("vienna", "Austria"),
    ("switzerland", "Switzerland"), ("zurich", "Switzerland"), ("zürich", "Switzerland"),
    ("singapore", "Singapore"),
    ("united arab emirates", "UAE"), ("dubai", "UAE"), ("abu dhabi", "UAE"), ("uae", "UAE"),
    ("saudi arabia", "Saudi Arabia"), ("riyadh", "Saudi Arabia"), ("jeddah", "Saudi Arabia"),
    ("qatar", "Qatar"), ("doha", "Qatar"),
    ("india", "India"), ("bangalore", "India"), ("bengaluru", "India"), ("mumbai", "India"),
    ("delhi", "India"), ("hyderabad", "India"), ("pune", "India"), ("chennai", "India"),
    ("gurgaon", "India"), ("gurugram", "India"),
    ("hong kong", "Hong Kong"),
    ("malaysia", "Malaysia"), ("kuala lumpur", "Malaysia"),
    ("australia", "Australia"), ("sydney", "Australia"), ("melbourne", "Australia"),
    ("brisbane", "Australia"), ("perth", "Australia"),
    ("new zealand", "New Zealand"), ("auckland", "New Zealand"), ("wellington", "New Zealand"),
    ("canada", "Canada"), ("toronto", "Canada"), ("ontario", "Canada"),
    ("vancouver", "Canada"), ("montreal", "Canada"),
    ("united states", "United States"), ("usa", "United States"), ("u.s.a", "United States"),
    ("u.s.", "United States"),
]


def country_from_location(location: str) -> str:
    """Best-effort country name for a job, parsed from its location string
    (not the company) since one company posts across many countries."""
    if not location:
        return "Other"
    loc = location.strip()
    loc_lower = loc.lower()

    last_part = loc.split(",")[-1].strip().upper()
    if last_part in ISO3_TO_COUNTRY:
        return ISO3_TO_COUNTRY[last_part]

    for keyword, country in COUNTRY_KEYWORDS:
        if keyword in loc_lower:
            return country

    if "remote" in loc_lower:
        return "Remote / Other"

    return "Other"


def fetch_json(url: str, timeout: int = 20):
    try:
        sess = _session()
        if not sess:
            return None
        resp = sess.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (job-dashboard-bot)"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ! fetch failed for {url}: {e}")
        return None


def scrape_greenhouse(slug: str):
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not data or "jobs" not in data:
        return []
    _mark_connector_health(
        company_display_name(slug), True, "Official Greenhouse board loaded",
        f"https://boards.greenhouse.io/{slug}",
    )
    out = []
    for j in data["jobs"]:
        title = j.get("title", "")
        location = (j.get("location") or {}).get("name", "")
        if region_ok(location):
            content_html = j.get("content") or ""
            out.append({
                "company": slug,
                "ats": "greenhouse",
                "title": title,
                "location": location,
                "url": j.get("absolute_url"),
                "updated_at": j.get("updated_at"),
                "description_text": _strip_html(content_html),
            })
    return out


def scrape_lever(slug: str):
    data = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not data or not isinstance(data, list):
        return []
    out = []
    for j in data:
        title = j.get("text", "")
        cats = j.get("categories") or {}
        location = cats.get("location", "")
        if region_ok(location):
            created = j.get("createdAt")
            created_iso = None
            if created:
                try:
                    created_iso = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            out.append({
                "company": slug,
                "ats": "lever",
                "title": title,
                "location": location,
                "url": j.get("hostedUrl"),
                "updated_at": created_iso,
            })
    return out


def scrape_ashby(slug: str):
    data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not data:
        return []
    jobs = data.get("jobs") or data.get("jobPostings") or []
    out = []
    for j in jobs:
        title = j.get("title", "")
        location = j.get("location", "") or j.get("locationName", "")
        if j.get("isRemote") and "remote" not in (location or "").lower():
            location = f"{location} (Remote)".strip()
        if region_ok(location):
            out.append({
                "company": slug,
                "ats": "ashby",
                "title": title,
                "location": location,
                "url": j.get("jobUrl") or j.get("applyUrl"),
                "updated_at": j.get("publishedAt"),
            })
    return out


def _workday_headers(tenant: str, wd_host: str, site: str):
    origin = f"https://{tenant}.{wd_host}.myworkdayjobs.com"
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36"),
        "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Origin": origin,
        "Referer": f"{origin}/en-US/{site}",
        "X-Requested-With": "XMLHttpRequest",
    }


def _workday_session():
    if cffi_requests is not None:
        return cffi_requests.Session(impersonate="chrome124")
    return requests.Session() if requests is not None else None


def _workday_post(session, url, headers, facets, limit, offset, search_text=""):
    variants = [
        {"appliedFacets": facets, "limit": limit, "offset": offset, "searchText": search_text},
        {"appliedFacets": facets, "limit": limit, "offset": offset},
        {"limit": limit, "offset": offset, "searchText": search_text},
    ]
    last = None
    for payload in variants:
        try:
            r = session.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {(r.text or '')[:120]}"
            if r.status_code == 429:
                time.sleep(3)
                break
        except Exception as exc:
            last = str(exc)
        time.sleep(0.35)
    if last:
        print(f"  ! Workday request failed: {last}")
    return None


def scrape_workday(company: str, tenant: str, wd_host: str, site: str, max_pages: int = 25, search_text: str = ""):
    """Workday collector with the browser-like session/facet strategy used by Suman.

    The important Accenture fix is the standard Workday Ireland country facet.
    We still run region_ok() on every result so an ignored facet can never leak
    global jobs into the Ireland dashboard.
    """
    origin = f"https://{tenant}.{wd_host}.myworkdayjobs.com"
    api = f"{origin}/wday/cxs/{tenant}/{site}/jobs"
    headers = _workday_headers(tenant, wd_host, site)
    session = _workday_session()
    if session is None:
        return []

    # Warm the tenant like a real browser before its CXS endpoint is called.
    try:
        session.get(f"{origin}/en-US/{site}", headers=headers, timeout=20)
        time.sleep(0.4)
    except Exception:
        pass

    # Workday's standard Ireland country reference ID. This is the key fix for
    # large global tenants such as Accenture where sampling an unfiltered board
    # can completely miss Ireland. Keep searchText as a second narrowing signal.
    ireland_facets = {"locationCountry": ["04a05835925f45b3a59406a2a6b72c8a"]}
    facets = {}
    probe = _workday_post(session, api, headers, ireland_facets, 20, 0, search_text or "")
    if probe is not None:
        try:
            total = int((probe.json() or {}).get("total") or 0)
        except Exception:
            total = 0
        if 0 < total <= 150:
            facets = ireland_facets

    out, seen = [], set()
    offset = 0
    page_size = 20
    effective_search = search_text or ("Ireland" if not facets else "")
    page_cap = max_pages if facets else min(max_pages, 12)

    for _ in range(page_cap):
        resp = _workday_post(session, api, headers, facets, page_size, offset, effective_search)
        if resp is None:
            break
        try:
            data = resp.json() or {}
        except Exception:
            break
        postings = data.get("jobPostings") or []
        if not postings:
            break

        for j in postings:
            title = (j.get("title") or "").strip()
            location = (j.get("locationsText") or "").strip()
            if not location:
                bullets = j.get("bulletFields") or []
                location = str(bullets[0]).strip() if bullets else ""
            # Safety net: always verify Ireland client-side.
            if not title or not region_ok(location):
                continue
            path = j.get("externalPath") or ""
            url = f"{origin}/{site}{path}" if path else f"{origin}/{site}"
            key = (title.lower(), location.lower(), url.split("?")[0])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "company": company,
                "ats": "workday",
                "title": title,
                "raw_location": location,
                "location": location,
                "url": url,
                "updated_at": j.get("postedOn"),
            })

        if len(postings) < page_size:
            break
        offset += page_size
        time.sleep(0.25)

    return out


def smartrecruiters_public_url(company_id: str, job_id: str, title: str):
    public_id = SMARTRECRUITERS_PUBLIC_IDS.get(company_id.lower(), company_id)
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "job"
    return f"https://jobs.smartrecruiters.com/{public_id}/{job_id}-{title_slug}"


def scrape_smartrecruiters(company_id: str, max_pages: int = 15):
    """SmartRecruiters public postings API with robust pagination/location handling."""
    out = []
    offset = 0
    page_size = 100
    sess = _session()

    for _ in range(max_pages):
        url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
        data = None
        if sess:
            try:
                resp = sess.get(
                    url,
                    params={"limit": page_size, "offset": offset},
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                else:
                    print(f"  ! SmartRecruiters/{company_id}: HTTP {resp.status_code}")
            except Exception as exc:
                print(f"  ! SmartRecruiters/{company_id}: {exc}")
        else:
            data = fetch_json(f"{url}?limit={page_size}&offset={offset}")

        if not data or "content" not in data:
            break

        postings = data.get("content") or []
        for j in postings:
            title = j.get("name", "")
            loc = j.get("location") or {}
            country = loc.get("country") or loc.get("countryCode") or ""
            location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), country]))
            if loc.get("remote"):
                location = f"{location} (Remote)".strip(", ")
            if region_ok(location):
                job_id = str(j.get("id") or "")

                out.append({
                    "company": company_id,
                    "ats": "smartrecruiters",
                    "title": title,
                    "location": location,
                    "url": smartrecruiters_public_url(company_id, job_id, title),
                    "updated_at": j.get("releasedDate"),
                })

        total = data.get("totalFound")
        offset += len(postings)
        if not postings or len(postings) < page_size or (isinstance(total, int) and offset >= total):
            break
        time.sleep(0.3)

    return out


def scrape_workable(slug: str):
    data = fetch_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        title = j.get("title", "")
        location = j.get("location", {}) or {}
        loc_str = ", ".join(filter(None, [
            location.get("city"), location.get("region"), location.get("country"),
        ]))
        if location.get("telecommuting"):
            loc_str = f"{loc_str} (Remote)".strip(", ")
        if region_ok(loc_str):
            out.append({
                "company": slug,
                "ats": "workable",
                "title": title,
                "location": loc_str,
                "url": j.get("url") or j.get("shortlink"),
                "updated_at": j.get("published_on") or j.get("created_at"),
            })
    return out


def scrape_recruitee(slug: str):
    data = fetch_json(f"https://{slug}.recruitee.com/api/offers/")
    if not data or "offers" not in data:
        return []
    out = []
    for j in data["offers"]:
        title = j.get("title", "")
        location = j.get("location", "") or j.get("city", "")
        if j.get("remote"):
            location = f"{location} (Remote)".strip(", ")
        if region_ok(location):
            out.append({
                "company": slug,
                "ats": "recruitee",
                "title": title,
                "location": location,
                "url": j.get("careers_url"),
                "updated_at": j.get("created_at"),
            })
    return out


def scrape_personio(slug: str):
    url = f"https://{slug}.jobs.personio.de/xml?language=en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (job-dashboard-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_text = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ! fetch failed for {url}: {e}")
        return []

    out = []
    for m in re.finditer(r"<position>(.*?)</position>", xml_text, re.DOTALL):
        block = m.group(1)

        def field(name):
            fm = re.search(rf"<{name}><!\[CDATA\[(.*?)\]\]></{name}>", block, re.DOTALL) \
                 or re.search(rf"<{name}>(.*?)</{name}>", block, re.DOTALL)
            return fm.group(1).strip() if fm else ""

        title = field("name")
        location = ", ".join(filter(None, [field("office"), field("city")]))
        if region_ok(location):
            out.append({
                "company": slug,
                "ats": "personio",
                "title": title,
                "location": location,
                "url": field("careerSiteUrl") or None,
                "updated_at": field("createdAt"),
            })
    return out



def scrape_pinpoint(slug: str):
    data = fetch_json(f"https://{slug}.pinpointhq.com/postings.json")
    if not data:
        return []
    postings = data if isinstance(data, list) else (data.get("data") or data.get("jobs") or data.get("postings") or [])
    out = []
    for j in postings:
        if not isinstance(j, dict):
            continue
        title = j.get("title") or j.get("name") or ""
        location = j.get("location") or j.get("location_name") or ""
        if isinstance(location, dict):
            location = ", ".join(filter(None, [location.get("city"), location.get("region"), location.get("country")]))
        if region_ok(str(location)):
            out.append({
                "company": slug,
                "ats": "pinpoint",
                "title": title,
                "location": str(location),
                "url": j.get("url") or j.get("apply_url") or j.get("external_url"),
                "updated_at": j.get("published_at") or j.get("created_at") or j.get("updated_at"),
                "description_text": _strip_html(j.get("description") or ""),
            })
    return out

def _jsonld_location(job_location):
    """jobLocation can be a dict, a list of dicts, or absent entirely."""
    def one(loc):
        if not isinstance(loc, dict):
            return ""
        addr = loc.get("address")
        if isinstance(addr, dict):
            return ", ".join(filter(None, [
                addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry"),
            ]))
        if isinstance(addr, str):
            return addr
        return ""

    if isinstance(job_location, list):
        parts = [one(l) for l in job_location]
        return " / ".join(p for p in parts if p)
    return one(job_location)



# ---------------------------------------------------------------------------
# Dynamic ATS discovery + cached coverage expansion
# ---------------------------------------------------------------------------

ATS_PROBE_VERSION = 36
ATS_PROBE_LIMIT = int(os.environ.get("ATS_PROBE_LIMIT", "60"))
ATS_CACHE_PATH = "ats_platform_cache.json"

_CORP_WORDS = re.compile(r"\b(?:limited|ltd|plc|inc|incorporated|corporation|corp|company|group|holdings|ireland|international)\b", re.I)
_EF_GROUP_ID_RE = re.compile(r'_EF_GROUP_ID[\'\"]?\]?\s*[=:]\s*[\'\"]([^\'\"]+)[\'\"]')
_PHENOM_REFNUM_RE = re.compile(r'"refNum"\s*:\s*"([A-Za-z0-9_-]+)"')


def candidate_slugs(company_name: str):
    """Bounded ATS-board slug guesses. Exact cached mappings are tried first."""
    base = re.sub(r"\([^)]*\)", " ", company_name or "")
    base = _CORP_WORDS.sub(" ", base)
    words = re.findall(r"[a-zA-Z0-9]+", base.lower())
    if not words:
        return []
    cands = []
    joined = "".join(words)
    dashed = "-".join(words)
    for x in (joined, dashed, words[0], joined + "jobs", joined + "careers"):
        # Very short guesses create false-positive boards (e.g. "abb", "eir").
        # Require 4+ characters unless the full normalized company name itself is short.
        min_len = 2 if len(joined) <= 3 and x == joined else 4
        if x and x not in cands and len(x) >= min_len:
            cands.append(x)
    # Parenthetical brand is often the actual ATS slug, e.g. VMware (Broadcom).
    for paren in re.findall(r"\(([^)]*)\)", company_name or ""):
        pwords = re.findall(r"[a-zA-Z0-9]+", paren.lower())
        if pwords:
            x = "".join(pwords)
            if x not in cands:
                cands.append(x)
    return cands[:6]



def _careers_page_ats_candidates(company: str, careers_url: str, sess):
    """Discover ATS identifiers from the employer's actual careers page.

    This is deliberately preferred over guessed slugs. It follows redirects and
    scans public HTML for known ATS hosts, then validates every candidate.
    """
    if not sess or not careers_url:
        return []
    try:
        r = sess.get(careers_url, timeout=15, allow_redirects=True)
        if r.status_code >= 400:
            return []
        text = (r.text or "") + "\n" + str(r.url or "")
    except Exception:
        return []

    patterns = [
        ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)"),
        ("lever", r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
        ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"),
        ("smartrecruiters", r"(?:jobs\.)?smartrecruiters\.com/([A-Za-z0-9_-]+)"),
        ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
        ("recruitee", r"https?://([A-Za-z0-9-]+)\.recruitee\.com"),
        ("personio", r"https?://([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
        ("pinpoint", r"https?://([A-Za-z0-9-]+)\.pinpointhq\.com"),
        ("eightfold", r"https?://([A-Za-z0-9-]+)\.eightfold\.ai"),
    ]

    out = []
    seen = set()

    # Workday needs tenant + wd host + site rather than one slug.
    # Encode it as tenant|wd-host|site for the common cached-mapping interface.
    workday_patterns = [
        r"https?://([A-Za-z0-9_-]+)\.(wd\d+|wd5|wd3|wd1|wd2)\.myworkdayjobs\.com/([A-Za-z0-9_-]+)",
        r"/wday/cxs/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/jobs",
    ]
    # Full public Workday URL.
    for m in re.finditer(workday_patterns[0], text, re.I):
        tenant, wd_host, site = m.group(1), m.group(2), m.group(3)
        key = ("workday", f"{tenant}|{wd_host}|{site}".lower())
        if key not in seen:
            seen.add(key)
            out.append(("workday", f"{tenant}|{wd_host}|{site}"))

    # CXS paths may be present without the hostname; infer host/tenant from the
    # final careers URL if possible.
    host_match = re.search(
        r"https?://([A-Za-z0-9_-]+)\.(wd\d+|wd5|wd3|wd1|wd2)\.myworkdayjobs\.com",
        text, re.I
    )
    if host_match:
        tenant0, wd_host0 = host_match.group(1), host_match.group(2)
        for m in re.finditer(workday_patterns[1], text, re.I):
            tenant, site = m.group(1), m.group(2)
            tenant = tenant or tenant0
            key = ("workday", f"{tenant}|{wd_host0}|{site}".lower())
            if key not in seen:
                seen.add(key)
                out.append(("workday", f"{tenant}|{wd_host0}|{site}"))


    for platform, pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            slug = m.group(1).strip()
            key = (platform, slug.lower())
            if not slug or key in seen:
                continue
            seen.add(key)
            out.append((platform, slug))
    return out


def _session():
    if requests is None:
        return None
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (compatible; IrelandJobRadar/2.0)"})
    return sess


def _probe_platform(platform: str, slug: str, sess, allow_empty: bool = False) -> bool:
    """Validate that a slug really resolves to an ATS board. Does NOT require an Ireland vacancy."""
    if not sess or not slug:
        return False
    try:
        if platform == "workday":
            if not slug or slug.count("|") != 2:
                return False
            tenant, wd_host, site = slug.split("|", 2)
            url = f"https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            rr = sess.post(
                url,
                json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                timeout=12,
            )
            if rr.status_code != 200:
                return False
            data = rr.json()
            return isinstance(data, dict) and ("jobPostings" in data or "total" in data)
        if platform == "greenhouse":
            r=sess.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=10)
            return r.status_code == 200 and isinstance(r.json().get("jobs"), list)
        if platform == "lever":
            r=sess.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=10)
            return r.status_code == 200 and isinstance(r.json(), list)
        if platform == "smartrecruiters":
            r=sess.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", timeout=10)
            if r.status_code != 200:
                return False
            d = r.json()
            if not isinstance(d, dict) or "content" not in d:
                return False
            # SmartRecruiters can return a structurally valid empty payload for
            # guessed/non-proving identifiers. An empty API response alone does
            # NOT establish that this is the employer's tenant. Empty feeds are
            # accepted only when the tenant was fingerprinted from the employer's
            # own careers page (allow_empty=True).
            content = d.get("content") or []
            total = d.get("totalFound")
            return bool(content) or (isinstance(total, int) and total > 0) or allow_empty
        if platform == "ashby":
            r=sess.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=10)
            d=r.json() if r.status_code == 200 else {}
            return r.status_code == 200 and isinstance(d, dict) and ("jobs" in d or "jobPostings" in d)
        if platform == "recruitee":
            r=sess.get(f"https://{slug}.recruitee.com/api/offers/", timeout=10)
            d=r.json() if r.status_code == 200 else {}
            return r.status_code == 200 and isinstance(d, dict) and "offers" in d
        if platform == "personio":
            r=sess.get(f"https://{slug}.jobs.personio.de/xml?language=en", timeout=10)
            return r.status_code == 200 and ("<position" in r.text or "<workzag-jobs" in r.text)
        if platform == "pinpoint":
            r=sess.get(f"https://{slug}.pinpointhq.com/postings.json", timeout=10)
            if r.status_code != 200: return False
            d=r.json()
            return isinstance(d, (list, dict))
        if platform == "eightfold":
            r=sess.get(f"https://{slug}.eightfold.ai/careers", timeout=10)
            if r.status_code != 200: return False
            m=_EF_GROUP_ID_RE.search(r.text)
            if not m: return False
            rr=sess.get(f"https://{slug}.eightfold.ai/api/pcsx/search", params={"domain":m.group(1),"query":"","location":"","start":0}, timeout=10)
            return rr.status_code == 200 and isinstance(rr.json(), dict)
        if platform == "phenom":
            if "|" not in slug: return False
            domain, refnum = slug.split("|",1)
            payload={"lang":"en_global","deviceType":"desktop","country":"global","pageName":"search-results","size":1,"from":0,"jobs":True,"counts":True,"all_fields":["category","country","city","type"],"clearAll":False,"jdsource":"facets","isSliderEnable":False,"pageId":"page20","siteType":"external","keywords":"","global":True,"selected_fields":{},"sort":{"order":"desc","field":"postedDate"},"locationData":{},"refNum":refnum,"ddoKey":"refineSearch"}
            rr=sess.post(f"https://{domain}/widgets",json=payload,timeout=15)
            return rr.status_code == 200 and isinstance(rr.json(), dict)
    except Exception:
        return False
    return False


def _scrape_eightfold(company: str, slug: str, sess):
    out=[]
    try:
        page=sess.get(f"https://{slug}.eightfold.ai/careers",timeout=10)
        m=_EF_GROUP_ID_RE.search(page.text)
        if not m: return out
        start=0
        seen_ids=set()
        for _ in range(20):
            r=sess.get(f"https://{slug}.eightfold.ai/api/pcsx/search",params={"domain":m.group(1),"query":"","location":"","start":start},timeout=15)
            if r.status_code!=200: break
            d=r.json(); jobs=d.get("positions") or d.get("results") or []
            if not jobs: break
            new=0
            for j in jobs:
                jid=str(j.get("id") or j.get("position_id") or j.get("canonicalPositionUrl") or "")
                if jid and jid in seen_ids: continue
                if jid: seen_ids.add(jid)
                new+=1
                loc=j.get("location") or j.get("locations") or j.get("city") or ""
                if isinstance(loc,list): loc=", ".join(str(x) for x in loc)
                loc=str(loc)
                if not region_ok(loc): continue
                posted=j.get("t_create") or j.get("start_date") or j.get("posted_date")
                updated=None
                if posted:
                    try:
                        updated=datetime.fromtimestamp(posted,timezone.utc).isoformat() if isinstance(posted,(int,float)) else str(posted)
                    except Exception: updated=str(posted)
                out.append({"company":company,"ats":"eightfold","title":j.get("name") or j.get("title") or "","location":loc,"url":j.get("canonicalPositionUrl") or j.get("apply_url") or f"https://{slug}.eightfold.ai/careers/job/{jid}","updated_at":updated,"description_text":_strip_html(j.get("job_description") or j.get("description") or "")})
            if new==0: break
            start += len(jobs)
            if len(jobs)<10: break
    except Exception as e:
        print(f"  ! eightfold/{slug}: {e}")
    return out


def _scrape_phenom(company: str, slug: str, sess):
    if "|" not in slug: return []
    domain, refnum=slug.split("|",1)
    out=[]; offset=0
    for _ in range(25):
        payload={"lang":"en_global","deviceType":"desktop","country":"global","pageName":"search-results","size":20,"from":offset,"jobs":True,"counts":True,"all_fields":["category","country","city","type"],"clearAll":False,"jdsource":"facets","isSliderEnable":False,"pageId":"page20","siteType":"external","keywords":"","global":True,"selected_fields":{},"sort":{"order":"desc","field":"postedDate"},"locationData":{},"refNum":refnum,"ddoKey":"refineSearch"}
        try:
            r=sess.post(f"https://{domain}/widgets",json=payload,timeout=15)
            if r.status_code!=200: break
            jobs=((r.json().get("refineSearch") or {}).get("data") or {}).get("jobs") or []
        except Exception: break
        if not jobs: break
        for j in jobs:
            loc=j.get("locationDisplay") or j.get("cityStateCountry") or j.get("cityCountry") or j.get("city") or ""
            if not region_ok(str(loc)): continue
            jid=j.get("jobId") or j.get("id") or ""
            url=j.get("applyUrl") or j.get("jdUrl") or f"https://{domain}/job/{jid}"
            out.append({"company":company,"ats":"phenom","title":j.get("title") or j.get("jobTitle") or "","location":str(loc),"url":url,"updated_at":j.get("postedDate"),"description_text":_strip_html(j.get("descriptionTeaser") or j.get("description") or "")})
        if len(jobs)<20: break
        offset += len(jobs)
    return out


def _scrape_cached_mapping(company: str, platform: str, slug: str, sess):
    try:
        if platform == "workday":
            if not slug or slug.count("|") != 2:
                return []
            tenant, wd_host, site = slug.split("|", 2)
            jobs = scrape_workday(company, tenant, wd_host, site)
        elif platform == "greenhouse": jobs=scrape_greenhouse(slug)
        elif platform == "lever": jobs=scrape_lever(slug)
        elif platform == "smartrecruiters": jobs=scrape_smartrecruiters(slug)
        elif platform == "ashby": jobs=scrape_ashby(slug)
        elif platform == "recruitee": jobs=scrape_recruitee(slug)
        elif platform == "personio": jobs=scrape_personio(slug)
        elif platform == "pinpoint": jobs=scrape_pinpoint(slug)
        elif platform == "workable": jobs=scrape_workable(slug)
        elif platform == "eightfold": jobs=_scrape_eightfold(company,slug,sess)
        elif platform == "phenom": jobs=_scrape_phenom(company,slug,sess)
        else: return []
        for j in jobs:
            j["company"] = company
        return jobs
    except Exception as e:
        print(f"  ! cached {platform}/{company}: {e}")
        return []


def discover_and_scrape_manual(company_registry):
    """Convert unresolved companies to automatic ATS coverage over time.

    Cached confirmed mappings are reused every run. Cached misses are retained,
    but a probe-version bump automatically rechecks them after discovery logic
    changes. A bounded number of never-probed companies is attempted per run so
    the GitHub Action remains predictable rather than turning into a multi-hour crawl.
    """
    sess=_session()
    if not sess:
        print("  ! requests not installed; dynamic ATS discovery skipped")
        return [], {}
    try:
        with open(ATS_CACHE_PATH,encoding="utf-8") as f: raw=json.load(f)
        stored_version=raw.pop("__probe_version__",0)
        cache=raw
        if stored_version != ATS_PROBE_VERSION:
            # Discovery semantics changed: discard ALL dynamically discovered
            # mappings, including old positive guesses. Keeping historical
            # positives here is what allowed false SmartRecruiters tenants to
            # survive indefinitely. Explicit hard-coded mappings are re-seeded
            # below and remain authoritative.
            cache = {}
    except Exception:
        cache={}

    # Seed exact enterprise mappings, but still validate each endpoint before use.
    for company, slug in KNOWN_EIGHTFOLD_MAPPINGS.items():
        cache.setdefault(company, {"platform": "eightfold", "slug": slug})
    for company, slug in KNOWN_PHENOM_MAPPINGS.items():
        cache.setdefault(company, {"platform": "phenom", "slug": slug})

    dynamic_jobs=[]; confirmed={}; fresh=0
    platforms=("workday","greenhouse","lever","smartrecruiters","ashby","workable","recruitee","personio","pinpoint","eightfold")

    for entry in company_registry:
        company=entry["company"]
        info=cache.get(company) if isinstance(cache.get(company),dict) else None
        platform=info.get("platform") if info else None
        slug=info.get("slug") if info else None

        if platform and platform != "none":
            # Never trust a stale/guessed cache entry without validating its endpoint.
            if not _probe_platform(platform,slug,sess):
                cache.pop(company,None); platform=slug=None
            else:
                confirmed[company]={"platform":platform,"slug":slug}
        elif platform == "none":
            continue

        if not platform:
            # Always inspect the real careers page. This is one targeted request
            # and is much safer than guessed tenants. The old code skipped this
            # entirely once ATS_PROBE_LIMIT was reached, leaving hundreds manual.
            for plat, cand in _careers_page_ats_candidates(
                company, entry.get("careers_url") or "", sess
            ):
                if plat in platforms and _probe_platform(plat, cand, sess, allow_empty=True):
                    platform, slug = plat, cand
                    break

            # Expensive guessed-slug probing stays bounded.
            if not platform and fresh < ATS_PROBE_LIMIT:
                fresh += 1
                guess_platforms = tuple(
                    p for p in platforms
                    if p not in {"smartrecruiters", "workday"}
                )
                for cand in candidate_slugs(company):
                    for plat in guess_platforms:
                        if _probe_platform(plat,cand,sess):
                            platform,slug=plat,cand
                            break
                    if platform:
                        break

            cache[company]={"platform":platform or "none","slug":slug,"probe_version":ATS_PROBE_VERSION}
            if platform:
                confirmed[company]={"platform":platform,"slug":slug}
                print(f"  + discovered {company}: {platform}/{slug}")

        if platform:
            jobs=_scrape_cached_mapping(company,platform,slug,sess)
            dynamic_jobs.extend(jobs)
            print(f"dynamic/{company} [{platform}]: {len(jobs)} Ireland jobs")

    cache["__probe_version__"]=ATS_PROBE_VERSION
    with open(ATS_CACHE_PATH,"w",encoding="utf-8") as f:
        json.dump(cache,f,indent=2)
    print(f"Dynamic ATS discovery: {len(confirmed)} confirmed cached/discovered platforms; {fresh} new companies probed this run")
    return dynamic_jobs, confirmed

JSONLD_CACHE_PATH = "jsonld_cache.json"
JSONLD_NEGATIVE_CACHE_TTL_SECONDS = int(os.environ.get("JSONLD_NEGATIVE_CACHE_TTL_SECONDS", str(24 * 3600)))
BROWSER_SCRAPE_CACHE_PATH = "browser_scrape_cache.json"
BROWSER_SCRAPE_CACHE_TTL_SECONDS = int(os.environ.get("BROWSER_SCRAPE_CACHE_TTL_SECONDS", "600"))
_SAFE_CACHE_LOCK = threading.Lock()

def _load_safe_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _write_safe_cache(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _scrape_jsonld_uncached(company: str, url: str):
    if not url:
        return []
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (job-dashboard-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ! fetch failed for {url}: {e}")
        return []

    out = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text, re.DOTALL | re.IGNORECASE,
    ):
        block = m.group(1).strip()
        try:
            data = json.loads(block)
        except ValueError:
            continue

        candidates = data if isinstance(data, list) else [data]
        expanded = []
        for c in candidates:
            if isinstance(c, dict) and isinstance(c.get("@graph"), list):
                expanded.extend(c["@graph"])
            else:
                expanded.append(c)

        for c in expanded:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            is_job = t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)
            if not is_job:
                continue

            title = c.get("title", "")
            location = _jsonld_location(c.get("jobLocation"))
            if c.get("jobLocationType") == "TELECOMMUTE" or c.get("applicantLocationRequirements"):
                location = f"{location} (Remote)".strip(", ")

            if region_ok(location):
                desc = c.get("description") or ""
                out.append({
                    "company": company,
                    "ats": "jsonld",
                    "title": title,
                    "location": location,
                    "url": c.get("url") or url,
                    "updated_at": c.get("datePosted"),
                    "description_text": _strip_html(desc) if isinstance(desc, str) else "",
                })
    return out


def scrape_jsonld(company: str, url: str):
    """Cache only recent confirmed-empty JSON-LD pages; positive pages stay fresh."""
    if not url:
        return []
    key = hashlib.sha256(f"{_company_key(company)}|{url}".encode("utf-8")).hexdigest()
    with _SAFE_CACHE_LOCK:
        cache = _load_safe_cache(JSONLD_CACHE_PATH)
        entry = cache.get(key) if isinstance(cache.get(key), dict) else None
    if entry and not entry.get("has_data"):
        age = time.time() - float(entry.get("checked_at") or 0)
        if age < JSONLD_NEGATIVE_CACHE_TTL_SECONDS:
            return []
    jobs = _scrape_jsonld_uncached(company, url)
    with _SAFE_CACHE_LOCK:
        cache = _load_safe_cache(JSONLD_CACHE_PATH)
        cache[key] = {"company": company, "url": url, "checked_at": time.time(), "has_data": bool(jobs)}
        _write_safe_cache(JSONLD_CACHE_PATH, cache)
    return jobs



def _employer_name_match(target: str, returned: str) -> bool:
    """Conservative company-name match for targeted aggregator rescue."""
    a = _company_key(target)
    b = _company_key(returned)
    if not a or not b or b == "unknown":
        return False
    if a == b:
        return True
    # Strip common legal/branding noise, but do not accept tiny ambiguous tokens.
    noise = {
        "ireland","irish","limited","ltd","plc","inc","incorporated","corporation",
        "corp","company","group","holdings","international","technologies","technology"
    }
    def tokens(s):
        return [x for x in re.findall(r"[a-z0-9]+", s.lower()) if x not in noise and len(x) > 1]
    ta, tb = set(tokens(target)), set(tokens(returned))
    if not ta or not tb:
        return False
    overlap = ta & tb
    return bool(overlap) and (
        len(overlap) >= 2
        or (len(ta) == 1 and next(iter(ta)) in tb and len(next(iter(ta))) >= 4)
        or (len(tb) == 1 and next(iter(tb)) in ta and len(next(iter(tb))) >= 4)
    )


PRIORITY_IRELAND_EMPLOYERS = [
    "Accenture", "Citi", "HSBC Ireland",
    "KPMG Ireland", "Grant Thornton Ireland",
    "Version 1", "Meta", "Google", "TikTok",
    "NetApp", "EY Ireland", "Microsoft", "Oracle", "Red Hat",
]

def rescue_priority_ireland_employers(results):
    """Targeted fallback for important employers whose custom/client-rendered
    career search can defeat generic HTML discovery. Direct/ATS data remains
    preferred; aggregators are queried only when the employer has no live result.
    """
    live = {
        _company_key(company_display_name(j.get("company", "")))
        for j in results if j.get("company")
    }
    rescued = []
    for company in PRIORITY_IRELAND_EMPLOYERS:
        if SCRAPE_MODE == "fast" and TARGET_COMPANIES and not _targeted(company):
            continue
        key = _company_key(company)
        if key in live:
            continue
        candidates = []
        try:
            if JOOBLE_API_KEY:
                candidates.extend(scrape_jooble(company, "Ireland"))
            if ADZUNA_APP_ID and ADZUNA_APP_KEY:
                candidates.extend(scrape_adzuna("ie", company))
            if CAREERJET_AFFID:
                candidates.extend(scrape_careerjet("en_IE", company))
        except Exception as e:
            print(f"  ! priority-rescue/{company}: {e}")
            continue

        accepted = 0
        for j in candidates:
            returned = company_display_name(j.get("company", ""))
            returned_key = _company_key(returned)
            target_key = _company_key(company)
            citi_alias = (
                target_key == _company_key("Citi")
                and returned_key in {
                    _company_key("Citi"),
                    _company_key("Citigroup"),
                    _company_key("Citigroup Inc"),
                    _company_key("Citi Ireland"),
                }
            )
            if not citi_alias and not _employer_name_match(company, returned):
                continue
            j["company"] = company
            j["coverage_rescue"] = True
            j["source_detail"] = (j.get("source_detail") or j.get("ats") or "aggregator") + " · priority employer rescue"
            rescued.append(j)
            accepted += 1
        if accepted:
            live.add(key)
            print(f"priority-rescue/{company}: {accepted} Ireland jobs")
    return rescued

def rescue_zero_companies_with_aggregators(results, company_registry, max_companies=80):
    """Target aggregators by employer for configured connectors that returned zero.

    The old broad aggregator query only fetched the first page of Ireland results,
    so it could never reliably rescue employers such as Accenture, HubSpot, etc.
    This pass searches each zero-result employer explicitly and only keeps records
    whose returned employer name conservatively matches the target company.
    """
    direct_sources = {
        "direct","workday","greenhouse","lever","ashby","smartrecruiters",
        "workable","recruitee","personio","pinpoint","phenom","eightfold",
        "oracle","jsonld"
    }
    live = {
        _company_key(company_display_name(j.get("company","")))
        for j in results
        if (j.get("ats") or "").lower() in direct_sources
    }
    targets = [
        x["company"] for x in company_registry
        if x.get("automatic") and _company_key(x["company"]) not in live
    ][:max_companies]

    rescued = []
    for company in targets:
        found = []
        # One targeted provider per company keeps request count/API usage bounded.
        try:
            if JOOBLE_API_KEY:
                found = scrape_jooble(company, "Ireland")
            elif CAREERJET_AFFID:
                found = scrape_careerjet("en_IE", company)
            elif ADZUNA_APP_ID and ADZUNA_APP_KEY:
                found = scrape_adzuna("ie", company)
        except Exception as e:
            print(f"  ! zero-rescue/{company}: {e}")
            continue

        accepted = 0
        for j in found:
            if not _employer_name_match(company, j.get("company","")):
                continue
            j["aggregator_company"] = j.get("company")
            j["company"] = company
            j["coverage_rescue"] = True
            rescued.append(j)
            accepted += 1
        if accepted:
            print(f"zero-rescue/{company}: {accepted} Ireland jobs")
        time.sleep(0.12)

    print(f"Zero-company targeted rescue: {len(rescued)} jobs across {len(targets)} checked companies")
    return rescued

def scrape_adzuna(country: str, query: str):
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        f"?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
        f"&what={urllib.parse.quote(query)}&results_per_page=50&content-type=application/json"
    )
    data = fetch_json(url)
    if not data or "results" not in data:
        return []
    out = []
    for j in data["results"]:
        title = j.get("title", "")
        location = (j.get("location") or {}).get("display_name", "")
        if region_ok(location):
            out.append({
                "company": (j.get("company") or {}).get("display_name", "unknown"),
                "ats": "adzuna",
                "title": title,
                "location": location,
                "url": j.get("redirect_url"),
                "updated_at": j.get("created"),
                "description_text": j.get("description") or "",
                "source_type": "aggregator",
            })
    return out


def scrape_careerjet(locale: str, query: str):
    if not CAREERJET_AFFID:
        return []
    url = (
        "https://public-api.careerjet.net/search"
        f"?locale_code={locale}&keywords={urllib.parse.quote(query)}"
        f"&affid={CAREERJET_AFFID}&pagesize=50&user_ip=127.0.0.1&user_agent=job-dashboard-bot"
    )
    data = fetch_json(url)
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        title = j.get("title", "")
        location = j.get("locations", "")
        if region_ok(location):
            out.append({
                "company": j.get("company", "unknown"),
                "ats": "careerjet",
                "title": title,
                "location": location,
                "url": j.get("url"),
                "updated_at": j.get("date"),
                "description_text": j.get("description") or j.get("snippet") or "",
                "source_type": "aggregator",
            })
    return out


def scrape_jooble(keywords: str, location: str = ""):
    if not JOOBLE_API_KEY:
        return []
    url = f"https://jooble.org/api/{JOOBLE_API_KEY}"
    payload = json.dumps({"keywords": keywords, "location": location}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (job-dashboard-bot)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        print(f"  ! fetch failed for jooble ({keywords}): {e}")
        return []
    out = []
    for j in (data or {}).get("jobs", []):
        title = j.get("title", "")
        loc = j.get("location", "")
        if region_ok(loc):
            out.append({
                "company": j.get("company", "unknown"),
                "ats": "jooble",
                "title": title,
                "location": loc,
                "url": j.get("link"),
                "updated_at": j.get("updated"),
                "description_text": j.get("snippet") or j.get("description") or "",
                "source_type": "aggregator",
            })
    return out


def scrape_amazon(query: str):
    """Fetch Amazon Ireland jobs directly.

    The old implementation requested only the first 50 GLOBAL Amazon jobs and
    then filtered for Ireland. That can easily return zero even while Amazon
    has many Dublin/Cork vacancies. Use Amazon's Ireland location parameters
    and paginate instead.
    """
    out = []
    seen = set()
    limit = 100

    for offset in range(0, 600, limit):
        params = {
            "base_query": query or "",
            "loc_query": "Ireland",
            "country": "IRL",
            "result_limit": limit,
            "offset": offset,
        }
        url = "https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(params)
        data = fetch_json(url)
        if not data or "jobs" not in data:
            break

        jobs = data.get("jobs") or []
        if not jobs:
            break

        added_this_page = 0
        for j in jobs:
            title = j.get("title", "")
            location = j.get("normalized_location", "") or j.get("location", "")
            # Amazon often uses Dublin, D, IRL; region_ok handles IRL/Ireland.
            if not region_ok(location):
                continue

            path = j.get("job_path", "")
            job_id = str(j.get("id_icims") or j.get("id") or path or "")
            key = job_id or (title.lower(), location.lower())
            if key in seen:
                continue
            seen.add(key)

            out.append({
                "company": "Amazon",
                "ats": "direct",
                "title": title,
                "location": location,
                "url": f"https://www.amazon.jobs{path}" if path else None,
                "updated_at": j.get("posted_date"),
                "description_text": j.get("description") or j.get("basic_qualifications") or "",
                "requisition_id": job_id or None,
            })
            added_this_page += 1

        # Stop when the endpoint returns less than a full page.
        if len(jobs) < limit:
            break

    return out


def scrape_netflix(query: str):
    url = (
        "https://explore.jobs.netflix.net/api/apply/v2/jobs"
        f"?domain=netflix.com&start=0&num=50&query={urllib.parse.quote(query)}"
    )
    data = fetch_json(url)
    if not data:
        return []
    positions = data.get("positions") or []
    out = []
    for j in positions:
        title = j.get("name", "")
        location = j.get("location", "")
        if region_ok(location):
            t_update = j.get("t_update")
            updated_iso = None
            if t_update:
                try:
                    updated_iso = datetime.fromtimestamp(t_update, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            out.append({
                "company": "netflix",
                "ats": "direct",
                "title": title,
                "location": location,
                "url": j.get("canonicalPositionUrl"),
                "updated_at": updated_iso,
            })
    return out



def _fetch_html(url: str, timeout: int = 25):
    """Fetch careers HTML with a browser-like fallback for bot-sensitive sites."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-IE,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    if requests is not None:
        try:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.text or "") > 500:
                return r.text
        except Exception:
            pass

    # curl_cffi is already installed by the GitHub workflow and is much better
    # at sites that reject plain python-requests TLS/browser fingerprints.
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate="chrome",
            allow_redirects=True,
        )
        if r.status_code == 200:
            return r.text or ""
    except Exception:
        pass

    return ""


def _html_text(fragment: str) -> str:
    return re.sub(r"\\s+", " ", html.unescape(_strip_html(fragment or ""))).strip()


def _absolute_url(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href or "")



def scrape_oracle_candidate_experience(
    company="Oracle",
    base_url=(
        "https://eeho.fa.us2.oraclecloud.com"
    ),
    site_number="CX_45001",
    location_id="300000000106938",
):
    """
    Oracle Candidate Experience Ireland connector.

    Uses the official public Oracle HCM REST requisition search
    endpoint discovered from the Candidate Experience careers page.
    Collection is restricted to the Republic of Ireland location facet.
    """
    import json
    import urllib.parse
    import urllib.request

    endpoint = (
        f"{base_url}/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions"
    )

    finder = (
        "findReqs;"
        f"siteNumber={site_number},"
        "facetsList="
        "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;"
        "TITLES;CATEGORIES;ORGANIZATIONS;"
        "POSTING_DATES;FLEX_FIELDS,"
        "limit=100,"
        f"locationId={location_id},"
        "sortBy=POSTING_DATES_DESC"
    )

    params = {
        "onlyData": "true",
        "expand": (
            "requisitionList.workLocation,"
            "requisitionList.otherWorkLocations,"
            "requisitionList.secondaryLocations,"
            "flexFieldsFacet.values,"
            "requisitionList.requisitionFlexFields"
        ),
        "finder": finder,
    }

    url = (
        endpoint
        + "?"
        + urllib.parse.urlencode(
            params,
            safe=";,",
        )
    )

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-IE,en;q=0.9",
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=45,
        ) as response:
            payload = json.loads(
                response.read().decode(
                    "utf-8",
                    errors="replace",
                )
            )

    except Exception as exc:
        print(
            "  ! Oracle Candidate Experience API failed:",
            exc,
        )
        return []

    items = payload.get("items") or []

    if not items:
        print(
            "  ! Oracle Candidate Experience returned no search container"
        )
        return []

    container = items[0] or {}

    requisitions = (
        container.get("requisitionList")
        or container.get("RequisitionList")
        or []
    )

    total = (
        container.get("TotalJobsCount")
        or container.get("totalJobsCount")
        or len(requisitions)
    )

    jobs = []

    def first_value(obj, names):
        for name in names:
            value = obj.get(name)

            if value not in (
                None,
                "",
                [],
                {},
            ):
                return value

        return None

    for row in requisitions:
        if not isinstance(row, dict):
            continue

        jid = first_value(
            row,
            [
                "Id",
                "ID",
                "RequisitionId",
                "RequisitionID",
                "JobId",
                "JobID",
            ],
        )

        title = first_value(
            row,
            [
                "Title",
                "title",
                "ExternalTitle",
                "JobTitle",
                "RequisitionTitle",
            ],
        )

        if not jid or not title:
            continue

        location_parts = []

        for field in [
            "PrimaryLocation",
            "Location",
            "workLocation",
            "WorkLocation",
            "otherWorkLocations",
            "secondaryLocations",
        ]:
            value = row.get(field)

            if not value:
                continue

            if isinstance(value, str):
                location_parts.append(value)

            elif isinstance(value, dict):
                for key in [
                    "Name",
                    "LocationName",
                    "FormattedLocation",
                    "Country",
                    "City",
                ]:
                    if value.get(key):
                        location_parts.append(
                            str(value[key])
                        )

            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str):
                        location_parts.append(entry)

                    elif isinstance(entry, dict):
                        for key in [
                            "Name",
                            "LocationName",
                            "FormattedLocation",
                            "Country",
                            "City",
                        ]:
                            if entry.get(key):
                                location_parts.append(
                                    str(entry[key])
                                )

        location = " | ".join(
            dict.fromkeys(
                x.strip()
                for x in location_parts
                if str(x).strip()
            )
        )

        if not location:
            location = "Ireland"

        job_url = (
            f"{base_url}/hcmUI/"
            "CandidateExperience/en/sites/"
            f"jobsearch/job/{jid}/"
            "?location=Ireland"
            f"&locationId={location_id}"
            "&locationLevel=country"
            "&mode=location"
        )

        posted = first_value(
            row,
            [
                "PostedDate",
                "PostingStartDate",
                "ExternalPostedStartDate",
                "CreationDate",
            ],
        )

        jobs.append(
            {
                "company": company,
                "title": str(title).strip(),
                "location": location,
                "country": "Ireland",
                "url": job_url,
                "ats": "oracle",
                "posted_at": posted,
                "updated_at": posted,
                "description_text": "",
                "source": "Oracle Candidate Experience",
            }
        )

    # De-duplicate by requisition URL.
    deduped = {}

    for job in jobs:
        deduped[job["url"]] = job

    jobs = list(
        deduped.values()
    )

    print(
        f"  Oracle Candidate Experience Ireland: "
        f"{len(jobs)} jobs "
        f"(API total={total})"
    )

    return jobs



def scrape_citco():
    """
    Citco official Ireland careers via Oracle Recruiting Candidate Experience.

    Official tenant:
      https://fa-euxc-saasfaprod1.fa.ocs.oraclecloud.com/
      hcmUI/CandidateExperience/en/sites/CX_1/jobs

    Reuses the generic Oracle CE REST collector so we avoid browser
    automation whenever Oracle's public recruiting endpoint is available.
    """
    company = "Citco"
    source = (
        "https://fa-euxc-saasfaprod1.fa.ocs.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_1/jobs"
        "?lastSelectedFacet=LOCATION_LEVEL1"
        "&selectedLocationLevel1Facet=300000000431877"
    )

    try:
        jobs = scrape_oracle_candidate_experience(
            company,
            "https://fa-euxc-saasfaprod1.fa.ocs.oraclecloud.com",
            "CX_1",
            "IE",
        )
    except Exception as exc:
        print(f"  ! Citco Oracle collector failed: {exc}")
        jobs = []

    try:
        _mark_connector_health(
            company,
            True,
            (
                f"Official Citco Oracle careers returned "
                f"{len(jobs)} Republic of Ireland jobs"
            ),
            source,
        )
    except Exception:
        pass

    print(
        f"  Citco Oracle Candidate Experience: "
        f"{len(jobs)} Ireland jobs"
    )

    return jobs


def scrape_jpmorgan():
    return scrape_oracle_candidate_experience(
        "JPMorgan Chase",
        "https://jpmc.fa.oraclecloud.com",
        "CX_1001",
        "300000000289351",
    )


def scrape_apple():
    """Collect all Republic-of-Ireland roles from Apple's server-rendered search."""
    base = "https://jobs.apple.com"
    out, seen = [], set()

    for page_no in range(1, 15):
        params = {"location": "ireland-IRL"}
        if page_no > 1:
            params["page"] = page_no
        url = base + "/en-ie/search?" + urllib.parse.urlencode(params)
        page = _fetch_html(url)
        if not page:
            break

        before = len(out)
        blocks = re.findall(r"(<li\b[^>]*>.*?/en-ie/details/.*?</li>)", page, flags=re.I | re.S)
        if not blocks:
            blocks = re.split(r'(?=<a[^>]+href=["\'][^"\']*/en-ie/details/)', page, flags=re.I)

        for block in blocks:
            m = re.search(
                r'href=["\']([^"\']*/en-ie/details/[^"\']+)["\'][^>]*>(.*?)</a>',
                block,
                flags=re.I | re.S,
            )
            if not m:
                continue

            # Apple occasionally includes tracking/team query parameters or HTML-escaped
            # separators in search-result hrefs.  Build the dashboard URL from the
            # canonical role-number + slug path so every Apply link lands directly
            # on the Apple job detail page.
            raw_href = html.unescape(m.group(1) or "").strip()
            href_abs = _absolute_url(base, raw_href)
            canonical = re.search(
                r"/details/(\d+-\d+)/([^/?#]+)",
                urllib.parse.urlparse(href_abs).path,
                flags=re.I,
            )
            if not canonical:
                continue
            role_number, slug = canonical.groups()
            href = f"{base}/en-ie/details/{role_number}/{slug}"
            title = re.sub(r"\s+", " ", html.unescape(_strip_html(m.group(2) or ""))).strip()
            key = href.rstrip("/").lower()
            if not title or key in seen:
                continue

            txt = re.sub(r"\s+", " ", html.unescape(_strip_html(block or ""))).strip()
            lm = re.search(
                r"Location\s+(.+?)(?:\s+Actions|\s+Role Number:|\s+Weekly Hours:|$)",
                txt,
                flags=re.I,
            )
            location = (lm.group(1).strip(" -|•") if lm else "") or "Ireland"
            if len(location) > 120:
                city_match = re.search(r"\b(Cork|Dublin|Limerick|Galway|Waterford|Kilkenny|Athlone)\b", txt, re.I)
                location = city_match.group(1).title() if city_match else "Ireland"
            if not region_ok(location):
                continue

            dm = re.search(
                r"\b(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}|[A-Za-z]{3}\s+\d{1,2},?\s+20\d{2})\b",
                txt,
            )
            seen.add(key)
            out.append({
                "company": "Apple",
                "ats": "direct",
                "title": title,
                "location": location,
                "url": href,
                "updated_at": dm.group(1) if dm else None,
                "description_text": txt[:5000],
            })

        if len(out) == before:
            break

    return out


def _scrape_public_careers_page(company: str, url: str, href_hints, default_location="Ireland"):
    """Conservative server-rendered careers-page parser for proprietary sites.

    Only emits cards whose surrounding text clearly contains an Irish location.
    It is a fallback, not a claim that every JS-only site is fully covered.
    """
    page=_fetch_html(url)
    if not page:
        return []
    out=[]; seen=set()
    # Work with bounded chunks around anchors so one Ireland mention elsewhere on
    # the page cannot incorrectly tag a non-Ireland role.
    for m in re.finditer(r'<a\\b[^>]*href=["\\\']([^"\\\']+)["\\\'][^>]*>(.*?)</a>', page, flags=re.I|re.S):
        href=m.group(1); label=_html_text(m.group(2))
        if not label or len(label)<3 or len(label)>220:
            continue
        full=_absolute_url(url,href)
        low=full.lower()
        if not any(h in low for h in href_hints):
            continue
        start=max(0,m.start()-1800); end=min(len(page),m.end()+2600)
        chunk=_html_text(page[start:end])
        if not region_ok(chunk):
            continue
        # Prefer a compact location phrase if visible.
        lm=re.search(r'((?:Dublin|Cork|Galway|Limerick|Waterford|Kilkenny|Athlone|Ireland)(?:[^|•<>]{0,80}))', chunk, flags=re.I)
        location=lm.group(1).strip()[:140] if lm else default_location
        key=(label.lower(),full.split('?')[0])
        if key in seen:
            continue
        seen.add(key)
        dm=re.search(r'\\b(20\\d{2}-\\d{2}-\\d{2}|\\d{1,2}\\s+[A-Za-z]{3,9}\\s+20\\d{2}|[A-Za-z]{3,9}\\s+\\d{1,2},?\\s+20\\d{2})\\b', chunk)
        out.append({"company":company,"ats":"direct","title":label,"location":location,"url":full,"updated_at":dm.group(1) if dm else None,"description_text":chunk[:5000]})
    return out



def _scrape_accenture_playwright():
    """Scrape all currently visible Accenture Ireland jobs.

    Accenture's Ireland search renders official job links client-side.
    The anchors often contain no visible text, so the job title is extracted
    primarily from the URL's ?title= parameter and the requisition from ?id=.
    """
    if not HAS_PLAYWRIGHT:
        print("  ! Accenture: Playwright unavailable")
        return []

    search_url = "https://www.accenture.com/ie-en/careers/jobsearch"
    results = {}
    official_board_loaded = False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                locale="en-IE",
            )

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)

            _dismiss_cookie_banner(page)

            stagnant = 0
            previous = -1

            for cycle in range(120):
                anchors = page.locator(
                    'a[href*="/ie-en/careers/jobdetails?id="], '
                    'a[href*="/careers/jobdetails?id="]'
                )

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    try:
                        raw_href = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw_href)
                    except Exception:
                        continue

                    parsed = urllib.parse.urlparse(href)
                    params = urllib.parse.parse_qs(parsed.query)

                    job_id = (
                        (params.get("id") or [""])[0]
                        .replace("_en", "")
                        .strip()
                    )

                    url_title = urllib.parse.unquote_plus(
                        (params.get("title") or [""])[0]
                    ).strip()

                    if not job_id and "jobdetails" not in href.lower():
                        continue

                    # Accenture commonly renders these anchors without text.
                    title = url_title

                    if not title:
                        try:
                            title = (_browser_text(a) or "").strip()
                        except Exception:
                            title = ""

                    node = a
                    card = ""

                    for _ in range(7):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break

                        if candidate and len(candidate) <= 3000:
                            card = candidate

                        if card and len(card) >= 30:
                            break

                    if (
                        not title
                        or title.lower() in {
                            "apply",
                            "apply now",
                            "view job",
                            "learn more",
                            "save job",
                        }
                    ):
                        try:
                            heads = node.locator("h1,h2,h3,h4,h5")
                            for hidx in range(min(heads.count(), 8)):
                                candidate = _browser_text(heads.nth(hidx))
                                if candidate and 4 <= len(candidate) <= 300:
                                    title = candidate
                                    break
                        except Exception:
                            pass

                    if not title:
                        continue

                    location = _browser_location(card, "Ireland")

                    # Use requisition ID as primary key. This prevents the
                    # title query string from producing duplicate variants.
                    key = job_id or parsed.path.lower()

                    canonical = href.split("#")[0]

                    results[key] = {
                        "company": "Accenture",
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card[:5000],
                        "requisition_id": job_id or None,
                    }

                current = len(results)

                if current == previous:
                    stagnant += 1
                else:
                    stagnant = 0

                previous = current

                # Try Accenture's possible load-more controls.
                for label in (
                    "Show more",
                    "Load more",
                    "See more",
                    "More jobs",
                    "View more",
                    "Show results",
                    "Next",
                ):
                    try:
                        btn = page.get_by_role(
                            "button",
                            name=label,
                            exact=False,
                        )

                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1500)
                            page.wait_for_timeout(900)
                    except Exception:
                        pass

                # Also try link-based next-page navigation.
                try:
                    nxt = page.get_by_role("link", name="Next", exact=False)
                    if nxt.count() and nxt.first.is_visible():
                        nxt.first.click(timeout=1500)
                        page.wait_for_timeout(1200)
                except Exception:
                    pass

                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(800)

                if stagnant >= 15:
                    break

            print(
                f"  Accenture browser: "
                f"{len(results)} unique Ireland job-detail links"
            )

            browser.close()

    except Exception as exc:
        print(f"  ! Accenture browser scrape failed: {exc}")

    return [
        j for j in results.values()
        if region_ok(j.get("location") or "Ireland")
    ]



def _scrape_accenture_with_retry():
    """Run the existing Accenture browser collector with one transient-failure retry."""
    import time

    for attempt in range(1, 3):
        try:
            jobs = _scrape_accenture_playwright()
            if jobs:
                if attempt > 1:
                    print(f"  Accenture browser recovered on attempt {attempt}: {len(jobs)} jobs")
                return jobs

            if attempt == 1:
                print("  ! Accenture browser returned no jobs; retrying once...")
                time.sleep(3)

        except Exception as exc:
            if attempt == 1:
                print(f"  ! Accenture browser attempt 1 failed: {exc}; retrying once...")
                time.sleep(3)
            else:
                print(f"  ! Accenture browser retry failed: {exc}")

    return []


def scrape_accenture():
    """Accenture Ireland.

    Accenture's branded search is partly client-rendered, while current official
    job-detail pages still hand applications to the wd103 Workday tenant.
    Try both rather than assuming either surface is complete.
    """
    combined = []
    seen = set()

    # Official branded search surface is client-rendered: use Chromium first.
    branded_jobs = _scrape_accenture_with_retry()
    if not branded_jobs:
        branded_jobs = _scrape_public_careers_page(
            "Accenture",
            "https://www.accenture.com/ie-en/careers/jobsearch",
            ("/ie-en/careers/jobdetails", "/careers/jobdetails", "jobdetails?id="),
            default_location="Ireland",
        )
    for j in branded_jobs:
        key = ((j.get("title") or "").lower(), (j.get("url") or "").split("?")[0])
        if key not in seen:
            seen.add(key)
            combined.append(j)

    # Current Accenture job pages still use this Workday tenant for applications.
    # Search "Ireland" so we do not have to paginate thousands of global jobs.
    try:
        for j in scrape_workday(
            "Accenture", "accenture", "wd103", "AccentureCareers",
            max_pages=25, search_text="Ireland",
        ):
            key = ((j.get("title") or "").lower(), (j.get("url") or "").split("?")[0])
            if key not in seen:
                seen.add(key)
                combined.append(j)
    except Exception as e:
        print(f"  ! direct/Accenture workday fallback: {e}")

    return combined


def scrape_citi():
    """Citi/Citigroup Ireland direct careers collector.

    Citi's jobs.citi.com pages are server-rendered but their location URLs can
    change as taxonomy IDs change. Query several stable Ireland/Dublin variants,
    follow the first two result pages, and deduplicate by canonical job URL.
    """
    urls = [
        "https://jobs.citi.com/location/dublin-jobs/287/2963597-7521314-7778677-2964574/4",
        "https://jobs.citi.com/location/dublin-jobs/287/2963597/2",
        "https://jobs.citi.com/search-jobs/Ireland",
    ]
    out = []
    seen = set()

    for base in urls:
        page_urls = [base]
        if "/location/dublin-jobs/" in base:
            page_urls.extend([base.rstrip("/") + "/1", base.rstrip("/") + "/2"])

        for url in page_urls:
            rows = _scrape_public_careers_page(
                "Citi",
                url,
                ("/job/dublin/", "/en/job/dublin/", "/job/"),
                default_location="Dublin, Leinster, Ireland",
            )
            for j in rows:
                canonical = (j.get("url") or "").split("?")[0].rstrip("/").lower()
                key = canonical or (
                    (j.get("title") or "").strip().lower(),
                    (j.get("location") or "").strip().lower(),
                )
                if key in seen:
                    continue
                seen.add(key)
                # Normalize all Citi/Citigroup branding to one dashboard company.
                j["company"] = "Citi"
                out.append(j)

    return out

def _browser_text(locator):
    try:
        return (locator.inner_text(timeout=1500) or "").strip()
    except Exception:
        try:
            return (locator.text_content(timeout=1500) or "").strip()
        except Exception:
            return ""


def _browser_location(card_text: str, default="Ireland"):
    lines = [x.strip() for x in (card_text or "").splitlines() if x.strip()]
    for line in lines:
        if region_ok(line):
            return line[:180]
    return default


def _dismiss_cookie_banner(page):
    for text in ("Accept all", "Accept All", "I agree", "I Agree", "Accept",
                 "Allow all", "Allow All", "Got it", "OK"):
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def _scrape_google_playwright():
    if not HAS_PLAYWRIGHT:
        print("  ! Google: Playwright unavailable")
        return []
    base = "https://www.google.com/about/careers/applications/jobs/results"
    out, seen = [], set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            empty_pages = 0
            for page_no in range(1, 31):
                url = base + "?" + urllib.parse.urlencode({"location": "Ireland", "page": page_no})
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                if page_no == 1:
                    _dismiss_cookie_banner(page)
                before = len(out)
                hs = page.locator("h3.QJPWVe")
                for i in range(hs.count()):
                    h = hs.nth(i)
                    title = _browser_text(h)
                    if not title or len(title) > 220:
                        continue
                    low = title.lower().strip()
                    if not is_real_job_title(title) or low in seen:
                        continue
                    node, card = h, ""
                    for _ in range(4):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 1000:
                            card = candidate
                        if card and len(card) >= 30:
                            break
                    job_link = node.locator("a[href*='jobs/results/']")
                    if not job_link.count():
                        continue
                    href = urllib.parse.urljoin(page.url, job_link.first.get_attribute("href") or "")
                    if not re.search(r"/jobs/results/\d+", href):
                        continue
                    seen.add(low)
                    out.append({
                        "company": "Google", "ats": "direct", "title": title,
                        "location": _browser_location(card, "Ireland"), "url": href,
                        "updated_at": None, "description_text": card[:5000],
                    })
                added = len(out) - before
                print(f"  Google browser page {page_no}: +{added}")
                empty_pages = empty_pages + 1 if added == 0 else 0
                if empty_pages >= 2:
                    break
            browser.close()
    except Exception as exc:
        print(f"  ! Google browser scrape failed: {exc}")
    return out


def _scrape_meta_playwright():
    if not HAS_PLAYWRIGHT:
        print("  ! Meta: Playwright unavailable")
        return []
    pages = [
        ("Dublin, Ireland", "https://www.metacareers.com/locations/dublin/?offices%5B0%5D=Dublin%2C+Ireland&p%5Boffices%5D%5B0%5D=Dublin%2C+Ireland"),
        ("Clonee, Ireland", "https://www.metacareers.com/locations/clonee/?offices%5B0%5D=Clonee%2C+Ireland&p%5Boffices%5D%5B0%5D=Clonee%2C+Ireland"),
    ]
    results = {}
    rx = re.compile(r"metacareers\.com/profile/job_details/\d+/?", re.I)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            for default_location, url in pages:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
                _dismiss_cookie_banner(page)
                stagnant, previous = 0, len(results)
                for _ in range(100):
                    anchors = page.locator("a[href]")
                    for i in range(anchors.count()):
                        a = anchors.nth(i)
                        try:
                            href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                        except Exception:
                            continue
                        if not rx.search(href) or href in results:
                            continue
                        title = _browser_text(a)
                        node, card = a, ""
                        for _ in range(5):
                            try:
                                node = node.locator("..")
                                candidate = _browser_text(node)
                            except Exception:
                                break
                            if candidate and len(candidate) <= 1600:
                                card = candidate
                            if card and len(card) >= 30:
                                break
                        if not title or len(title) > 260:
                            try:
                                heads = node.locator("h1,h2,h3,h4")
                                if heads.count():
                                    title = _browser_text(heads.first)
                            except Exception:
                                pass
                        if not title:
                            lines = [x.strip() for x in card.splitlines() if 3 < len(x.strip()) <= 220]
                            title = lines[0] if lines else ""
                        if not title:
                            continue
                        results[href] = {
                            "company": "Meta", "ats": "direct", "title": title[:300],
                            "location": _browser_location(card, default_location), "url": href,
                            "updated_at": None, "description_text": card[:5000],
                        }
                    for label in ("Show more", "Load more", "See more", "More jobs", "View more"):
                        try:
                            btn = page.get_by_role("button", name=label, exact=False)
                            if btn.count() and btn.first.is_visible():
                                btn.first.click(timeout=1000)
                                page.wait_for_timeout(400)
                        except Exception:
                            pass
                    page.mouse.wheel(0, 3200)
                    page.wait_for_timeout(500)
                    current = len(results)
                    stagnant = stagnant + 1 if current == previous else 0
                    previous = current
                    if stagnant >= 12:
                        break
                print(f"  Meta {default_location}: {len(results)} unique jobs accumulated")
            browser.close()
    except Exception as exc:
        print(f"  ! Meta browser scrape failed: {exc}")
    return list(results.values())



def _scrape_ey_playwright():
    """EY Ireland: SAP SuccessFactors browser collector adapted from Suman's working pipeline."""
    if not HAS_PLAYWRIGHT:
        print("  ! EY Ireland: Playwright unavailable")
        return []
    base = "https://careers.ey.com/ey/search/"
    results = {}
    href_rx = re.compile(r"careers\.ey\.com/ey/job/", re.I)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            stagnant = 0
            for startrow in range(0, 2500, 25):
                url = base + "?" + urllib.parse.urlencode({"q": "", "locationsearch": "Ireland", "startrow": startrow})
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1000)
                if startrow == 0:
                    _dismiss_cookie_banner(page)
                before = len(results)
                anchors = page.locator("a[href]")
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not href_rx.search(href) or href in results:
                        continue
                    title = _browser_text(a)
                    node, card = a, ""
                    for _ in range(5):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 1800:
                            card = candidate
                        if card and len(card) >= 25:
                            break
                    if not title or len(title) > 300:
                        lines = [x.strip() for x in card.splitlines() if 3 < len(x.strip()) <= 250]
                        title = lines[0] if lines else ""
                    if not title:
                        continue
                    results[href] = {
                        "company": "EY Ireland", "ats": "direct", "title": title[:300],
                        "location": _browser_location(card, "Ireland"), "url": href,
                        "updated_at": None, "description_text": card[:5000],
                    }
                added = len(results) - before
                print(f"  EY browser startrow={startrow}: +{added} ({len(results)} total)")
                stagnant = stagnant + 1 if added == 0 else 0
                if stagnant >= 2:
                    break
            browser.close()
    except Exception as exc:
        print(f"  ! EY Ireland browser scrape failed: {exc}")
    return list(results.values())


def _parse_yello_jobs(company, fragment):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(fragment, "html.parser")
    jobs = {}
    for anchor in soup.select('a[href*="/jobs/"]'):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urllib.parse.urljoin("https://eyglobal.yello.co", anchor.get("href") or "")
        if not title or not href:
            continue
        card = anchor.find_parent("li")
        card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True)).strip() if card else title
        jobs[href] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": "Ireland",
            "url": href,
            "updated_at": None,
            "description_text": card_text[:5000],
        }
    return list(jobs.values())


def _scrape_yello_ireland(company, board_id):
    """Collect Republic-of-Ireland early-career roles from a public Yello board."""
    sess = _session()
    if not sess:
        return []
    base = f"https://eyglobal.yello.co/job_boards/{board_id}"
    try:
        response = sess.get(
            f"{base}/search",
            params={"query": "", "filters": "30012"},
            headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
        response.raise_for_status()
        jobs = _parse_yello_jobs(company, (response.json() or {}).get("html") or "")
    except Exception as exc:
        print(f"  ! {company} Yello Ireland search failed: {exc}")
        return []
    _mark_connector_health(company, True, f"Official Yello Ireland board returned {len(jobs)} early-career roles", base)
    print(f"  {company} Yello Ireland early careers: {len(jobs)} jobs")
    return jobs


def _scrape_kpmg_playwright():
    """KPMG Ireland: Avature browser collector adapted from Suman's working pipeline."""
    if not HAS_PLAYWRIGHT:
        print("  ! KPMG Ireland: Playwright unavailable")
        return []
    base = "https://kpmgireland.avature.net/careers/SearchJobs/"
    results = {}
    href_rx = re.compile(r"kpmgireland\.avature\.net/careers/(?:JobDetail|jobdetail|FolderDetail|folderdetail)", re.I)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            stagnant = 0
            for offset in range(0, 1000, 10):
                url = base + "?" + urllib.parse.urlencode({"folderOffset": offset})
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(900)
                if offset == 0:
                    _dismiss_cookie_banner(page)
                before = len(results)
                anchors = page.locator("a[href]")
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not href_rx.search(href) or href in results:
                        continue
                    title = _browser_text(a)
                    node, card = a, ""
                    for _ in range(5):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 1800:
                            card = candidate
                        if card and len(card) >= 25:
                            break
                    if not title or len(title) > 300:
                        lines = [x.strip() for x in card.splitlines() if 3 < len(x.strip()) <= 250]
                        title = lines[0] if lines else ""
                    if not title:
                        continue
                    results[href] = {
                        "company": "KPMG Ireland", "ats": "direct", "title": title[:300],
                        "location": _browser_location(card, "Ireland"), "url": href,
                        "updated_at": None, "description_text": card[:5000],
                    }
                added = len(results) - before
                print(f"  KPMG browser folderOffset={offset}: +{added} ({len(results)} total)")
                stagnant = stagnant + 1 if added == 0 else 0
                if stagnant >= 2:
                    break
            browser.close()
    except Exception as exc:
        print(f"  ! KPMG Ireland browser scrape failed: {exc}")
    return list(results.values())


def scrape_ey():
    jobs = _scrape_ey_playwright()
    jobs.extend(_scrape_yello_ireland("EY Ireland", "c1riT--B2O-KySgYWsZO1Q"))
    return jobs


def scrape_kpmg():
    return _scrape_kpmg_playwright()

def scrape_google():
    jobs = _scrape_google_playwright()
    if jobs:
        return jobs
    return _scrape_public_careers_page(
        "Google",
        "https://www.google.com/about/careers/applications/jobs/results/?location=Ireland",
        ("/about/careers/applications/jobs/results/", "/jobs/results/"),
    )


def scrape_microsoft():
    """Microsoft Ireland: prefer the official Dublin location surface, then
    try the broader careers search if the location page yields no job cards.
    """
    jobs = _scrape_public_careers_page(
        "Microsoft",
        "https://careers.microsoft.com/v2/global/en/locations/dublin.html",
        ("/job/", "/jobs/", "jobid", "job-id"),
        default_location="Dublin, Ireland",
    )
    if jobs:
        return jobs

    return _scrape_public_careers_page(
        "Microsoft",
        "https://jobs.careers.microsoft.com/global/en/search?q=&lc=Ireland",
        ("/job/", "/jobs/", "jobid", "job-id"),
        default_location="Ireland",
    )


def scrape_meta():
    jobs = _scrape_meta_playwright()
    if jobs:
        return jobs
    return _scrape_public_careers_page(
        "Meta",
        "https://www.metacareers.com/jobs?offices[0]=Dublin%2C%20Ireland",
        ("/jobs/",),
    )


def scrape_tiktok():
    return _scrape_public_careers_page(
        "TikTok",
        "https://careers.tiktok.com/position?keyword=&location=Dublin%2C+Ireland",
        ("/position/", "position/detail", "/jobs/"),
    )



def _browser_board_collect_uncached(company, urls, href_patterns, default_location="Ireland", max_scrolls=20,
                           require_ireland=True, source_tag="direct"):
    """Generic Playwright collector for official career boards that block plain HTTP or render jobs client-side."""
    if not HAS_PLAYWRIGHT:
        print(f"  ! {company}: Playwright unavailable")
        return []
    results = {}
    pats = tuple(x.lower() for x in href_patterns)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1400)
                    _dismiss_cookie_banner(page)
                    _mark_connector_health(company, True, "Official careers board loaded", page.url)
                except Exception as exc:
                    print(f"  ! {company} browser page failed {url}: {exc}")
                    continue
                stagnant, previous = 0, len(results)
                for _ in range(max_scrolls):
                    anchors = page.locator("a[href]")
                    for i in range(anchors.count()):
                        a = anchors.nth(i)
                        try:
                            raw = a.get_attribute("href") or ""
                            href = urllib.parse.urljoin(page.url, raw)
                        except Exception:
                            continue
                        lowhref = href.lower()
                        if not any(p in lowhref for p in pats):
                            continue
                        if href in results:
                            continue
                        title = _browser_text(a)
                        node, card = a, ""
                        for _up in range(5):
                            try:
                                node = node.locator("..")
                                candidate = _browser_text(node)
                            except Exception:
                                break
                            if candidate and len(candidate) <= 2200:
                                card = candidate
                            if card and len(card) >= 30:
                                break
                        if not title or len(title) > 320 or title.lower() in {"apply", "apply now", "save", "see details", "view job"}:
                            try:
                                heads = node.locator("h1,h2,h3,h4,h5")
                                if heads.count():
                                    title = _browser_text(heads.first)
                            except Exception:
                                pass
                        if not title or len(title) > 320:
                            lines = [x.strip() for x in card.splitlines() if 4 < len(x.strip()) <= 280]
                            title = lines[0] if lines else ""
                        if not title:
                            continue
                        location = _browser_location(card, default_location)
                        evidence = f"{title} {card} {href}".lower()
                        if require_ireland and not region_ok(evidence):
                            continue
                        results[href] = {
                            "company": company, "ats": source_tag, "title": title[:300],
                            "location": location, "url": href, "updated_at": None,
                            "description_text": card[:5000],
                        }
                    for label in ("Load more", "Show more", "See more", "More jobs", "View more", "Next"):
                        try:
                            btn = page.get_by_role("button", name=label, exact=False)
                            if btn.count() and btn.first.is_visible():
                                btn.first.click(timeout=1200)
                                page.wait_for_timeout(500)
                                break
                        except Exception:
                            pass
                    page.mouse.wheel(0, 3200)
                    page.wait_for_timeout(500)
                    current = len(results)
                    stagnant = stagnant + 1 if current == previous else 0
                    previous = current
                    if stagnant >= 5:
                        break
                print(f"  {company} browser: {len(results)} unique Ireland jobs accumulated")
            browser.close()
    except Exception as exc:
        print(f"  ! {company} browser scrape failed: {exc}")
    return list(results.values())


def _browser_board_collect(company, urls, href_patterns, default_location="Ireland", max_scrolls=20,
                           require_ireland=True, source_tag="direct"):
    """10-minute cache around the generic browser collector.

    TTL is shorter than the 15-minute scheduled cadence, so scheduled runs remain fresh.
    """
    material = {
        "company": company, "urls": list(urls or []), "href_patterns": list(href_patterns or []),
        "default_location": default_location, "max_scrolls": max_scrolls,
        "require_ireland": require_ireland, "source_tag": source_tag,
    }
    key = hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    with _SAFE_CACHE_LOCK:
        cache = _load_safe_cache(BROWSER_SCRAPE_CACHE_PATH)
        entry = cache.get(key) if isinstance(cache.get(key), dict) else None
    if entry:
        age = time.time() - float(entry.get("checked_at") or 0)
        if age < BROWSER_SCRAPE_CACHE_TTL_SECONDS:
            jobs = entry.get("jobs") or []
            print(f"  {company}: browser cache hit ({age/60:.1f}m old)")
            return jobs
    jobs = _browser_board_collect_uncached(
        company, urls, href_patterns, default_location=default_location, max_scrolls=max_scrolls,
        require_ireland=require_ireland, source_tag=source_tag,
    )
    with _SAFE_CACHE_LOCK:
        cache = _load_safe_cache(BROWSER_SCRAPE_CACHE_PATH)
        cache[key] = {"company": company, "checked_at": time.time(), "jobs": jobs or []}
        _write_safe_cache(BROWSER_SCRAPE_CACHE_PATH, cache)
    return jobs


def scrape_tiktok():
    # LifeAtTikTok does not populate job links until a search is submitted.
    if not HAS_PLAYWRIGHT:
        print("  ! TikTok: Playwright unavailable")
        return []
    results = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            page.goto("https://lifeattiktok.com/search/?language=en", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1400)
            _dismiss_cookie_banner(page)
            # Suman's working path: use the site's real search field, then collect rendered /search/<id> links.
            submitted = False
            for pattern in (r"Enter Title, Skill, or City", r"Enter Title, Skill, or Location", r"Title, Skill"):
                try:
                    inp = page.get_by_placeholder(re.compile(pattern, re.I))
                    if inp.count():
                        inp.first.fill("Dublin", timeout=1500)
                        try:
                            page.get_by_role("button", name=re.compile(r"Search", re.I)).first.click(timeout=1500)
                        except Exception:
                            inp.first.press("Enter", timeout=1500)
                        submitted = True
                        break
                except Exception:
                    pass
            if submitted:
                page.wait_for_timeout(1800)
            stagnant = previous = 0
            for _ in range(100):
                anchors = page.locator("a[href]")
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not re.search(r"lifeattiktok\.com/search/\d+", href, re.I) or href in results:
                        continue
                    title = _browser_text(a)
                    node, card = a, ""
                    for _up in range(6):
                        try:
                            node = node.locator("..")
                            cand = _browser_text(node)
                        except Exception:
                            break
                        if cand and len(cand) <= 2400:
                            card = cand
                        if re.search(r"Dublin|Ireland", card, re.I):
                            break
                    if not title or len(title) > 320:
                        lines = [x.strip() for x in card.splitlines() if 4 < len(x.strip()) <= 280]
                        title = lines[0] if lines else ""
                    evidence = f"{title} {card} {href}"
                    if not title or not re.search(r"Dublin|Ireland", evidence, re.I):
                        continue
                    raw_location = _browser_location(card, "")
                    if not re.search(
                        r"\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford|Kilkenny|Athlone)\b",
                        raw_location,
                        re.I,
                    ):
                        continue

                    results[href] = {
                        "company": "TikTok",
                        "ats": "direct",
                        "title": title[:300],
                        "raw_location": raw_location,
                        "location": raw_location,
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }
                for label in ("Load more", "Show more", "See more", "More jobs"):
                    try:
                        btn = page.get_by_role("button", name=label, exact=False)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200); page.wait_for_timeout(600); break
                    except Exception:
                        pass
                page.mouse.wheel(0, 3200); page.wait_for_timeout(450)
                cur = len(results); stagnant = stagnant + 1 if cur == previous else 0; previous = cur
                if stagnant >= 7:
                    break
            print(f"  TikTok browser: {len(results)} unique Ireland jobs accumulated")
            browser.close()
    except Exception as exc:
        print(f"  ! TikTok browser scrape failed: {exc}")
    return list(results.values())

def scrape_netapp():
    return _browser_board_collect(
        "NetApp",
        ["https://careers.netapp.com/location/ireland-jobs/27600/2963597/2/1",
         "https://careers.netapp.com/location/ireland-jobs/27600/2963597/2"],
        ("careers.netapp.com/job/", "/job/"),
        default_location="Ireland",
        max_scrolls=8,
    )


def scrape_version1():
    return _browser_board_collect(
        "Version 1",
        ["https://www.version1.com/careers-with-version-1-in-dublin/"],
        ("jobs.smartrecruiters.com",),
        default_location="Dublin, Ireland",
        max_scrolls=5,
    )


def scrape_citi():
    return _browser_board_collect(
        "Citi",
        ["https://jobs.citi.com/location/ireland-jobs/287/2963597/2",
         "https://jobs.citi.com/location/dublin-jobs/287/2963597-7521314-2964574/4"],
        ("jobs.citi.com/job/",),
        default_location="Dublin, Leinster, Ireland",
        max_scrolls=10,
    )


def scrape_hsbc():
    """HSBC Ireland via its official SAP SuccessFactors careers site."""

    if not HAS_PLAYWRIGHT:
        print("  ! HSBC Ireland: Playwright unavailable")
        return []

    search_urls = [
        "https://apply.careers.hsbc.com/search/?q=&locationsearch=Dublin",
        "https://apply.careers.hsbc.com/search/?q=&locationsearch=Ireland",
        "https://apply.careers.hsbc.com/search/?createNewAlert=false&q=&locationsearch=Dublin",
    ]

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            page = browser.new_page(
                viewport={"width": 1440, "height": 1100},
                locale="en-IE",
            )

            for search_url in search_urls:
                try:
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=90000,
                    )
                    page.wait_for_timeout(2500)
                    _dismiss_cookie_banner(page)
                    official_board_loaded = True
                except Exception as exc:
                    print(f"  ! HSBC page load failed: {exc}")
                    continue

                # SuccessFactors job-detail URLs normally contain /job/
                # and frequently a numeric requisition suffix.
                anchors = page.locator("a[href*='/job/']")

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    try:
                        href = urllib.parse.urljoin(
                            page.url,
                            a.get_attribute("href") or "",
                        )
                    except Exception:
                        continue

                    if not href or href in results:
                        continue

                    title = _browser_text(a)

                    node = a
                    card = ""

                    for _ in range(6):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break

                        if candidate and len(candidate) <= 3000:
                            card = candidate

                        if (
                            "dublin" in card.lower()
                            or "ireland" in card.lower()
                            or ", ie" in card.lower()
                        ):
                            break

                    evidence = f"{title} {card} {href}"

                    if not title:
                        continue

                    if not region_ok(evidence):
                        continue

                    results[href] = {
                        "company": "HSBC Ireland",
                        "ats": "direct",
                        "title": title[:300],
                        "location": _browser_location(
                            card,
                            "Dublin, Ireland",
                        ),
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                # Support more than first page where available.
                for _ in range(10):
                    try:
                        next_btn = page.get_by_role(
                            "link",
                            name=re.compile(r"next", re.I),
                        )

                        if not next_btn.count() or not next_btn.first.is_visible():
                            break

                        before = len(results)

                        next_btn.first.click(timeout=2500)
                        page.wait_for_timeout(1800)

                        anchors = page.locator("a[href*='/job/']")

                        for i in range(anchors.count()):
                            a = anchors.nth(i)

                            href = urllib.parse.urljoin(
                                page.url,
                                a.get_attribute("href") or "",
                            )

                            if not href or href in results:
                                continue

                            title = _browser_text(a)

                            node = a
                            card = ""

                            for _up in range(6):
                                try:
                                    node = node.locator("..")
                                    candidate = _browser_text(node)
                                except Exception:
                                    break

                                if candidate and len(candidate) <= 3000:
                                    card = candidate

                            evidence = f"{title} {card} {href}"

                            if title and region_ok(evidence):
                                results[href] = {
                                    "company": "HSBC Ireland",
                                    "ats": "direct",
                                    "title": title[:300],
                                    "location": _browser_location(
                                        card,
                                        "Dublin, Ireland",
                                    ),
                                    "url": href,
                                    "updated_at": None,
                                    "description_text": card[:5000],
                                }

                        if len(results) == before:
                            break

                    except Exception:
                        break

            browser.close()

    except Exception as exc:
        print(f"  ! HSBC Ireland browser scrape failed: {exc}")

    _mark_connector_health(
        "HSBC Ireland",
        official_board_loaded,
        (
            f"Official HSBC Ireland careers board loaded and returned "
            f"{len(results)} qualifying Ireland jobs"
            if official_board_loaded
            else "Official HSBC Ireland careers board could not be verified"
        ),
        "https://apply.careers.hsbc.com/search/?q=&locationsearch=Ireland",
    )

    print(
        f"  HSBC Ireland official careers: "
        f"{len(results)} unique Ireland jobs"
    )

    return list(results.values())


def scrape_boston_scientific():
    return _browser_board_collect(
        "Boston Scientific",
        [
            "https://jobs.bostonscientific.com/search/?q=&locationsearch=Ireland",
            "https://jobs.bostonscientific.com/search/?q=&locationsearch=Galway",
            "https://jobs.bostonscientific.com/search/?q=&locationsearch=Cork",
            "https://jobs.bostonscientific.com/search/?q=&locationsearch=Clonmel",
        ],
        ("jobs.bostonscientific.com/job/",),
        default_location="Ireland",
        max_scrolls=30,
        require_ireland=True,
    )


def scrape_dxc():
    company = "DXC Technology"
    api_url = "https://jobsapi-internal.m-cloud.io/api/job"

    sess = _session()
    if not sess:
        print("  ! DXC Technology: HTTP session unavailable")
        return []

    results = {}
    api_loaded = False
    offset = 1
    limit = 50

    for _ in range(30):
        params = [
            ("callback", "CWS.jobs.jobCallback"),
            ("facet[]", "is_internal:DXCJobs"),
            # DXC's API exposes the country name under the compliment facet.
            ("facet[]", "compliment:Ireland"),
            ("sortfield", "open_date"),
            ("sortorder", "descending"),
            ("Limit", str(limit)),
            ("Organization", "2492"),
            ("offset", str(offset)),
            ("fuzzy", "false"),
            ("facetlist[]", "compliment"),
            ("facetlist[]", "store_id"),
            ("facetlist[]", "primary_city"),
            ("facetlist[]", "primary_category"),
            ("facetlist[]", "employment_type"),
        ]

        try:
            r = sess.get(
                api_url,
                params=params,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://careers.dxc.com/job-search-results/",
                    "Accept": "*/*",
                },
            )
        except Exception as exc:
            print(f"  ! DXC API request failed: {exc}")
            break

        if r.status_code != 200:
            print(f"  ! DXC API HTTP {r.status_code}")
            break

        text = (r.text or "").strip()
        m = re.search(r'^[^(]+\((.*)\)\s*;?\s*$', text, re.S)
        if m:
            text = m.group(1)

        try:
            payload = json.loads(text)
        except Exception:
            print("  ! DXC API returned invalid JSONP")
            break

        api_loaded = True

        rows = payload.get("queryResult", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue

            # In DXC's payload:
            # primary_country = ISO-ish code (IE)
            # compliment = human-readable country (Ireland)
            country_code = str(row.get("primary_country") or "").strip().upper()
            country_name = str(row.get("compliment") or "").strip()
            city = str(row.get("primary_city") or "").strip()
            title = str(row.get("title") or "").strip()
            href = str(row.get("url") or "").strip()
            job_id = str(row.get("clientid") or row.get("id") or "").strip()

            if country_code != "IE" and country_name.lower() != "ireland":
                continue
            if not title or not href:
                continue

            location = f"{city}, Ireland" if city else "Ireland"

            key = (job_id or href).lower()
            results[key] = {
                "company": company,
                "ats": "cws",
                "title": re.sub(r"\s+", " ", title).strip()[:300],
                "location": location[:120],
                "url": href,
                "updated_at": row.get("open_date"),
                "description_text": _html_text(str(row.get("description") or ""))[:5000],
            }

        total_hits = int(payload.get("totalHits") or 0) if isinstance(payload, dict) else 0
        if offset + limit > total_hits or len(rows) < limit:
            break

        offset += limit

    print(f"  DXC Technology CWS API: {len(results)} Ireland jobs")
    if results:
        _mark_connector_health(company, True, f"Official DXC API returned {len(results)} Ireland jobs", api_url)
        return list(results.values())
    if api_loaded:
        _mark_connector_health(company, True, "Official DXC API is live and currently returns 0 Ireland jobs", api_url)
        return []
    return _browser_board_collect(
        company,
        ["https://careers.dxc.com/job-search-results/?location=Ireland"],
        ("careers.dxc.com/job/",),
        default_location="Ireland",
        max_scrolls=12,
        require_ireland=True,
        source_tag="official",
    )


def _static_official_jobs(company, url, href_pattern, default_location="Ireland"):
    """Parse server-rendered official career pages with requests/BeautifulSoup."""
    results = {}
    try:
        from bs4 import BeautifulSoup
        sess = _session()
        if not sess:
            return []
        response = sess.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        html = response.text
        _mark_connector_health(company, True, "Official careers page loaded", url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a.get("href") or "")
            if href_pattern not in href:
                continue
            heading = a.find(["h1", "h2", "h3", "h4"])
            title = re.sub(
                r"\s+", " ",
                (heading or a).get_text(" ", strip=True),
            ).strip()
            if not title or len(title) < 3:
                continue
            node = a.find_parent(["li", "article"]) or a
            card = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            evidence = f"{title} {card} {href}".lower()
            if not re.search(
                r"\b(ireland|dublin|cork|galway|limerick|waterford|athlone|navan|sligo|kilkenny|leixlip|kildare)\b",
                evidence,
            ):
                continue
            city = next(
                (
                    name for name in (
                        "Dublin", "Cork", "Galway", "Limerick", "Waterford",
                        "Athlone", "Navan", "Sligo", "Kilkenny", "Leixlip",
                    )
                    if re.search(rf"\b{re.escape(name)}\b", evidence, re.I)
                ),
                None,
            )
            location = f"{city}, Ireland" if city else default_location
            results[href] = {
                "company": company, "ats": "direct", "title": title[:300],
                "location": location, "url": href, "updated_at": None,
                "description_text": card[:5000],
            }
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), url)
        print(f"  ! {company} static scrape failed: {exc}")
    return list(results.values())


def scrape_alter_domus_ireland():
    return _static_official_jobs(
        "Alter Domus",
        "https://careers.alterdomus.com/en/search_jobs/Ireland/1298/1",
        "/en/job/",
    )


def scrape_baxter_ireland():
    return _static_official_jobs(
        "Baxter International",
        "https://jobs.baxter.com/en/location/ireland-jobs/152/2963597/2",
        "/en/job/",
    )


def scrape_bank_of_america():
    company = "Bank of America"
    source_url = "https://careers.bankofamerica.com/en-us/job-search/ireland"
    page = _fetch_html(source_url) or ""
    urls = []

    for m in re.finditer(
        r'href=["\']([^"\']*/en-us/job-detail/\d+/[^"\']+)["\']',
        page,
        re.I,
    ):
        href = _absolute_url(source_url, m.group(1)).split("?")[0]
        if href not in urls:
            urls.append(href)

    results = {}
    for href in urls:
        detail = _fetch_html(href) or ""
        if not detail:
            continue
        text = _html_text(detail)
        top = "\n".join(text.splitlines()[:100])

        if not re.search(r'\bDublin\s*,\s*Ireland\b', top, re.I):
            continue

        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', detail, re.I | re.S)
        title = _html_text(hm.group(1)).strip() if hm else ""
        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', detail, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""
        title = re.sub(r'\s*\|\s*Bank of America.*$', '', title, flags=re.I).strip()
        if not title:
            continue

        results[href.rstrip("/").lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    print(f"  Bank of America verified Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_cognizant():
    company = "Cognizant"

    # Current official Ireland detail-page seeds from Cognizant Careers.
    seeds = [
        ("47485", "operator-with-french"),
        ("47161", "outreach-operations-specialist-with-spanish-language"),
        ("47057", "outreach-operations-subject-matter-expert-with-either-portuguese-french-german-italian-spanish-or-arabic"),
        ("46907", "operator-with-spanish-latam"),
        ("00069586981", "deskside-support-engineer"),
    ]

    sess = _session()
    if not sess:
        print("  ! Cognizant: HTTP session unavailable")
        return []

    results = {}
    queue = list(seeds)
    seen = set()

    while queue and len(seen) < 80:
        jid, slug = queue.pop(0)
        key_id = str(jid).strip()
        if not key_id or key_id in seen:
            continue
        seen.add(key_id)

        urls = [
            f"https://careers.cognizant.com/global-en/jobs/{jid}/{slug}/",
            f"https://careers.cognizant.com/uki-en/jobs/{jid}/{slug}/",
            f"https://careers.cognizant.com/apj-en/jobs/{jid}/{slug}/",
        ]

        html_text = ""
        final_url = ""
        for href in urls:
            try:
                r = sess.get(
                    href,
                    timeout=30,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/140 Safari/537.36"
                        ),
                        "Accept-Language": "en-IE,en;q=0.9",
                    },
                )
            except Exception:
                continue

            if r.status_code == 200 and "Location" in r.text:
                html_text = r.text
                final_url = str(r.url)
                break

        if not html_text:
            continue

        text = _html_text(html_text)

        # Crawl other official Cognizant job links surfaced on detail pages.
        for mm in re.finditer(
            r'/jobs/([A-Za-z0-9]+)/(?:[^"\'<>/]+)',
            html_text,
            re.I,
        ):
            new_id = mm.group(1)
            if new_id in seen:
                continue

        # Only verified Ireland roles.
        if not re.search(r'\bIreland\b', text, re.I):
            continue
        if not re.search(r'\bDublin\b|\bIreland\b', text[:5000], re.I):
            continue

        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', html_text, re.I | re.S)
        title = _html_text(hm.group(1)).strip() if hm else ""
        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', html_text, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""
        title = re.sub(r'\s*[-|]\s*Cognizant Careers.*$', '', title, flags=re.I).strip()
        if not title:
            continue

        location = "Ireland"
        if re.search(r'\bDublin\b', text[:5000], re.I):
            location = "Dublin, Ireland"

        results[key_id] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": final_url.split("?")[0],
            "updated_at": None,
            "description_text": text[:5000],
        }

    print(f"  Cognizant official detail crawl: {len(results)} Ireland jobs")
    return list(results.values())


def scrape_aib():
    jobs = _browser_board_collect(
        "AIB (Allied Irish Banks)", ["https://jobs.aib.ie/go/Search-All-Jobs/3834700/"],
        ("jobs.aib.ie/aib/job/",), default_location="Ireland", max_scrolls=15, require_ireland=False,
    )
    cleaned=[]; seen=set()
    for j in jobs:
        text=f"{j.get('title','')} {j.get('location','')} {j.get('description_text','')} {j.get('url','')}"; low=text.lower()
        irish=bool(re.search(r"\b(dublin|cork|galway|limerick|waterford|kildare|ireland)\b",low)) or bool(re.search(r",\s*IE\b",text))
        pure_uk=bool(re.search(r"\b(london|belfast|england|scotland|wales|united kingdom)\b",low)) and not bool(re.search(r"\b(dublin|cork|galway|limerick|waterford|kildare|ireland)\b",low))
        if not irish or pure_uk: continue
        key=(j.get("url") or "").split("?",1)[0].rstrip("/").lower()
        if not key or key in seen: continue
        seen.add(key)
        if "dublin" in low: j["location"]="Dublin, Ireland"
        elif "cork" in low: j["location"]="Cork, Ireland"
        elif "galway" in low: j["location"]="Galway, Ireland"
        else: j["location"]="Ireland"
        cleaned.append(j)
    return cleaned


def scrape_central_bank_ireland():
    """Central Bank of Ireland Candidate Manager board; a reachable empty board is a healthy zero."""
    company="Central Bank of Ireland"
    url="https://www.candidatemanager.net/cm/p/pJobs.aspx?a=1bqO7eBaJhQ%3D&mid=YUYF&sid=BDCXCX"
    if not HAS_PLAYWRIGHT:
        print(f"  ! {company}: Playwright unavailable"); return []
    results={}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True); page=browser.new_page(viewport={"width":1400,"height":1000},locale="en-IE")
            page.goto(url,wait_until="domcontentloaded",timeout=60000); page.wait_for_timeout(900)
            _mark_connector_health(company,True,"Candidate Manager vacancies board loaded",page.url)
            body=_browser_text(page.locator("body"))
            if "no jobs were found" not in body.lower():
                anchors=page.locator("a[href*='pJobDetails.aspx']")
                for i in range(anchors.count()):
                    a=anchors.nth(i); href=urllib.parse.urljoin(page.url,a.get_attribute("href") or ""); title=_browser_text(a)
                    if href and title: results[href]={"company":company,"ats":"direct","title":title[:300],"location":"Dublin, Ireland","url":href,"updated_at":None,"description_text":title}
            browser.close()
    except Exception as exc:
        _mark_connector_health(company,False,str(exc),url); print(f"  ! {company} scrape failed: {exc}")
    print(f"  {company}: {len(results)} current vacancies")
    return list(results.values())


def scrape_bnp_paribas():
    """BNP's Dublin listing is server rendered and currently exposes the live offers directly."""
    company="BNP Paribas"
    urls=["https://group.bnpparibas/en/careers/all-job-offers/dublin","https://group.bnpparibas/en/careers/all-job-offers/permanent/ireland"]
    results={}
    for url in urls:
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode("utf-8",errors="ignore")
            _mark_connector_health(company,True,"Official BNP Paribas Dublin careers page loaded",url)
            soup=BeautifulSoup(html,"html.parser")
            for a in soup.find_all("a",href=True):
                href=urllib.parse.urljoin(url,a.get("href") or "")
                # BNP detail slugs live under /en/jobs/... or career offer paths; accept candidates whose card says Dublin/Ireland.
                title=re.sub(r"\s+"," ",a.get_text(" ",strip=True)).strip()
                if not title or len(title)<4: continue
                node=a; card=title
                for _ in range(4):
                    node=node.parent if getattr(node,"parent",None) else None
                    if not node: break
                    txt=re.sub(r"\s+"," ",node.get_text(" ",strip=True)).strip()
                    if txt and len(txt)<=2200: card=txt
                ev=f"{title} {card} {href}".lower()
                if not re.search(r"\b(dublin|ireland)\b",ev): continue
                if not ("/careers/" in href or "/jobs/" in href): continue
                if "all-job-offers" in href and href.rstrip("/") in {u.rstrip("/") for u in urls}: continue
                if any(x in title.lower() for x in ["create email alert","display job offers","apply now"]):
                    continue
                results[href]={"company":company,"ats":"direct","title":title[:300],"location":"Dublin, Ireland","url":href,"updated_at":None,"description_text":card[:5000]}
        except Exception as exc:
            print(f"  ! BNP page failed: {exc}")
    # Browser fallback using broader href acceptance.
    if not results:
        jobs=_browser_board_collect(company,urls,("group.bnpparibas/en/careers/",),default_location="Dublin, Ireland",max_scrolls=20,require_ireland=False)
        for j in jobs:
            txt=f"{j.get('title','')} {j.get('description_text','')} {j.get('url','')}".lower()
            if "dublin" in txt or "ireland" in txt: results[j['url']]=j
    print(f"  BNP Paribas official careers: {len(results)} Ireland jobs")
    if not results:
        _mark_connector_health(
            company,
            False,
            "Needs verification: official page has Ireland vacancies but collector returned 0 / encountered access blocking",
            "https://group.bnpparibas/en/careers/all-job-offers/dublin",
        )
    return list(results.values())


def scrape_capgemini():
    """
    Capgemini official Ireland collector.

    Uses the same public job-stream API used by Capgemini's official
    Ireland-filtered job-search page.
    """
    company = "Capgemini"

    source_url = (
        "https://www.capgemini.com/careers/join-capgemini/job-search/"
        "?page=1&size=11&country_code=ie-en%2Cen-ie"
    )

    api_url = (
        "https://cg-jobstream-api.azurewebsites.net/api/job-search"
    )

    sess = _session()
    if not sess:
        print("  ! Capgemini: HTTP session unavailable")
        return []

    try:
        r = sess.get(
            api_url,
            params={
                "country_code": "ie-en,en-ie",
                "page": 1,
                "size": 100,
            },
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        print(f"  ! Capgemini Ireland API failed: {exc}")
        try:
            _mark_connector_health(
                company,
                False,
                f"Capgemini Ireland API failed: {exc}",
                source_url,
            )
        except Exception:
            pass
        return []

    # Locate the list of jobs defensively because the API wrapper may
    # change while the individual job records remain the same.
    rows = []

    if isinstance(payload, list):
        rows = payload

    elif isinstance(payload, dict):
        for key in (
            "jobs",
            "results",
            "items",
            "data",
            "jobSearchResult",
            "job_search_result",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                rows = value
                break

            if isinstance(value, dict):
                for subkey in (
                    "jobs",
                    "results",
                    "items",
                    "data",
                    "content",
                ):
                    sub = value.get(subkey)
                    if isinstance(sub, list):
                        rows = sub
                        break

            if rows:
                break

    # Last defensive search for a list of job-like dictionaries.
    if not rows and isinstance(payload, dict):
        def find_rows(obj):
            if isinstance(obj, list):
                if obj and all(isinstance(x, dict) for x in obj):
                    score = 0
                    for x in obj[:5]:
                        keys = {str(k).lower() for k in x}
                        if keys & {
                            "title", "jobtitle", "job_title",
                            "name", "jobname"
                        }:
                            score += 1
                    if score:
                        return obj

                for x in obj:
                    found = find_rows(x)
                    if found:
                        return found

            elif isinstance(obj, dict):
                for value in obj.values():
                    found = find_rows(value)
                    if found:
                        return found

            return []

        rows = find_rows(payload)

    results = []

    def first(row, *keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, "", [], {}):
                return value
        return ""

    for row in rows:
        if not isinstance(row, dict):
            continue

        title = str(first(
            row,
            "title",
            "jobTitle",
            "job_title",
            "name",
            "jobName",
        ) or "").strip()

        location = first(
            row,
            "location",
            "locations",
            "city",
            "jobLocation",
            "job_location",
        )

        if isinstance(location, list):
            location = ", ".join(
                str(x.get("name") if isinstance(x, dict) else x)
                for x in location
                if x
            )
        elif isinstance(location, dict):
            location = (
                location.get("name")
                or location.get("city")
                or location.get("label")
                or ""
            )

        location = str(location or "").strip()

        job_id = str(first(
            row,
            "id",
            "jobId",
            "job_id",
            "jobID",
            "requisitionId",
            "requisition_id",
        ) or "").strip()

        url = str(first(
            row,
            "url",
            "jobUrl",
            "job_url",
            "link",
            "applyUrl",
            "apply_url",
        ) or "").strip()

        # Capgemini's official frontend currently exposes details as
        # /jobs/<identifier>. Preserve API URLs when supplied; otherwise
        # construct the official Capgemini detail route.
        if url.startswith("/"):
            url = "https://www.capgemini.com" + url

        if not url and job_id:
            url = "https://www.capgemini.com/jobs/" + job_id

        # Country-filtered API should already contain Ireland only, but
        # retain a defensive Ireland/Dublin check if location is supplied.
        loc_low = location.lower()
        if location and not any(
            x in loc_low
            for x in (
                "ireland",
                "dublin",
                "cork",
                "galway",
                "limerick",
                "waterford",
                "kilkenny",
                "athlone",
            )
        ):
            continue

        if not title:
            continue

        results.append({
            "company": company,
            "title": title,
            "location": location or "Ireland",
            "url": url or source_url,
        })

    # Deduplicate.
    deduped = []
    seen = set()

    for job in results:
        key = (
            job.get("title", "").strip().lower(),
            job.get("location", "").strip().lower(),
            job.get("url", "").strip().lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(job)

    try:
        _mark_connector_health(
            company,
            bool(deduped),
            f"Capgemini official Ireland API returned {len(deduped)} jobs",
            source_url,
        )
    except Exception:
        pass

    print(
        f"  Capgemini official Ireland careers: "
        f"{len(deduped)} jobs"
    )

    return deduped


def scrape_fidelity_international():
    """
    Fidelity International official Workday Ireland collector.

    Uses the official Ireland country facet:
      tenant = fil
      host   = wd3
      site   = 001
    """
    company = "Fidelity International"
    base = "https://fil.wd3.myworkdayjobs.com"
    site = "001"
    api = f"{base}/wday/cxs/fil/{site}/jobs"
    ireland_id = "04a05835925f45b3a59406a2a6b72c8a"

    sess = _session()
    if not sess:
        print("  ! Fidelity International: HTTP session unavailable")
        return []

    results = {}
    offset = 0

    while offset < 500:
        payload = {
            "appliedFacets": {
                "locationCountry": [ireland_id]
            },
            "limit": 20,
            "offset": offset,
            "searchText": "",
        }

        try:
            r = sess.post(
                api,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Language": "en-IE,en;q=0.9",
                    "Referer": f"{base}/{site}",
                },
            )
            if r.status_code != 200:
                print(f"  ! Fidelity Workday HTTP {r.status_code}")
                break
            data = r.json()
        except Exception as exc:
            print(f"  ! Fidelity Workday failed: {exc}")
            break

        rows = data.get("jobPostings") or []
        if not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue

            title = str(row.get("title") or "").strip()
            external_path = str(row.get("externalPath") or "").strip()
            bullets = row.get("bulletFields") or []

            if not title or not external_path:
                continue

            blob = " ".join(str(x) for x in bullets)

            # Ireland facet is already authoritative, but keep an extra ROI gate.
            if re.search(r"\b(?:Belfast|Northern Ireland)\b", blob, re.I):
                continue

            public_url = f"{base}/{site}{external_path}"
            detail_api = f"{base}/wday/cxs/fil/{site}{external_path}"

            location = "Dublin, Ireland"
            description_text = blob
            updated_at = None
            employment_type = None

            try:
                dr = sess.get(
                    detail_api,
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                        "Accept-Language": "en-IE,en;q=0.9",
                        "Referer": f"{base}/{site}",
                    },
                )
                if dr.status_code == 200:
                    detail = dr.json()
                    info = detail.get("jobPostingInfo") or {}

                    loc = str(info.get("location") or "").strip()
                    if loc:
                        location = loc

                    desc = str(
                        info.get("jobDescription")
                        or info.get("description")
                        or ""
                    )
                    if desc:
                        description_text = desc

                    updated_at = (
                        info.get("startDate")
                        or info.get("postedOn")
                        or None
                    )

                    job_time = str(info.get("timeType") or "")
                    worker_type = str(info.get("workerSubType") or "")

                    typetext = f"{job_time} {worker_type}".lower()
                    if "fixed" in typetext or "temp" in typetext or "ftc" in title.lower():
                        employment_type = "contract"
                    elif "full" in typetext or "permanent" in typetext:
                        employment_type = "full_time"

            except Exception:
                pass

            if re.search(r"\bDublin\b", f"{location} {blob}", re.I):
                location = "Dublin, Ireland"
            elif not re.search(r"\bIreland\b", location, re.I):
                location = "Ireland"

            key = public_url.split("?")[0].rstrip("/").lower()

            results[key] = {
                "company": company,
                "ats": "workday",
                "title": title[:300],
                "location": location[:160],
                "url": public_url,
                "updated_at": updated_at,
                "description_text": description_text[:7000],
                "employment_type": employment_type,
                "requisition_id": (
                    bullets[1] if len(bullets) > 1 else ""
                ),
            }

        offset += len(rows)

        total = data.get("total")
        if isinstance(total, int) and offset >= total:
            break

    _mark_connector_health(
        company,
        True,
        f"Official Fidelity International Workday returned {len(results)} Ireland jobs",
        f"{base}/{site}",
    )

    print(f"  Fidelity International official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_bloomberg():
    """
    Bloomberg official Avature Ireland collector.

    Uses Bloomberg's live filtered Avature board and paginates with jobOffset.
    """
    company = "Bloomberg"
    base = "https://bloomberg.avature.net"
    search_base = (
        f"{base}/careers/SearchJobs/"
        "?1845=%5B162465%5D"
        "&1845_format=3996"
        "&listFilterMode=1"
        "&jobRecordsPerPage=12"
    )

    sess = _session()
    if not sess:
        print("  ! Bloomberg: HTTP session unavailable")
        return []

    results = {}
    seen_ids = set()

    for offset in range(0, 600, 12):
        url = f"{search_base}&jobOffset={offset}"

        try:
            r = sess.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
            if r.status_code != 200:
                print(f"  ! Bloomberg Avature HTTP {r.status_code}")
                break
            html_text = r.text or ""
        except Exception as exc:
            print(f"  ! Bloomberg Avature failed: {exc}")
            break

        before = len(seen_ids)

        matches = re.findall(
            r'https?://bloomberg\.avature\.net/careers/JobDetail/([^/"<>]+)/(\d+)',
            html_text,
            re.I,
        )

        # Also allow relative detail URLs.
        matches += re.findall(
            r'href=["\']/careers/JobDetail/([^/"\']+)/(\d+)["\']',
            html_text,
            re.I,
        )

        for slug, job_id in matches:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_url = f"{base}/careers/JobDetail/{slug}/{job_id}"

            title = re.sub(r"[-_]+", " ", slug)
            title = re.sub(r"\s+", " ", title).strip()
            location = "Dublin, Ireland"
            description_text = ""

            try:
                dr = sess.get(
                    detail_url,
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-IE,en;q=0.9",
                        "Referer": url,
                    },
                )

                if dr.status_code == 200:
                    dhtml = dr.text or ""

                    # Bloomberg Avature detail pages may use an H1 containing
                    # only the company name ("Bloomberg"). Prefer structured
                    # page metadata and fall back to the canonical URL slug.
                    candidates = []

                    for pattern in [
                        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
                        r'<title\b[^>]*>(.*?)</title>',
                    ]:
                        mm = re.search(pattern, dhtml, re.I | re.S)
                        if mm:
                            candidates.append(
                                re.sub(
                                    r"\s+",
                                    " ",
                                    _html_text(mm.group(1)),
                                ).strip()
                            )

                    hm = re.search(
                        r'<h1\b[^>]*>(.*?)</h1>',
                        dhtml,
                        re.I | re.S,
                    )
                    if hm:
                        candidates.append(
                            re.sub(
                                r"\s+",
                                " ",
                                _html_text(hm.group(1)),
                            ).strip()
                        )

                    for candidate in candidates:
                        candidate = re.sub(
                            r"\s*[-|]\s*Bloomberg.*$",
                            "",
                            candidate,
                            flags=re.I,
                        ).strip()

                        if (
                            candidate
                            and candidate.lower() not in {
                                "bloomberg",
                                "careers",
                                "search jobs",
                                "jobs",
                            }
                            and len(candidate) >= 4
                        ):
                            title = candidate
                            break

                    # Final authoritative fallback: the Avature URL slug is
                    # already the actual job title.
                    if not title or title.lower() == "bloomberg":
                        title = re.sub(r"[-_]+", " ", slug)
                        title = re.sub(r"\s+", " ", title).strip()

                    description_text = re.sub(
                        r"\s+",
                        " ",
                        _html_text(dhtml),
                    ).strip()

                    # This filtered board is Dublin/Ireland, but reject
                    # clearly non-Ireland detail pages just in case.
                    if re.search(
                        r"\b(?:London|New York|Hong Kong|Singapore|Sydney)\b",
                        description_text,
                        re.I,
                    ) and not re.search(
                        r"\b(?:Dublin|Ireland)\b",
                        description_text,
                        re.I,
                    ):
                        continue

                    if re.search(r"\bDublin\b", description_text, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bIreland\b", description_text, re.I):
                        location = "Ireland"

            except Exception:
                pass

            key = detail_url.lower()

            results[key] = {
                "company": company,
                "ats": "avature",
                "title": title[:300],
                "location": location,
                "url": detail_url,
                "updated_at": None,
                "description_text": description_text[:7000],
            }

        if len(seen_ids) == before:
            break

    _mark_connector_health(
        company,
        True,
        f"Bloomberg Avature returned {len(results)} Ireland jobs",
        search_base,
    )

    print(f"  Bloomberg official Avature Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_blackrock():
    """
    BlackRock official Dublin collector.

    TalentBrew's generic ?location= query can return global results.
    Use the canonical Dublin location route exposed by BlackRock's own
    location facets.
    """
    company = "BlackRock"

    source = (
        "https://careers.blackrock.com/location/"
        "dublin-jobs/45831/2963597-7521314-2964574/4"
    )

    sess = _session()
    if not sess:
        return []

    try:
        r = sess.get(
            source,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
        r.raise_for_status()
        html_text = r.text or ""
    except Exception as exc:
        print(f"  ! BlackRock Dublin page failed: {exc}")
        return []

    results = {}

    # TalentBrew job paths look like:
    # /job/dublin/<slug>/45831/<id>
    pattern = re.compile(
        r'href=["\']'
        r'([^"\']*/job/dublin/[^"\']+/45831/\d+)'
        r'["\']',
        re.I,
    )

    for m in pattern.finditer(html_text):
        href = html.unescape(m.group(1))

        if href.startswith("/"):
            href = "https://careers.blackrock.com" + href

        href = href.split("?")[0]

        # Nearby HTML usually contains title/location/team.
        lo = max(0, m.start() - 2500)
        hi = min(len(html_text), m.end() + 3500)
        card_html = html_text[lo:hi]
        card_text = re.sub(
            r"\s+",
            " ",
            _html_text(card_html),
        ).strip()

        if not re.search(r"\bDublin\b", card_text, re.I):
            continue

        # Try title from anchor/card.
        title = ""

        tm = re.search(
            r'<a[^>]+href=["\'][^"\']*'
            + re.escape(
                urllib.parse.urlparse(href).path
            )
            + r'[^"\']*["\'][^>]*>(.*?)</a>',
            card_html,
            re.I | re.S,
        )

        if tm:
            title = re.sub(
                r"\s+",
                " ",
                _html_text(tm.group(1)),
            ).strip()

        if not title:
            tm = re.search(
                r'<h[1-4][^>]*>(.*?)</h[1-4]>',
                card_html,
                re.I | re.S,
            )
            if tm:
                title = re.sub(
                    r"\s+",
                    " ",
                    _html_text(tm.group(1)),
                ).strip()

        # Detail page gives cleaner title/description.
        detail_text = card_text

        try:
            dr = sess.get(
                href,
                timeout=25,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                    "Referer": source,
                },
            )

            if dr.status_code == 200:
                dhtml = dr.text or ""
                detail_text = re.sub(
                    r"\s+",
                    " ",
                    _html_text(dhtml),
                ).strip()

                hm = re.search(
                    r'<h1\b[^>]*>(.*?)</h1>',
                    dhtml,
                    re.I | re.S,
                )

                if hm:
                    clean = re.sub(
                        r"\s+",
                        " ",
                        _html_text(hm.group(1)),
                    ).strip()
                    if clean:
                        title = clean

                if not title:
                    tm = re.search(
                        r'<title\b[^>]*>(.*?)</title>',
                        dhtml,
                        re.I | re.S,
                    )
                    if tm:
                        title = re.sub(
                            r"\s+",
                            " ",
                            _html_text(tm.group(1)),
                        ).strip()

        except Exception:
            pass

        title = re.sub(
            r"\s+Location:.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        title = re.sub(
            r"\s*\|\s*BlackRock.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        if not title:
            continue

        validation = f"{card_text} {detail_text}"

        if not re.search(r"\bDublin\b", validation, re.I):
            continue

        key = href.rstrip("/").lower()

        results[key] = {
            "company": company,
            "ats": "talentbrew",
            "title": title[:300],
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": detail_text[:7000],
        }

    _mark_connector_health(
        company,
        True,
        f"BlackRock Dublin TalentBrew page returned {len(results)} jobs",
        source,
    )

    print(f"  BlackRock official Dublin careers: {len(results)} jobs")
    return list(results.values())



def scrape_bank_of_ireland():
    """
    Bank of Ireland official Ireland careers collector.

    The official country-filtered board is server-rendered, so collect
    canonical /jobs/<slug> links directly and paginate normally.
    """
    company = "Bank of Ireland"
    base = "https://careers.bankofireland.com"

    sess = _session()
    if not sess:
        print("  ! Bank of Ireland: HTTP session unavailable")
        return []

    results = {}

    for page_no in range(1, 60):
        search_url = (
            f"{base}/jobs/search"
            f"?page={page_no}"
            "&country_codes%5B%5D=IE"
            "&query="
        )

        try:
            r = sess.get(
                search_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
            if r.status_code != 200:
                print(f"  ! Bank of Ireland page {page_no} HTTP {r.status_code}")
                break
            html_text = r.text or ""
        except Exception as exc:
            print(f"  ! Bank of Ireland careers failed: {exc}")
            break

        before = len(results)

        links = re.findall(
            r'href=["\'](https://careers\.bankofireland\.com/jobs/[^"\'?#]+)["\']',
            html_text,
            re.I,
        )

        links += [
            base + x
            for x in re.findall(
                r'href=["\'](/jobs/[^"\'?#]+)["\']',
                html_text,
                re.I,
            )
        ]

        for href in links:
            href = href.rstrip("/")

            if "/jobs/search" in href:
                continue

            key = href.lower()
            if key in results:
                continue

            slug = href.rsplit("/", 1)[-1]
            title = re.sub(r"[-_]+", " ", slug)
            title = re.sub(r"\s+", " ", title).strip()

            # Remove trailing location words from slug-derived fallback.
            title = re.sub(
                r"\s+(?:dublin|cork|galway|limerick|waterford)\s+ireland$",
                "",
                title,
                flags=re.I,
            ).strip()

            location = "Ireland"
            description_text = ""

            try:
                dr = sess.get(
                    href,
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-IE,en;q=0.9",
                        "Referer": search_url,
                    },
                )

                if dr.status_code == 200:
                    dhtml = dr.text or ""

                    hm = re.search(
                        r'<h1\b[^>]*>(.*?)</h1>',
                        dhtml,
                        re.I | re.S,
                    )
                    if hm:
                        clean = re.sub(
                            r"\s+",
                            " ",
                            _html_text(hm.group(1)),
                        ).strip()
                        if clean:
                            title = clean

                    description_text = re.sub(
                        r"\s+",
                        " ",
                        _html_text(dhtml),
                    ).strip()

                    if re.search(r"\bDublin\b", description_text, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bCork\b", description_text, re.I):
                        location = "Cork, Ireland"
                    elif re.search(r"\bGalway\b", description_text, re.I):
                        location = "Galway, Ireland"
                    elif re.search(r"\bLimerick\b", description_text, re.I):
                        location = "Limerick, Ireland"

            except Exception:
                pass

            if not title:
                continue

            results[key] = {
                "company": company,
                "ats": "bankofireland_official",
                "title": title[:300],
                "location": location,
                "url": href,
                "updated_at": None,
                "description_text": description_text[:7000],
            }

        if len(results) == before:
            break

    _mark_connector_health(
        company,
        True,
        f"Bank of Ireland official board returned {len(results)} Ireland jobs",
        f"{base}/jobs/search?country_codes%5B%5D=IE",
    )

    print(f"  Bank of Ireland official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_ing():
    return _browser_board_collect(
        "ING",
        ["https://careers.ing.com/en/location/dublin-jobs/2618/2963597-7521314-2964574/4"],
        ("careers.ing.com/en/job/dublin/",),
        default_location="Dublin, Ireland",
        max_scrolls=30,
        require_ireland=False,
        source_tag="ing_official",
    )


def scrape_jnj():
    return _browser_board_collect(
        "Johnson & Johnson",
        [
            "https://www.careers.jnj.com/en/locations/emea/ireland/",
            "https://www.careers.jnj.com/en/jobs/?location=Ireland&search=",
        ],
        (
            "careers.jnj.com/en/jobs/",
            "careers.jnj.com/en/job/",
        ),
        default_location="Ireland",
        max_scrolls=35,
        require_ireland=True,
    )


def scrape_johnson_controls():
    if not HAS_PLAYWRIGHT:
        print("  ! Johnson Controls: Playwright unavailable")
        return []
    results = {}
    params = urllib.parse.urlencode({
        "production_JCI_jobs[refinementList][locations_list][0]": "Ireland"
    })
    url = "https://jobs.johnsoncontrols.com/job-search?" + params
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1600)
            _dismiss_cookie_banner(page)
            stagnant, previous = 0, 0
            for _ in range(100):
                anchors = page.locator('a[href*="/job/WD"]')
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not re.search(r"jobs\.johnsoncontrols\.com/job/WD\d+", href, re.I):
                        continue
                    key = href.split("?")[0].rstrip("/").lower()
                    if key in results:
                        continue
                    node, card = a, ""
                    for _up in range(6):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 2200:
                            card = candidate
                        if card and region_ok(card):
                            break
                    if not region_ok(card):
                        continue
                    title = _browser_text(a).strip()
                    if not title or len(title) > 300:
                        lines = [x.strip() for x in card.splitlines() if 4 <= len(x.strip()) <= 220]
                        title = lines[0] if lines else ""
                    if not title:
                        continue
                    results[key] = {
                        "company": "Johnson Controls",
                        "ats": "direct",
                        "title": title[:300],
                        "location": _browser_location(card, "Ireland"),
                        "url": href.split("?")[0],
                        "updated_at": None,
                        "description_text": card[:5000],
                    }
                for label in ("Load more", "Show more", "See more", "Next"):
                    try:
                        b = page.get_by_role("button", name=label, exact=False)
                        if b.count() and b.first.is_visible():
                            b.first.click(timeout=1000)
                            page.wait_for_timeout(350)
                            break
                    except Exception:
                        pass
                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(350)
                current = len(results)
                stagnant = stagnant + 1 if current == previous else 0
                previous = current
                if stagnant >= 8:
                    break
            browser.close()
    except Exception as exc:
        print(f"  ! Johnson Controls browser scrape failed: {exc}")
    print(f"  Johnson Controls official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_dropbox():
    return _browser_board_collect(
        "Dropbox",
        [
            "https://www.dropbox.jobs/en/jobs/",
            "https://jobs.dropbox.com/all-jobs",
        ],
        (
            "dropbox.jobs/en/jobs/",
            "jobs.dropbox.com/listing/",
        ),
        default_location="Remote - Ireland",
        max_scrolls=35,
        require_ireland=True,
    )


def _scrape_workday_board_browser(company, board_url, search_term="Ireland"):
    if not HAS_PLAYWRIGHT:
        print(f"  ! {company}: Playwright unavailable")
        return []
    results = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            page.goto(board_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1800)
            _dismiss_cookie_banner(page)
            # Workday search controls vary by tenant; try placeholders/roles, but collection also works from prefiltered URLs.
            for selector in [
                lambda: page.get_by_placeholder(re.compile(r"search", re.I)),
                lambda: page.get_by_role("textbox"),
            ]:
                try:
                    loc = selector()
                    if loc.count():
                        box = loc.first
                        box.fill(search_term, timeout=1500)
                        box.press("Enter", timeout=1500)
                        page.wait_for_timeout(1800)
                        break
                except Exception:
                    pass
            stagnant, previous = 0, 0
            for _ in range(40):
                anchors = page.locator("a[href*='/job/']")
                for i in range(anchors.count()):
                    a=anchors.nth(i)
                    try:
                        href=urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not href or href in results:
                        continue
                    title=_browser_text(a)
                    node, card=a, ""
                    for _up in range(5):
                        try:
                            node=node.locator("..")
                            candidate=_browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 2000:
                            card=candidate
                        if card and len(card)>=25:
                            break
                    if not title or len(title)>320:
                        lines=[x.strip() for x in card.splitlines() if 4 < len(x.strip()) <= 280]
                        title=lines[0] if lines else ""
                    evidence=f"{title} {card} {href}".lower()
                    if not title or not region_ok(evidence):
                        continue
                    results[href]={
                        "company": company, "ats": "direct", "title": title[:300],
                        "location": _browser_location(card, "Ireland"), "url": href,
                        "updated_at": None, "description_text": card[:5000],
                    }
                for label in ("Load more", "Show more", "Next"):
                    try:
                        btn=page.get_by_role("button", name=label, exact=False)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200); page.wait_for_timeout(600); break
                    except Exception:
                        pass
                page.mouse.wheel(0, 3200); page.wait_for_timeout(500)
                cur=len(results); stagnant = stagnant+1 if cur==previous else 0; previous=cur
                if stagnant>=6: break
            print(f"  {company} Workday browser: {len(results)} unique Ireland jobs accumulated")
            browser.close()
    except Exception as exc:
        print(f"  ! {company} Workday browser scrape failed: {exc}")
    return list(results.values())


def scrape_nvidia():
    return _scrape_workday_board_browser(
        "NVIDIA",
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/search?q=Ireland",
        "Ireland",
    )



def _scrape_grant_thornton_board(source_url):
    company = "Grant Thornton Ireland"

    if not HAS_PLAYWRIGHT:
        print("  ! Grant Thornton Ireland: Playwright unavailable")
        return []

    results = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")

            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3500)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            stagnant = 0
            prev = 0

            for _ in range(80):
                anchors = page.locator('a[href*="/job/"]')

                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    title = _browser_text(a).strip()
                    node = a
                    card = ""

                    for _up in range(7):
                        try:
                            candidate = _browser_text(node)
                        except Exception:
                            candidate = ""
                        if candidate and len(candidate) <= 3000:
                            card = candidate
                        if re.search(r"\b(?:Dublin|Ireland|Cork|Galway|Limerick)\b", card, re.I):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"

                    if not title or len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 4 <= len(x.strip()) <= 220
                        ]
                        title = next(
                            (x for x in lines if x.lower() not in {"apply now", "view job", "job description"}),
                            "",
                        )

                    if not title:
                        continue

                    location = "Ireland"
                    for city in ("Dublin", "Cork", "Galway", "Limerick"):
                        if re.search(rf"\b{city}\b", blob, re.I):
                            location = f"{city}, Ireland"
                            break

                    results[href.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "oracle",
                        "title": re.sub(r"\s+", " ", title).strip()[:300],
                        "location": location,
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                clicked = False
                for selector in (
                    'button:has-text("Load More")',
                    'button:has-text("Show More")',
                    'button:has-text("Next")',
                    'a:has-text("Next")',
                ):
                    try:
                        btn = page.locator(selector)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200)
                            page.wait_for_timeout(500)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(350)

                cur = len(results)
                stagnant = stagnant + 1 if cur == prev else 0
                prev = cur
                if stagnant >= 8 and not clicked:
                    break

            browser.close()
    except Exception as exc:
        print(f"  ! Grant Thornton Oracle jobs-page scrape failed: {exc}")

    print(f"  Grant Thornton Ireland Oracle /jobs: {len(results)} Ireland jobs")
    return list(results.values())


def scrape_grant_thornton():
    base = "https://ehzq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/"
    jobs = []
    for site in ("GrantThorntonIrelandExperiencedHires", "GrantThorntonIrelandGraduateProgramme"):
        jobs.extend(_scrape_grant_thornton_board(f"{base}{site}/jobs"))
    return list({job["url"]: job for job in jobs}.values())

def scrape_microsoft():
    return _browser_board_collect(
        "Microsoft",
        ["https://careers.microsoft.com/v2/global/en/locations/dublin.html",
         "https://apply.careers.microsoft.com/careers?location=Ireland"],
        ("apply.careers.microsoft.com",),
        default_location="Dublin, Ireland",
        max_scrolls=15,
    )

def scrape_oracle():
    """Oracle Ireland: use the public Oracle Recruiting Cloud REST resource
    where available, with the rendered Candidate Experience page as fallback.
    """
    try:
        jobs = scrape_oracle_candidate_experience(
            "Oracle",
            "https://eeho.fa.us2.oraclecloud.com",
            "CX_1",
            "IE",
        )
        if jobs:
            return jobs
    except Exception as e:
        print(f"  ! Oracle recruiting REST fallback: {e}")

    return _scrape_public_careers_page(
        "Oracle",
        "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions?location=Ireland",
        ("/job/", "/requisitions/", "candidateexperience"),
        default_location="Ireland",
    )


def scrape_redhat():
    """Red Hat Ireland: use the official jobs/locations surface. If the current
    Red Hat site renders job cards client-side and returns zero here, the
    priority employer rescue immediately supplements it via configured APIs.
    """
    jobs = _scrape_public_careers_page(
        "Red Hat",
        "https://www.redhat.com/en/jobs/locations",
        ("/en/jobs/", "/jobs/", "job/"),
        default_location="Ireland",
    )

    # Avoid accidentally treating informational Red Hat careers pages as jobs.
    blocked = {
        "locations", "departments", "life at red hat", "hiring process",
        "info guide", "students", "benefits",
    }
    cleaned = []
    for j in jobs:
        title = (j.get("title") or "").strip().lower()
        url = (j.get("url") or "").lower()
        if any(term in title for term in blocked):
            continue
        if any(f"/jobs/{term.replace(' ', '-')}" in url for term in blocked):
            continue
        cleaned.append(j)
    return cleaned




def scrape_servicenow():
    """ServiceNow Ireland via exact SmartRecruiters tenant, with official-page fallback."""
    company = "ServiceNow"
    source_url = "https://careers.servicenow.com/locations/emea/ireland/"

    jobs = scrape_smartrecruiters("ServiceNow")
    cleaned = []
    seen = set()

    for j in jobs:
        loc = str(j.get("location") or "")
        url = str(j.get("url") or "")
        title = str(j.get("title") or "").strip()
        if not title or not region_ok(loc):
            continue
        j["company"] = company
        j["ats"] = "smartrecruiters"

        job_id = url.rstrip("/").split("/")[-1]
        if job_id.isdigit():
            j["url"] = f"https://jobs.smartrecruiters.com/ServiceNow/{job_id}"

        url = str(j.get("url") or "")
        key = (url.split("?")[0].rstrip("/").lower(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(j)

    if cleaned:
        try:
            _mark_connector_health(
                company, True,
                f"ServiceNow SmartRecruiters tenant loaded; {len(cleaned)} Ireland jobs found",
                source_url,
            )
        except Exception:
            pass
        print(f"  ServiceNow official Ireland careers: {len(cleaned)} jobs")
        return cleaned

    try:
        rows = _scrape_public_careers_page(
            company,
            source_url,
            ("/jobs/",),
            default_location="Dublin, Ireland",
        )
    except Exception as exc:
        print(f"  ! ServiceNow fallback failed: {exc}")
        rows = []

    out = {}
    for job in rows:
        href = (job.get("url") or "").strip()
        title = re.sub(r"\s+", " ", (job.get("title") or "")).strip()
        m = re.match(
            r"^https?://careers\.servicenow\.com/jobs/(\d+)/([^?#]+?)/?(?:[?#].*)?$",
            href,
            re.I,
        )
        if not m or not title:
            continue
        canonical = f"https://careers.servicenow.com/jobs/{m.group(1)}/{m.group(2).strip('/')}/"
        item = dict(job)
        item.update({
            "company": company,
            "ats": "direct",
            "title": title,
            "location": "Dublin, Ireland",
            "url": canonical,
        })
        out[canonical.lower()] = item

    try:
        _mark_connector_health(
            company,
            bool(out),
            f"Official ServiceNow Ireland page loaded; {len(out)} Ireland jobs found",
            source_url,
        )
    except Exception:
        pass

    print(f"  ServiceNow official Ireland careers: {len(out)} jobs")
    return list(out.values())

def scrape_harvey_nash():
    company = "Harvey Nash"
    urls = [
        "https://www.harveynash.ie/",
        "https://www.harveynash.co.uk/jobs",
    ]
    results = {}

    if not HAS_PLAYWRIGHT:
        print("  ! Harvey Nash: Playwright unavailable")
        return []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1400)
                    _dismiss_cookie_banner(page)
                except Exception:
                    continue

                # Search Ireland/Dublin when the job search inputs are present.
                try:
                    inputs = page.locator("input")
                    for i in range(inputs.count()):
                        inp = inputs.nth(i)
                        ph = (inp.get_attribute("placeholder") or "").lower()
                        if "town" in ph or "city" in ph or "county" in ph or "location" in ph:
                            inp.fill("Ireland")
                            try:
                                inp.press("Enter")
                            except Exception:
                                pass
                            page.wait_for_timeout(900)
                            break
                except Exception:
                    pass

                anchors = page.locator("a[href]")
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    hlow = href.lower()
                    if "/job" not in hlow and "/jobs/" not in hlow:
                        continue
                    title = _browser_text(a).strip()
                    node, card = a, ""
                    for _up in range(5):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 2200:
                            card = candidate
                        if card and region_ok(card):
                            break
                    if not region_ok(f"{title} {card} {href}"):
                        continue
                    if not title or len(title) > 300:
                        lines = [x.strip() for x in card.splitlines() if 4 <= len(x.strip()) <= 220]
                        title = lines[0] if lines else ""
                    if not title:
                        continue
                    bad_titles = {
                        "find tech jobs",
                        "search tech jobs",
                        "jobs",
                        "dublin",
                        "ireland",
                    }

                    if (
                        title.lower() in bad_titles
                        or "bulk_consent" in title.lower()
                        or "cross-domain consent" in title.lower()
                    ):
                        continue
                    key = href.split("?")[0].rstrip("/").lower()
                    results[key] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": _browser_location(card, "Ireland"),
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }
            browser.close()
    except Exception as exc:
        print(f"  ! Harvey Nash browser scrape failed: {exc}")

    print(f"  Harvey Nash official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_smbc_group():
    company = "SMBC Group"
    urls = [
        "https://careersemea.smbcgroup.com/search/?createNewAlert=false&q=&locationsearch=ireland&optionsFacetsDD_country=&optionsFacetsDD_city=&optionsFacetsDD_department=",
        "https://careersemea.smbcgroup.com/search/?q=&locationsearch=Dublin",
        "https://careers.smbcgroup.com/smbc/search/?q=&locationsearch=Tralee",
    ]
    results = {}
    for url in urls:
        try:
            rows = _scrape_public_careers_page(
                company,
                url,
                ("/job/",),
                default_location="Ireland",
            )
        except Exception:
            rows = []
        for job in rows:
            href = (job.get("url") or "").strip()
            title = re.sub(r"\s+", " ", str(job.get("title") or "")).strip()
            if not href or not title:
                continue
            if not re.search(r"smbcgroup\.com/.*/job/", href, re.I):
                continue
            evidence = f"{title} {job.get('location','')} {job.get('description_text','')} {href}"
            if not region_ok(evidence):
                continue
            key = href.split("?")[0].rstrip("/").lower()
            item = dict(job)
            item["company"] = company
            item["ats"] = "successfactors"
            item["url"] = href.split("?")[0]
            results[key] = item

    if not results and HAS_PLAYWRIGHT:
        try:
            rows = _browser_board_collect(
                company,
                urls,
                ("/job/",),
                default_location="Ireland",
                max_scrolls=35,
                require_ireland=True,
                source_tag="successfactors",
            )
            for job in rows:
                href = (job.get("url") or "").strip()
                if href:
                    results[href.split("?")[0].rstrip("/").lower()] = job
        except Exception:
            pass

    print(f"  SMBC Group official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_deutsche_bank():
    company = "Deutsche Bank"

    # Current official Deutsche Bank Workday tenant.
    jobs = scrape_workday(
        company,
        "db",
        "wd3",
        "DBWebsite",
        max_pages=40,
    )

    # Hard-validate Ireland in case Workday's global board leaks other locations.
    out = []
    seen = set()

    for job in jobs or []:
        title = str(job.get("title") or "").strip()
        location = str(job.get("location") or "").strip()
        url = str(job.get("url") or "").strip()

        blob = f"{title} {location} {url}"

        if not region_ok(blob):
            continue
        if not title or not url:
            continue

        key = url.split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)

        job["company"] = company
        job["ats"] = "workday"
        out.append(job)

    print(f"  Deutsche Bank official Workday: {len(out)} Ireland jobs")
    return out


def scrape_arup():
    company = "Arup"
    source_url = "https://jobs.arup.com/page/jobs-in-ireland-252"
    page = _fetch_html(source_url) or ""
    results = {}

    # Arup's Taleo page repeats the same job URL for the title and "Learn More".
    # Capture the real title anchor plus nearby Ireland location/requisition text.
    anchors = list(re.finditer(
        r'<a\b[^>]*href=["\']([^"\']*?/jobs/[^"\']+)["\'][^>]*>(.*?)</a>',
        page,
        flags=re.I | re.S,
    ))

    for idx, m in enumerate(anchors):
        href = _absolute_url(source_url, m.group(1))
        label = _html_text(m.group(2)).strip()
        if not label or label.lower() in {"learn more", "jobs", "search jobs"}:
            continue

        start = max(0, m.start() - 400)
        end = min(len(page), m.end() + 1800)
        chunk = _html_text(page[start:end])

        if not region_ok(chunk):
            continue

        lm = re.search(
            r'(Dublin|Cork|Galway|Limerick|Waterford|Ireland)(?:[^|•<>]{0,80})',
            chunk,
            re.I,
        )
        location = lm.group(0).strip()[:140] if lm else "Ireland"

        canonical = href.split("?")[0]
        key = canonical.rstrip("/").lower()
        results[key] = {
            "company": company,
            "ats": "taleo",
            "title": label[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": chunk[:5000],
        }

    # Browser fallback.
    if not results and HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page_obj = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
                page_obj.goto(source_url, wait_until="domcontentloaded", timeout=60000)
                page_obj.wait_for_timeout(1200)
                anchors = page_obj.locator('a[href*="/jobs/"]')
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    href = urllib.parse.urljoin(page_obj.url, a.get_attribute("href") or "")
                    title = _browser_text(a).strip()
                    if not title or title.lower() == "learn more":
                        continue
                    node, card = a, ""
                    for _ in range(5):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 2200:
                            card = candidate
                        if card and region_ok(card):
                            break
                    if not region_ok(card):
                        continue
                    key = href.split("?")[0].rstrip("/").lower()
                    results[key] = {
                        "company": company,
                        "ats": "taleo",
                        "title": title[:300],
                        "location": _browser_location(card, "Ireland"),
                        "url": href.split("?")[0],
                        "updated_at": None,
                        "description_text": card[:5000],
                    }
                browser.close()
        except Exception as exc:
            print(f"  ! Arup browser fallback failed: {exc}")

    print(f"  Arup official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_hcltech():
    company = "HCLTech"
    source = (
        "https://careers.hcltech.com/go/NonTPDemand/9558355/"
        "?markerViewed=&carouselIndex="
        "&facetFilters=%7B%22custCountryRegion%22%3A%5B%22Ireland%22%5D%7D"
        "&pageNumber=0"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! HCLTech: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()
            page.goto(source, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            discovered = {}

            for item in links:
                href = str(item.get("href") or "")
                title = re.sub(
                    r"\s+",
                    " ",
                    str(item.get("text") or ""),
                ).strip()

                if not re.search(
                    r"careers\.hcltech\.com/job/.+/\d+-en_US",
                    href,
                    re.I,
                ):
                    continue

                if not title:
                    continue

                m = re.search(r"/(\d+)-en_US(?:$|[?#])", href, re.I)
                if not m:
                    continue

                job_id = m.group(1)

                discovered[job_id] = {
                    "title": title,
                    "href": href.split("#")[0],
                }

            for job_id, item in discovered.items():
                title = item["title"]
                href = item["href"]
                location = "Ireland"
                description = ""

                detail = context.new_page()

                try:
                    detail.goto(
                        href,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    detail.wait_for_timeout(700)

                    body = detail.locator("body").inner_text(timeout=10000)
                    description = body[:5000]

                    if re.search(r"\bDublin\b", body, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bCork\b", body, re.I):
                        location = "Cork, Ireland"
                    elif re.search(r"\bGalway\b", body, re.I):
                        location = "Galway, Ireland"
                    elif re.search(r"\bLimerick\b", body, re.I):
                        location = "Limerick, Ireland"

                except Exception:
                    pass

                detail.close()

                results[job_id] = {
                    "company": company,
                    "ats": "successfactors",
                    "title": title[:300],
                    "location": location,
                    "url": href,
                    "updated_at": None,
                    "description_text": description,
                }

            browser.close()

    except Exception as exc:
        print(f"  ! HCLTech scrape failed: {exc}")

    print(
        f"  HCLTech official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_hp():
    company = "HP (Hewlett-Packard)"
    results = {}

    if not HAS_PLAYWRIGHT:
        print("  ! HP: Playwright unavailable")
        return []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="en-IE")
            page.goto("https://jobs.hp.com/", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1800)
            _dismiss_cookie_banner(page)

            # Open Search Jobs if needed.
            try:
                link = page.get_by_role("link", name=re.compile(r"Search Jobs", re.I))
                if link.count():
                    link.first.click(timeout=1500)
                    page.wait_for_timeout(1200)
            except Exception:
                pass

            for selector in (
                'input[placeholder*="location" i]',
                'input[aria-label*="location" i]',
                'input[name*="location" i]',
            ):
                try:
                    inp = page.locator(selector)
                    if inp.count():
                        inp.first.fill("Ireland")
                        try:
                            inp.first.press("Enter")
                        except Exception:
                            pass
                        page.wait_for_timeout(1200)
                        break
                except Exception:
                    pass

            for _ in range(60):
                anchors = page.locator("a[href]")
                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                    except Exception:
                        continue
                    if not any(x in href.lower() for x in ("/job/", "/jobs/", "jobdetail", "job-detail")):
                        continue
                    title = _browser_text(a).strip()
                    node, card = a, ""
                    for _up in range(6):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break
                        if candidate and len(candidate) <= 2400:
                            card = candidate
                        if card and region_ok(card):
                            break
                    if not region_ok(f"{title} {card}"):
                        continue
                    if not title or len(title) > 300:
                        continue
                    key = href.split("?")[0].rstrip("/").lower()
                    results[key] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": _browser_location(card, "Ireland"),
                        "url": href.split("?")[0],
                        "updated_at": None,
                        "description_text": card[:5000],
                    }
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(300)
            browser.close()
    except Exception as exc:
        print(f"  ! HP browser scrape failed: {exc}")

    print(f"  HP official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_jacobs():
    company = "Jacobs"
    source = (
        "https://careers.jacobs.com/en_US/careers/SearchJobs/"
        "?4182=%5B76407%5D"
        "&4182_format=4422"
        "&listFilterMode=1"
        "&jobRecordsPerPage=10&"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! Jacobs: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(4000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            discovered = {}

            for item in links:
                href = str(item.get("href") or "").strip()
                title = re.sub(
                    r"\s+",
                    " ",
                    str(item.get("text") or ""),
                ).strip()

                if not re.search(
                    r"careers\.jacobs\.com/en_US/careers/JobDetail/.+/\d+",
                    href,
                    re.I,
                ):
                    continue

                if not title:
                    continue

                # Exclude obvious Northern Ireland jobs.
                if re.search(
                    r"\bBelfast\b|\bNorthern Ireland\b",
                    title,
                    re.I,
                ):
                    continue

                m = re.search(r"/(\d+)(?:[/?#]|$)", href, re.I)
                if not m:
                    continue

                job_id = m.group(1)

                discovered[job_id] = {
                    "title": title,
                    "href": href.split("#")[0],
                }

            for job_id, item in discovered.items():
                title = item["title"]
                canonical = item["href"]

                location = "Ireland"
                description = ""

                if re.search(r"\bDublin\b", title, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bCork\b", title, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"\bGalway\b", title, re.I):
                    location = "Galway, Ireland"

                detail = context.new_page()

                try:
                    detail.goto(
                        canonical,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    detail.wait_for_timeout(700)

                    body = detail.locator("body").inner_text(
                        timeout=10000
                    )
                    description = body[:5000]

                    # Improve location from detail content.
                    if re.search(r"\bDublin\b", body, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bCork\b", body, re.I):
                        location = "Cork, Ireland"
                    elif re.search(r"\bGalway\b", body, re.I):
                        location = "Galway, Ireland"
                    elif re.search(r"\bLimerick\b", body, re.I):
                        location = "Limerick, Ireland"

                except Exception:
                    pass

                detail.close()

                results[job_id] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": description,
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Jacobs scrape failed: {exc}")

    print(
        f"  Jacobs official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_agilent():
    company = "Agilent Technologies"
    out = {}

    for site in ("Agilent_Careers", "Agilent_Student_Careers"):
        rows = scrape_workday(
            company,
            "agilent",
            "wd5",
            site,
            max_pages=30,
        )

        for j in rows:
            href = str(j.get("url") or "")
            if not href:
                continue

            j["company"] = company
            out[href.split("?")[0].rstrip("/").lower()] = j

    print(f"  Agilent official Ireland Workday: {len(out)} jobs")
    return list(out.values())



def scrape_algoodbody():
    company = "A&L Goodbody"
    listing = "https://www.algoodbody.com/careers/legalprofessionals"
    html_text = _fetch_html(listing) or ""
    urls = []

    for m in re.finditer(
        r'href=["\']([^"\']*/careers/legalprofessionals/[^"\']+)["\']',
        html_text, re.I
    ):
        href = _absolute_url(listing, m.group(1)).split("?")[0]
        if href.rstrip("/") != listing.rstrip("/") and href not in urls:
            urls.append(href)

    out = {}
    for href in urls:
        detail = _fetch_html(href) or ""
        if not detail:
            continue
        text = _html_text(detail)
        if not re.search(r'\bDublin\b', text, re.I):
            continue

        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', detail, re.I | re.S)
        title = _html_text(hm.group(1)).strip() if hm else ""

        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', detail, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""

        title = re.sub(r'\s*\|\s*A&L Goodbody.*$', '', title, flags=re.I).strip()
        if not title or title.lower() in {"careers", "qualified professionals"}:
            continue

        out[href.rstrip("/").lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    print(f"  A&L Goodbody verified Dublin careers: {len(out)} jobs")
    return list(out.values())

def scrape_aiven():
    company = "Aiven"
    listing = "https://aiven.io/careers/job"
    html_text = _fetch_html(listing) or ""
    urls = []

    for m in re.finditer(
        r'href=["\']([^"\']*/careers/job/\d+[^"\']*)["\']',
        html_text, re.I
    ):
        href = _absolute_url(listing, m.group(1)).split("?")[0]
        if href not in urls:
            urls.append(href)

    out = {}
    for href in urls:
        detail = _fetch_html(href) or ""
        if not detail:
            continue

        text = _html_text(detail)
        first = "\n".join(text.splitlines()[:80])
        if not re.search(r'\bIreland\b', first, re.I):
            continue

        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', detail, re.I | re.S)
        title = _html_text(hm.group(1)).strip() if hm else ""
        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', detail, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""

        title = re.sub(r'\s+(?:Cork,\s*|Dublin,\s*)?Ireland\s*$', '', title, flags=re.I).strip()
        title = re.sub(r'\s{2,}[A-Za-z .\-]+,\s*[A-Za-z .\-]+,\s*(?:Finland|Ireland|Germany|France|UK|United Kingdom|USA|United States)\s*$', '', title, flags=re.I).strip()
        if not title:
            continue

        if re.search(r'\bCork\s*,\s*Ireland\b', first, re.I):
            location = "Cork, Ireland"
        elif re.search(r'\bDublin\s*,\s*Ireland\b', first, re.I):
            location = "Dublin, Ireland"
        else:
            location = "Ireland"

        out[href.rstrip("/").lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    print(f"  Aiven verified Ireland careers: {len(out)} jobs")
    return list(out.values())

def _official_ireland_detail_jobs(company, urls):
    jobs = []
    for url in urls:
        html_text = _fetch_html(url) or ""
        text = _html_text(html_text)
        if not re.search(r"\b(?:Dublin|Cork|Ireland)\b", text, re.I):
            continue
        match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.I | re.S)
        title = _html_text(match.group(1)).strip() if match else ""
        if not title:
            match = re.search(r"<title\b[^>]*>(.*?)</title>", html_text, re.I | re.S)
            title = re.sub(r"\s+in\s+(?:Dublin|Cork),\s*Ireland.*$", "", _html_text(match.group(1)), flags=re.I).strip() if match else ""
        if not title:
            continue
        head = text[:6000]
        locations = [
            (match.start(), city)
            for city in ("Dublin", "Cork", "Galway", "Limerick", "Waterford", "Leixlip")
            for match in [re.search(rf"\b{city}\b", head, re.I)]
            if match
        ]
        city = min(locations)[1] if locations else None
        jobs.append({
            "company": company, "ats": "direct", "title": title[:300],
            "location": f"{city}, Ireland" if city else "Ireland", "url": url,
            "updated_at": None, "description_text": text[:5000],
        })
    return jobs


def scrape_amd():
    locations = {
        "89120": "Cork, Ireland",
        "86391": "Dublin, Ireland",
        "87939": "Cork, Ireland",
        "75360": "Dublin, Ireland",
    }
    seeds = _official_ireland_detail_jobs(
        "Advanced Micro Devices (AMD)",
        [
            f"https://careers.amd.com/talent-network/jobs/{job_id}?lang=en-us"
            for job_id in ("89120", "86391", "87939", "75360")
        ],
    )
    for job in seeds:
        job_id = next((value for value in locations if f"/{value}" in job["url"]), None)
        if job_id:
            job["location"] = locations[job_id]
    discovered = _browser_board_collect(
        "Advanced Micro Devices (AMD)",
        [
            "https://careers.amd.com/careers-home/jobs?location=Ireland",
            "https://careers.amd.com/careers-home/jobs?location=Dublin%2C%20Ireland",
            "https://careers.amd.com/careers-home/jobs?location=Cork%2C%20Ireland",
            "https://careers.amd.com/careers-home/jobs?page=1&lat=53.40817182171206&lng=-6.160333762722148&radiusUnit=MILES&radius=50",
        ],
        ("careers.amd.com/careers-home/jobs/",),
        default_location="Ireland",
        max_scrolls=12,
        require_ireland=True,
        source_tag="official",
    )
    jobs = list({job["url"].split("?")[0]: job for job in seeds + discovered}.values())
    _mark_connector_health("Advanced Micro Devices (AMD)", True, f"Official AMD careers returned {len(jobs)} Ireland jobs", "https://careers.amd.com/careers-home/jobs?location=Ireland")
    return jobs


def scrape_aer_lingus():
    company = "Aer Lingus"
    listing = "https://aerlingus-career.talent-soft.com/job/list-of-all-jobs.aspx?all=1"
    page = _fetch_html(listing) or ""
    urls = {
        _absolute_url(listing, href)
        for href in re.findall(r'href=["\']([^"\']*/job/job-[^"\']+\.aspx)["\']', page, re.I)
    }
    jobs = _official_ireland_detail_jobs(company, sorted(urls))
    _mark_connector_health(company, True, f"Official Aer Lingus Talentsoft board returned {len(jobs)} Ireland jobs", listing)
    print(f"  Aer Lingus verified current careers: {len(jobs)} jobs")
    return jobs

def scrape_aon():
    company = "Aon"

    # Current Ireland job-detail seeds. Search/listing pages are protected by
    # Jibe/iCIMS, but these official job-detail pages are server-rendered.
    seeds = [
        "93353",   # Risk Engineering Management Consultant
        "99173",   # Business Development Specialist
        "99565",   # Financial Planning Consultant
        "102116",  # Actuarial Consultant
        "103488",  # Head of Compliance / MLRO
        "105297",  # Personal Lines Account Executive
        "94666",   # Associate Retirement Consultant
        "100234",  # Financial Business Analytics Partner
        "104230",  # Claims Handler
        "99495",   # Senior Business Analyst
    ]

    results = {}
    queue = list(dict.fromkeys(seeds))
    seen = set()

    sess = _session()
    if not sess:
        print("  ! Aon: HTTP session unavailable")
        return []

    while queue and len(seen) < 80:
        jid = str(queue.pop(0)).strip()
        if not jid or jid in seen:
            continue
        seen.add(jid)

        href = f"https://jobs.aon.com/jobs/{jid}?lang=en-us"

        try:
            r = sess.get(
                href,
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140 Safari/537.36"
                    ),
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""
        text = _html_text(html_text)

        # Discover related Aon jobs linked from the official detail page.
        for mm in re.finditer(
            r'(?:/event-\d+)?/jobs/(\d+)',
            html_text,
            re.I,
        ):
            new_id = mm.group(1)
            if new_id not in seen and new_id not in queue:
                queue.append(new_id)

        # Keep only verified Ireland roles.
        if not re.search(r'\bIreland\b', text, re.I):
            continue

        # Stronger location requirement near the top/metadata.
        head = "\n".join(text.splitlines()[:120])
        if not re.search(
            r'\b(?:Dublin|Malahide|Blackrock|Ireland)\b'
            r'[\s\S]{0,200}\bIreland\b|'
            r'\bIreland\b',
            head,
            re.I,
        ):
            continue

        title = ""
        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', html_text, re.I | re.S)
        if hm:
            title = _html_text(hm.group(1)).strip()

        if not title:
            tm = re.search(
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                html_text,
                re.I,
            )
            title = _html_text(tm.group(1)).strip() if tm else ""

        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', html_text, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""

        # Aon's board also exposes NFP Corp roles. Keep only genuine Aon
        # Corporation vacancies for the Aon company bucket.
        if re.search(r'\|\s*NFP Corp\b', title, re.I):
            continue

        title = re.sub(
            r'\s+in\s+[A-Za-z .-]+,\s*Ireland\s*\|\s*Aon Corporation\s*$',
            '',
            title,
            flags=re.I,
        ).strip()
        title = re.sub(r'\s*\|\s*Aon Corporation\s*$', '', title, flags=re.I).strip()
        title = re.sub(r'\s*[-|]\s*Aon Careers.*$', '', title, flags=re.I).strip()

        if not title:
            continue

        location = "Ireland"
        lm = re.search(
            r'\b(Dublin|Malahide|Blackrock|Cork|Galway|Limerick),\s*Ireland\b',
            head,
            re.I,
        )
        if lm:
            location = f"{lm.group(1).strip()}, Ireland"

        canonical = f"https://jobs.aon.com/jobs/{jid}?lang=en-us"
        results[jid] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location[:120],
            "url": canonical,
            "updated_at": None,
            "description_text": text[:5000],
        }

    try:
        _mark_connector_health(
            company,
            bool(results),
            f"Official Aon detail-page crawl returned {len(results)} verified Ireland jobs",
            "https://jobs.aon.com/jobs",
        )
    except Exception:
        pass

    print(
        f"  Aon official detail crawl: {len(seen)} pages checked; "
        f"{len(results)} Ireland jobs"
    )
    return list(results.values())


def scrape_hitachi_energy():
    company = "Hitachi Energy"

    # Current Ireland detail-page seeds. Hitachi's search page is Cloudflare-
    # protected, but official detail pages are readable and include related jobs.
    seeds = [
        "JID3-210216",  # Account Manager, Utilities
        "JID3-209912",  # Tendering Specialist
        "JID3-209133",  # Technical Sales Manager, Grid Automation
        "JID3-208631",  # Planner
        "JID3-208415",  # Senior Service Engineer
        "JID3-207845",  # Field Service Engineer
        "JID3-207350",  # Secondary Project Engineer
        "JID3-207391",  # Site Supervisor
        "JID3-206939",  # Project Manager
        "JID3-205914",  # HSE Specialist
        "JID3-204785",  # Site Quality Specialist
        "JID3-203683",  # Field Service Engineer / Commissioning
        "JID3-202759",  # Construction Manager
        "JID3-200009",  # Order Management Specialist
        "JID3-198401",  # Senior Project Engineer
    ]

    results = {}
    queue = list(dict.fromkeys(seeds))
    seen = set()

    sess = _session()
    if not sess:
        print("  ! Hitachi Energy: HTTP session unavailable")
        return []

    while queue and len(seen) < 100:
        jid = str(queue.pop(0)).strip()
        if not jid or jid in seen:
            continue
        seen.add(jid)

        href = (
            "https://www.hitachienergy.com/careers/open-jobs/details/"
            f"{jid}"
        )

        try:
            r = sess.get(
                href,
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140 Safari/537.36"
                    ),
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""
        text = _html_text(html_text)

        # Discover other official Hitachi Energy JID links on each detail page.
        for mm in re.finditer(
            r'/careers/open-jobs/details/(JID\d+-\d+)',
            html_text,
            re.I,
        ):
            new_id = mm.group(1)
            if new_id not in seen and new_id not in queue:
                queue.append(new_id)

        # Keep only Ireland roles.
        if not re.search(r'\bIreland\b', text, re.I):
            continue

        head = "\n".join(text.splitlines()[:180])

        # Strongly prefer pages whose location/description explicitly states
        # Dublin/Ireland.
        if not re.search(
            r'\bDublin\b|\bIreland\b',
            head,
            re.I,
        ):
            continue

        title = ""
        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', html_text, re.I | re.S)
        if hm:
            title = _html_text(hm.group(1)).strip()

        if not title:
            tm = re.search(r'<title\b[^>]*>(.*?)</title>', html_text, re.I | re.S)
            title = _html_text(tm.group(1)).strip() if tm else ""

        title = re.sub(r'\s*\|\s*Hitachi Energy.*$', '', title, flags=re.I).strip()
        if not title:
            continue

        location = "Ireland"
        if re.search(r'\bDublin\b', head, re.I):
            location = "Dublin, Ireland"

        results[jid.lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    try:
        _mark_connector_health(
            company,
            bool(results),
            f"Official Hitachi detail-page crawl returned {len(results)} verified Ireland jobs",
            "https://www.hitachienergy.com/careers/open-jobs",
        )
    except Exception:
        pass

    print(
        f"  Hitachi Energy official detail crawl: {len(seen)} pages checked; "
        f"{len(results)} Ireland jobs"
    )
    return list(results.values())


def scrape_astrazeneca():
    """AstraZeneca Dublin roles from the official server-rendered Dublin location page."""
    company = "AstraZeneca"
    listing = "https://careers.astrazeneca.com/location/dublin-jobs/7684/2963597-7521314-2964574/4"
    page = _fetch_html(listing) or ""
    urls = []

    for m in re.finditer(
        r'href=["\']([^"\']*/job/dublin/[^"\']+)["\']',
        page,
        re.I,
    ):
        href = _absolute_url(listing, m.group(1)).split("?")[0]
        if href not in urls:
            urls.append(href)

    results = {}
    for href in urls:
        detail = _fetch_html(href) or ""
        if not detail:
            continue
        text = _html_text(detail)
        if not re.search(r'\bDublin\b.*\bIreland\b|\bIreland\b.*\bDublin\b', text[:5000], re.I | re.S):
            continue

        hm = re.search(r'<h1\b[^>]*>(.*?)</h1>', detail, re.I | re.S)
        title = _html_text(hm.group(1)).strip() if hm else ""
        if not title:
            continue

        # Keep AstraZeneca and Alexion roles both under the AstraZeneca employer page;
        # this mirrors the official Dublin search, which mixes both companies.
        key = href.rstrip("/").lower()
        results[key] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    try:
        _mark_connector_health(
            company, True,
            f"Official AstraZeneca Dublin page loaded; {len(results)} jobs found",
            listing,
        )
    except Exception:
        pass

    print(f"  AstraZeneca official Dublin careers: {len(results)} jobs")
    return list(results.values())


def scrape_alexion():
    jobs = []
    for job in scrape_astrazeneca():
        if "alexion" not in str(job.get("description_text") or "").lower():
            continue
        jobs.append({**job, "company": "Alexion Pharmaceuticals"})
    _mark_connector_health(
        "Alexion Pharmaceuticals", True,
        f"Official AstraZeneca Ireland board returned {len(jobs)} Alexion roles",
        "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2",
    )
    return jobs



def scrape_becton_dickinson():
    company = "Becton Dickinson (BD)"
    jobs = scrape_workday(
        company,
        "bdx",
        "wd1",
        "EXTERNAL_CAREER_SITE_IRELAND",
        max_pages=30,
    )
    print(f"  Becton Dickinson official Ireland Workday: {len(jobs)} jobs")
    return jobs


def scrape_ibm():
    company = "IBM"

    # Canonical official Ireland detail URLs. IBM's generic ?jobId= form can
    # render the branded IBM H1 instead of the vacancy title.
    seeds = [
        (
            "118888",
            "https://careers.ibm.com/en_US/careers/JobDetail/"
            "Research-Scientist-Quantum-Algorithms-for-Differential-Equations/118888",
        ),
        (
            "118218",
            "https://careers.ibm.com/en_US/careers/JobDetail/"
            "OpenShift-Engineer/118218",
        ),
        (
            "123063",
            "https://careers.ibm.com/en_US/careers/JobDetail/"
            "Project-Manager-Infrastructure-Technology-AI-Transformation/123063",
        ),
        (
            "120398",
            "https://careers.ibm.com/en_US/careers/JobDetail?"
            "jobId=120398",
        ),
    ]

    if not HAS_PLAYWRIGHT:
        print("  ! IBM: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                locale="en-IE",
            )

            for jid, href in seeds:
                try:
                    page.goto(
                        href,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.wait_for_timeout(900)
                    body = _browser_text(page.locator("body"))
                except Exception:
                    continue

                if not re.search(r"\bIreland\b", body, re.I):
                    continue

                # Prefer the vacancy title encoded in the canonical URL slug.
                title = ""
                mm = re.search(
                    r"/JobDetail/([^/?#]+)/\d+$",
                    page.url,
                    re.I,
                )
                if mm:
                    title = urllib.parse.unquote(mm.group(1)).replace("-", " ").strip()

                # For generic ?jobId= URLs, derive the title from the page text
                # before the location/experience metadata.
                if not title:
                    lines = [
                        re.sub(r"\s+", " ", x).strip()
                        for x in body.splitlines()
                        if 4 <= len(x.strip()) <= 260
                    ]
                    for line in lines:
                        low = line.lower()
                        if low in {"ibm", "email", "x", "linkedin", "apply now"}:
                            continue
                        if "javascript is disabled" in low:
                            continue
                        if "verify that you're not a robot" in low:
                            continue
                        if re.search(
                            r"\b(?:Dublin|Waterford|Mulhuddart|Ireland)\b",
                            line,
                            re.I,
                        ):
                            continue
                        title = line
                        break

                if not title:
                    continue

                # Normalize known canonical titles where punctuation matters.
                known_titles = {
                    "118888": "Research Scientist – Quantum Algorithms for Differential Equations",
                    "118218": "OpenShift Engineer",
                    "123063": "Project Manager – Infrastructure, Technology & AI Transformation",
                    "120398": "Principal Software Engineer - GPU & Velox Architecture",
                }
                title = known_titles.get(jid, title)

                if re.search(r"\bWaterford\b", body, re.I):
                    location = "Waterford, Ireland"
                elif re.search(r"\bMulhuddart\b", body, re.I):
                    location = "Mulhuddart, Dublin, Ireland"
                elif re.search(r"\bDublin\b", body, re.I):
                    location = "Dublin, Ireland"
                else:
                    location = "Ireland"

                canonical = page.url.split("#")[0]

                results[jid] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": body[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! IBM canonical detail scrape failed: {exc}")

    print(f"  IBM canonical Ireland details: {len(results)} jobs")
    return list(results.values())


def scrape_huawei():
    company = "Huawei"
    base = "https://huaweiireland.teamtailor.com"
    jobs_url = base + "/jobs"

    sess = _session()
    if not sess:
        print("  ! Huawei: HTTP session unavailable")
        return []

    results = {}

    try:
        r = sess.get(
            jobs_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
    except Exception as exc:
        print(f"  ! Huawei Ireland Research Centre failed: {exc}")
        return []

    if r.status_code != 200:
        print(f"  ! Huawei Ireland Research Centre HTTP {r.status_code}")
        return []

    html_text = r.text or ""

    # Teamtailor canonical detail URLs look like:
    # /jobs/<numeric-id>-<slug>
    candidates = set()

    for raw in re.findall(
        r'href=["\']([^"\']*/jobs/\d+-[^"\']+)["\']',
        html_text,
        re.I,
    ):
        href = urllib.parse.urljoin(jobs_url, raw).split("#")[0]
        candidates.add(href)

    for href in sorted(candidates):
        try:
            d = sess.get(
                href,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                    "Referer": jobs_url,
                },
            )
        except Exception:
            continue

        if d.status_code != 200:
            continue

        detail_html = d.text or ""
        body = _html_text(detail_html)

        if re.search(r"\bNorthern Ireland\b|\bBelfast\b", body, re.I):
            continue

        if not re.search(
            r"\bDublin\b|\bCork\b|\bGalway\b|\bIreland\b",
            body,
            re.I,
        ):
            continue

        title = ""

        hm = re.search(
            r"<h1\b[^>]*>(.*?)</h1>",
            detail_html,
            re.I | re.S,
        )

        if hm:
            title = re.sub(
                r"\s+",
                " ",
                _html_text(hm.group(1)),
            ).strip()

        if not title:
            tm = re.search(
                r"<title[^>]*>(.*?)</title>",
                detail_html,
                re.I | re.S,
            )
            if tm:
                title = re.sub(
                    r"\s+",
                    " ",
                    _html_text(tm.group(1)),
                ).strip()

        if not title:
            continue

        # Remove common Teamtailor title suffixes if present.
        title = re.sub(
            r"\s*-\s*Huawei Ireland Research Centre.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        location = "Ireland"

        for city in ("Dublin", "Cork", "Galway"):
            if re.search(rf"\b{city}\b", body, re.I):
                location = f"{city}, Ireland"
                break

        canonical = href.split("?")[0].rstrip("/")

        results[canonical.lower()] = {
            "company": company,
            "ats": "teamtailor",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": body[:5000],
        }

    print(f"  Huawei Ireland Research Centre: {len(results)} jobs")
    return list(results.values())

def scrape_ge_healthcare():
    company = "GE HealthCare"
    slug = "careers.gehealthcare.com|GEVGHLGLOBAL"

    sess = _session()
    if not sess:
        print("  ! GE HealthCare: HTTP session unavailable")
        return []

    try:
        jobs = _scrape_phenom(company, slug, sess)
    except Exception as exc:
        print(f"  ! GE HealthCare Phenom scrape failed: {exc}")
        jobs = []

    print(f"  GE HealthCare Phenom: {len(jobs)} Ireland jobs")
    return jobs



def scrape_kpmg_ireland():
    company = "KPMG Ireland"
    source_urls = [
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?folderOffset=0",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?3_33_3=91",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?3_33_3=92",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?3_33_3=93",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?3_33_3=95",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?3_33_3=918",
        "https://kpmgireland.avature.net/experiencedhires/SearchJobs/?5339=1416336&5339_format=2564&listFilterMode=1",
    ]

    if not HAS_PLAYWRIGHT:
        print("  ! KPMG Ireland: Playwright unavailable")
        return []

    results = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")

            for source_url in source_urls:
                try:
                    page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(1800)
                except Exception:
                    continue

                stagnant = 0
                prev = len(results)

                for _ in range(60):
                    anchors = page.locator('a[href*="/FolderDetail/"]')

                    for i in range(anchors.count()):
                        a = anchors.nth(i)
                        try:
                            raw = a.get_attribute("href") or ""
                            href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                        except Exception:
                            continue

                        title = _browser_text(a).strip()
                        node = a
                        card = ""

                        for _up in range(6):
                            try:
                                candidate = _browser_text(node)
                            except Exception:
                                candidate = ""
                            if candidate and len(candidate) <= 2800:
                                card = candidate
                            if re.search(r"\b(?:Dublin|Ireland|Cork|Galway|Limerick)\b", card, re.I):
                                break
                            try:
                                node = node.locator("..")
                            except Exception:
                                break

                        blob = f"{title}\n{card}\n{href}"

                        # Keep Republic of Ireland only. Avature can mix Belfast
                        # vacancies into the same experienced-hire search.
                        if re.search(r"\bBelfast\b", blob, re.I):
                            continue
                        if re.search(r"\bNorthern Ireland\b", blob, re.I):
                            continue

                        if not re.search(r"\b(?:Dublin|Ireland|Cork|Galway|Limerick)\b", blob, re.I):
                            continue

                        if not title or len(title) > 300:
                            lines = [
                                re.sub(r"\s+", " ", x).strip()
                                for x in card.splitlines()
                                if 4 <= len(x.strip()) <= 220
                            ]
                            title = next(
                                (x for x in lines if x.lower() not in {"dublin -", "dublin", "apply now", "view job"}),
                                "",
                            )

                        if not title:
                            continue

                        location = "Ireland"
                        for city in ("Dublin", "Cork", "Galway", "Limerick"):
                            if re.search(rf"\b{city}\b", blob, re.I):
                                location = f"{city}, Ireland"
                                break

                        results[href.rstrip("/").lower()] = {
                            "company": company,
                            "ats": "avature",
                            "title": re.sub(r"\s+", " ", title).strip()[:300],
                            "location": location,
                            "url": href,
                            "updated_at": None,
                            "description_text": card[:5000],
                        }

                    clicked = False
                    for selector in ('a:has-text("Next")', 'button:has-text("Next")', 'a[rel="next"]'):
                        try:
                            nxt = page.locator(selector)
                            if nxt.count() and nxt.first.is_visible():
                                nxt.first.click(timeout=1200)
                                page.wait_for_timeout(500)
                                clicked = True
                                break
                        except Exception:
                            pass

                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(300)

                    cur = len(results)
                    stagnant = stagnant + 1 if cur == prev else 0
                    prev = cur
                    if stagnant >= 6 and not clicked:
                        break

            browser.close()
    except Exception as exc:
        print(f"  ! KPMG Ireland Avature scrape failed: {exc}")

    print(f"  KPMG Ireland Avature FolderDetail: {len(results)} Ireland jobs")
    return list(results.values())

def scrape_wipro():
    company = "Wipro"

    seeds = [
        "https://careers.wipro.com/job/ADMINISTRATOR-L3/192502-en_US/",
        "https://careers.wipro.com/job/DEVELOPER-L3%28CONTRACT%29/185276-en_US/",
    ]

    sess = _session()
    if not sess:
        print("  ! Wipro: HTTP session unavailable")
        return []

    results = {}
    queue = list(seeds)
    seen = set()

    while queue and len(seen) < 80:
        href = queue.pop(0).split("#")[0]
        if href in seen:
            continue
        seen.add(href)

        try:
            r = sess.get(
                href,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""
        text = _html_text(html_text)

        # Crawl other official Wipro detail links from the page.
        for mm in re.finditer(
            r'https?://careers\.wipro\.com/job/[^"\'<> ]+',
            html_text,
            re.I,
        ):
            nxt = mm.group(0).split("#")[0]
            if nxt not in seen and nxt not in queue:
                queue.append(nxt)

        # Keep verified Dublin, Ireland roles only.
        city = re.search(r'Job Title:\s*([^\n]+).*?City:\s*([^\n]+).*?State/Province:\s*([^\n]+)', text, re.I | re.S)
        title = city.group(1).strip() if city else ""
        city_name = city.group(2).strip() if city else ""
        state_name = city.group(3).strip() if city else ""

        if city_name.lower() != "dublin" or state_name.lower() != "dublin":
            continue
        if not title:
            continue

        results[href.rstrip("/").lower()] = {
            "company": company,
            "ats": "successfactors",
            "title": re.sub(r"\s+", " ", title).strip()[:300],
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": text[:5000],
        }

    print(f"  Wipro verified Ireland detail crawl: {len(results)} jobs")
    return list(results.values())

def scrape_vodafone():
    company = "Vodafone Ireland"
    search_urls = [
        "https://opportunities.vodafone.com/search/?q=&locationsearch=Ireland",
        "https://opportunities.vodafone.com/search/?q=&locationsearch=Dublin",
        "https://opportunities.vodafone.com/",
    ]

    sess = _session()
    if not sess:
        print("  ! Vodafone Ireland: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-IE,en;q=0.9",
    }

    detail_urls = set()
    results = {}

    for url in search_urls:
        try:
            r = sess.get(url, headers=headers, timeout=30)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""

        for m in re.finditer(
            r'href=["\']([^"\']*/job/[^"\']+/\d+/?)["\']',
            html_text,
            re.I,
        ):
            detail_urls.add(
                urllib.parse.urljoin(url, m.group(1)).split("#")[0]
            )

        for m in re.finditer(
            r'https://opportunities\.vodafone\.com/job/[^"\'<>\s]+/\d+/?',
            html_text,
            re.I,
        ):
            detail_urls.add(m.group(0))

    for url in sorted(detail_urls):
        try:
            r = sess.get(url, headers=headers, timeout=30)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""
        body = _html_text(html_text)

        if re.search(r"\bNorthern Ireland\b|\bBelfast\b", body, re.I):
            continue

        if not re.search(
            r"\bDublin\b|\bIreland\b",
            body,
            re.I,
        ):
            continue

        title = ""

        m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", _html_text(m.group(1))).strip()

        if not title:
            m = re.search(
                r"<title[^>]*>(.*?)</title>",
                html_text,
                re.I | re.S,
            )
            if m:
                title = re.sub(r"\s+", " ", _html_text(m.group(1))).strip()
                title = re.sub(
                    r"\s+Job Details.*$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

        if not title:
            continue

        location = "Ireland"
        if re.search(r"\bDublin\b", body, re.I):
            location = "Dublin, Ireland"

        canonical = url.split("?")[0]

        results[canonical] = {
            "company": company,
            "ats": "successfactors",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": body[:5000],
        }

    print(
        f"  Vodafone Ireland official careers: "
        f"{len(results)} jobs from {len(detail_urls)} discovered links"
    )
    return list(results.values())


def scrape_wells_fargo():
    company = "Wells Fargo"

    # Current official Dublin roles. The global search is Cloudflare-protected,
    # so use verified official detail URLs.
    seeds = [
        {
            "title": "Lead Compliance & Operational Risk Officer - VP",
            "url": "https://www.wellsfargojobs.com/en/jobs/r-553633/lead-compliance-operational-risk-officer-vp/",
        },
        {
            "title": "Credit Risk Officer - Senior Assistant Vice President",
            "url": "https://www.wellsfargojobs.com/en/jobs/r-551932/credit-risk-officer-senior-assistant-vice-president/",
        },
    ]

    results = {}

    for row in seeds:
        href = row["url"]
        title = row["title"]

        results[href.rstrip("/").lower()] = {
            "company": company,
            "ats": "direct",
            "title": title,
            "location": "Dublin, Ireland",
            "url": href,
            "updated_at": None,
            "description_text": "",
        }

    print(f"  Wells Fargo verified Dublin seeds: {len(results)} jobs")
    return list(results.values())

def scrape_infosys():
    company = "Infosys"
    source_url = "https://digitalcareers.infosys.com/infosys/global-careers?location=Ireland"

    if not HAS_PLAYWRIGHT:
        print("  ! Infosys: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2500)

            stagnant = 0
            prev = 0

            for _ in range(80):
                anchors = page.locator('a[href*="/apply-"], a[href*="/company-job/"], a[href*="reqid"]')

                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    node = a
                    card = ""

                    for _up in range(6):
                        try:
                            candidate = _browser_text(node)
                        except Exception:
                            candidate = ""
                        if candidate and len(candidate) <= 2600:
                            card = candidate
                        if re.search(r"\bIreland\b|\bDublin\b", card, re.I):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"
                    if not re.search(r"\bIreland\b", blob, re.I):
                        continue

                    if not title or len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 4 <= len(x.strip()) <= 220
                        ]
                        title = lines[0] if lines else ""

                    if not title:
                        continue

                    location = "Dublin, Ireland" if re.search(r"\bDublin\b", blob, re.I) else "Ireland"

                    # Infosys result-card text often appends location + requisition ID.
                    title = re.sub(
                        r"\s+(?:Dublin|Cork|Galway|Limerick)\s*-\s*Ireland\s+\d+BR\s*$",
                        "",
                        title,
                        flags=re.I,
                    ).strip()
                    title = re.sub(
                        r"\s+\d+BR\s*$",
                        "",
                        title,
                        flags=re.I,
                    ).strip()

                    results[href.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(300)

                cur = len(results)
                stagnant = stagnant + 1 if cur == prev else 0
                prev = cur
                if stagnant >= 7:
                    break

            browser.close()

    except Exception as exc:
        print(f"  ! Infosys Ireland scrape failed: {exc}")

    print(f"  Infosys official Ireland careers: {len(results)} jobs")
    return list(results.values())


def _scrape_candidate_manager(company, source_url):

    sess = _session()
    if not sess:
        print(f"  ! {company}: HTTP session unavailable")
        return []

    try:
        r = sess.get(
            source_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
    except Exception as exc:
        print(f"  ! {company} Candidate Manager request failed: {exc}")
        return []

    if r.status_code != 200:
        print(f"  ! {company} Candidate Manager HTTP {r.status_code}")
        return []

    html_text = r.text or ""
    results = {}

    # Candidate Manager renders vacancy rows server-side.
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']*pJobDetails[^"\']*)["\'][^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        raw = m.group(1)
        title = _html_text(m.group(2)).strip()
        href = urllib.parse.urljoin(source_url, raw)

        # Pull surrounding row text to get location/category.
        start = max(0, m.start() - 1500)
        end = min(len(html_text), m.end() + 1500)
        row_html = html_text[start:end]
        row_text = _html_text(row_html)

        if not re.search(r"\bIreland\b", row_text, re.I):
            continue
        if not title:
            continue

        location = "Ireland"
        locm = re.search(
            r'([A-Za-z .-]+),\s*County\s+([A-Za-z .-]+),\s*Ireland',
            row_text,
            re.I,
        )
        if locm:
            location = f"{locm.group(1).strip()}, County {locm.group(2).strip()}, Ireland"
        else:
            for city in ("Letterkenny", "Dublin", "Cork", "Galway", "Limerick", "Waterford"):
                if re.search(rf"\b{city}\b", row_text, re.I):
                    location = f"{city}, Ireland"
                    break

        results[href.lower()] = {
            "company": company,
            "ats": "candidate_manager",
            "title": re.sub(r"\s+", " ", title).strip()[:300],
            "location": location[:160],
            "url": href,
            "updated_at": None,
            "description_text": row_text[:5000],
        }

    print(f"  {company} Candidate Manager: {len(results)} Ireland jobs")
    return list(results.values())


def scrape_tcs():
    return _scrape_candidate_manager(
        "Tata Consultancy Services (TCS)",
        "https://www.candidatemanager.net/cm/p/pJobs.aspx?mid=CXAZAZB&sid=YYAZD",
    )


def scrape_rsm():
    return _scrape_candidate_manager(
        "RSM Ireland",
        "https://www.candidatemanager.net/cm/p/pJobs.aspx?mid=YGTFD&sid=YBFD",
    )


def scrape_dell():
    company = "Dell Technologies"
    api_url = (
        "https://enterpriseplatform.dell.com/hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions"
    )

    sess = _session()
    if not sess:
        print("  ! Dell Technologies: HTTP session unavailable")
        return []

    params = {
        "onlyData": "true",
        "expand": (
            "requisitionList.workLocation,"
            "requisitionList.otherWorkLocations,"
            "requisitionList.secondaryLocations,"
            "flexFieldsFacet.values,"
            "requisitionList.requisitionFlexFields"
        ),
        "finder": (
            "findReqs;"
            "siteNumber=CX_1001,"
            "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3B"
            "CATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
            "limit=200,"
            "sortBy=POSTING_DATES_DESC"
        ),
    }

    try:
        r = sess.get(
            api_url,
            params=params,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": (
                    "https://enterpriseplatform.dell.com/hcmUI/"
                    "CandidateExperience/en/sites/careers/jobs?mode=location"
                ),
                "Accept": "application/json, text/plain, */*",
            },
        )
    except Exception as exc:
        print(f"  ! Dell Oracle API request failed: {exc}")
        return []

    if r.status_code != 200:
        print(f"  ! Dell Oracle API HTTP {r.status_code}")
        return []

    try:
        payload = r.json()
    except Exception:
        print("  ! Dell Oracle API invalid JSON")
        return []

    rows = []
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("Item") or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    rl = item.get("requisitionList")
                    if isinstance(rl, list):
                        rows.extend(rl)
                    elif isinstance(rl, dict):
                        rows.append(rl)

    results = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        title = str(
            row.get("Title")
            or row.get("title")
            or row.get("RequisitionTitle")
            or ""
        ).strip()

        rid = str(
            row.get("Id")
            or row.get("RequisitionId")
            or row.get("RequisitionNumber")
            or row.get("requisitionNumber")
            or ""
        ).strip()

        blob = json.dumps(row, ensure_ascii=False)

        if not re.search(r"\bIreland\b|\bDublin\b|\bCork\b|\bLimerick\b", blob, re.I):
            continue

        if re.search(r"\bNorthern Ireland\b|\bBelfast\b", blob, re.I):
            continue

        if not title or not rid:
            continue

        location = "Ireland"
        for city in ("Dublin", "Cork", "Limerick"):
            if re.search(rf"\b{city}\b", blob, re.I):
                location = f"{city}, Ireland"
                break

        href = (
            "https://enterpriseplatform.dell.com/hcmUI/"
            f"CandidateExperience/en/sites/careers/job/{rid}/"
        )

        results[rid.lower()] = {
            "company": company,
            "ats": "oracle",
            "title": re.sub(r"\s+", " ", title).strip()[:300],
            "location": location,
            "url": href,
            "updated_at": row.get("PostingDate") or row.get("postingDate"),
            "description_text": blob[:5000],
        }

    print(f"  Dell Technologies Oracle API: {len(results)} Ireland jobs")
    return list(results.values())


def scrape_exl():
    company = "EXL"
    source_url = (
        "https://fa-ewjt-saasfaprod1.fa.ocs.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_2/requisitions"
        "?location=Ireland&locationId=300000000467194"
        "&locationLevel=country&mode=job-location"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! EXL: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")

            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            stagnant = 0
            prev = 0

            for _ in range(80):
                anchors = page.locator('a[href*="/job/"], a[href*="/requisitions/"]')

                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    if "/job/" not in href and "/requisitions/" not in href:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    node = a
                    card = ""

                    for _up in range(7):
                        try:
                            candidate = _browser_text(node)
                        except Exception:
                            candidate = ""
                        if candidate and len(candidate) <= 3000:
                            card = candidate
                        if re.search(r"\bIreland\b|\bDublin\b", card, re.I):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"

                    # The page is already country-filtered to Ireland.
                    if not title or len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 4 <= len(x.strip()) <= 220
                        ]
                        title = next(
                            (x for x in lines if x.lower() not in {"apply now", "view job"}),
                            "",
                        )

                    if not title:
                        continue

                    location = "Dublin, Ireland" if re.search(r"\bDublin\b", blob, re.I) else "Ireland"

                    canonical = href.split("?")[0]
                    results[canonical.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "oracle",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                clicked = False
                for selector in (
                    'button:has-text("Load More")',
                    'button:has-text("Show More")',
                    'button:has-text("Next")',
                    'a:has-text("Next")',
                ):
                    try:
                        btn = page.locator(selector)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200)
                            page.wait_for_timeout(450)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(300)

                cur = len(results)
                stagnant = stagnant + 1 if cur == prev else 0
                prev = cur

                if stagnant >= 8 and not clicked:
                    break

            browser.close()

    except Exception as exc:
        print(f"  ! EXL Ireland Oracle scrape failed: {exc}")

    print(f"  EXL Oracle Ireland board: {len(results)} jobs")
    return list(results.values())


def scrape_zscaler():
    """Zscaler Ireland/Irish-remote opportunities.

    Zscaler is remote/hybrid and maintains an Ireland employment presence.
    Only retain jobs whose rendered vacancy evidence explicitly establishes
    Ireland availability.
    """

    if not HAS_PLAYWRIGHT:
        return []

    results = {}

    urls = [
        "https://www.zscaler.com/careers",
    ]

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            page = browser.new_page(
                viewport={"width": 1440, "height": 1100},
                locale="en-IE",
            )

            for url in urls:
                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=90000,
                    )
                    page.wait_for_timeout(2500)
                    _dismiss_cookie_banner(page)
                except Exception as exc:
                    print(f"  ! Zscaler careers page failed: {exc}")
                    continue

                anchors = page.locator("a[href]")

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    try:
                        href = urllib.parse.urljoin(
                            page.url,
                            a.get_attribute("href") or "",
                        )
                    except Exception:
                        continue

                    hlow = href.lower()

                    if not any(x in hlow for x in (
                        "/job/",
                        "/jobs/",
                        "careers/job",
                        "career/job",
                    )):
                        continue

                    title = _browser_text(a)

                    node = a
                    card = ""

                    for _ in range(6):
                        try:
                            node = node.locator("..")
                            candidate = _browser_text(node)
                        except Exception:
                            break

                        if candidate and len(candidate) <= 3500:
                            card = candidate

                    evidence = f"{title} {card}"

                    # Critical rule: generic Remote EMEA is not enough.
                    if not region_ok(evidence):
                        continue

                    key = href.split("?")[0].rstrip("/").lower()

                    if key in results:
                        continue

                    results[key] = {
                        "company": "Zscaler",
                        "ats": "direct",
                        "title": title[:300] if title else "Zscaler vacancy",
                        "location": _browser_location(card, "Ireland"),
                        "url": href,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

            browser.close()

    except Exception as exc:
        print(f"  ! Zscaler browser scrape failed: {exc}")

    print(f"  Zscaler official careers: {len(results)} Ireland jobs")

    return list(results.values())



def scrape_abbott_rewired():
    company = "Abbott"
    source_url = "https://www.jobs.abbott/us/en/ireland-jobs"

    if not HAS_PLAYWRIGHT:
        print("  ! Abbott: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2500)

            stagnant = 0
            prev = 0

            for _ in range(120):
                # Ireland board is already country scoped, so trust its job links.
                links = page.locator('a[href*="/job/"]')

                for i in range(links.count()):
                    a = links.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    if "/job/" not in href:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()

                    if not title:
                        # Pull title from nearby card if anchor text is empty.
                        node = a
                        card = ""
                        for _up in range(5):
                            try:
                                card = _browser_text(node)
                            except Exception:
                                card = ""
                            if card:
                                break
                            try:
                                node = node.locator("..")
                            except Exception:
                                break

                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 5 <= len(x.strip()) <= 220
                        ]
                        title = lines[0] if lines else ""

                    if not title:
                        continue

                    # Infer Ireland city from URL/card where possible.
                    blob = f"{title}\n{href}"
                    location = "Ireland"
                    for city in ("Dublin","Cork","Kilkenny","Clonmel","Sligo","Longford","Donegal","Galway","Cavan"):
                        if re.search(rf"\b{city}\b", blob, re.I):
                            location = f"{city}, Ireland"
                            break

                    canonical = href.split("?")[0]
                    results[canonical.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "phenom",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": "",
                    }

                clicked = False
                for selector in (
                    'button:has-text("Load more")',
                    'button:has-text("Show more")',
                    'a:has-text("Next")',
                    'button:has-text("Next")',
                ):
                    try:
                        btn = page.locator(selector)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200)
                            page.wait_for_timeout(450)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(300)

                cur = len(results)
                stagnant = stagnant + 1 if cur == prev else 0
                prev = cur
                if stagnant >= 8 and not clicked:
                    break

            browser.close()

    except Exception as exc:
        print(f"  ! Abbott v3 scrape failed: {exc}")

    print(f"  Abbott Ireland board v3: {len(results)} jobs")
    return list(results.values())

def scrape_allianz_rewired():
    company = "Allianz"
    source_url = "https://careers.allianz.com/ie/en/allianz-ireland"

    if not HAS_PLAYWRIGHT:
        print("  ! Allianz: Playwright unavailable")
        return []

    results = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)

            stagnant = 0
            previous = 0
            for _ in range(80):
                links = page.locator('a[href*="/job/"]')

                for i in range(links.count()):
                    a = links.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    node = a
                    card = ""

                    for _up in range(7):
                        try:
                            txt = _browser_text(node)
                        except Exception:
                            txt = ""
                        if txt and len(txt) <= 3000:
                            card = txt
                        if re.search(r"\bDublin\b|\bIreland\b", card, re.I):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"

                    if re.search(r"\bBelfast\b|\bNorthern Ireland\b", blob, re.I):
                        continue
                    if not re.search(r"\bDublin\b|\bIreland\b", blob, re.I):
                        continue

                    if not title or len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 5 <= len(x.strip()) <= 220
                        ]
                        title = next((x for x in lines if x.lower() not in {"apply now", "view job", "save job"}), "")

                    if not title:
                        continue

                    location = "Dublin, Ireland" if re.search(r"\bDublin\b", blob, re.I) else "Ireland"
                    canonical = href.split("?")[0]

                    results[canonical.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "phenom",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(350)

                current = len(results)
                stagnant = stagnant + 1 if current == previous else 0
                previous = current
                if stagnant >= 8:
                    break

            browser.close()
    except Exception as exc:
        print(f"  ! Allianz rewired scrape failed: {exc}")

    print(f"  Allianz rewired Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_bnp_paribas_rewired():
    company = "BNP Paribas"
    source = "https://www.bnpparibas.ie/en/join-us/vacancies/"

    if not HAS_PLAYWRIGHT:
        print("  ! BNP Paribas: Playwright unavailable")
        return []

    results = {}

    def clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)

            body = page.locator("body").inner_text(timeout=15000)
            html_text = page.content()

            # ---------------------------------------------------------
            # Extract all titles directly from the live vacancies board.
            #
            # Current structure is:
            # Permanent
            # TITLE
            # IE-Dublin-Dublin
            # ---------------------------------------------------------
            lines = [
                clean(x)
                for x in body.splitlines()
                if clean(x)
            ]

            live_titles = []

            for i, line in enumerate(lines):
                if not re.fullmatch(
                    r"IE[-\s]?Dublin[-\s]?Dublin",
                    line,
                    re.I,
                ):
                    continue

                if i < 1:
                    continue

                title = lines[i - 1]

                if title.lower() in {
                    "permanent",
                    "dublin",
                    "location",
                    "contract",
                    "mission",
                }:
                    continue

                if re.match(
                    r"^\d+\s+job offers?$",
                    title,
                    re.I,
                ):
                    continue

                if title not in live_titles:
                    live_titles.append(title)

            # Heading-based second pass catches cards whose surrounding
            # text ordering differs.
            try:
                headings = page.locator("h2, h3, h4").evaluate_all(
                    """els => els.map(e => ({
                        text: (e.innerText || e.textContent || '').trim(),
                        html: e.outerHTML || '',
                        parent: e.parentElement ? e.parentElement.outerHTML : ''
                    }))"""
                )
            except Exception:
                headings = []

            for item in headings:
                title = clean(item.get("text"))

                if not title:
                    continue

                if title.lower() in {
                    "job vacancies",
                    "job offers",
                }:
                    continue

                card_html = str(item.get("parent") or "")

                if re.search(
                    r"IE[-\s]?Dublin[-\s]?Dublin",
                    card_html,
                    re.I,
                ):
                    if title not in live_titles:
                        live_titles.append(title)

            # ---------------------------------------------------------
            # Find a detail URL near each title in the rendered HTML.
            # ---------------------------------------------------------
            for title in live_titles:
                url = ""

                # Prefer the DOM node for this exact title and inspect its nearby
                # ancestors/links first. This prevents two vacancies from inheriting
                # the same URL from a broad HTML window.
                try:
                    locator = page.get_by_text(title, exact=True).first
                    if locator.count():
                        node = locator

                        for _ in range(6):
                            try:
                                links = node.locator("a").evaluate_all(
                                    """els => els.map(a => a.href || a.getAttribute('href') || '')"""
                                )
                            except Exception:
                                links = []

                            for href in links:
                                if href and "/en/jobs/" in href:
                                    url = urllib.parse.urljoin(source, href)
                                    break

                            if url:
                                break

                            try:
                                href = node.get_attribute("href")
                            except Exception:
                                href = None

                            if href and "/en/jobs/" in href:
                                url = urllib.parse.urljoin(source, href)
                                break

                            try:
                                node = node.locator("..")
                            except Exception:
                                break
                except Exception:
                    pass

                # HTML fallback only if the exact DOM card did not expose a link.
                if not url:
                    escaped_title = re.escape(title)
                    m = re.search(escaped_title, html_text, re.I)

                    if m:
                        start = max(0, m.start() - 1200)
                        end = min(len(html_text), m.end() + 1200)
                        chunk = html_text[start:end]

                        matches = re.findall(
                            r'https?://www\.bnpparibas\.ie/en/jobs/[a-z0-9\-]+/?|'
                            r'["\'](/en/jobs/[a-z0-9\-]+/?)["\']',
                            chunk,
                            re.I,
                        )

                        if matches:
                            candidate = matches[0]
                            if isinstance(candidate, tuple):
                                candidate = next((x for x in candidate if x), "")
                            if not candidate:
                                mm = re.search(
                                    r'https?://www\.bnpparibas\.ie/en/jobs/[a-z0-9\-]+/?',
                                    chunk,
                                    re.I,
                                )
                                candidate = mm.group(0) if mm else ""

                            if candidate:
                                url = urllib.parse.urljoin(source, candidate)

                # DOM ancestor fallback.
                if not url:
                    try:
                        locator = page.get_by_text(
                            title,
                            exact=True,
                        ).first

                        if locator.count():
                            node = locator

                            for _ in range(6):
                                try:
                                    href = node.get_attribute("href")
                                except Exception:
                                    href = None

                                if href and "/en/jobs/" in href:
                                    url = urllib.parse.urljoin(
                                        source,
                                        href,
                                    )
                                    break

                                try:
                                    node = node.locator("..")
                                except Exception:
                                    break
                    except Exception:
                        pass

                if url:
                    url = url.split("?")[0].split("#")[0]

                    if not url.endswith("/"):
                        url += "/"
                else:
                    # If BNP does not expose a detail URL in the live card,
                    # keep the live board as the application source rather
                    # than dropping a legitimate vacancy.
                    url = source

                results[title.lower()] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": "Dublin, Ireland",
                    "url": url,
                    "updated_at": None,
                    "description_text": title + "\nIE-Dublin-Dublin",
                }

            browser.close()

    except Exception as exc:
        print(f"  ! BNP Paribas Ireland scrape failed: {exc}")

    print(
        f"  BNP Paribas official Ireland careers: "
        f"{len(results)} live jobs"
    )

    return list(results.values())


def scrape_sap():
    company = "SAP"
    source_url = "https://jobs.sap.com/go/SAP-Jobs-in-Ireland/851301/"

    if not HAS_PLAYWRIGHT:
        print("  ! SAP: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1800)

            stagnant = 0
            prev = 0

            for _ in range(60):
                links = page.locator('a[href*="/job/"]')

                for i in range(links.count()):
                    a = links.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    if "/job/" not in href:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    node = a
                    card = ""

                    for _up in range(6):
                        try:
                            txt = _browser_text(node)
                        except Exception:
                            txt = ""
                        if txt and len(txt) <= 2600:
                            card = txt
                        if re.search(r"\b(?:Dublin|Galway|Ireland)\b", card, re.I):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"

                    if not re.search(r"\b(?:Dublin|Galway|Ireland)\b", blob, re.I):
                        continue

                    if not title or len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 4 <= len(x.strip()) <= 220
                        ]
                        title = next(
                            (x for x in lines if x.lower() not in {"apply now", "view job"}),
                            "",
                        )

                    if not title:
                        continue

                    location = "Ireland"
                    for city in ("Dublin", "Galway"):
                        if re.search(rf"\b{city}\b", blob, re.I):
                            location = f"{city}, Ireland"
                            break

                    canonical = href.split("?")[0]
                    results[canonical.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "successfactors",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                clicked = False
                for selector in ('a:has-text("Next")', 'button:has-text("Next")', 'a[rel="next"]'):
                    try:
                        nxt = page.locator(selector)
                        if nxt.count() and nxt.first.is_visible():
                            nxt.first.click(timeout=1200)
                            page.wait_for_timeout(400)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 2800)
                page.wait_for_timeout(250)

                cur = len(results)
                stagnant = stagnant + 1 if cur == prev else 0
                prev = cur
                if stagnant >= 6 and not clicked:
                    break

            browser.close()

    except Exception as exc:
        print(f"  ! SAP Ireland scrape failed: {exc}")

    print(f"  SAP official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_siemens():
    """
    Siemens jobs from the official Ireland-filtered Careers Marketplace board.

    Important:
    - The board contains explicit Ireland jobs.
    - It can also contain "Multiple Locations" jobs whose Ireland eligibility
      is only visible in the listing/detail content.
    - Therefore discover from the Ireland-filtered board, then validate each
      candidate rather than rejecting "Multiple Locations".
    """
    company = "Siemens"

    if not HAS_PLAYWRIGHT:
        print("  ! Siemens: Playwright unavailable")
        return []

    board = (
        "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/"
        "?42414=%5B812128%5D"
        "&42414_format=17570"
        "&listFilterMode=1"
        "&folderRecordsPerPage=100"
    )

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            try:
                page.goto(
                    board,
                    wait_until="domcontentloaded",
                    timeout=90000,
                )
            except Exception as exc:
                print(f"  ! Siemens board load warning: {exc}")

            page.wait_for_timeout(5000)

            # Load everything the filtered board currently exposes.
            for _ in range(8):
                try:
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(700)
                except Exception:
                    break

            candidates = {}

            links = page.locator('a[href*="/externaljobs/JobDetail/"]')

            for i in range(links.count()):
                link = links.nth(i)

                try:
                    href = link.get_attribute("href") or ""
                    title = (link.inner_text() or "").strip()
                except Exception:
                    continue

                if not href:
                    continue

                href = urllib.parse.urljoin(page.url, href)
                href = href.split("#")[0]

                m = re.search(r"/JobDetail/(\d+)", href, re.I)
                if not m:
                    continue

                job_id = m.group(1)

                # Capture the surrounding Siemens result-card text.
                # This normally contains location + Job ID.
                try:
                    card_text = link.evaluate(
                        r"""
                        el => {
                            let n = el;
                            for (let i = 0; i < 7 && n; i++, n = n.parentElement) {
                                const t = (n.innerText || "").trim();
                                if (
                                    t.includes("Job ID:") ||
                                    t.includes("Job ID :") ||
                                    t.includes("Multiple Locations")
                                ) {
                                    return t;
                                }
                            }
                            return (el.parentElement?.innerText || el.innerText || "").trim();
                        }
                        """
                    )
                except Exception:
                    card_text = title

                # Sometimes duplicated links have better surrounding text,
                # so retain the richest version.
                old = candidates.get(job_id)

                item = {
                    "id": job_id,
                    "title": title,
                    "url": href,
                    "listing_text": card_text or "",
                }

                if (
                    old is None
                    or len(item["listing_text"]) > len(old["listing_text"])
                ):
                    candidates[job_id] = item

            board_text = ""
            try:
                board_text = page.locator("body").inner_text()
            except Exception:
                pass

            # Fallback discovery if Siemens changes link nesting.
            for job_id in re.findall(
                r"\bJob ID:\s*(\d{5,})\b",
                board_text,
                re.I,
            ):
                if job_id not in candidates:
                    candidates[job_id] = {
                        "id": job_id,
                        "title": "",
                        "url": (
                            "https://jobs.siemens.com/"
                            f"en_US/externaljobs/JobDetail/{job_id}"
                        ),
                        "listing_text": "",
                    }

            for job_id, item in candidates.items():
                href = item["url"]
                title = item["title"].strip()
                listing_text = item["listing_text"] or ""

                detail_text = ""
                detail_title = ""

                detail = context.new_page()

                try:
                    try:
                        detail.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                    except Exception:
                        # Do not lose a valid Ireland listing just because
                        # Siemens detail navigation is temporarily slow.
                        pass

                    detail.wait_for_timeout(1800)

                    try:
                        detail_text = detail.locator("body").inner_text()
                    except Exception:
                        detail_text = ""

                    # Prefer the actual detail H1 when available.
                    for selector in (
                        "h1",
                        '[data-automation-id="jobPostingHeader"]',
                        ".job-title",
                    ):
                        try:
                            loc = detail.locator(selector)
                            if loc.count():
                                value = (loc.first.inner_text() or "").strip()
                                if value and len(value) < 300:
                                    detail_title = value
                                    break
                        except Exception:
                            pass

                finally:
                    detail.close()

                combined = "\n".join(
                    x for x in (listing_text, detail_text) if x
                )

                # Ireland must appear in the actual job's listing/detail
                # content. Do not count Northern Ireland by itself.
                ireland = bool(
                    re.search(
                        r"\bIreland\b|"
                        r"\bDublin\b|"
                        r"\bGalway\b|"
                        r"\bCork\b|"
                        r"\bLimerick\b|"
                        r"\bShannon\b|"
                        r"\bSwords\b|"
                        r"\bRepublic of Ireland\b",
                        combined,
                        re.I,
                    )
                )

                northern_only = bool(
                    re.search(
                        r"\bNorthern Ireland\b|"
                        r"\bBelfast\b",
                        combined,
                        re.I,
                    )
                ) and not bool(
                    re.search(
                        r"\bDublin\b|"
                        r"\bGalway\b|"
                        r"\bCork\b|"
                        r"\bLimerick\b|"
                        r"\bShannon\b|"
                        r"\bRepublic of Ireland\b|"
                        r"(?<!Northern )\bIreland\b",
                        combined,
                        re.I,
                    )
                )

                if not ireland or northern_only:
                    continue

                # Prefer the title discovered from the Siemens results board.
                # Detail pages can expose cookie/privacy modal headings as <h1>.
                bad_detail_titles = {
                    "we value your privacy",
                    "privacy",
                    "cookie settings",
                    "cookies",
                    "careers marketplace",
                    "job search",
                    "siemens",
                }

                if (
                    detail_title
                    and detail_title.strip().lower() not in bad_detail_titles
                    and not re.search(
                        r"privacy|cookie|consent|preferences",
                        detail_title,
                        re.I,
                    )
                ):
                    title = detail_title

                # Ignore generic link labels.
                if not title or title.lower() in {
                    "learn more",
                    "apply",
                    "apply now",
                    "view job",
                    "job details",
                }:
                    # Recover title from board text immediately before Job ID.
                    m = re.search(
                        rf"([^\n]{{3,250}})\n[^\n]*Job ID:\s*{re.escape(job_id)}\b",
                        board_text,
                        re.I,
                    )
                    if m:
                        title = m.group(1).strip()

                if not title:
                    title = f"Siemens Job {job_id}"

                # Normalise location conservatively.
                if re.search(r"\bDublin\b", combined, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bGalway\b", combined, re.I):
                    location = "Galway, Ireland"
                elif re.search(r"\bCork\b", combined, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"\bLimerick\b", combined, re.I):
                    location = "Limerick, Ireland"
                elif re.search(r"\bShannon\b", combined, re.I):
                    location = "Shannon, Ireland"
                else:
                    location = "Ireland"

                canonical = (
                    "https://jobs.siemens.com/"
                    f"en_US/externaljobs/JobDetail/{job_id}"
                )

                results[job_id] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": combined[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Siemens Ireland scrape failed: {exc}")

    print(
        f"  Siemens official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_musgrave():
    company = "Musgrave"
    source_url = "https://musgravegroup.com/careers/vacancies/"

    if not HAS_PLAYWRIGHT:
        print("  ! Musgrave: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1300}, locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2500)

            stagnant = 0
            previous = 0

            for _ in range(100):
                anchors = page.locator("a[href]")

                for i in range(anchors.count()):
                    a = anchors.nth(i)
                    try:
                        raw = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    low = href.lower()

                    # Keep likely vacancy/detail links, reject navigation/social links.
                    if any(x in low for x in (
                        "linkedin.com", "facebook.com", "instagram.com",
                        "/careers/", "/about/", "/news/", "/contact/"
                    )) and "vacanc" not in low and "job" not in low:
                        continue

                    title = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    node = a
                    card = ""

                    for _up in range(6):
                        try:
                            txt = _browser_text(node)
                        except Exception:
                            txt = ""
                        if txt and len(txt) <= 3200:
                            card = txt
                        if re.search(
                            r"\b(?:Dublin|Cork|Limerick|Galway|Waterford|Kildare|Meath|Westmeath|Kilkenny|Tipperary|Ireland)\b",
                            card,
                            re.I,
                        ):
                            break
                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    blob = f"{title}\n{card}\n{href}"

                    # Current vacancies page is already Musgrave scoped; use title/card evidence
                    # and ignore obvious non-job navigation.
                    bad_titles = {
                        "", "careers", "current vacancies", "all current vacancies",
                        "learn more", "read more", "home", "contact"
                    }
                    if title.lower() in bad_titles:
                        continue

                    # Require vacancy-ish content.
                    if not (
                        re.search(r"\b(?:Dublin|Cork|Limerick|Galway|Waterford|Kildare|Meath|Westmeath|Kilkenny|Tipperary|Ireland)\b", blob, re.I)
                        or any(k in low for k in ("vacanc", "job", "career"))
                    ):
                        continue

                    # Avoid the generic vacancies landing page itself.
                    if href.rstrip("/") == source_url.rstrip("/"):
                        continue

                    if len(title) > 300:
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in card.splitlines()
                            if 5 <= len(x.strip()) <= 220
                        ]
                        title = next(
                            (x for x in lines if x.lower() not in bad_titles),
                            "",
                        )

                    if not title:
                        continue

                    location = "Ireland"
                    for city in (
                        "Dublin", "Cork", "Limerick", "Galway", "Waterford",
                        "Kildare", "Meath", "Westmeath", "Kilkenny", "Tipperary"
                    ):
                        if re.search(rf"\b{city}\b", blob, re.I):
                            location = f"{city}, Ireland"
                            break

                    canonical = href.split("?")[0]
                    key = canonical.rstrip("/").lower()

                    results[key] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card[:5000],
                    }

                # Lazy load / pagination if present.
                clicked = False
                for selector in (
                    'button:has-text("Load more")',
                    'button:has-text("Show more")',
                    'a:has-text("Next")',
                    'button:has-text("Next")',
                ):
                    try:
                        btn = page.locator(selector)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200)
                            page.wait_for_timeout(450)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(300)

                current = len(results)
                stagnant = stagnant + 1 if current == previous else 0
                previous = current
                if stagnant >= 8 and not clicked:
                    break

            browser.close()

    except Exception as exc:
        print(f"  ! Musgrave Ireland scrape failed: {exc}")

    print(f"  Musgrave official vacancies: {len(results)} jobs")
    return list(results.values())



def scrape_fedex():
    company = "FedEx"
    source_url = "https://careers.fedex.com/international/european-operations/jobs"

    if not HAS_PLAYWRIGHT:
        print("  ! FedEx: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1400},
                locale="en-IE",
            )

            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2500)

            # The FedEx page is server-rendered but its detail-link URL shape
            # changes. Do NOT assume href contains "/jobs/".
            anchors = page.locator("a[href]")

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    raw = a.get_attribute("href") or ""
                    href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                except Exception:
                    continue

                # Only FedEx careers links; reject nav/social/category links later.
                if "careers.fedex.com" not in href.lower():
                    continue

                node = a
                card = ""
                for _up in range(9):
                    try:
                        txt = _browser_text(node)
                    except Exception:
                        txt = ""

                    if txt and len(txt) <= 4500:
                        card = txt

                    # A real FedEx vacancy card includes requisition + physical location.
                    if (
                        re.search(r"\bRC\d+\b", card, re.I)
                        and re.search(r",\s*IE\b|\bIreland\b", card, re.I)
                    ):
                        break

                    try:
                        node = node.locator("..")
                    except Exception:
                        break

                if not card:
                    continue

                # Republic of Ireland only; avoid Belfast/NI false positives.
                if re.search(r"\bNorthern Ireland\b|\bBelfast\b", card, re.I):
                    continue

                if not re.search(r",\s*IE\b|\bIreland\b", card, re.I):
                    continue

                req = re.search(r"\b(RC\d+)\b", card, re.I)
                if not req:
                    continue

                req_id = req.group(1).upper()

                # Navigation/listing links can sit inside the same ancestor.
                low = href.lower()
                if href.rstrip("/") == source_url.rstrip("/"):
                    continue
                if any(x in low for x in (
                    "/international/",
                    "/career-areas/",
                    "/benefits",
                    "/about",
                    "/locations",
                    "/search",
                    "/jobs/page/",
                )):
                    # Allow it only if the anchor text itself contains the requisition.
                    anchor_text = re.sub(r"\s+", " ", _browser_text(a)).strip()
                    if req_id.lower() not in anchor_text.lower():
                        continue

                # Extract title from the text immediately before requisition ID.
                compact = re.sub(r"[ \t]+", " ", card)
                lines = [
                    re.sub(r"\s+", " ", x).strip()
                    for x in compact.splitlines()
                    if x.strip()
                ]

                title = ""
                for line in lines:
                    if req_id.lower() in line.lower():
                        candidate = re.sub(
                            rf"\s*{re.escape(req_id)}\s*$",
                            "",
                            line,
                            flags=re.I,
                        ).strip()
                        if candidate and len(candidate) <= 240:
                            title = candidate
                            break

                if not title:
                    # Fallback: title + requisition may have collapsed to one block.
                    tm = re.search(
                        rf"([A-Za-z0-9][^|]{{3,180}}?)\s*{re.escape(req_id)}\b",
                        compact,
                        re.I,
                    )
                    if tm:
                        title = re.sub(r"\s+", " ", tm.group(1)).strip()

                if not title or title.lower() in {
                    "view job", "view job ", "apply now", "save job"
                }:
                    continue

                location = "Ireland"
                if re.search(r"\bDublin\b", card, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bShannon\b", card, re.I):
                    location = "Shannon, Ireland"
                elif re.search(r"\bCork\b", card, re.I):
                    location = "Cork, Ireland"

                # If this anchor is just an action link, still use it as the
                # clickable job URL; dedupe by requisition ID.
                results[req_id.lower()] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": href,
                    "updated_at": None,
                    "description_text": card[:5000],
                }

            # Absolute fallback for the verified current Dublin vacancy.
            # We only use the board URL if FedEx changes the card's detail href,
            # so the dashboard never falsely shows zero while the verified role exists.
            body = _browser_text(page.locator("body"))
            if "rc779390" in body.lower() and re.search(r"\bDublin\b.*,\s*IE\b", body, re.I | re.S):
                if "rc779390" not in results:
                    results["rc779390"] = {
                        "company": company,
                        "ats": "direct",
                        "title": "Handler (Day shift)",
                        "location": "Dublin, Ireland",
                        "url": source_url,
                        "updated_at": None,
                        "description_text": "RC779390 — Constellation Road, Dublin, IE",
                    }

            browser.close()

    except Exception as exc:
        print(f"  ! FedEx Ireland v4 scrape failed: {exc}")

    print(f"  FedEx verified Ireland careers v4: {len(results)} jobs")
    return list(results.values())


def scrape_coca_cola():
    company = "Coca-Cola"
    source_url = "https://careers.coca-colahellenic.com/en_US/careers/SearchJobs/ireland"

    if not HAS_PLAYWRIGHT:
        print("  ! Coca-Cola HBC: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1400},
                locale="en-IE",
            )

            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2200)

            anchors = page.locator('a[href*="/careers/ProjectDetail/"]')

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    raw = a.get_attribute("href") or ""
                    href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                except Exception:
                    continue

                if "/careers/projectdetail/" not in href.lower():
                    continue

                title = re.sub(r"\s+", " ", _browser_text(a)).strip()

                node = a
                card = ""

                for _up in range(7):
                    try:
                        txt = _browser_text(node)
                    except Exception:
                        txt = ""

                    if txt and len(txt) <= 3800:
                        card = txt

                    if re.search(
                        r"\bIreland\b|\bDublin\b|\bMeath\b|\bCavan\b|\bMonaghan\b|\bLongford\b",
                        card,
                        re.I,
                    ):
                        break

                    try:
                        node = node.locator("..")
                    except Exception:
                        break

                if not title:
                    lines = [
                        re.sub(r"\s+", " ", x).strip()
                        for x in card.splitlines()
                        if 5 <= len(x.strip()) <= 220
                    ]
                    title = next(
                        (
                            x for x in lines
                            if x.lower() not in {
                                "apply now", "view job", "learn more"
                            }
                        ),
                        "",
                    )

                if not title:
                    continue

                blob = f"{title}\n{card}\n{href}"

                if re.search(r"\bNorthern Ireland\b|\bBelfast\b", blob, re.I):
                    continue

                location = "Ireland"

                county_hits = [
                    x for x in (
                        "Dublin", "Meath", "Cavan", "Monaghan", "Longford",
                        "Westmeath", "Offaly", "Laois", "Kildare"
                    )
                    if re.search(rf"\b{x}\b", blob, re.I)
                ]

                if len(county_hits) == 1:
                    location = f"{county_hits[0]}, Ireland"
                elif len(county_hits) > 1:
                    location = ", ".join(county_hits) + ", Ireland"

                canonical = href.split("?")[0]

                results[canonical.rstrip("/").lower()] = {
                    "company": company,
                    "ats": "avature",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": card[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Coca-Cola HBC Ireland scrape failed: {exc}")

    print(f"  Coca-Cola HBC Ireland careers: {len(results)} jobs")
    return list(results.values())

def scrape_pepsico():
    company = "PepsiCo"

    ireland_url = (
        "https://www.pepsicojobs.com/main/jobs"
        "?stretchUnit=MILES&stretch=10&location=Ireland&woe=12&regionCode=IE"
    )

    fallback_urls = [
        "https://www.pepsicojobs.com/main/jobs/451831?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/443247?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/447137?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/415897?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/457279?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/462258?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/401833?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/461086?lang=en-us",
        "https://www.pepsicojobs.com/main/jobs/456011?lang=en-us",
    ]

    sess = _session()
    results = {}

    def add_detail(href):
        if not sess:
            return

        try:
            r = sess.get(
                href,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                    "Referer": ireland_url,
                },
            )
        except Exception:
            return

        if r.status_code != 200:
            return

        html_text = r.text or ""
        body = _html_text(html_text)

        if re.search(r"\bNorthern Ireland\b|\bBelfast\b", body, re.I):
            return

        if not re.search(r"\bIreland\b|\bDublin\b|\bCork\b", body, re.I):
            return

        title = ""

        hm = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.I | re.S)
        if hm:
            title = re.sub(r"\s+", " ", _html_text(hm.group(1))).strip()

        if not title:
            tm = re.search(
                r'Pepsico Global is hiring a (.*?) in .*?Ireland',
                body,
                re.I | re.S,
            )
            if tm:
                title = re.sub(r"\s+", " ", tm.group(1)).strip()

        if not title:
            return

        location = "Ireland"
        if re.search(r"\bDublin(?: 2)?\b", body, re.I):
            location = "Dublin, Ireland"
        elif re.search(r"\bCork\b", body, re.I):
            location = "Cork, Ireland"

        canonical = href.split("?")[0]

        results[canonical.rstrip("/").lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": body[:5000],
        }

    if sess:
        # Primary discovery: exact Ireland-filtered PepsiCo search.
        try:
            r = sess.get(
                ireland_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
        except Exception:
            r = None

        if r is not None and r.status_code == 200:
            html_text = r.text or ""

            # Capture all PepsiCo detail links visible on the Ireland board.
            for mm in re.finditer(
                r'href=["\']([^"\']*/main/jobs/\d+[^"\']*)["\']',
                html_text,
                re.I,
            ):
                href = urllib.parse.urljoin(ireland_url, mm.group(1))

                # Nearby card text should already be Ireland scoped, but keep
                # only cards with explicit Irish location evidence.
                start = max(0, mm.start() - 1800)
                end = min(len(html_text), mm.end() + 2200)
                card_text = _html_text(html_text[start:end])

                if not re.search(r"\bIreland\b|\bDublin\b|\bCork\b", card_text, re.I):
                    continue

                add_detail(href)

        # Verified detail-page fallback for anti-bot / incomplete index responses.
        for href in fallback_urls:
            add_detail(href)

    print(f"  PepsiCo Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_ryanair():
    company = "Ryanair"
    source_urls = [
        "https://careers.ryanair.com/jobs/?ryanair-jobs-location=22038",  # Dublin
        "https://careers.ryanair.com/jobs/?ryanair-jobs-location=22020",  # Dublin Airport
    ]

    if not HAS_PLAYWRIGHT:
        print("  ! Ryanair: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1400}, locale="en-IE")

            for source_url in source_urls:
                page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1200)

                cards = page.locator(".job")

                for i in range(cards.count()):
                    card = cards.nth(i)

                    try:
                        title = re.sub(r"\s+", " ", _browser_text(card.locator(".job__title").first)).strip()
                    except Exception:
                        title = ""

                    try:
                        link = card.locator("a.job__link").first
                        raw = link.get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    try:
                        card_text = _browser_text(card)
                    except Exception:
                        card_text = title

                    if not title:
                        continue
                    if href.rstrip("/") == "https://careers.ryanair.com/jobs":
                        continue

                    if re.search(r"\bBelfast\b|\bNorthern Ireland\b", card_text, re.I):
                        continue
                    if not re.search(r"\bDublin\b|\bIreland\b", card_text, re.I):
                        continue

                    location = "Ireland"
                    if re.search(r"\bDublin Airport\b", card_text, re.I):
                        location = "Dublin Airport, Ireland"
                    elif re.search(r"\bDublin\b", card_text, re.I):
                        location = "Dublin, Ireland"

                    canonical = href.split("?")[0]
                    results[canonical.rstrip("/").lower()] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card_text[:5000],
                    }

            browser.close()

    except Exception as exc:
        print(f"  ! Ryanair clean Ireland scrape failed: {exc}")

    print(f"  Ryanair clean Ireland careers: {len(results)} jobs")
    return list(results.values())

def scrape_sp_global():
    """
    S&P Global official Workday Ireland collector.

    Workday search cards can use a non-Ireland PRIMARY location for
    multi-location roles, so use the official Ireland country facet and
    validate the full Workday job-detail JSON.
    """
    company = "S&P Global"
    base = "https://spgi.wd5.myworkdayjobs.com"
    site = "SPGI_Careers"
    api = f"{base}/wday/cxs/spgi/{site}/jobs"

    IRELAND_COUNTRY_ID = "04a05835925f45b3a59406a2a6b72c8a"

    sess = _session()
    if not sess:
        return []

    results = {}
    offset = 0

    while offset < 500:
        payload = {
            "appliedFacets": {
                "Location_Country": [IRELAND_COUNTRY_ID]
            },
            "limit": 20,
            "offset": offset,
            "searchText": "",
        }

        try:
            r = sess.post(
                api,
                json=payload,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Language": "en-IE,en;q=0.9",
                    "Referer": f"{base}/{site}",
                },
            )
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as exc:
            print(f"  ! S&P Global Workday search failed: {exc}")
            break

        rows = data.get("jobPostings") or []
        if not rows:
            break

        for row in rows:
            external_path = str(row.get("externalPath") or "").strip()
            if not external_path:
                continue

            detail_url = (
                f"{base}/wday/cxs/spgi/{site}"
                f"{external_path}"
            )

            try:
                dr = sess.get(
                    detail_url,
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                        "Accept-Language": "en-IE,en;q=0.9",
                        "Referer": f"{base}/{site}",
                    },
                )

                if dr.status_code != 200:
                    continue

                detail = dr.json()
            except Exception:
                continue

            info = detail.get("jobPostingInfo") or {}

            title = (
                info.get("title")
                or row.get("title")
                or ""
            ).strip()

            location = str(info.get("location") or "")
            additional = info.get("additionalLocations") or []

            if isinstance(additional, list):
                additional_text = " ".join(
                    str(x.get("location") if isinstance(x, dict) else x)
                    for x in additional
                )
            else:
                additional_text = str(additional)

            desc = str(
                info.get("jobDescription")
                or info.get("description")
                or ""
            )

            blob = (
                f"{title} {location} {additional_text} "
                f"{desc} {detail_url}"
            )

            if re.search(
                r"\b(?:Belfast|Northern Ireland)\b",
                blob,
                re.I,
            ):
                continue

            if not re.search(
                r"\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford)\b",
                blob,
                re.I,
            ):
                continue

            public_url = base + "/" + site + external_path

            key = public_url.split("?")[0].rstrip("/").lower()
            if key in results:
                continue

            if re.search(r"\bDublin\b", blob, re.I):
                clean_location = "Dublin, Ireland"
            elif re.search(r"\bCork\b", blob, re.I):
                clean_location = "Cork, Ireland"
            else:
                clean_location = "Ireland"

            results[key] = {
                "company": company,
                "ats": "workday",
                "title": title[:300],
                "location": clean_location,
                "url": public_url,
                "updated_at": info.get("startDate"),
                "description_text": desc[:7000],
                "requisition_id": (
                    (row.get("bulletFields") or [""])[0]
                    if row.get("bulletFields")
                    else ""
                ),
            }

        offset += len(rows)

        total = data.get("total")
        if isinstance(total, int) and offset >= total:
            break

    _mark_connector_health(
        company,
        True,
        f"S&P Global Workday Ireland facet returned {len(results)} jobs",
        f"{base}/{site}",
    )

    print(f"  S&P Global official Workday Ireland: {len(results)} jobs")
    return list(results.values())



def scrape_abb():
    """
    ABB Ireland jobs.

    ABB's Phenom search-results page is currently unreliable for direct
    Playwright navigation, so avoid blocking on the search board itself.
    Use lightweight HTTP discovery plus known ABB job-detail patterns.
    """
    company = "ABB"

    sess = _session()
    if not sess:
        print("  ! ABB: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "en-IE,en;q=0.9",
    }

    # ABB pages that can expose job-detail links without relying on the
    # client-side search board completing.
    sources = [
        "https://careers.abb/global/en/search-results?qcountry=Ireland",
        "https://careers.abb/global/en/search-results?keywords=Ireland",
        "https://careers.abb/global/en/life-at-abb-ireland",
        "https://careers.abb/global/en/field-service-careers",
        "https://careers.abb/global/en/service-careers",
    ]

    candidates = set()

    # Preserve the previously confirmed Ireland job as a seed. If it closes,
    # the detail-page validation below will naturally reject it.
    candidates.add(
        "https://careers.abb/global/en/job/"
        "JR00027417/Field-Service-Engineer"
    )

    for source in sources:
        try:
            r = sess.get(source, headers=headers, timeout=20)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""

        patterns = [
            r'https://careers\.abb/global/en/job/'
            r'[A-Za-z0-9_-]+/[^"\'<> ]+',

            r'["\'](/global/en/job/'
            r'[A-Za-z0-9_-]+/[^"\']+)["\']',
        ]

        for pattern in patterns:
            for m in re.finditer(pattern, html_text, re.I):
                href = m.group(1)

                if href.startswith("/"):
                    href = urllib.parse.urljoin(
                        "https://careers.abb",
                        href,
                    )

                href = href.replace("&amp;", "&")
                href = href.split("?")[0].split("#")[0].rstrip("/")
                candidates.add(href)

    results = {}

    for href in sorted(candidates):
        try:
            r = sess.get(href, headers=headers, timeout=20)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""
        body = _html_text(html_text)

        # Closed/invalid ABB pages should not survive.
        if len(body.strip()) < 100:
            continue

        # Require actual Republic of Ireland evidence.
        ireland = bool(
            re.search(
                r"\bDublin\b|\bIreland\b|\bRepublic of Ireland\b|"
                r"\bCork\b|\bGalway\b|\bLimerick\b|\bKildare\b",
                body,
                re.I,
            )
        )

        if not ireland:
            continue

        # Exclude Northern Ireland / UK-only jobs.
        if re.search(
            r"\bBelfast\b|\bNorthern Ireland\b",
            body,
            re.I,
        ):
            continue

        title = ""

        for pattern in [
            r'<h1[^>]*>(.*?)</h1>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+'
            r'content=["\']([^"\']+)',
            r'<title[^>]*>(.*?)</title>',
        ]:
            m = re.search(pattern, html_text, re.I | re.S)
            if m:
                title = re.sub(
                    r"\s+",
                    " ",
                    _html_text(m.group(1)),
                ).strip()
                if title:
                    break

        if not title:
            continue

        title = re.sub(
            r"\s*\|\s*ABB.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        title = re.sub(
            r"\s+in\s+(?:Dublin|Cork|Galway|Limerick|Kildare)"
            r"(?:,\s*[^,]+)?(?:,\s*Ireland)?\s*$",
            "",
            title,
            flags=re.I,
        ).strip()

        location = "Ireland"

        if re.search(r"\bDublin\b", body, re.I):
            location = "Dublin, Ireland"
        elif re.search(r"\bCork\b", body, re.I):
            location = "Cork, Ireland"
        elif re.search(r"\bGalway\b", body, re.I):
            location = "Galway, Ireland"
        elif re.search(r"\bLimerick\b", body, re.I):
            location = "Limerick, Ireland"
        elif re.search(r"\bKildare\b", body, re.I):
            location = "Kildare, Ireland"

        canonical = href.rstrip("/")

        results[canonical.lower()] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": body[:5000],
        }

    print(
        f"  ABB official Ireland: "
        f"{len(results)} jobs from {len(candidates)} details"
    )

    return list(results.values())


def scrape_aecom():
    """AECOM Ireland via official SmartRecruiters public postings API."""
    jobs = scrape_smartrecruiters("AECOM2")

    out = []
    for job in jobs:
        # Generic SmartRecruiters collector emits the ATS company id.
        # Normalize to registry-safe canonical company name.
        job["company"] = "AECOM"
        out.append(job)

    print(f"  AECOM SmartRecruiters Ireland: {len(out)} jobs")
    return out

def scrape_laya_healthcare():
    """
    Laya Healthcare Ireland jobs from the official AXA careers board,
    filtered specifically to Laya Healthcare Ltd + Ireland.
    """
    company = "Laya Healthcare"

    board = (
        "https://careers.axa.com/careers-home/jobs"
        "?page=1"
        "&tags3=Laya%20Healthcare%20Ltd"
        "&location=Ireland"
        "&woe=12"
        "&regionCode=IE"
        "&stretchUnit=MILES"
        "&stretch=10"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! Laya Healthcare: Playwright unavailable")
        return []

    results = {}
    detail_urls = set()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()

            # The board sometimes loads slowly / partially, so don't let
            # networkidle block the scraper.
            try:
                page.goto(
                    board,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
            except Exception:
                pass

            page.wait_for_timeout(5000)

            # Collect current filtered results.
            for _ in range(8):
                try:
                    links = page.locator("a").evaluate_all(
                        """els => els.map(a => ({
                            href: a.href || "",
                            text: (a.innerText || a.textContent || "").trim()
                        }))"""
                    )

                    for item in links:
                        href = str(item.get("href") or "")

                        if not re.search(
                            r"https://careers\.axa\.com/"
                            r"(?:careers-home/|axa-uk-careers/)?jobs/\d+",
                            href,
                            re.I,
                        ):
                            continue

                        detail_urls.add(href.split("#")[0])

                except Exception:
                    pass

                try:
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(1000)
                except Exception:
                    break

            # Also inspect rendered HTML because some cards are not exposed
            # cleanly as normal anchors.
            try:
                html_text = page.content()
            except Exception:
                html_text = ""

            patterns = [
                r'https://careers\.axa\.com/careers-home/jobs/\d+[^"\'<> ]*',
                r'https://careers\.axa\.com/axa-uk-careers/jobs/\d+[^"\'<> ]*',
                r'https://careers\.axa\.com/jobs/\d+[^"\'<> ]*',
                r'["\'](/careers-home/jobs/\d+[^"\']*)["\']',
                r'["\'](/jobs/\d+[^"\']*)["\']',
            ]

            for pattern in patterns:
                for m in re.finditer(pattern, html_text, re.I):
                    href = urllib.parse.urljoin(
                        "https://careers.axa.com",
                        m.group(1),
                    )
                    href = href.replace("&amp;", "&")
                    detail_urls.add(href.split("#")[0])

            page.close()

            # Detail pages are the authoritative check. Never rely solely
            # on the querystring filter.
            for href in sorted(detail_urls):
                detail = context.new_page()

                try:
                    try:
                        detail.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                    except Exception:
                        pass

                    detail.wait_for_timeout(1200)

                    try:
                        body = detail.locator("body").inner_text(timeout=7000)
                    except Exception:
                        body = ""

                    if not body:
                        detail.close()
                        continue

                    # Must actually belong to Laya Healthcare Ltd.
                    if not re.search(
                        r"\bLaya\s+Healthcare\s+Ltd\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    # Must be Republic of Ireland.
                    if not re.search(
                        r"\bIreland\b|\bIE\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    # Exclude Northern Ireland if it ever leaks into results.
                    if re.search(
                        r"\bNorthern Ireland\b|\bBelfast\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    title = ""

                    # H1 is normally the cleanest title.
                    try:
                        h1 = detail.locator("h1")
                        if h1.count():
                            title = (h1.first.inner_text() or "").strip()
                    except Exception:
                        pass

                    if not title:
                        try:
                            title = (detail.title() or "").strip()
                        except Exception:
                            title = ""

                    title = re.sub(r"\s+", " ", title).strip()

                    title = re.sub(
                        r"\s+in\s+.*?\|\s*AXA\s*$",
                        "",
                        title,
                        flags=re.I,
                    ).strip()

                    title = re.sub(
                        r"\s*\|\s*AXA\s*$",
                        "",
                        title,
                        flags=re.I,
                    ).strip()

                    if not title or title.lower() in {
                        "jobs",
                        "careers",
                        "job details",
                        "learn more",
                    }:
                        detail.close()
                        continue

                    location = "Ireland"

                    if re.search(
                        r"\bLittle Island\b",
                        body,
                        re.I,
                    ):
                        location = "Little Island, Cork, Ireland"
                    elif re.search(r"\bCork\b", body, re.I):
                        location = "Cork, Ireland"
                    elif re.search(r"\bDublin\b", body, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bGalway\b", body, re.I):
                        location = "Galway, Ireland"

                    # Normalise all AXA URL variants to careers-home.
                    m = re.search(r"/jobs/(\d+)", detail.url or href)
                    if not m:
                        detail.close()
                        continue

                    job_id = m.group(1)

                    canonical = (
                        "https://careers.axa.com/"
                        f"careers-home/jobs/{job_id}?lang=en-us"
                    )

                    results[job_id] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": body[:5000],
                    }

                except Exception:
                    pass

                try:
                    detail.close()
                except Exception:
                    pass

            browser.close()

    except Exception as exc:
        print(f"  ! Laya Healthcare scrape failed: {exc}")

    print(
        f"  Laya Healthcare official Ireland careers: "
        f"{len(results)} jobs from {len(detail_urls)} details"
    )

    return list(results.values())


def scrape_axa():
    company = "AXA Ireland"
    verified = _official_ireland_detail_jobs(
        company,
        ["https://careers.axa.com/careers-home/jobs/26376?lang=en-us"],
    )
    if verified:
        _mark_connector_health(company, True, f"Verified {len(verified)} official Dublin vacancy", verified[0]["url"])

    source_url = (
        "https://careers.axa.com/careers-home/jobs"
        "?tags3=AXA%20Ireland"
        "&page=1"
        "&lat=53.3498"
        "&lng=-6.2603"
        "&radiusUnit=MILES"
        "&radius=25"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! AXA Ireland: Playwright unavailable")
        return verified

    best = {}

    for attempt in range(1, 4):
        results = {}

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                    ],
                )

                page = browser.new_page(
                    locale="en-IE",
                    viewport={"width": 1440, "height": 1800},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                )

                page.goto(
                    source_url,
                    wait_until="domcontentloaded",
                    timeout=90000,
                )

                page.wait_for_timeout(9000)

                try:
                    _dismiss_cookie_banner(page)
                except Exception:
                    pass

                title_text = ""

                try:
                    title_text = page.title()
                except Exception:
                    pass

                if re.search(r"\b403\b|forbidden", title_text, re.I):
                    print(
                        f"  ! AXA Ireland attempt {attempt}: "
                        f"blocked page ({title_text})"
                    )
                    browser.close()
                    continue

                anchors = page.locator(
                    'a[href*="/careers-home/jobs/"]'
                )

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    href = urllib.parse.urljoin(
                        page.url,
                        a.get_attribute("href") or "",
                    )

                    m = re.search(
                        r"/careers-home/jobs/(\d+)",
                        href,
                        re.I,
                    )

                    if not m:
                        continue

                    card_text = ""

                    for level in range(1, 7):
                        try:
                            candidate = a.locator(
                                f"xpath=ancestor::div[{level}]"
                            )

                            txt = re.sub(
                                r"\s+",
                                " ",
                                _browser_text(candidate) or "",
                            ).strip()

                            if (
                                "Req ID:" in txt
                                and "Entity" in txt
                                and "Location" in txt
                            ):
                                card_text = txt
                                break

                        except Exception:
                            pass

                    if not card_text:
                        continue

                    entity_match = re.search(
                        r"\bEntity\s+(AXA Ireland|AXA XL)\b",
                        card_text,
                        re.I,
                    )

                    if not entity_match:
                        continue

                    if (
                        entity_match.group(1)
                        .strip()
                        .lower()
                        != "axa ireland"
                    ):
                        continue

                    if not re.search(
                        r"\bLocation\s+DUBLIN,\s*IE\b",
                        card_text,
                        re.I,
                    ):
                        continue

                    title = re.sub(
                        r"\s+",
                        " ",
                        _browser_text(a) or "",
                    ).strip()

                    if (
                        not title
                        or len(title) > 300
                        or title.lower() == "apply now"
                    ):
                        continue

                    job_id = m.group(1)

                    results[job_id] = {
                        "company": company,
                        "ats": "icims",
                        "title": title[:300],
                        "location": "Dublin, Ireland",
                        "url": href.split("#")[0],
                        "updated_at": None,
                        "description_text": card_text[:5000],
                    }

                browser.close()

        except Exception as exc:
            print(
                f"  ! AXA Ireland attempt {attempt} failed: "
                f"{exc}"
            )

        if len(results) > len(best):
            best = results

        if results:
            if attempt > 1:
                print(
                    f"  AXA Ireland recovered on attempt "
                    f"{attempt}"
                )
            break

        if attempt < 3:
            print(
                f"  ! AXA Ireland attempt {attempt}: "
                "0 jobs; retrying"
            )

    print(
        f"  AXA Ireland official Dublin careers: "
        f"{len(best)} jobs"
    )

    if best:
        return list({job["url"].split("?")[0]: job for job in verified + list(best.values())}.values())
    discovered = _browser_board_collect(
        company,
        ["https://careers.axa.com/careers-home/jobs?country=Ireland"],
        ("careers.axa.com/careers-home/jobs/",),
        default_location="Ireland",
        max_scrolls=12,
        require_ireland=True,
        source_tag="official",
    )
    return list({job["url"].split("?")[0]: job for job in verified + discovered}.values())










def scrape_ntt_data():
    company = "NTT DATA"
    base = "https://careers-inc.nttdata.com"

    sess = _session()
    if not sess:
        print("  ! NTT DATA: HTTP session unavailable")
        return []

    # Search Ireland/Dublin on NTT DATA's official SuccessFactors board.
    search_urls = [
        f"{base}/search/?q=&locationsearch=Ireland",
        f"{base}/search/?q=&locationsearch=Dublin",
    ]

    results = {}

    for source_url in search_urls:
        try:
            r = sess.get(
                source_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""

        # SuccessFactors detail links are /job/<city>-<slug>/<id>/
        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']*/job/[^"\']+/\d+/?)["\'][^>]*>(.*?)</a>',
            html_text,
            re.I | re.S,
        ):
            href = urllib.parse.urljoin(source_url, m.group(1)).split("#")[0]

            start = max(0, m.start() - 1600)
            end = min(len(html_text), m.end() + 2000)
            card_text = _html_text(html_text[start:end])

            if re.search(r"\bNorthern Ireland\b|\bBelfast\b", card_text, re.I):
                continue

            if not re.search(r"\bIreland\b|\bDublin\b", card_text, re.I):
                continue

            title = re.sub(r"\s+", " ", _html_text(m.group(2))).strip()

            if not title or title.lower() in {"view job", "apply now"}:
                lines = [
                    re.sub(r"\s+", " ", x).strip()
                    for x in card_text.splitlines()
                    if 5 <= len(x.strip()) <= 220
                ]
                title = next(
                    (
                        x for x in lines
                        if x.lower() not in {
                            "view job", "apply now", "search jobs"
                        }
                    ),
                    "",
                )

            if not title:
                continue

            location = "Dublin, Ireland" if re.search(r"\bDublin\b", card_text, re.I) else "Ireland"
            canonical = href.split("?")[0]

            results[canonical.rstrip("/").lower()] = {
                "company": company,
                "ats": "successfactors",
                "title": title[:300],
                "location": location,
                "url": canonical,
                "updated_at": None,
                "description_text": card_text[:5000],
            }

    print(f"  NTT DATA official Ireland careers: {len(results)} jobs")
    return list(results.values())



def scrape_qualcomm():
    """
    Qualcomm official Ireland collector.

    Qualcomm's current careers frontend is Eightfold-powered.
    The previous Workday /External board now returns zero jobs.
    """
    company = "Qualcomm"

    sess = _session()
    if not sess:
        return []

    jobs = []

    # First use the existing Eightfold adapter.
    try:
        jobs = _scrape_eightfold(
            company,
            "qualcomm",
            sess,
        ) or []
    except Exception as exc:
        print(f"  ! Qualcomm Eightfold adapter failed: {exc}")
        jobs = []

    out = []
    seen = set()

    for job in jobs:
        title = str(job.get("title") or "").strip()
        location = str(job.get("location") or "").strip()
        desc = str(job.get("description_text") or "")
        url = str(job.get("url") or "").strip()

        blob = f"{title} {location} {desc} {url}"

        if re.search(
            r"\b(?:Belfast|Northern Ireland)\b",
            blob,
            re.I,
        ):
            continue

        if not re.search(
            r"\b(?:Ireland|Cork|Dublin)\b",
            blob,
            re.I,
        ):
            continue

        if not title or not url:
            continue

        key = url.split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)

        item = dict(job)
        item["company"] = company
        item["ats"] = "eightfold"

        if re.search(r"\bCork\b", blob, re.I):
            item["location"] = "Cork, Ireland"
        elif re.search(r"\bDublin\b", blob, re.I):
            item["location"] = "Dublin, Ireland"
        else:
            item["location"] = "Ireland"

        out.append(item)

    _mark_connector_health(
        company,
        True,
        f"Qualcomm Eightfold returned {len(out)} Ireland jobs",
        "https://careers.qualcomm.com/careers",
    )

    print(f"  Qualcomm Eightfold Ireland careers: {len(out)} jobs")
    return out



def scrape_ptsb():
    """Scrape current PTSB vacancies from the official CoreHR POST search."""
    company = "PTSB"

    form_url = (
        "https://my.corehr.com/pls/ptsbrecruit/"
        "erq_search_package.search_form"
        "?p_company=1000&p_internal_external=E"
    )

    search_url = (
        "https://my.corehr.com/pls/ptsbrecruit/"
        "erq_search_version_4.start_search_with_params"
    )

    sess = _session()
    if not sess:
        print("  ! PTSB: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-IE,en;q=0.9",
    }

    # Prime CoreHR cookies/session.
    try:
        prime = sess.get(form_url, headers=headers, timeout=30)
        prime.raise_for_status()
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), form_url)
        print(f"  ! PTSB CoreHR form failed: {exc}")
        return []

    payload = {
        "p_company": "1000",
        "p_internal_external": "E",
        "p_display_in_irish": "N",
        "p_recruitment_id": "",
        "p_position_type": "ALLOPTIONS",
        "p_competition_type": "ALLOPTIONS",
        "p_keywords": "",
        "p_force_type": "E",
        "p_search_company": "",
        "p_position": "",
        "p_department": "",
        "p_management_unit": "",
        "p_description": "",
        "p_location": "",
        "p_division": "",
        "p_pay_scale": "",
        "p_user_field1": "",
        "p_user_field2": "",
        "p_user_field3": "",
        "p_user_field4": "",
        "p_user_field5": "",
        "p_emp_status": "",
        "p_emp_substatus": "",
        "p_category": "",
        "p_sub_category": "",
        "p_job_category": "",
    }

    try:
        r = sess.post(
            search_url,
            data=payload,
            headers={
                **headers,
                "Referer": prime.url,
            },
            timeout=40,
        )
        r.raise_for_status()
        html_text = r.text or ""
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), search_url)
        print(f"  ! PTSB CoreHR search failed: {exc}")
        return []

    # CoreHR search results can expose recruitment IDs in hrefs,
    # javascript/form values, or hidden fields.
    recruitment_ids = set(
        re.findall(
            r"p_recruitment_id(?:=|%3D|['\"\s:=]+)(\d{5,})",
            html_text,
            re.I,
        )
    )

    recruitment_ids.update(
        re.findall(
            r"name=[\"']p_recruitment_id[\"'][^>]+value=[\"'](\d{5,})",
            html_text,
            re.I,
        )
    )

    recruitment_ids.update(
        re.findall(
            r"value=[\"'](\d{5,})[\"'][^>]+name=[\"']p_recruitment_id[\"']",
            html_text,
            re.I,
        )
    )

    results = {}

    for rid in sorted(recruitment_ids):
        detail_url = (
            "https://my.corehr.com/pls/ptsbrecruit/"
            "erq_jobspec_version_4.display_form"
            "?p_applicant_no="
            "&p_company=1000"
            "&p_display_apply_ind=Y"
            "&p_display_in_irish=N"
            "&p_form_profile_detail="
            "&p_internal_external=E"
            "&p_process_type="
            f"&p_recruitment_id={rid}"
            "&p_refresh_search=Y"
        )

        try:
            rr = sess.get(
                detail_url,
                headers={
                    **headers,
                    "Referer": r.url,
                },
                timeout=30,
            )

            if rr.status_code != 200:
                continue

            text = re.sub(
                r"\s+",
                " ",
                _html_text(rr.text or ""),
            ).strip()

            # Ignore expired/no-longer-live vacancy IDs.
            if (
                not text
                or re.search(
                    r"(?:vacancy.*(?:closed|expired)|"
                    r"no longer available|appointment.*closed)",
                    text,
                    re.I,
                )
            ):
                continue

            # Try to infer a proper vacancy title.
            title = ""

            soup_title = re.search(
                r"<title[^>]*>(.*?)</title>",
                rr.text or "",
                re.I | re.S,
            )

            headings = re.findall(
                r"<h[1-4][^>]*>(.*?)</h[1-4]>",
                rr.text or "",
                re.I | re.S,
            )

            for raw in headings:
                candidate = re.sub(
                    r"\s+",
                    " ",
                    _html_text(raw),
                ).strip()

                if candidate and candidate.lower() not in {
                    "vacancy details",
                    "applicant options",
                    "search appointments",
                }:
                    title = candidate
                    break

            # CoreHR commonly links the actual Job Description document.
            doc_labels = re.findall(
                r'<a[^>]+href=["\'][^"\']+["\'][^>]*>(.*?)</a>',
                rr.text or "",
                re.I | re.S,
            )

            if not title:
                for raw in doc_labels:
                    candidate = re.sub(
                        r"\s+",
                        " ",
                        _html_text(raw),
                    ).strip()

                    if (
                        candidate
                        and candidate.lower()
                        not in {
                            "job description",
                            "return to search",
                            "login",
                            "register",
                        }
                        and len(candidate) > 4
                    ):
                        title = candidate
                        break

            if not title and soup_title:
                candidate = re.sub(
                    r"\s+",
                    " ",
                    _html_text(soup_title.group(1)),
                ).strip()

                if candidate.lower() != "vacancy details":
                    title = candidate

            if not title:
                title = f"PTSB Vacancy {rid}"

            location = "Ireland"

            loc = re.search(
                r"\b("
                r"Dublin|Cork|Galway|Limerick|Waterford|"
                r"Kildare|Kilkenny|Wexford|Athlone|Sligo|"
                r"Meath|Louth|Tipperary"
                r")\b",
                text,
                re.I,
            )

            if loc:
                location = f"{loc.group(1)}, Ireland"

            results[rid] = {
                "company": company,
                "ats": "corehr",
                "title": title[:300],
                "location": location,
                "url": detail_url,
                "updated_at": None,
                "description_text": text[:7000],
            }

        except Exception:
            continue

    if results:
        _mark_connector_health(
            company,
            True,
            f"Official PTSB CoreHR search completed: {len(results)} live vacancies",
            search_url,
        )
    else:
        _mark_connector_health(
            company,
            True,
            "Official PTSB CoreHR search completed successfully; no current external vacancies returned",
            search_url,
        )

    print(f"  PTSB CoreHR official careers: {len(results)} jobs")
    return list(results.values())



def scrape_publicjobs():
    company = "publicjobs.ie"
    board = (
        "https://publicjobs.tal.net/vx/lang-en-GB/mobile-0/"
        "appcentre-ext/brand-4/xf-423dd989250d/"
        "candidate/jobboard/vacancy/3/adv/"
    )

    sess = _session()

    if not sess:
        print("  ! publicjobs.ie: HTTP session unavailable")
        return []

    results = {}
    queue = [board]
    seen_pages = set()

    while queue and len(seen_pages) < 80:
        url = queue.pop(0)

        if url in seen_pages:
            continue

        seen_pages.add(url)

        try:
            r = sess.get(
                url,
                timeout=40,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""

        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']*/vacancy/\d+[^"\']*)["\'][^>]*>(.*?)</a>',
            html_text,
            re.I | re.S,
        ):
            href = urllib.parse.urljoin(
                r.url,
                m.group(1).replace("&amp;", "&"),
            ).split("#")[0]

            title = re.sub(
                r"\s+",
                " ",
                _html_text(m.group(2)),
            ).strip()

            card_html = html_text[
                max(0, m.start() - 1800):
                min(len(html_text), m.end() + 1800)
            ]
            card_text = _html_text(card_html)

            if not title or title.lower() in {
                "job details",
                "full details",
                "apply",
                "more details",
            }:
                lines = [
                    re.sub(r"\s+", " ", x).strip()
                    for x in card_text.splitlines()
                    if 5 <= len(x.strip()) <= 250
                ]

                title = next(
                    (
                        x for x in lines
                        if x.lower() not in {
                            "job details",
                            "full details",
                            "apply",
                            "more details",
                        }
                    ),
                    title,
                )

            if not title:
                continue

            if re.search(
                r"\bNorthern Ireland\b|\bAntrim\b|\bFermanagh\b|\bTyrone\b",
                card_text,
                re.I,
            ):
                continue

            location = "Ireland"

            counties = re.findall(
                r"\b(Dublin|Cork|Galway|Limerick|Kildare|Donegal|Louth|Mayo|"
                r"Westmeath|Kilkenny|Waterford|Sligo|Wicklow|Roscommon|Carlow|"
                r"Cavan|Offaly|Longford|Kerry|Laois|Tipperary|Clare|Leitrim|"
                r"Meath|Wexford|Monaghan)\b",
                card_text,
                re.I,
            )

            if counties:
                uniq = list(dict.fromkeys(x.title() for x in counties))
                location = ", ".join(uniq[:4]) + ", Ireland"
            elif re.search(r"\bNationwide\b", card_text, re.I):
                location = "Nationwide, Ireland"

            key = href.rstrip("/").lower()

            results[key] = {
                "company": company,
                "ats": "oleeo",
                "title": title[:300],
                "location": location,
                "url": href,
                "updated_at": None,
                "description_text": card_text[:5000],
            }

        for raw in re.findall(
            r'href=["\']([^"\']+)["\']',
            html_text,
            re.I,
        ):
            href = urllib.parse.urljoin(
                r.url,
                raw.replace("&amp;", "&"),
            ).split("#")[0]

            if "publicjobs.tal.net/" not in href:
                continue

            if "/candidate/jobboard/" not in href:
                continue

            if href in seen_pages or href in queue:
                continue

            if re.search(r"(page|start|offset|adv)", href, re.I):
                queue.append(href)

    print(f"  publicjobs Oleeo official board: {len(results)} jobs")
    return list(results.values())



def scrape_axa_xl():
    company = "AXA XL"

    source_url = (
        "https://careers.axa.com/careers-home/jobs"
        "?tags3=AXA%20XL"
        "&iisc=referral"
        "&iis=axaxl_website"
        "&iisn=axaxl_careers_page"
        "&page=1"
        "&lat=53.40820732213721"
        "&lng=-6.16041279943103"
        "&radiusUnit=MILES"
        "&radius=10"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! AXA XL: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            page = browser.new_page(
                locale="en-IE",
                viewport={"width": 1440, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36"
                ),
            )

            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=90000,
            )

            page.wait_for_timeout(9000)

            try:
                _dismiss_cookie_banner(page)
            except Exception:
                pass

            anchors = page.locator(
                'a[href*="/careers-home/jobs/"]'
            )

            for i in range(anchors.count()):
                a = anchors.nth(i)

                href = urllib.parse.urljoin(
                    page.url,
                    a.get_attribute("href") or "",
                )

                m = re.search(
                    r"/careers-home/jobs/(\d+)",
                    href,
                    re.I,
                )

                if not m:
                    continue

                card_text = ""

                for level in range(1, 7):
                    try:
                        candidate = a.locator(
                            f"xpath=ancestor::div[{level}]"
                        )

                        txt = re.sub(
                            r"\s+",
                            " ",
                            _browser_text(candidate) or "",
                        ).strip()

                        if (
                            "Req ID:" in txt
                            and "Entity" in txt
                            and "Location" in txt
                        ):
                            card_text = txt
                            break
                    except Exception:
                        pass

                if not card_text:
                    continue

                entity_match = re.search(
                    r"\bEntity\s+(AXA Ireland|AXA XL)\b",
                    card_text,
                    re.I,
                )

                if not entity_match:
                    continue

                entity = entity_match.group(1).strip().lower()

                if entity != "axa xl":
                    continue

                # "Multiple" is not enough evidence for ROI.
                # Only retain explicitly Dublin IE jobs.
                if not re.search(
                    r"\bLocation\s+DUBLIN,\s*IE\b",
                    card_text,
                    re.I,
                ):
                    continue

                title = re.sub(
                    r"\s+",
                    " ",
                    _browser_text(a) or "",
                ).strip()

                if (
                    not title
                    or len(title) > 300
                    or title.lower() == "apply now"
                ):
                    continue

                job_id = m.group(1)

                results[job_id] = {
                    "company": company,
                    "ats": "icims",
                    "title": title[:300],
                    "location": "Dublin, Ireland",
                    "url": href.split("#")[0],
                    "updated_at": None,
                    "description_text": card_text[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! AXA XL scrape failed: {exc}")

    print(
        f"  AXA XL official Dublin careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())




def scrape_atkinsrealis():
    company = "AtkinsRéalis"
    source_url = "https://careers.atkinsrealis.com/en"

    if not HAS_PLAYWRIGHT:
        print("  ! AtkinsRéalis: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            page = browser.new_page(
                locale="en-IE",
                viewport={"width": 1440, "height": 1800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36"
                ),
            )

            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=90000,
            )

            page.wait_for_timeout(6000)
            _dismiss_cookie_banner(page)

            anchors = page.locator('a[href*="/en/jobs/"]')

            urls = []

            for i in range(anchors.count()):
                href = urllib.parse.urljoin(
                    page.url,
                    anchors.nth(i).get_attribute("href") or "",
                )

                if re.search(r"/en/jobs/[^/?#]+-r-\d+", href, re.I):
                    urls.append(href.split("#")[0])

            urls = list(dict.fromkeys(urls))

            for href in urls:
                detail = context = None

                try:
                    detail = browser.new_page(
                        locale="en-IE",
                        viewport={"width": 1440, "height": 1800},
                    )

                    detail.goto(
                        href,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    detail.wait_for_timeout(1200)

                    body = detail.locator("body").inner_text()

                    if not re.search(r"\bIreland\b", body, re.I):
                        detail.close()
                        continue

                    title = ""

                    h1 = detail.locator("h1")

                    if h1.count():
                        title = re.sub(
                            r"\s+",
                            " ",
                            h1.first.inner_text(),
                        ).strip()

                    if not title:
                        slug = href.rstrip("/").split("/")[-1]
                        title = slug.rsplit("-r-", 1)[0]
                        title = title.replace("-", " ").title()

                    cities = []

                    for city in (
                        "Dublin",
                        "Cork",
                        "Galway",
                        "Sligo",
                        "Waterford",
                    ):
                        if re.search(rf"\b{city}\b", body, re.I):
                            cities.append(city)

                    location = (
                        ", ".join(cities) + ", Ireland"
                        if cities
                        else "Ireland"
                    )

                    m = re.search(r"-r-(\d+)", href, re.I)
                    job_id = m.group(1) if m else href

                    results[job_id] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location[:200],
                        "url": href,
                        "updated_at": None,
                        "description_text": re.sub(
                            r"\s+",
                            " ",
                            body,
                        ).strip()[:5000],
                    }

                    detail.close()

                except Exception:
                    try:
                        if detail:
                            detail.close()
                    except Exception:
                        pass
                    continue

            browser.close()

    except Exception as exc:
        print(f"  ! AtkinsRéalis scrape failed: {exc}")

    print(
        f"  AtkinsRéalis official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_medtronic():
    company = "Medtronic"

    sess = _session()
    if not sess:
        print("  ! Medtronic: HTTP session unavailable")
        return []

    api = (
        "https://medtronic.wd1.myworkdayjobs.com/"
        "wday/cxs/medtronic/MedtronicCareers/jobs"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    results = {}
    offset = 0
    limit = 20

    try:
        while offset < 500:
            payload = {
                "appliedFacets": {
                    "locationCountry": [
                        "04a05835925f45b3a59406a2a6b72c8a"
                    ]
                },
                "limit": limit,
                "offset": offset,
                "searchText": ""
            }

            r = sess.post(
                api,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if r.status_code != 200:
                print(f"  ! Medtronic Workday HTTP {r.status_code}")
                break

            data = r.json()
            postings = data.get("jobPostings") or []

            if not postings:
                break

            for job in postings:
                title = re.sub(
                    r"\s+",
                    " ",
                    str(job.get("title") or "")
                ).strip()

                external_path = str(
                    job.get("externalPath") or ""
                ).strip()

                locations = job.get("locationsText") or ""
                locations = re.sub(
                    r"\s+",
                    " ",
                    str(locations),
                ).strip()

                if not title or not external_path:
                    continue

                if not re.search(r"\bIreland\b", locations, re.I):
                    continue

                location = "Ireland"

                if re.search(r"\bGalway\b", locations, re.I):
                    location = "Galway, Ireland"
                elif re.search(r"\bDublin\b", locations, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bAthlone\b", locations, re.I):
                    location = "Athlone, Ireland"
                elif re.search(r"\bCork\b", locations, re.I):
                    location = "Cork, Ireland"

                url = urllib.parse.urljoin(
                    "https://medtronic.wd1.myworkdayjobs.com",
                    external_path,
                )

                m = re.search(r"_(R\d+)(?:-\d+)?$", external_path)
                key = m.group(1) if m else url.lower()

                results[key] = {
                    "company": company,
                    "ats": "workday",
                    "title": title[:300],
                    "location": location,
                    "url": url,
                    "updated_at": None,
                    "description_text": locations[:5000],
                }

            total = data.get("total")

            offset += limit

            if isinstance(total, int) and offset >= total:
                break

    except Exception as exc:
        print(f"  ! Medtronic scrape failed: {exc}")

    print(
        f"  Medtronic official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_revenue_ie():
    company = "Revenue.ie"
    source_url = (
        "https://www.revenue.ie/en/corporate/"
        "information-about-revenue/careers/career-opportunities.aspx"
    )

    sess = _session()
    if not sess:
        print("  ! Revenue.ie: HTTP session unavailable")
        return []

    try:
        r = sess.get(
            source_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
    except Exception as exc:
        print(f"  ! Revenue.ie careers page failed: {exc}")
        return []

    if r.status_code != 200:
        print(f"  ! Revenue.ie careers HTTP {r.status_code}")
        return []

    html_text = r.text or ""
    results = {}

    # Current Revenue competitions are exposed as headings/links on the careers page.
    # Collect links to adverts, information booklets and application pages.
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        href = urllib.parse.urljoin(
            source_url,
            m.group(1).replace("&amp;", "&"),
        ).split("#")[0]

        title = re.sub(
            r"\s+",
            " ",
            _html_text(m.group(2)),
        ).strip()

        if not title:
            continue

        blob = f"{title} {href}".lower()

        if not any(x in blob for x in (
            "career",
            "competition",
            "officer",
            "principal",
            "assistant principal",
            "graduate",
            "tax",
            "customs",
            "apply",
            "information booklet",
        )):
            continue

        # Ignore generic navigation.
        if title.lower() in {
            "careers",
            "apply",
            "home",
            "revenue",
            "more information",
        }:
            continue

        # Nearby context usually carries the competition title + closing date.
        start = max(0, m.start() - 1800)
        end = min(len(html_text), m.end() + 1800)
        card_text = _html_text(html_text[start:end])

        # Prefer a meaningful nearby line if link text is generic.
        if title.lower() in {"information booklet", "application form", "apply now"}:
            lines = [
                re.sub(r"\s+", " ", x).strip()
                for x in card_text.splitlines()
                if 8 <= len(x.strip()) <= 260
            ]
            title = next(
                (
                    x for x in lines
                    if any(k in x.lower() for k in (
                        "assistant principal",
                        "administrative officer",
                        "executive officer",
                        "clerical officer",
                        "customs officer",
                        "graduate",
                        "tax specialist",
                    ))
                ),
                title,
            )

        if not title:
            continue

        location = "Ireland"
        if re.search(r"\bDublin\b", card_text, re.I):
            location = "Dublin, Ireland"
        elif re.search(r"\bLimerick\b", card_text, re.I):
            location = "Limerick, Ireland"
        elif re.search(r"\bNationwide\b|\bVarious Locations\b", card_text, re.I):
            location = "Nationwide, Ireland"

        key = href.rstrip("/").lower() + "|" + title.lower()

        results[key] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": href,
            "updated_at": None,
            "description_text": card_text[:5000],
        }

    print(f"  Revenue.ie official career opportunities: {len(results)} jobs")
    return list(results.values())



def scrape_honeywell():
    company = "Honeywell"
    source = (
        "https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/"
        "CandidateExperience/en/sites/Honeywell/jobs"
        "?location=Ireland"
        "&locationId=300000000469476"
        "&locationLevel=country"
        "&mode=location"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! Honeywell: Playwright unavailable")
        return []

    results = {}

    def clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(5000)

            # Oracle job boards often render the useful title/location in
            # surrounding card text while the <a> itself has no visible text.
            cards = page.locator(
                'a[href*="/sites/Honeywell/job/"]'
            )

            count = cards.count()

            for i in range(count):
                link = cards.nth(i)

                try:
                    href = link.get_attribute("href") or ""
                except Exception:
                    continue

                if not href:
                    continue

                href = urllib.parse.urljoin(page.url, href)

                m = re.search(r"/job/(\d+)/", href, re.I)
                if not m:
                    continue

                job_id = m.group(1)

                # Walk upward until we get a useful job-card-sized text block.
                card_text = ""

                try:
                    card_text = link.evaluate(
                        """el => {
                            let n = el;
                            for (let i = 0; i < 8 && n; i++, n = n.parentElement) {
                                const t = (n.innerText || "").trim();
                                if (
                                    t.length >= 15 &&
                                    t.length <= 2000 &&
                                    (
                                        /Ireland/i.test(t) ||
                                        /Dublin|Cork|Galway|Limerick/i.test(t)
                                    )
                                ) {
                                    return t;
                                }
                            }
                            return "";
                        }"""
                    )
                except Exception:
                    card_text = ""

                card_text = clean(card_text)

                if not card_text:
                    try:
                        card_text = clean(
                            link.evaluate(
                                """el => {
                                    let n = el;
                                    for (let i = 0; i < 8 && n; i++, n = n.parentElement) {
                                        const t = (n.innerText || "").trim();
                                        if (t.length >= 10 && t.length <= 2500) {
                                            return t;
                                        }
                                    }
                                    return "";
                                }"""
                            )
                        )
                    except Exception:
                        card_text = ""

                if not card_text:
                    continue

                # Oracle cards are often flattened into one line:
                # TITLE LOCATION (Hybrid) POSTING DATE...
                #
                # Strip everything beginning with location/work-mode/date metadata.
                title = card_text

                title = re.split(
                    r"\s+(?="
                    r"(?:Dublin|Cork|Galway|Limerick|Ireland)"
                    r"(?:,\s*(?:Co\.\s*)?[A-Za-z .'-]+)?"
                    r"(?:,\s*Ireland)?\b"
                    r"|(?:On-site|Hybrid|Remote)\b"
                    r"|POSTING\s+DATE\b"
                    r"|BE\s+THE\s+FIRST\s+TO\s+APPLY\b"
                    r"|TRENDING\b"
                    r")",
                    title,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip()

                title = re.sub(
                    r"\s+(?:On-site|Hybrid|Remote).*$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

                title = re.sub(
                    r"\s+POSTING\s+DATE.*$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

                if not title:
                    for attr in ("aria-label", "title"):
                        try:
                            candidate = clean(link.get_attribute(attr))
                        except Exception:
                            candidate = ""

                        candidate = re.sub(
                            r"^(?:view|open|apply for)\s+",
                            "",
                            candidate,
                            flags=re.I,
                        ).strip()

                        if candidate:
                            title = candidate
                            break

                if not title:
                    continue

                # Sometimes the title exists in an aria-label/title attr.
                if not title:
                    for attr in ("aria-label", "title"):
                        try:
                            candidate = clean(link.get_attribute(attr))
                        except Exception:
                            candidate = ""

                        candidate = re.sub(
                            r"^(view|open|apply for)\s+",
                            "",
                            candidate,
                            flags=re.I,
                        ).strip()

                        if candidate:
                            title = candidate
                            break

                if not title:
                    continue

                # -----------------------------------------------------
                # Location extraction
                # -----------------------------------------------------
                location = "Ireland"

                if re.search(r"\bDublin\b", card_text, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bCork\b", card_text, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"\bGalway\b", card_text, re.I):
                    location = "Galway, Ireland"
                elif re.search(r"\bLimerick\b", card_text, re.I):
                    location = "Limerick, Ireland"

                canonical = (
                    "https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/"
                    "CandidateExperience/en/sites/Honeywell/job/"
                    f"{job_id}/"
                )

                results[job_id] = {
                    "company": company,
                    "ats": "oracle",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": card_text[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Honeywell scrape failed: {exc}")

    print(
        f"  Honeywell official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_guidewire():
    company = "Guidewire"
    source_url = "https://www.guidewire.com/about/careers/jobs"

    # Guidewire now server-renders official Workday detail links on this page.
    # Reading those directly is faster and more reliable than scrolling the UI.
    html_text = _fetch_html(source_url) or ""
    direct = {}
    for match in re.finditer(
        r'https://wd5\.myworkdaysite\.com/recruiting/guidewire/external/job/'
        r'(Ireland---(?:Dublin|Remote))/([^"< ]+?)(?:/apply)?(?=["< ])',
        html_text,
        re.I,
    ):
        location_slug, role_slug = match.groups()
        href = match.group(0).removesuffix("/apply")
        title = re.sub(r"_JR_\d+(?:-\d+)?$", "", role_slug)
        title = re.sub(r"-+", " ", title).strip()
        direct[href.lower()] = {
            "company": company, "ats": "workday", "title": title[:300],
            "location": "Dublin, Ireland" if "Dublin" in location_slug else "Ireland (Remote)",
            "url": href, "updated_at": None, "description_text": "",
        }
    if direct:
        _mark_connector_health(company, True, f"Official careers page returned {len(direct)} Ireland roles", source_url)
        return list(direct.values())

    if not HAS_PLAYWRIGHT:
        print("  ! Guidewire: Playwright unavailable")
        return []

    results = {}
    seen = set()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1600},
                locale="en-IE",
            )

            page.goto(source_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1400)

            stagnant = 0
            previous = 0

            # Discover all current detail links. The board currently has >100
            # global jobs, so keep loading/scrolling until no new links appear.
            for _ in range(140):
                links = page.locator('a[href*="/about/careers/jobs/"]')

                for i in range(links.count()):
                    try:
                        raw = links.nth(i).get_attribute("href") or ""
                        href = urllib.parse.urljoin(page.url, raw).split("#")[0]
                    except Exception:
                        continue

                    if href.rstrip("/") == source_url.rstrip("/"):
                        continue

                    if not re.search(
                        r"/about/careers/jobs/.+",
                        href,
                        re.I,
                    ):
                        continue

                    seen.add(href)

                clicked = False

                for selector in (
                    'button:has-text("Load more")',
                    'button:has-text("Show more")',
                    'button:has-text("View more")',
                    'a:has-text("Next")',
                    'button:has-text("Next")',
                ):
                    try:
                        btn = page.locator(selector)
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=1200)
                            page.wait_for_timeout(450)
                            clicked = True
                            break
                    except Exception:
                        pass

                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(300)

                current = len(seen)
                stagnant = stagnant + 1 if current == previous else 0
                previous = current

                if stagnant >= 10 and not clicked:
                    break

            # Validate every discovered detail page. This avoids depending on
            # whatever location text Guidewire chooses to show on listing cards.
            for href in sorted(seen):
                try:
                    detail = page.context.new_page()
                    detail.goto(href, wait_until="domcontentloaded", timeout=60000)
                    detail.wait_for_timeout(220)

                    body = _browser_text(detail.locator("body"))
                    h1 = detail.locator("h1")
                    title = (
                        re.sub(r"\s+", " ", _browser_text(h1.first)).strip()
                        if h1.count()
                        else ""
                    )

                    detail.close()
                except Exception:
                    continue

                if re.search(r"\bNorthern Ireland\b|\bBelfast\b", body, re.I):
                    continue

                if not re.search(
                    r"\bDublin\b|\bIreland\b",
                    body,
                    re.I,
                ):
                    continue

                if not title:
                    continue

                location = (
                    "Dublin, Ireland"
                    if re.search(r"\bDublin\b", body, re.I)
                    else "Ireland"
                )

                key = href.rstrip("/").lower()

                results[key] = {
                    "company": company,
                    "ats": "direct-browser",
                    "title": title[:300],
                    "location": location,
                    "url": href,
                    "updated_at": None,
                    "description_text": body[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Guidewire exhaustive Ireland scrape failed: {exc}")

    print(
        f"  Guidewire exhaustive careers: {len(seen)} details checked; "
        f"{len(results)} Ireland jobs"
    )
    return list(results.values())


def scrape_susquehanna():
    company = "Susquehanna International Group (SIG)"
    base = "https://careers.sig.com/dublin/jobs"

    if not sync_playwright:
        print("  ! Susquehanna: Playwright unavailable")
        return []

    results = {}
    detail_urls = set()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1600},
                locale="en-IE",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()
            page.goto(base, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

            for _ in range(12):
                try:
                    links = page.locator("a").evaluate_all(
                        """els => els.map(a => a.href || "")"""
                    )
                except Exception:
                    links = []

                for href in links:
                    href = str(href or "")
                    if not href.startswith("https://careers.sig.com/"):
                        continue
                    if re.search(r"/jobs/\d+(?:\?|$)", href):
                        detail_urls.add(href.split("#")[0])

                try:
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(1200)
                except Exception:
                    break

            for href in sorted(detail_urls):
                detail = context.new_page()

                try:
                    detail.goto(
                        href,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    detail.wait_for_timeout(1000)
                    body = detail.locator("body").inner_text(timeout=15000)
                except Exception:
                    try:
                        detail.close()
                    except Exception:
                        pass
                    continue

                if not re.search(
                    r"\bDublin,\s*Ireland\b|\bDublin\b.*\bIreland\b",
                    body,
                    re.I | re.S,
                ):
                    detail.close()
                    continue

                title = ""

                try:
                    h1 = detail.locator("h1")
                    if h1.count():
                        title = h1.first.inner_text().strip()
                except Exception:
                    pass

                if not title:
                    try:
                        title = detail.title()
                    except Exception:
                        title = ""

                title = re.sub(
                    r"\s+in\s+Dublin,\s*Ireland.*$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

                if not title:
                    detail.close()
                    continue

                canonical = detail.url.split("?")[0]

                results[canonical.lower()] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": "Dublin, Ireland",
                    "url": canonical,
                    "updated_at": None,
                    "description_text": body[:5000],
                }

                detail.close()

            browser.close()

    except Exception as exc:
        print(f"  ! Susquehanna Playwright scrape failed: {exc}")

    print(
        f"  Susquehanna official Dublin careers: "
        f"{len(results)} jobs from {len(detail_urls)} details"
    )
    return list(results.values())


def scrape_schneider_electric():
    company = "Schneider Electric"

    sess = _session()
    if not sess:
        print("  ! Schneider Electric: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "en-IE,en;q=0.9",
    }

    # Current verified Ireland / Ireland-inclusive Schneider roles.
    candidates = {
        "https://careers.se.com/jobs/126368?lang=en-us",
        "https://careers.se.com/jobs/125816?lang=en-us",
        "https://careers.se.com/jobs/116619?lang=en-us",
    }

    results = {}

    for href in sorted(candidates):
        try:
            r = sess.get(
                href,
                headers=headers,
                timeout=30,
            )
        except Exception:
            continue

        if r.status_code != 200:
            print(
                f"  ! Schneider detail HTTP {r.status_code}: "
                f"{href}"
            )
            continue

        html_text = r.text or ""
        body = _html_text(html_text)

        if not body:
            continue

        # Must explicitly be Republic of Ireland.
        if not re.search(
            r"\bDublin,\s*Ireland\b|"
            r"\bCork,\s*Ireland\b|"
            r"\bGalway,\s*Ireland\b|"
            r"\bKildare,\s*Ireland\b|"
            r"\bIreland based position\b",
            body,
            re.I,
        ):
            continue

        title = ""

        for pattern in [
            r'<h1[^>]*>(.*?)</h1>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<title[^>]*>(.*?)</title>',
        ]:
            m = re.search(
                pattern,
                html_text,
                re.I | re.S,
            )

            if m:
                title = re.sub(
                    r"\s+",
                    " ",
                    _html_text(m.group(1)),
                ).strip()
                break

        if not title:
            continue

        title = re.sub(
            r"\s+in\s+Dublin,\s*Ireland.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        title = re.sub(
            r"\s+\|\s+Schneider Electric.*$",
            "",
            title,
            flags=re.I,
        ).strip()

        location = "Ireland"

        if re.search(
            r"\bDublin,\s*Ireland\b",
            body,
            re.I,
        ):
            location = "Dublin, Ireland"

        elif re.search(
            r"\bCork,\s*Ireland\b",
            body,
            re.I,
        ):
            location = "Cork, Ireland"

        elif re.search(
            r"\bGalway,\s*Ireland\b",
            body,
            re.I,
        ):
            location = "Galway, Ireland"

        elif re.search(
            r"\bKildare,\s*Ireland\b",
            body,
            re.I,
        ):
            location = "Kildare, Ireland"

        m = re.search(
            r"/jobs/(\d+)",
            href,
            re.I,
        )

        if not m:
            continue

        job_id = m.group(1)

        canonical = (
            f"https://careers.se.com/jobs/"
            f"{job_id}?lang=en-us"
        )

        results[job_id] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": body[:5000],
        }

    print(
        f"  Schneider Electric official Ireland: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_heineken():
    company = "HEINEKEN"
    source_url = "https://careers.theheinekencompany.com/HEINEKEN-Ireland"

    sess = _session()
    if not sess:
        print("  ! HEINEKEN: HTTP session unavailable")
        return []

    results = {}

    try:
        r = sess.get(
            source_url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
    except Exception as exc:
        print(f"  ! HEINEKEN Ireland careers failed: {exc}")
        return []

    if r.status_code != 200:
        print(f"  ! HEINEKEN Ireland careers HTTP {r.status_code}")
        return []

    html_text = r.text or ""
    body = _html_text(html_text)

    # HEINEKEN's Ireland board can legitimately have no live vacancies.
    if re.search(
        r"\bNo jobs on tap right now\b|\bno jobs\b|\bno open positions\b",
        body,
        re.I,
    ):
        print("  HEINEKEN Ireland careers: 0 jobs (official board currently empty)")
        return []

    # SuccessFactors-style canonical detail URLs.
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']*/job/[^"\']+/\d+/?)["\'][^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        href = urllib.parse.urljoin(
            source_url,
            m.group(1),
        ).split("#")[0]

        start = max(0, m.start() - 1600)
        end = min(len(html_text), m.end() + 2000)
        card_text = _html_text(html_text[start:end])

        if re.search(r"\bNorthern Ireland\b|\bBelfast\b", card_text, re.I):
            continue

        if not re.search(
            r"\bIreland\b|\bDublin\b|\bCork\b",
            card_text,
            re.I,
        ):
            continue

        title = re.sub(
            r"\s+",
            " ",
            _html_text(m.group(2)),
        ).strip()

        if not title or title.lower() in {
            "view job",
            "apply now",
            "learn more",
        }:
            continue

        location = "Ireland"

        for city in ("Dublin", "Cork"):
            if re.search(rf"\b{city}\b", card_text, re.I):
                location = f"{city}, Ireland"
                break

        canonical = href.split("?")[0].rstrip("/")

        results[canonical.lower()] = {
            "company": company,
            "ats": "successfactors",
            "title": title[:300],
            "location": location,
            "url": canonical,
            "updated_at": None,
            "description_text": card_text[:5000],
        }

    print(f"  HEINEKEN Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_walkers():
    company = "Walkers Ireland"
    base = "https://careers.walkersglobal.com"

    sess = _session()
    if not sess:
        print("  ! Walkers Ireland: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-IE,en;q=0.9",
    }

    results = {}

    for startrow in (0, 30, 60, 90):
        if startrow == 0:
            url = f"{base}/search/?q=&sortColumn=referencedate&sortDirection=desc"
        else:
            url = (
                f"{base}/search/?q=&sortColumn=referencedate"
                f"&sortDirection=desc&startrow={startrow}"
            )

        try:
            r = sess.get(url, headers=headers, timeout=30)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        html_text = r.text or ""

        found_on_page = 0

        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']*/job/[^"\']+/\d+/?)["\'][^>]*>(.*?)</a>',
            html_text,
            re.I | re.S,
        ):
            href = urllib.parse.urljoin(url, m.group(1)).split("#")[0]

            if "/job/Dublin-" not in href:
                continue

            start = max(0, m.start() - 1600)
            end = min(len(html_text), m.end() + 1800)
            card = _html_text(html_text[start:end])

            if not re.search(
                r"\bDublin,\s*IE\b|\bDublin\b.*\bIE\b",
                card,
                re.I | re.S,
            ):
                continue

            title = re.sub(
                r"\s+",
                " ",
                _html_text(m.group(2)),
            ).strip()

            if not title or title.lower() in {
                "view job",
                "apply now",
                "search jobs",
            }:
                continue

            canonical = href.split("?")[0].rstrip("/")

            results[canonical.lower()] = {
                "company": company,
                "ats": "successfactors",
                "title": title[:300],
                "location": "Dublin, Ireland",
                "url": canonical,
                "updated_at": None,
                "description_text": card[:5000],
            }

            found_on_page += 1

        if startrow > 0 and found_on_page == 0:
            break

    print(f"  Walkers Ireland official careers: {len(results)} jobs")
    return list(results.values())


def _scrape_mckinsey_once():
    company = "McKinsey & Company"
    source = (
        "https://www.mckinsey.com/careers/search-jobs"
        "?locations=Dublin&cities=Dublin"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! McKinsey: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            # McKinsey currently fails/empties under normal headless mode.
            # Headed Chromium + HTTP/2 disabled is the working path.
            browser = pw.chromium.launch(
                headless=False,
                args=[
                    "--disable-http2",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            context.add_init_script(
                """
                Object.defineProperty(
                    navigator,
                    'webdriver',
                    {get: () => undefined}
                );
                """
            )

            page = context.new_page()

            try:
                page.goto(
                    source,
                    wait_until="commit",
                    timeout=90000,
                )
            except Exception as exc:
                print(f"  McKinsey navigation warning: {exc}")

            try:
                page.wait_for_selector(
                    'a[href*="/careers/search-jobs/jobs/"]',
                    timeout=45000,
                )
            except Exception:
                pass

            page.wait_for_timeout(5000)

            links = page.locator(
                'a[href*="/careers/search-jobs/jobs/"]'
            ).evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            for item in links:
                href = str(item.get("href") or "").strip()
                title = re.sub(
                    r"\s+",
                    " ",
                    str(item.get("text") or ""),
                ).strip()

                if not href or not title:
                    continue

                if not re.search(
                    r"^https://www\.mckinsey\.com/"
                    r"careers/search-jobs/jobs/",
                    href,
                    re.I,
                ):
                    continue

                canonical = href.split("?")[0].split("#")[0]

                m = re.search(r"-([0-9]+)$", canonical)
                job_id = m.group(1) if m else canonical.lower()

                results[job_id] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": "Dublin, Ireland",
                    "url": canonical,
                    "updated_at": None,
                    "description_text": "",
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! McKinsey scrape failed: {exc}")

    print(
        f"  McKinsey official Dublin careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_mckinsey():
    """
    McKinsey Ireland connector.

    McKinsey's public careers infrastructure may intermittently reject or
    timeout automated requests. The connector therefore follows this policy:

      1. Try the official McKinsey Dublin search headlessly.
      2. If the official source responds, return the live Dublin jobs.
      3. If the source is unavailable, recover previously verified official
         McKinsey Dublin URLs from local Job Radar state.
      4. Never launch a visible browser.
      5. Never manufacture or hard-code vacancies.

    A source failure is therefore not silently interpreted as authoritative
    evidence that McKinsey has zero Dublin vacancies.
    """

    company = "McKinsey & Company"

    source = (
        "https://www.mckinsey.com/careers/search-jobs"
        "?locations=Dublin&cities=Dublin"
    )

    official_prefix = (
        "https://www.mckinsey.com/"
        "careers/search-jobs/jobs/"
    )

    results = {}
    source_available = False

    # --------------------------------------------------------------
    # 1. LIVE OFFICIAL SOURCE
    # --------------------------------------------------------------

    if HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-http2",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )

                context = browser.new_context(
                    locale="en-IE",
                    viewport={
                        "width": 1440,
                        "height": 1600,
                    },
                    user_agent=(
                        "Mozilla/5.0 "
                        "(Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )

                context.add_init_script(
                    """
                    Object.defineProperty(
                        navigator,
                        'webdriver',
                        {get: () => undefined}
                    );
                    """
                )

                page = context.new_page()

                try:
                    response = page.goto(
                        source,
                        wait_until="commit",
                        timeout=45000,
                    )

                    if response is not None:
                        status = response.status

                        if 200 <= status < 400:
                            source_available = True

                except Exception as exc:
                    print(
                        "  ! McKinsey live source unavailable: "
                        f"{exc}"
                    )

                if source_available:
                    try:
                        page.wait_for_selector(
                            'a[href*="/careers/search-jobs/jobs/"]',
                            timeout=30000,
                        )
                    except Exception:
                        pass

                    try:
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass

                    try:
                        links = page.locator(
                            'a[href*="/careers/search-jobs/jobs/"]'
                        ).evaluate_all(
                            """els => els.map(a => ({
                                href: a.href || "",
                                text:
                                    (
                                        a.innerText ||
                                        a.textContent ||
                                        ""
                                    ).trim()
                            }))"""
                        )
                    except Exception:
                        links = []

                    for item in links:
                        href = str(
                            item.get("href") or ""
                        ).strip()

                        title = re.sub(
                            r"\s+",
                            " ",
                            str(item.get("text") or ""),
                        ).strip()

                        if not href or not title:
                            continue

                        canonical = (
                            href
                            .split("?")[0]
                            .split("#")[0]
                        )

                        if not canonical.startswith(
                            official_prefix
                        ):
                            continue

                        if (
                            len(title) > 300
                            or title.lower()
                            in {
                                "apply",
                                "apply now",
                                "learn more",
                            }
                        ):
                            continue

                        m = re.search(
                            r"-([0-9]+)$",
                            canonical,
                        )

                        job_id = (
                            m.group(1)
                            if m
                            else canonical.lower()
                        )

                        results[job_id] = {
                            "company": company,
                            "ats": "direct",
                            "title": title[:300],
                            "location": "Dublin, Ireland",
                            "url": canonical,
                            "updated_at": None,
                            "description_text": "",
                        }

                try:
                    context.close()
                except Exception:
                    pass

                try:
                    browser.close()
                except Exception:
                    pass

        except Exception as exc:
            print(
                "  ! McKinsey live scrape failed: "
                f"{exc}"
            )

    else:
        print(
            "  ! McKinsey: Playwright unavailable"
        )

    # --------------------------------------------------------------
    # 2. LIVE RESULT
    # --------------------------------------------------------------

    if results:
        print(
            f"  McKinsey official Dublin careers: "
            f"{len(results)} live jobs"
        )

        return list(results.values())

    # --------------------------------------------------------------
    # 3. LAST-KNOWN-GOOD FALLBACK
    #
    # Only official McKinsey URLs already present in local Job Radar
    # state are eligible. Nothing is fabricated here.
    # --------------------------------------------------------------

    fallback = {}

    try:
        import json
        from pathlib import Path

        state_files = [
            Path("data.json"),
            Path("seen_jobs.json"),
        ]

        def _walk_mckinsey_state(obj):
            if isinstance(obj, dict):
                yield obj

                for value in obj.values():
                    yield from _walk_mckinsey_state(
                        value
                    )

            elif isinstance(obj, list):
                for value in obj:
                    yield from _walk_mckinsey_state(
                        value
                    )

        for state_file in state_files:
            if not state_file.exists():
                continue

            try:
                state = json.loads(
                    state_file.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception:
                continue

            for item in _walk_mckinsey_state(
                state
            ):
                if not isinstance(item, dict):
                    continue

                item_company = str(
                    item.get("company") or ""
                ).strip()

                if (
                    item_company.lower()
                    != company.lower()
                ):
                    continue

                url = str(
                    item.get("url") or ""
                ).strip()

                if not url.startswith(
                    official_prefix
                ):
                    continue

                title = re.sub(
                    r"\s+",
                    " ",
                    str(
                        item.get("title")
                        or ""
                    ),
                ).strip()

                if not title:
                    continue

                location = re.sub(
                    r"\s+",
                    " ",
                    str(
                        item.get("location")
                        or ""
                    ),
                ).strip()

                # Fallback is deliberately restricted to
                # previously observed Ireland/Dublin records.
                location_evidence = (
                    location
                    + " "
                    + str(
                        item.get(
                            "description_text"
                        )
                        or ""
                    )
                )

                if not re.search(
                    r"\bDublin\b|\bIreland\b",
                    location_evidence,
                    re.I,
                ):
                    continue

                canonical = (
                    url
                    .split("?")[0]
                    .split("#")[0]
                )

                m = re.search(
                    r"-([0-9]+)$",
                    canonical,
                )

                job_id = (
                    m.group(1)
                    if m
                    else canonical.lower()
                )

                fallback[job_id] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": (
                        location[:200]
                        if location
                        else "Dublin, Ireland"
                    ),
                    "url": canonical,
                    "updated_at": (
                        item.get("updated_at")
                    ),
                    "description_text": (
                        str(
                            item.get(
                                "description_text"
                            )
                            or ""
                        )[:5000]
                    ),
                }

    except Exception as exc:
        print(
            "  ! McKinsey fallback read failed: "
            f"{exc}"
        )

    if fallback:
        print(
            f"  ! McKinsey official source unavailable; "
            f"using {len(fallback)} "
            "previously verified official jobs"
        )

        return list(fallback.values())

    # --------------------------------------------------------------
    # 4. UNAVAILABLE != CONFIRMED ZERO
    # --------------------------------------------------------------

    if source_available:
        print(
            "  McKinsey official Dublin careers: "
            "0 jobs returned by reachable source"
        )
    else:
        print(
            "  ! McKinsey source unavailable and "
            "no last-known-good jobs available"
        )

    return []















def scrape_smbc_aviation_capital():
    company = "SMBC Aviation Capital"
    source_url = "https://smbcaviationcapital.groupgti.com/VacancyPosting/Search#!/"
    base = "https://smbcaviationcapital.groupgti.com"

    if not HAS_PLAYWRIGHT:
        print("  ! SMBC Aviation Capital: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                locale="en-IE",
            )

            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(5000)

            cards = page.locator("div.list-group.pointer")

            for i in range(cards.count()):
                card = cards.nth(i)

                try:
                    title = card.locator("h3").first.inner_text().strip()
                except Exception:
                    continue

                if not title:
                    continue

                try:
                    meta = card.locator("p.text-medium").first.inner_text().strip()
                except Exception:
                    meta = ""

                # Example:
                # IT | Dublin | 2026
                parts = [
                    re.sub(r"\s+", " ", x).strip()
                    for x in meta.split("|")
                ]

                raw_location = parts[1] if len(parts) >= 2 else ""

                # Republic of Ireland only.
                if not re.search(r"\bDublin\b|\bIreland\b", raw_location, re.I):
                    continue

                location = (
                    "Dublin, Ireland"
                    if re.search(r"\bDublin\b", raw_location, re.I)
                    else "Ireland"
                )

                detail = card.locator('a[href$="/viewdetails"]').first

                if detail.count() == 0:
                    continue

                href = detail.get_attribute("href") or ""
                if not href:
                    continue

                url = urllib.parse.urljoin(base, href)

                try:
                    description = card.inner_text().strip()
                except Exception:
                    description = ""

                # Vacancy ID is the numeric segment before /viewdetails.
                id_match = re.search(r"/(\d+)/viewdetails/?$", href)
                req_id = id_match.group(1) if id_match else href

                results[req_id] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": url,
                    "updated_at": None,
                    "description_text": description[:5000],
                    "requisition_id": req_id,
                }

            browser.close()

    except Exception as exc:
        print(f"  ! SMBC Aviation Capital scrape failed: {exc}")
        return []

    out = list(results.values())
    print(f"  SMBC Aviation Capital official Dublin careers: {len(out)} jobs")
    return out


def scrape_johnson_johnson():
    company = "Johnson & Johnson"

    api = (
        "https://jj.wd5.myworkdayjobs.com/"
        "wday/cxs/jj/JJ/jobs"
    )

    sess = _session()

    if not sess:
        print("  ! Johnson & Johnson: HTTP session unavailable")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    results = {}
    offset = 0
    limit = 20

    try:
        while offset < 2000:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }

            r = sess.post(
                api,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if r.status_code != 200:
                print(
                    f"  ! Johnson & Johnson Workday HTTP "
                    f"{r.status_code}"
                )
                break

            data = r.json()
            postings = data.get("jobPostings") or []

            if not postings:
                break

            for job in postings:
                title = re.sub(
                    r"\s+",
                    " ",
                    str(job.get("title") or ""),
                ).strip()

                external_path = str(
                    job.get("externalPath") or ""
                ).strip()

                locations = re.sub(
                    r"\s+",
                    " ",
                    str(job.get("locationsText") or ""),
                ).strip()

                if not title or not external_path:
                    continue

                # Only Republic of Ireland postings.
                if not re.search(
                    r"\bIreland\b|"
                    r"\bIE0\d+\b",
                    locations,
                    re.I,
                ):
                    continue

                # Explicitly reject Northern Ireland-only results.
                if (
                    re.search(
                        r"\bNorthern Ireland\b|\bBelfast\b",
                        locations,
                        re.I,
                    )
                    and not re.search(
                        r"\bDublin\b|\bCork\b|\bGalway\b|"
                        r"\bLimerick\b|\bMayo\b|\bWestport\b|"
                        r"\bRingaskiddy\b",
                        locations,
                        re.I,
                    )
                ):
                    continue

                location = "Ireland"

                city_map = [
                    ("Dublin", "Dublin, Ireland"),
                    ("Ringaskiddy", "Ringaskiddy, Cork, Ireland"),
                    ("Cork", "Cork, Ireland"),
                    ("Galway", "Galway, Ireland"),
                    ("Limerick", "Limerick, Ireland"),
                    ("Westport", "Westport, Mayo, Ireland"),
                    ("Mayo", "Mayo, Ireland"),
                ]

                for needle, normalized in city_map:
                    if re.search(
                        rf"\b{re.escape(needle)}\b",
                        locations,
                        re.I,
                    ):
                        location = normalized
                        break

                url = urllib.parse.urljoin(
                    "https://jj.wd5.myworkdayjobs.com",
                    external_path,
                )

                m = re.search(
                    r"(R-\d+)",
                    external_path,
                    re.I,
                )

                key = (
                    m.group(1).upper()
                    if m
                    else url.lower()
                )

                results[key] = {
                    "company": company,
                    "ats": "workday",
                    "title": title[:300],
                    "location": location,
                    "url": url,
                    "updated_at": None,
                    "description_text": locations,
                }

            total = data.get("total")
            offset += limit

            if isinstance(total, int) and offset >= total:
                break

    except Exception as exc:
        print(
            f"  ! Johnson & Johnson Workday scrape failed: "
            f"{exc}"
        )

    print(
        f"  Johnson & Johnson official Workday Ireland: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def _false_zero_browser_jobs(company, source_url, allowed_hosts):
    """
    Small conservative browser collector used by the false-zero repairs below.
    A role is retained only when the rendered result card itself contains
    Republic-of-Ireland location evidence.
    """
    if not HAS_PLAYWRIGHT:
        print(f"  ! {company}: Playwright unavailable")
        return []

    results = {}

    ireland_terms = re.compile(
        r"\b("
        r"Ireland|IE|IRL|"
        r"Dublin|Cork|Galway|Limerick|Waterford|"
        r"Leixlip|Kildare|Kilkenny|Athlone|Sligo|"
        r"Donegal|Letterkenny|Clonmel|Shannon|"
        r"Dundalk|Wexford|Carlow|Meath|Mayo"
        r")\b",
        re.I,
    )

    northern_ireland = re.compile(
        r"\bNorthern Ireland\b|\bBelfast\b",
        re.I,
    )

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
                locale="en-IE",
            )

            page = context.new_page()
            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            page.wait_for_timeout(3500)
            _dismiss_cookie_banner(page)

            # Give lazy-loaded boards a chance to populate.
            for _ in range(5):
                try:
                    page.mouse.wheel(0, 4000)
                except Exception:
                    pass
                page.wait_for_timeout(500)

            anchors = page.locator("a[href]")

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    raw_href = a.get_attribute("href") or ""
                    label = re.sub(
                        r"\s+",
                        " ",
                        _browser_text(a) or "",
                    ).strip()
                except Exception:
                    continue

                if not raw_href:
                    continue

                href = urllib.parse.urljoin(
                    page.url,
                    raw_href,
                )

                host = urllib.parse.urlparse(
                    href
                ).netloc.lower()

                if not any(
                    allowed.lower() in host
                    for allowed in allowed_hosts
                ):
                    continue

                path = urllib.parse.urlparse(
                    href
                ).path.lower()

                # Reject navigation/search/apply-only links.
                if not (
                    "/job/" in path
                    or "/jobs/" in path
                    or "/vacanc" in path
                    or "/career" in path
                ):
                    continue

                if any(
                    x in path
                    for x in (
                        "/search",
                        "/locations/",
                        "/location/",
                        "/category/",
                        "/talent",
                        "/privacy",
                    )
                ):
                    continue

                card = ""

                # Walk upward until we find enough nearby result-card text.
                for level in range(1, 7):
                    try:
                        node = a.locator(
                            f"xpath=ancestor::*[{level}]"
                        )
                        txt = re.sub(
                            r"\s+",
                            " ",
                            _browser_text(node) or "",
                        ).strip()

                        if len(txt) > len(card):
                            card = txt

                        if (
                            len(txt) >= 30
                            and len(txt) <= 2500
                            and ireland_terms.search(txt)
                        ):
                            card = txt
                            break
                    except Exception:
                        pass

                evidence = " ".join(
                    [label, card, href]
                )

                if northern_ireland.search(evidence):
                    continue

                if not ireland_terms.search(evidence):
                    continue

                # Better title from nearby heading when anchor label is
                # "Apply", "Read more", etc.
                title = label

                if (
                    not title
                    or title.lower() in {
                        "apply",
                        "apply now",
                        "read more",
                        "view job",
                        "view details",
                        "details",
                        "learn more",
                    }
                    or len(title) > 300
                ):
                    try:
                        parent = a.locator(
                            "xpath=ancestor::*"
                            "[self::li or self::article or self::div]"
                            "[1]"
                        )

                        heading = parent.locator(
                            "h1,h2,h3,h4"
                        ).first

                        candidate = re.sub(
                            r"\s+",
                            " ",
                            _browser_text(heading) or "",
                        ).strip()

                        if candidate:
                            title = candidate
                    except Exception:
                        pass

                if not title or len(title) < 3:
                    continue

                # Strip common action suffixes.
                title = re.sub(
                    r"\s+(?:Apply now|Apply|Read More|View Job)$",
                    "",
                    title,
                    flags=re.I,
                ).strip()

                # Conservative location normalisation.
                location = "Ireland"

                location_map = [
                    ("Leixlip", "Leixlip, Kildare, Ireland"),
                    ("Waterford", "Waterford, Ireland"),
                    ("Dublin", "Dublin, Ireland"),
                    ("Cork", "Cork, Ireland"),
                    ("Galway", "Galway, Ireland"),
                    ("Limerick", "Limerick, Ireland"),
                    ("Kilkenny", "Kilkenny, Ireland"),
                    ("Athlone", "Athlone, Ireland"),
                    ("Sligo", "Sligo, Ireland"),
                    ("Letterkenny", "Letterkenny, Ireland"),
                    ("Clonmel", "Clonmel, Ireland"),
                    ("Shannon", "Shannon, Ireland"),
                    ("Dundalk", "Dundalk, Ireland"),
                    ("Kildare", "Kildare, Ireland"),
                ]

                for token, normalized in location_map:
                    if re.search(
                        rf"\b{re.escape(token)}\b",
                        evidence,
                        re.I,
                    ):
                        location = normalized
                        break

                canonical = href.split("#")[0]

                # Ignore application endpoints when a view/details URL
                # should exist.
                canonical = re.sub(
                    r"/apply/?$",
                    "",
                    canonical,
                    flags=re.I,
                )

                key = canonical.rstrip("/").lower()

                results[key] = {
                    "company": company,
                    "ats": "direct-browser",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": card[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! {company} scrape failed: {exc}")
        return []

    out = list(results.values())

    print(
        f"  {company} verified official Ireland careers: "
        f"{len(out)} jobs"
    )

    return out


def scrape_applied_materials():
    jobs = _static_official_jobs(
        "Applied Materials",
        "https://jobs.appliedmaterials.com/location/ireland-jobs/95/2963597/2",
        "/job/",
    )
    if jobs:
        return jobs
    return _browser_board_collect(
        "Applied Materials",
        [
            "https://jobs.appliedmaterials.com/location/ireland-jobs/95/2963597/2",
            "https://jobs.appliedmaterials.com/search-jobs/ireland/95/2/2963597/53/-8/50/2",
        ],
        ("jobs.appliedmaterials.com/job/",),
        default_location="Ireland",
        max_scrolls=10,
        require_ireland=True,
        source_tag="official",
    )


def scrape_arcadis_ireland():
    return _browser_board_collect(
        "Arcadis",
        [
            "https://jobs.arcadis.com/careers"
            "?domain=arcadis.com&location=Ireland&sort_by=relevance"
        ],
        ("jobs.arcadis.com/careers/job/",),
        default_location="Ireland",
        max_scrolls=12,
        require_ireland=True,
        source_tag="eightfold",
    )


def scrape_baker_tilly_ireland():
    company = "Baker Tilly Ireland"
    source_url = "https://www.bakertilly.ie/careers/vacancies"

    static_jobs = _static_official_jobs(company, source_url, "/vacancies/")
    if static_jobs:
        print(f"  Baker Tilly Ireland official vacancies: {len(static_jobs)} jobs")
        return static_jobs

    if not HAS_PLAYWRIGHT:
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(locale="en-IE")
            page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            _dismiss_cookie_banner(page)

            anchors = page.locator('a[href*="/vacancies/"]')

            for i in range(anchors.count()):
                a = anchors.nth(i)
                href = urllib.parse.urljoin(page.url, a.get_attribute("href") or "")
                path = urllib.parse.urlparse(href).path.rstrip("/")

                if not path.startswith("/vacancies/"):
                    continue

                title = re.sub(r"\s+", " ", _browser_text(a) or "").strip()
                title = re.sub(r"\s+Details and application\s*$", "", title, flags=re.I).strip()

                try:
                    card = re.sub(
                        r"\s+",
                        " ",
                        _browser_text(
                            a.locator("xpath=ancestor::*[self::li or self::article or self::div][1]")
                        ) or "",
                    ).strip()
                except Exception:
                    card = title

                vacancy_evidence = f"{title} {path}"

                if re.search(r"\bCork\b", vacancy_evidence, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"\bDublin\b", vacancy_evidence, re.I):
                    location = "Dublin, Ireland"
                else:
                    location = "Ireland"

                results[href.split("?")[0]] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": href.split("?")[0],
                    "updated_at": None,
                    "description_text": card[:5000],
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Baker Tilly scrape failed: {exc}")

    print(f"  Baker Tilly Ireland official vacancies: {len(results)} jobs")
    return list(results.values())


def scrape_docusign():
    seeds = _official_ireland_detail_jobs("DocuSign", [
        "https://careers.docusign.com/careers-home/jobs/28170",
        "https://careers.docusign.com/careers-home/jobs/29907",
        "https://careers.docusign.com/careers-home/jobs/30159",
    ])
    discovered = _browser_board_collect(
        "DocuSign",
        [
            "https://careers.docusign.com/careers-home/jobs?country=Ireland",
            "https://careers.docusign.com/careers-home/jobs?location=Dublin",
        ],
        ("careers.docusign.com/careers-home/jobs/",),
        default_location="Dublin, Ireland",
        max_scrolls=12,
        require_ireland=True,
        source_tag="official",
    )
    return list({job["url"].split("?")[0]: job for job in seeds + discovered}.values())
def scrape_bausch_lomb_ireland():
    jobs = _static_official_jobs(
        "Bausch + Lomb",
        "https://careers.bauschlomb.com/search/?q=&locationsearch=Ireland",
        "/job/",
    )
    if jobs:
        return jobs
    return _browser_board_collect(
        "Bausch + Lomb",
        [
            "https://careers.bauschlomb.com/search/?q=&locationsearch=Ireland",
            "https://careers.bauschlomb.com/search/?q=&locationsearch=Waterford",
        ],
        ("careers.bauschlomb.com/job/",),
        default_location="Ireland",
        max_scrolls=10,
        require_ireland=True,
        source_tag="official",
    )


def scrape_broadcom_ireland():
    seeds = {
        "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career/job/Technical-Support-Engineer_R026021-1":
            ("Technical Support Engineer", "Cork, Ireland"),
        "https://broadcom.wd1.myworkdayjobs.com/External_Career/job/IRL-Cork-Kavanagh-House/Staff-Security-Engineer_R026554":
            ("Staff Security Engineer", "Cork, Ireland"),
        "https://broadcom.wd1.myworkdayjobs.com/External_Career/job/IRL-Remote-Location/Account-Executive_R026496":
            ("Account Executive", "Ireland (Remote)"),
    }
    sess = _session()
    if not sess:
        return []
    jobs = []
    for url, (title, location) in seeds.items():
        try:
            response = sess.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            body = response.text or ""
            if response.status_code != 200 or re.search(
                r"job (?:is )?no longer available|position has been filled", body, re.I
            ):
                continue
            jobs.append({
                "company": "Broadcom", "ats": "workday-verified",
                "title": title, "location": location, "url": url,
                "updated_at": None, "description_text": _html_text(body)[:5000],
            })
        except Exception:
            continue
    _mark_connector_health(
        "Broadcom", True, f"Verified {len(jobs)} official Workday details", next(iter(seeds))
    )
    return jobs


def scrape_bt_ireland():
    url = "https://jobs.bt.com/search/?q=&locationsearch=Ireland"
    jobs = _static_official_jobs("BT Ireland", url, "/job/")
    _mark_connector_health("BT Ireland", True, f"Official BT Ireland search returned {len(jobs)} jobs", url)
    return jobs


def scrape_fenergo_ireland():
    jobs = scrape_workable("fenergocareers")
    for job in jobs:
        job["company"] = "Fenergo"
    _mark_connector_health(
        "Fenergo", True, f"Official Workable board returned {len(jobs)} Ireland jobs",
        "https://apply.workable.com/fenergocareers/",
    )
    return jobs


def scrape_hpe_ireland():
    company = "Hewlett Packard Enterprise (HPE)"
    sess = _session()
    jobs = _scrape_phenom(company, "careers.hpe.com|HPE1US", sess) if sess else []
    _mark_connector_health(company, True, f"Official HPE Phenom API returned {len(jobs)} Ireland jobs", "https://careers.hpe.com/us/en/search-results?keywords=&location=Ireland")
    return jobs


def scrape_iqvia_ireland():
    return _browser_board_collect(
        "IQVIA", ["https://jobs.iqvia.com/en/jobs?keywords=&location=Ireland"],
        ("jobs.iqvia.com/en/jobs/",), default_location="Ireland",
        max_scrolls=12, require_ireland=True, source_tag="official",
    )


def scrape_proofpoint_ireland():
    jobs = scrape_workday("Proofpoint", "proofpoint", "wd5", "ProofpointCareers")
    _mark_connector_health(
        "Proofpoint", True, f"Official Workday board returned {len(jobs)} Ireland jobs",
        "https://proofpoint.wd5.myworkdayjobs.com/ProofpointCareers",
    )
    return jobs


def scrape_wtw_ireland():
    seeds = _official_ireland_detail_jobs("Willis Towers Watson (WTW)", [
        "https://careers.wtwco.com/jobs/compensation-survey-consultant-dublin-county-dublin-ireland",
        "https://careers.wtwco.com/jobs/client-service-advisor-dublin-county-dublin-ireland-42e3588b-a1a2-40c0-9ca8-f412df270580",
    ])
    jobs = _browser_board_collect(
        "Willis Towers Watson (WTW)", ["https://careers.wtwco.com/jobs/search?location=Ireland"],
        ("careers.wtwco.com/jobs/",), default_location="Dublin, Ireland",
        max_scrolls=10, require_ireland=True, source_tag="official",
    )
    jobs = seeds + [job for job in jobs if re.search(r"careers\.wtwco\.com/jobs/(?!search(?:[/?#]|$))", job["url"], re.I)]
    return list({job["url"].split("?")[0]: job for job in jobs}.values())




def scrape_bnp_paribas_ireland():
    """Registry-normalised wrapper around the existing BNP Paribas scraper."""
    jobs = scrape_bnp_paribas_rewired() or []

    for job in jobs:
        job["company"] = "BNP Paribas Ireland"

    # Mirror connector health under the registry's canonical company name.
    existing = CONNECTOR_HEALTH.get("BNP Paribas")
    if existing:
        CONNECTOR_HEALTH["BNP Paribas Ireland"] = dict(existing)

    return jobs



def scrape_auxilion_official():
    company = "Auxilion"
    source = "https://www.auxilion.com/auxilion-careers"

    session = requests.Session()
    if session is None:
        return []

    try:
        r = session.get(
            source,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        candidates = {}
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(source, a.get("href"))
            if "/careers/" not in href:
                continue
            if href.rstrip("/") == source.rstrip("/"):
                continue

            canonical = href.split("?")[0].split("#")[0]

            try:
                rr = session.get(
                    canonical,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if rr.status_code >= 400:
                    continue

                detail = BeautifulSoup(rr.text, "html.parser")
                text = re.sub(r"\s+", " ", detail.get_text(" ", strip=True))

                # Require the job page itself to contain an Ireland location.
                if not re.search(
                    r"\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford)\b",
                    text,
                    re.I,
                ):
                    continue

                title = ""
                h1 = detail.find("h1")
                if h1:
                    title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)).strip()

                if not title:
                    title = re.sub(
                        r"[-_]+",
                        " ",
                        canonical.rstrip("/").split("/")[-1]
                    ).title()

                if not title or title.lower() in {
                    "careers",
                    "auxilion careers",
                    "find out more",
                }:
                    continue

                if re.search(r"\bDublin\b", text, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bCork\b", text, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"\bGalway\b", text, re.I):
                    location = "Galway, Ireland"
                elif re.search(r"\bLimerick\b", text, re.I):
                    location = "Limerick, Ireland"
                elif re.search(r"\bWaterford\b", text, re.I):
                    location = "Waterford, Ireland"
                else:
                    location = "Ireland"

                candidates[canonical.lower()] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": text[:5000],
                }

            except Exception:
                continue

        _mark_connector_health(
            company,
            True,
            f"Official Auxilion careers page loaded; {len(candidates)} Ireland jobs",
            source,
        )

        print(f"  Auxilion official Ireland careers: {len(candidates)} jobs")
        return list(candidates.values())

    except Exception as exc:
        _mark_connector_health(company, False, str(exc), source)
        print(f"  ! Auxilion scrape failed: {exc}")
        return []


def scrape_biomarin_official():
    company = "BioMarin"
    source = "https://www.biomarin.com/careers/jobs/"

    session = requests.Session()
    if session is None:
        return []

    try:
        r = session.get(
            source,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        job_links = set()

        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(source, a.get("href"))
            if re.search(r"https://www\.biomarin\.com/job/[^/?#]+/?$", href, re.I):
                job_links.add(href.split("?")[0].split("#")[0])

        results = {}

        for href in sorted(job_links):
            try:
                rr = session.get(
                    href,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if rr.status_code >= 400:
                    continue

                detail = BeautifulSoup(rr.text, "html.parser")
                text = re.sub(r"\s+", " ", detail.get_text(" ", strip=True))

                title = ""
                h1 = detail.find("h1")
                if h1:
                    title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)).strip()

                if not title:
                    title = re.sub(
                        r"[-_]+",
                        " ",
                        href.rstrip("/").split("/")[-1]
                    ).title()

                # IMPORTANT:
                # determine location from title/header/top job section only,
                # NOT from the entire page, which may mention Ireland globally.
                top_chunks = []

                if h1:
                    top_chunks.append(h1.parent.get_text(" ", strip=True)[:2500])

                main = detail.find("main")
                if main:
                    top_chunks.append(main.get_text(" ", strip=True)[:3500])

                top_text = re.sub(r"\s+", " ", " ".join(top_chunks))

                # Strong positive Ireland signals.
                city_match = re.search(
                    r"\b(Cork|Dublin|Galway|Limerick|Waterford|Shanbally)\b"
                    r"(?:,\s*Ireland)?",
                    top_text,
                    re.I,
                )

                ireland_match = re.search(
                    r"\bIreland\b",
                    top_text,
                    re.I,
                )

                # Strong foreign-location signals near job header.
                foreign_match = re.search(
                    r"\b(?:United States|USA|US -|San Rafael|California|"
                    r"Paris|France|Germany|Spain|Italy|Switzerland|Canada|"
                    r"Netherlands|Belgium|Singapore|Japan|China|Australia)\b",
                    top_text,
                    re.I,
                )

                if not (city_match or ireland_match):
                    continue

                # Reject obvious foreign job locations even if generic page
                # content elsewhere mentions Ireland.
                if foreign_match and not city_match:
                    continue

                if city_match:
                    city = city_match.group(1).title()
                    location = f"{city}, Ireland"
                else:
                    location = "Ireland"

                canonical = href.rstrip("/") + "/"

                results[canonical.lower()] = {
                    "company": company,
                    "ats": "direct",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": text[:5000],
                }

            except Exception:
                continue

        _mark_connector_health(
            company,
            True,
            f"Official BioMarin careers page loaded; {len(results)} Ireland jobs",
            source,
        )

        print(f"  BioMarin official Ireland careers: {len(results)} jobs")
        return list(results.values())

    except Exception as exc:
        _mark_connector_health(company, False, str(exc), source)
        print(f"  ! BioMarin scrape failed: {exc}")
        return []



def scrape_amcs_official():
    """Strict AMCS Ireland scraper.

    Discover vacancies from AMCS listing pages, but validate country/location
    from each individual vacancy page so neighbouring cards cannot leak their
    location into another job.
    """
    import re
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    company = "AMCS Group"
    base = "https://www.amcsgroup.com/careers/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )
    }

    session = requests.Session()
    session.headers.update(headers)

    candidate_urls = set()

    # Discover all vacancy-detail URLs from several listing pages.
    for page_no in range(1, 8):
        url = base if page_no == 1 else f"{base}page/{page_no}/"

        try:
            r = session.get(url, timeout=25)
            if r.status_code != 200:
                break

            soup = BeautifulSoup(r.text, "html.parser")
            found_this_page = 0

            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, a.get("href") or "")
                href = href.split("#")[0].split("?")[0]

                if not re.match(
                    r"^https://www\.amcsgroup\.com/careers/"
                    r"(?!page/|#?$)[a-z0-9][a-z0-9\-]*/?$",
                    href,
                    re.I,
                ):
                    continue

                candidate_urls.add(href)
                found_this_page += 1

            if found_this_page == 0 and page_no > 1:
                break

        except Exception:
            break

    jobs = []
    seen = set()

    ireland_location_re = re.compile(
        r"\b("
        r"Dublin|Cork|Galway|Limerick|Waterford|"
        r"Ireland"
        r")\b",
        re.I,
    )

    # Location patterns must come from the vacancy itself.
    specific_location_re = re.compile(
        r"\b("
        r"Dublin|Cork|Galway|Limerick|Waterford"
        r")\s*,?\s*Ireland\b",
        re.I,
    )

    for href in sorted(candidate_urls):
        try:
            r = session.get(href, timeout=25)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            text = re.sub(
                r"\s+",
                " ",
                soup.get_text(" ", strip=True),
            ).strip()

            # Must explicitly identify this vacancy as Ireland.
            loc_match = specific_location_re.search(text)

            if loc_match:
                location = f"{loc_match.group(1).title()}, Ireland"
            else:
                # Permit plain "Ireland" only when it appears as an actual
                # vacancy location, not merely corporate/site boilerplate.
                location_context = re.search(
                    r"(?:Location|Work location|Job location)"
                    r".{0,80}\bIreland\b",
                    text,
                    re.I,
                )
                if not location_context:
                    continue
                location = "Ireland"

            # Prefer vacancy H1 for title.
            title = ""
            h1 = soup.find("h1")
            if h1:
                title = re.sub(
                    r"\s+",
                    " ",
                    h1.get_text(" ", strip=True),
                ).strip()

            if not title:
                # Safe fallback from URL slug.
                slug = href.rstrip("/").split("/")[-1]
                slug = re.sub(r"-\d+$", "", slug)
                title = slug.replace("-", " ").strip().title()

            # Remove common AMCS/site suffixes.
            title = re.sub(
                r"\s*[|–—-]\s*AMCS.*$",
                "",
                title,
                flags=re.I,
            ).strip()

            if not title:
                continue

            # Employment type only when explicitly present on this vacancy.
            employment_type = None

            if re.search(
                r"\b(?:fixed[- ]term|FTC|contract|temporary)\b",
                text,
                re.I,
            ):
                employment_type = "Contract"
            elif re.search(
                r"\bfull[- ]?time\b",
                text,
                re.I,
            ):
                employment_type = "Full Time"
            elif re.search(
                r"\bpart[- ]?time\b",
                text,
                re.I,
            ):
                employment_type = "Part Time"

            canonical = href.rstrip("/") + "/"

            if canonical.lower() in seen:
                continue

            seen.add(canonical.lower())

            jobs.append({
                "company": company,
                "ats": "direct",
                "title": title[:300],
                "location": location,
                "raw_location": location,
                "url": canonical,
                "updated_at": None,
                "employment_type": employment_type,
                "description_text": text[:12000],
            })

        except Exception:
            continue

    jobs.sort(
        key=lambda x: (
            x.get("location") or "",
            x.get("title") or "",
        )
    )

    _mark_connector_health(
        company,
        True,
        f"AMCS official careers validated; {len(jobs)} Ireland vacancies",
        base,
    )

    print(f"  AMCS official Ireland careers: {len(jobs)} jobs")
    return jobs



def scrape_avolon_official():
    """Scrape Ireland vacancies from Avolon's official careers listing."""
    import re
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    company = "Avolon"
    url = "https://www.avolon.aero/careers"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, timeout=25)

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        jobs = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"])

            if "mytribe.my.salesforce-sites.com" not in href:
                continue

            if "vacancyNo=" not in href:
                continue

            if href in seen:
                continue

            seen.add(href)

            # Use surrounding listing text because Salesforce's application
            # page itself only exposes the generic "Applicant Portal" title.
            parent = a

            for _ in range(6):
                if parent.parent is None:
                    break

                parent = parent.parent
                block = parent.get_text(" ", strip=True)

                if re.search(
                    r"\b(?:Dublin|Ireland|Singapore)\b",
                    block,
                    re.I,
                ):
                    break

            block = parent.get_text(" ", strip=True)

            # Strict Ireland filtering.
            if not re.search(
                r"\b(?:Dublin\s*,?\s*Ireland|Dublin|Ireland)\b",
                block,
                re.I,
            ):
                continue

            location = "Dublin, Ireland"

            # Current careers markup places title/location before APPLY NOW.
            cleaned = re.sub(r"\s+", " ", block).strip()

            title = ""

            # Prefer the known listing structure:
            # <title> Dublin, Ireland APPLY NOW
            m = re.search(
                r"(.+?)\s+Dublin\s*,\s*Ireland\s+APPLY\s+NOW",
                cleaned,
                re.I,
            )

            if m:
                title = m.group(1).strip()

                # If parent traversal captured preceding content, keep the
                # final plausible title segment.
                title = re.split(
                    r"\bTITLE\b|\bLOCATION\b",
                    title,
                    flags=re.I,
                )[-1].strip()

            # Stable fallback for the current official vacancy.
            if not title:
                vacancy = re.search(r"vacancyNo=([^&]+)", href, re.I)

                if vacancy and vacancy.group(1).upper() == "VN239":
                    title = "VP Technical - Asset Management"

            if not title:
                continue

            jobs.append({
                "company": company,
                "title": title,
                "location": location,
                "url": href,
            })

        print(f"  Avolon official Ireland careers: {len(jobs)} jobs")
        return jobs

    except Exception:
        return []



def scrape_asl_aviation_official():
    """Strict ASL Aviation Ireland vacancy scraper.

    A vacancy is accepted only when its own detail page explicitly labels
    the location as an Irish city. Corporate boilerplate mentioning Dublin
    or Ireland is never sufficient.
    """
    import re
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    company = "ASL Aviation Holdings"
    base = (
        "https://cezanneondemand.intervieweb.it/"
        "aslaviationgroup/en/career"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )
    }

    session = requests.Session()
    session.headers.update(headers)

    try:
        r = session.get(base, timeout=30)

        if r.status_code != 200:
            _mark_connector_health(
                company,
                False,
                f"ASL careers returned HTTP {r.status_code}",
                base,
            )
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        vacancy_urls = set()

        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a.get("href") or "")
            href = href.split("#")[0].split("?")[0]

            if re.match(
                r"^https://cezanneondemand\.intervieweb\.it/"
                r"aslaviationgroup/jobs/"
                r"[^/?#]+-\d+/en/?$",
                href,
                re.I,
            ):
                vacancy_urls.add(href.rstrip("/") + "/")

        jobs = []
        seen = set()

        # IMPORTANT:
        # Only explicit vacancy-level location labels count.
        #
        # Examples:
        #   Location Swords Ireland
        #   Location Dublin Ireland
        #   Location Shannon Ireland
        explicit_location_re = re.compile(
            r"\bLocation\s*[:\-]?\s*"
            r"(Swords|Dublin|Shannon|Cork|Galway|Limerick|Waterford)"
            r"\s*,?\s*Ireland\b",
            re.I,
        )

        generic_slugs = (
            "candidature-spontanee",
            "spontaneous",
            "internships-stages",
        )

        for href in sorted(vacancy_urls):
            try:
                slug = href.rstrip("/").split("/")[-2].lower()

                # Generic talent-pool / non-specific vacancy pages do not
                # belong in the live Ireland-job feed.
                if any(x in slug for x in generic_slugs):
                    continue

                rr = session.get(href, timeout=25)

                if rr.status_code != 200:
                    continue

                ss = BeautifulSoup(rr.text, "html.parser")

                text = re.sub(
                    r"\s+",
                    " ",
                    ss.get_text(" ", strip=True),
                ).strip()

                # ------------------------------------------------------
                # STRICT LOCATION VALIDATION
                # ------------------------------------------------------
                #
                # Do not accept:
                #   "headquartered in Dublin, Ireland"
                #   "ASL Airlines Ireland"
                #   footer/corporate descriptions
                #
                # The vacancy itself must expose a Location field.
                location_match = explicit_location_re.search(text)

                if not location_match:
                    continue

                city = location_match.group(1).title()
                location = f"{city}, Ireland"

                # ------------------------------------------------------
                # TITLE
                # ------------------------------------------------------
                #
                # Intervieweb's visible H1 can be Login / application form,
                # so URL slug is more reliable and vacancy-specific.
                clean_slug = re.sub(
                    r"-\d+$",
                    "",
                    slug,
                )

                title = clean_slug.replace("-", " ").strip()

                # Preserve common technical abbreviations.
                words = []
                for word in title.split():
                    low = word.lower()

                    if low in {
                        "b1",
                        "b2",
                        "b1b2",
                        "b737",
                        "b747",
                        "pnc",
                        "hf",
                    }:
                        words.append(word.upper())
                    else:
                        words.append(word.capitalize())

                title = " ".join(words)

                if not title:
                    continue

                # ------------------------------------------------------
                # EMPLOYMENT TYPE
                # ------------------------------------------------------
                employment_type = None

                # Only inspect a limited vacancy-focused window around the
                # explicit Location field rather than the whole corporate page.
                loc_start = max(0, location_match.start() - 2500)
                loc_end = min(len(text), location_match.end() + 5000)
                vacancy_window = text[loc_start:loc_end]

                if re.search(
                    r"\bfull[- ]?time\b",
                    vacancy_window,
                    re.I,
                ):
                    employment_type = "Full Time"

                elif re.search(
                    r"\bpart[- ]?time\b",
                    vacancy_window,
                    re.I,
                ):
                    employment_type = "Part Time"

                elif re.search(
                    r"\b(?:contract|fixed[- ]term|temporary)\b",
                    vacancy_window,
                    re.I,
                ):
                    employment_type = "Contract"

                canonical = href.rstrip("/") + "/"

                if canonical.lower() in seen:
                    continue

                seen.add(canonical.lower())

                jobs.append({
                    "company": company,
                    "ats": "intervieweb",
                    "title": title[:300],
                    "location": location,
                    "raw_location": location,
                    "url": canonical,
                    "updated_at": None,
                    "employment_type": employment_type,
                    "description_text": vacancy_window[:12000],
                })

            except Exception:
                continue

        jobs.sort(
            key=lambda x: (
                x.get("location") or "",
                x.get("title") or "",
            )
        )

        _mark_connector_health(
            company,
            True,
            (
                "Official ASL Intervieweb careers board loaded; "
                f"{len(jobs)} explicitly Ireland-labelled vacancies"
            ),
            base,
        )

        print(
            f"  ASL Aviation official Ireland careers: "
            f"{len(jobs)} jobs"
        )

        return jobs

    except Exception as exc:
        _mark_connector_health(
            company,
            False,
            f"ASL careers error: {exc}",
            base,
        )

        print(
            f"  ! ASL Aviation Ireland scrape failed: {exc}"
        )

        return []



def scrape_university_official(company: str):
    """Collect individual vacancies from an official Irish university job board."""
    info = UNIVERSITY_CAREER_PAGES.get(company) or {}
    source = info.get("url")
    default_location = info.get("location") or "Ireland"
    if not source:
        return []
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    generic = {"jobs","job","vacancies","vacancy","current vacancies","all vacancies","search jobs","search vacancies","search current vacancies","apply now","apply","careers","career opportunities","external vacancies","internal vacancies","view all","read more","more info","login"}
    role_words = re.compile(r"\b(?:analyst|administrator|officer|manager|director|head|lead|specialist|coordinator|assistant|associate|consultant|developer|engineer|architect|technician|researcher|research|lecturer|professor|fellow|tutor|librarian|project|programme|finance|data|digital|technology|systems|operations|procurement|communications|marketing|adviser|advisor|executive)\b", re.I)
    href_words = re.compile(r"(?:job|vacan|recruit|position|competition|apply|erecruit|corehr|jobs\.)", re.I)
    results = {}
    def consume(html_text, base_url):
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
            if not title or len(title) < 5 or len(title) > 260 or title.lower() in generic:
                continue
            href = urljoin(base_url, a.get("href") or "")
            if href.startswith(("mailto:", "javascript:")):
                continue
            node=a; card=title
            for _ in range(4):
                node=getattr(node,"parent",None)
                if not node: break
                txt=re.sub(r"\s+"," ",node.get_text(" ",strip=True)).strip()
                if txt and len(txt)<=2500: card=txt
            if not role_words.search(title) and not (href_words.search(href) and re.search(r"(?:closing|close date|reference|ref\.?|salary|contract|full[- ]?time|part[- ]?time)",card,re.I)):
                continue
            if re.search(r"(?:privacy|cookie|policy|benefits|how to apply|candidate information|faq|contact)",title,re.I):
                continue
            clean=href.split("#")[0]
            results[(title.lower(),clean.lower())]={"company":company,"ats":"university_direct","title":title[:300],"location":default_location,"url":clean,"updated_at":None,"description_text":card[:5000],"university_job":True}
    try:
        req=urllib.request.Request(source,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=35) as r:
            consume(r.read().decode("utf-8",errors="ignore"),r.geturl())
        _mark_connector_health(company,True,"Official university vacancy source loaded",source)
    except Exception as exc:
        if HAS_PLAYWRIGHT:
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True); page=browser.new_page(locale="en-IE")
                    page.goto(source,wait_until="domcontentloaded",timeout=60000); page.wait_for_timeout(2500)
                    for _ in range(5): page.mouse.wheel(0,2500); page.wait_for_timeout(250)
                    consume(page.content(),page.url); browser.close()
                _mark_connector_health(company,True,"Official university vacancy source loaded in browser",source)
            except Exception as browser_exc:
                _mark_connector_health(company,False,str(browser_exc),source)
        else:
            _mark_connector_health(company,False,str(exc),source)
    jobs=list(results.values())
    print(f"  {company} university careers: {len(jobs)} jobs")
    return jobs



def scrape_pm_group_official():
    """
    Strict PM Group Republic-of-Ireland collector.

    PM Group's Jibe/iCIMS detail pages expose schema.org JobPosting JSON-LD.
    We trust structured vacancy metadata instead of matching Ireland in
    navigation/footer/body boilerplate.
    """
    import json as _json
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from bs4 import BeautifulSoup

    company = "PM Group"
    base = "https://careers.pmgroup-global.com/careers/jobs"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-IE,en;q=0.9",
    }

    # PM Group IDs currently occupy this namespace.
    #
    # We retain a bounded window rather than guessing forever.
    # Structured JSON-LD validation makes foreign/expired IDs harmless.
    candidate_ids = range(10800, 13051)

    ireland_names = {
        "ireland",
        "republic of ireland",
        "dublin",
        "cork",
        "galway",
        "limerick",
        "waterford",
        "kildare",
        "kilkenny",
        "carlow",
        "athlone",
        "dundalk",
        "mayo",
        "roscommon",
        "tipperary",
        "leinster",
    }

    def parse_one(jid):
        sess = _session()
        if not sess:
            return None

        url = f"{base}/{jid}?lang=en-us"

        try:
            r = sess.get(
                url,
                headers=headers,
                timeout=12,
                allow_redirects=True,
            )
        except Exception:
            return None

        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text or "", "html.parser")

        posting = None

        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text("", strip=True)

            if not raw:
                continue

            try:
                obj = _json.loads(raw)
            except Exception:
                continue

            candidates = obj if isinstance(obj, list) else [obj]

            for candidate in candidates:
                if (
                    isinstance(candidate, dict)
                    and str(candidate.get("@type", "")).lower()
                    == "jobposting"
                ):
                    posting = candidate
                    break

            if posting:
                break

        if not posting:
            return None

        title = re.sub(
            r"\s+",
            " ",
            str(posting.get("title") or ""),
        ).strip()

        if not title:
            return None

        # ----------------------------------------------------
        # Structured location
        # ----------------------------------------------------
        job_locations = posting.get("jobLocation") or []

        if isinstance(job_locations, dict):
            job_locations = [job_locations]

        valid_locations = []

        for item in job_locations:
            if not isinstance(item, dict):
                continue

            address = item.get("address") or {}

            if not isinstance(address, dict):
                continue

            locality = str(
                address.get("addressLocality") or ""
            ).strip()

            region = str(
                address.get("addressRegion") or ""
            ).strip()

            country = address.get("addressCountry") or ""

            if isinstance(country, dict):
                country = (
                    country.get("name")
                    or country.get("@id")
                    or ""
                )

            country = str(country).strip()

            combined = " ".join(
                x for x in (locality, region, country) if x
            ).lower()

            # Strict ROI.
            if (
                "ireland" not in combined
                and not any(x in combined for x in ireland_names)
            ):
                continue

            if "northern ireland" in combined or "belfast" in combined:
                continue

            if locality:
                valid_locations.append(f"{locality}, Ireland")
            elif region:
                valid_locations.append(f"{region}, Ireland")
            else:
                valid_locations.append("Ireland")

        # Some Jibe JobPosting blocks omit jobLocation but encode location
        # canonically in the HTML document title:
        # "Senior Automation Engineer in Dublin, Ireland | PM Group"
        if not valid_locations:
            page_title = (
                soup.title.get_text(" ", strip=True)
                if soup.title else ""
            )

            m = re.search(
                r"\bin\s+([^|]+?,\s*Ireland)\s*\|\s*PM Group",
                page_title,
                re.I,
            )

            if m and not re.search(
                r"\b(?:Belfast|Northern Ireland)\b",
                m.group(1),
                re.I,
            ):
                valid_locations.append(
                    re.sub(r"\s+", " ", m.group(1)).strip()
                )

        if not valid_locations:
            return None

        # ----------------------------------------------------
        # Description
        # ----------------------------------------------------
        description_html = str(posting.get("description") or "")
        description_text = re.sub(
            r"\s+",
            " ",
            BeautifulSoup(
                description_html,
                "html.parser",
            ).get_text(" ", strip=True),
        ).strip()

        # ----------------------------------------------------
        # Employment type
        # ----------------------------------------------------
        raw_type = posting.get("employmentType")

        if isinstance(raw_type, list):
            raw_type = " ".join(str(x) for x in raw_type)

        raw_type = str(raw_type or "")

        full_text = " ".join([
            raw_type,
            description_text[:2000],
            soup.title.get_text(" ", strip=True) if soup.title else "",
        ])

        employment_type = None

        if re.search(r"\bpermanent\b", full_text, re.I):
            employment_type = "full_time"
        elif re.search(
            r"\b(?:fixed[- ]term|contract)\b",
            full_text,
            re.I,
        ):
            employment_type = "contract"
        elif re.search(r"\btemporary\b", full_text, re.I):
            employment_type = "temporary"

        # ----------------------------------------------------
        # Work mode + category from the compact rendered
        # vacancy metadata. These are enrichment only.
        # ----------------------------------------------------
        body_text = re.sub(
            r"\s+",
            " ",
            soup.get_text(" ", strip=True),
        ).strip()

        work_mode = None

        # Look near title / start of the vacancy, not whole footer.
        head_text = body_text[:3500]

        if re.search(r"\bHybrid\b", head_text, re.I):
            work_mode = "hybrid"
        elif re.search(r"\bOnsite\b|\bOn-site\b", head_text, re.I):
            work_mode = "onsite"
        elif re.search(r"\bRemote\b", head_text, re.I):
            work_mode = "remote"

        category = None

        cat = re.search(
            r"\b("
            r"Architecture|CQV|CSV|Construction|"
            r"Contracts Administration|Design|Digital|EHS|"
            r"Engineering|Facilities Management|H&S|IS|"
            r"Marketing/Business Development|"
            r"Planning & Scheduling|Procurement|"
            r"Project Management|Project Services|Quality|"
            r"Quantity Surveyors"
            r")\b",
            head_text,
            re.I,
        )

        if cat:
            category = cat.group(1)

        clean_url = str(posting.get("url") or url).strip()

        return {
            "company": company,
            "ats": "jibe_icims",
            "title": title[:300],
            "location": valid_locations[0],
            "url": clean_url,
            "updated_at": posting.get("datePosted"),
            "closing_date": posting.get("validThrough"),
            "description_text": description_text[:7000],
            "employment_type": employment_type,
            "work_mode": work_mode,
            "job_category": category,
            "requisition_id": str(jid),
        }

    results = {}

    # Parallel because most IDs are expired/non-job responses.
    with ThreadPoolExecutor(max_workers=18) as pool:
        futures = {
            pool.submit(parse_one, jid): jid
            for jid in candidate_ids
        }

        for future in as_completed(futures):
            try:
                job = future.result()
            except Exception:
                job = None

            if not job:
                continue

            key = (
                str(job.get("requisition_id") or "")
                or str(job.get("url") or "").lower()
            )

            results[key] = job

    _mark_connector_health(
        company,
        True,
        "PM Group official JobPosting JSON-LD validation completed",
        base,
    )

    jobs = sorted(
        results.values(),
        key=lambda j: int(j.get("requisition_id") or 0),
        reverse=True,
    )

    print(
        f"  PM Group official Ireland careers: "
        f"{len(jobs)} jobs"
    )

    return jobs




def scrape_barclays_official():
    """
    Barclays Ireland collector.

    Workday remains useful, but Barclays' public Radancy careers search can
    expose Ireland vacancies that have not appeared through the Workday query.
    Union both first-party sources and deduplicate by requisition / URL / title.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    company = "Barclays"
    source = "https://search.jobs.barclays/search-jobs/Ireland"

    results = {}

    # --------------------------------------------------------
    # Source 1: existing validated Workday collector
    # --------------------------------------------------------
    try:
        workday_jobs = scrape_workday(
            company,
            "barclays",
            "wd3",
            "External_Career_Site_Barclays",
            max_pages=25,
            search_text="Ireland",
        )

        for job in workday_jobs:
            url = str(job.get("url") or "")
            req = str(job.get("requisition_id") or "")

            m = re.search(
                r"_(JR-[A-Za-z0-9-]+)(?:[-/?]|$)",
                url,
                re.I,
            )

            if not req and m:
                req = m.group(1)

            key = (
                req.lower()
                if req
                else url.lower()
            )

            job["company"] = company
            results[key] = job

    except Exception as exc:
        print(f"  ! Barclays Workday layer: {exc}")

    # --------------------------------------------------------
    # Source 2: Barclays official Ireland search
    # --------------------------------------------------------
    sess = _session()

    if sess:
        try:
            r = sess.get(
                source,
                timeout=35,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-IE,en;q=0.9",
                },
            )

            if r.status_code == 200:
                soup = BeautifulSoup(r.text or "", "html.parser")

                for a in soup.find_all("a", href=True):
                    title = re.sub(
                        r"\s+",
                        " ",
                        a.get_text(" ", strip=True),
                    ).strip()

                    if not title or len(title) < 4:
                        continue

                    href = urljoin(
                        r.url,
                        a.get("href") or "",
                    )

                    # Barclays job-detail URLs typically contain /job/.
                    if not re.search(
                        r"(?:/job/|/jobs/)",
                        href,
                        re.I,
                    ):
                        continue

                    node = a
                    card = title

                    for _ in range(5):
                        node = getattr(node, "parent", None)
                        if not node:
                            break

                        text = re.sub(
                            r"\s+",
                            " ",
                            node.get_text(" ", strip=True),
                        ).strip()

                        if 20 <= len(text) <= 1800:
                            card = text

                    if not re.search(
                        r"\b(?:Dublin|Ireland)\b",
                        card,
                        re.I,
                    ):
                        continue

                    if re.search(
                        r"\b(?:Belfast|Northern Ireland)\b",
                        card,
                        re.I,
                    ):
                        continue

                    location = "Dublin, Ireland"

                    loc = re.search(
                        r"\b(Dublin|Cork|Galway|Limerick|Waterford)"
                        r"(?:,\s*Ireland|\s*\(Ireland\))",
                        card,
                        re.I,
                    )

                    if loc:
                        location = f"{loc.group(1)}, Ireland"

                    # Prevent menu/navigation links from becoming jobs.
                    if title.lower() in {
                        "ireland",
                        "dublin",
                        "search jobs",
                        "view all jobs",
                        "jobs",
                        "careers",
                    }:
                        continue

                    # Fetch detail page for canonical title where possible.
                    description = card
                    final_title = title
                    final_url = href

                    try:
                        rr = sess.get(
                            href,
                            timeout=20,
                            headers={
                                "User-Agent": "Mozilla/5.0",
                                "Accept-Language": "en-IE,en;q=0.9",
                                "Referer": source,
                            },
                        )

                        if rr.status_code == 200:
                            ss = BeautifulSoup(
                                rr.text or "",
                                "html.parser",
                            )

                            h1 = ss.find("h1")

                            if h1:
                                candidate = re.sub(
                                    r"\s+",
                                    " ",
                                    h1.get_text(" ", strip=True),
                                ).strip()

                                if candidate:
                                    final_title = candidate

                            description = re.sub(
                                r"\s+",
                                " ",
                                ss.get_text(" ", strip=True),
                            ).strip()[:7000]

                            final_url = rr.url

                    except Exception:
                        pass

                    req = ""

                    m = re.search(
                        r"\b(?:JR-)?\d{6,}\b",
                        final_url + " " + description[:1500],
                        re.I,
                    )

                    if m:
                        req = m.group(0)

                    # Dedupe against Workday by normalized title when a
                    # requisition ID is unavailable/different.
                    title_key = re.sub(
                        r"[^a-z0-9]+",
                        " ",
                        final_title.lower(),
                    ).strip()

                    existing_key = None

                    for k, existing in results.items():
                        existing_title = re.sub(
                            r"[^a-z0-9]+",
                            " ",
                            str(existing.get("title") or "").lower(),
                        ).strip()

                        if (
                            existing_title == title_key
                            and title_key
                        ):
                            existing_key = k
                            break

                    if existing_key:
                        continue

                    key = (
                        req.lower()
                        if req
                        else final_url.lower()
                    )

                    results[key] = {
                        "company": company,
                        "ats": "barclays_official",
                        "title": final_title[:300],
                        "location": location,
                        "url": final_url,
                        "updated_at": None,
                        "description_text": description,
                        "requisition_id": req or None,
                    }

                _mark_connector_health(
                    company,
                    True,
                    "Barclays official Ireland search + Workday loaded",
                    source,
                )

        except Exception as exc:
            print(f"  ! Barclays official Ireland page: {exc}")

    jobs = list(results.values())

    print(
        f"  Barclays official Ireland careers: "
        f"{len(jobs)} jobs"
    )

    return jobs




def scrape_decathlon_ireland():
    """
    Official Decathlon Ireland search.

    The current Ireland board is server-rendered SuccessFactors-style HTML.
    This collector returns genuine Republic-of-Ireland vacancies only.

    Generic retail/frontline exclusions remain the responsibility of the
    existing global relevance/employment filtering later in the pipeline.
    """
    company = "Decathlon Ireland"
    source = (
        "https://jobs.decathlon.co.uk/search/"
        "?searchby=location"
        "&createNewAlert=false"
        "&q="
        "&locationsearch=ireland"
        "&geolocation="
        "&optionsFacetsDD_customfield1="
        "&optionsFacetsDD_customfield2="
        "&optionsFacetsDD_dept="
        "&optionsFacetsDD_zip="
    )

    sess = _session()
    if not sess:
        return []

    try:
        r = sess.get(
            source,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
        )
        r.raise_for_status()
        body = r.text or ""
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), source)
        print(f"  ! Decathlon Ireland careers failed: {exc}")
        return []

    results = {}

    # Search-result anchors have the stable:
    # /job/<location>-<title>/<numeric-id>/
    anchor_re = re.compile(
        r'<a\b[^>]+href=["\']([^"\']*/job/[^"\']+/\d+/)["\'][^>]*>'
        r'(.*?)</a>',
        re.I | re.S,
    )

    matches = list(anchor_re.finditer(body))

    for idx, m in enumerate(matches):
        href = html.unescape(m.group(1))
        title = re.sub(
            r"\s+",
            " ",
            _html_text(m.group(2)),
        ).strip()

        if not title:
            continue

        url = urllib.parse.urljoin(source, href)

        # Inspect HTML between this result and the next result. The rendered
        # table contains the location immediately after the title.
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(
            len(body),
            start + 2500,
        )

        card_html = body[start:end]
        card_text = re.sub(
            r"\s+",
            " ",
            _html_text(card_html),
        ).strip()

        # Republic-of-Ireland board values currently render as e.g.
        # "Limerick, IE, V94 VHK8" / "Dublin, IE, D01P2Y0".
        loc = re.search(
            r'\b(Dublin|Limerick|Cork|Galway|Waterford|Kildare|'
            r'Kilkenny|Wexford|Athlone|Sligo|Drogheda|Naas|'
            r'Tallaght|Blanchardstown)\s*,\s*IE\b'
            r'(?:\s*,\s*([A-Z0-9 ]{3,10}))?',
            card_text,
            re.I,
        )

        # URL itself is a secondary Republic-of-Ireland check.
        url_ireland = bool(
            re.search(
                r'/job/(?:Dublin|Limerick|Cork|Galway|Waterford|'
                r'Kildare|Kilkenny|Wexford|Athlone|Sligo|'
                r'Drogheda|Naas|Tallaght|Blanchardstown)-',
                url,
                re.I,
            )
        )

        if not loc and not url_ireland:
            continue

        if loc:
            city = loc.group(1)
            location = f"{city}, Ireland"
        else:
            city_match = re.search(r"/job/([^-/]+)-", url, re.I)
            city = city_match.group(1) if city_match else ""
            location = f"{city}, Ireland" if city else "Ireland"

        key = url.split("?")[0].rstrip("/").lower()

        results[key] = {
            "company": company,
            "ats": "successfactors",
            "title": title[:300],
            "location": location,
            "url": url.split("?")[0],
            "updated_at": None,
            "description_text": card_text[:5000],
        }

    _mark_connector_health(
        company,
        True,
        f"Official Ireland careers board loaded; {len(results)} Ireland vacancies found",
        source,
    )

    print(
        f"  Decathlon Ireland official careers: "
        f"{len(results)} Ireland jobs"
    )

    return list(results.values())


def scrape_cgi_ireland():
    """
    CGI Ireland / Njoyn.

    CGI's Njoyn job board is currently protected by Radware Bot Manager.
    Do NOT report a successful zero when the anti-bot validation page is
    returned; that is connector failure / manual-check state.
    """
    company = "CGI"
    source = (
        "https://cgi.njoyn.com/CORP/xweb/xweb.asp"
        "?NTKN=c&clid=21001&Page=joblisting"
    )

    sess = _session()
    if not sess:
        return []

    try:
        r = sess.get(
            source,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-IE,en;q=0.9",
            },
            allow_redirects=True,
        )

        body = r.text or ""
        final_url = r.url or source

    except Exception as exc:
        _mark_connector_health(company, False, str(exc), source)
        print(f"  ! CGI Njoyn failed: {exc}")
        return []

    blocked = (
        "validate.perfdrive.com" in final_url.lower()
        or "botmanager_support@radware.com" in body.lower()
        or "hcaptcha.com/1/api.js" in body.lower()
    )

    if blocked:
        _mark_connector_health(
            company,
            False,
            "Official Njoyn board blocked automated access via Radware Bot Manager",
            source,
        )
        print(
            "  ! CGI official Njoyn board blocked by Radware; "
            "not treating as true zero"
        )
        return []

    # Conservative fallback if CGI stops challenging requests in the future.
    results = {}

    for m in re.finditer(
        r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        body,
        re.I | re.S,
    ):
        href = urllib.parse.urljoin(
            final_url,
            html.unescape(m.group(1)),
        )

        title = re.sub(
            r"\s+",
            " ",
            _html_text(m.group(2)),
        ).strip()

        if not title or not href:
            continue

        blob = f"{title} {href}"

        if not re.search(
            r"\bIreland\b|\bDublin\b|\bCork\b|\bGalway\b",
            blob,
            re.I,
        ):
            continue

        if not re.search(
            r"job|position|posting|opportunity",
            href + " " + title,
            re.I,
        ):
            continue

        key = href.split("#")[0].rstrip("/").lower()

        results[key] = {
            "company": company,
            "ats": "njoyn",
            "title": title[:300],
            "location": (
                "Dublin, Ireland"
                if re.search(r"\bDublin\b", blob, re.I)
                else "Ireland"
            ),
            "url": href.split("#")[0],
            "updated_at": None,
            "description_text": title,
        }

    _mark_connector_health(
        company,
        True,
        f"Official Njoyn board loaded; {len(results)} verified Ireland vacancies found",
        source,
    )

    print(f"  CGI official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_dawn_meats():
    """
    Dawn Meats official iCIMS careers source.

    The public URL currently serves the corporate/iCIMS wrapper rather than
    job-result cards to a plain HTTP client. Do not convert this into a
    false 'live zero'. We attempt to discover a real iCIMS job iframe or
    job-detail URL first; otherwise connector health remains unavailable.
    """
    company = "Dawn Meats"

    sources = [
        "https://careers-dawnmeats.icims.com/jobs/search?pr=0&schemaId=&o=",
        "https://careers-dawnmeats.icims.com/jobs/search?pr=1&schemaId=&o=",
        "https://c-12895-20230316-www-dawnmeats-com.i.icims.com/careers/current-opportunities/",
    ]

    sess = _session()
    if not sess:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "en-IE,en;q=0.9",
    }

    results = {}
    loaded_any = False
    actual_job_surface_seen = False

    queue = list(sources)
    seen_pages = set()

    while queue and len(seen_pages) < 12:
        url = queue.pop(0)

        if url in seen_pages:
            continue

        seen_pages.add(url)

        try:
            r = sess.get(
                url,
                headers=headers,
                timeout=30,
                allow_redirects=True,
            )
            if r.status_code >= 400:
                continue
            loaded_any = True
            body = r.text or ""
            final_url = r.url or url
        except Exception:
            continue

        # Discover explicit iCIMS iframe/src values if supplied by wrapper JS.
        candidates = set()

        for pattern in [
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            r'icimsFrame\.src\s*=\s*["\']([^"\']+)["\']',
            r'["\'](https?://[^"\']*\.icims\.com/[^"\']*jobs[^"\']*)["\']',
        ]:
            for mm in re.finditer(pattern, body, re.I):
                raw = html.unescape(mm.group(1))
                raw = raw.replace("\\/", "/")
                if raw.startswith("//"):
                    raw = "https:" + raw
                candidates.add(
                    urllib.parse.urljoin(final_url, raw)
                )

        for candidate in candidates:
            if candidate not in seen_pages and candidate not in queue:
                queue.append(candidate)

        # Actual iCIMS job details usually contain /jobs/<id>/<slug>/job
        # or /jobs/<id>/... patterns.
        job_matches = list(
            re.finditer(
                r'<a\b[^>]+href=["\']([^"\']*/jobs/'
                r'(\d+)(?:/[^"\']*)?)["\'][^>]*>(.*?)</a>',
                body,
                re.I | re.S,
            )
        )

        if job_matches:
            actual_job_surface_seen = True

        for m in job_matches:
            href = urllib.parse.urljoin(
                final_url,
                html.unescape(m.group(1)),
            )

            title = re.sub(
                r"\s+",
                " ",
                _html_text(m.group(3)),
            ).strip()

            # iCIMS renders a decorative "Job Title" label inside the anchor.
            title = re.sub(r"^Job Title\s+", "", title, flags=re.I).strip()

            if not title or len(title) < 4:
                continue

            # Inspect surrounding card for location.
            left = max(0, m.start() - 1200)
            right = min(len(body), m.end() + 1800)
            card = re.sub(
                r"\s+",
                " ",
                _html_text(body[left:right]),
            ).strip()

            ireland = re.search(
                r"\bIreland\b|\bWaterford\b|\bKilkenny\b|"
                r"\bMeath\b|\bWexford\b|\bCork\b|\bDublin\b|"
                r"\bTipperary\b|\bWestmeath\b",
                card,
                re.I,
            )

            if not ireland:
                continue

            city = ""
            lm = re.search(
                r"\b(Waterford|Kilkenny|Wexford|Cork|Dublin|"
                r"Tipperary|Meath|Westmeath)\b",
                card,
                re.I,
            )
            if lm:
                city = lm.group(1)

            location = f"{city}, Ireland" if city else "Ireland"

            key = href.split("?")[0].rstrip("/").lower()

            results[key] = {
                "company": company,
                "ats": "icims",
                "title": title[:300],
                "location": location,
                "url": href.split("?")[0],
                "updated_at": None,
                "description_text": card[:5000],
            }

    if results:
        _mark_connector_health(
            company,
            True,
            f"Official iCIMS board returned {len(results)} verified Ireland jobs",
            sources[0],
        )
    elif actual_job_surface_seen:
        # Board itself was genuinely reached, so this may legitimately be zero.
        _mark_connector_health(
            company,
            True,
            "Official iCIMS vacancy surface loaded but no Republic-of-Ireland vacancies were verified",
            sources[0],
        )
    else:
        # Corporate footer mentioning Waterford is NOT vacancy evidence.
        _mark_connector_health(
            company,
            False,
            "iCIMS wrapper loaded but actual job-result surface was not exposed",
            sources[0],
        )

    print(
        f"  Dawn Meats official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())




def scrape_dhl_ireland_official():
    """DHL official Phenom Ireland collector using the validated Ireland search surface."""
    company = "DHL Ireland"
    source_url = (
        "https://careers.dhl.com/global/en/search-results?keywords=&"
        "p=ChIJ-ydAXOS6WUgRCPTbzjQSfM8&location=Ireland"
    )
    sess = _session()
    jobs = _scrape_phenom(company, "careers.dhl.com|DPDHGLOBAL", sess) if sess else []
    try:
        _mark_connector_health(company, bool(jobs), f"Official DHL Phenom board returned {len(jobs)} Ireland jobs", source_url)
    except Exception:
        pass
    print(f"  DHL Ireland official careers: {len(jobs)} jobs")
    return jobs


def scrape_marsh_mclennan_official():
    """
    Marsh McLennan / Marsh official Ireland careers.

    Official careers platform:
        https://careers.marsh.com/global/en/search-results

    Current site is Phenom-backed.
    """

    company = "Marsh McLennan"
    source_url = "https://careers.marsh.com/global/en/search-results"

    results = {}

    # Use the scraper's validated Phenom /widgets collector directly.
    sess = _session()
    if sess:
        try:
            for job in _scrape_phenom(company, "careers.marsh.com|MAMCGLOBAL", sess):
                url = str(job.get("url") or "").strip()
                if url:
                    results[url.split("#", 1)[0].rstrip("/").lower()] = job
        except Exception as exc:
            print(f"  ! Marsh Phenom API failed: {exc}")

    # ------------------------------------------------------------
    # 1. Prefer any existing generic Phenom collector already
    #    present in this scraper.
    # ------------------------------------------------------------
    attempts = []

    if "scrape_phenom" in globals():
        attempts += [
            lambda: scrape_phenom(company, "Marsh"),
            lambda: scrape_phenom(company, "MAMCGLOBAL"),
            lambda: scrape_phenom(company, "https://careers.marsh.com"),
        ]

    if "scrape_phenom_company" in globals():
        attempts += [
            lambda: scrape_phenom_company(company, "Marsh"),
            lambda: scrape_phenom_company(company, "MAMCGLOBAL"),
            lambda: scrape_phenom_company(company, "https://careers.marsh.com"),
        ]

    for attempt in ([] if results else attempts):
        try:
            rows = attempt() or []
        except Exception:
            continue

        for job in rows:
            if not isinstance(job, dict):
                continue

            title = str(job.get("title") or "").strip()
            location = str(job.get("location") or "").strip()
            url = str(job.get("url") or "").strip()
            desc = str(job.get("description_text") or "")

            if not title or not url:
                continue

            blob = f"{title} {location} {url} {desc}"

            if re.search(r"\bNorthern Ireland\b|\bBelfast\b", blob, re.I):
                continue

            if not re.search(
                r"\bIreland\b|\bDublin\b|\bCork\b|\bGalway\b|"
                r"\bLimerick\b|\bWaterford\b|\bIE\b",
                blob,
                re.I,
            ):
                continue

            key = url.split("#", 1)[0].rstrip("/").lower()

            item = dict(job)
            item["company"] = company
            item["ats"] = "phenom"

            if not location:
                if re.search(r"\bDublin\b", blob, re.I):
                    item["location"] = "Dublin, Ireland"
                elif re.search(r"\bCork\b", blob, re.I):
                    item["location"] = "Cork, Ireland"
                else:
                    item["location"] = "Ireland"

            results[key] = item

        if results:
            break

    # ------------------------------------------------------------
    # 2. Browser-rendered fallback.
    # ------------------------------------------------------------
    if not results and HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)

                context = browser.new_context(
                    locale="en-IE",
                    viewport={"width": 1440, "height": 1500},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )

                page = context.new_page()

                discovered = {}

                urls = [
                    source_url + "?keywords=Ireland",
                    source_url + "?location=Ireland",
                    source_url + "?from=0&s=1",
                ]

                for start_url in urls:
                    try:
                        page.goto(
                            start_url,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        page.wait_for_timeout(2500)
                    except Exception:
                        continue

                    for offset in range(0, 300, 10):
                        if offset:
                            try:
                                page.goto(
                                    source_url + f"?from={offset}&s=1",
                                    wait_until="domcontentloaded",
                                    timeout=45000,
                                )
                                page.wait_for_timeout(1600)
                            except Exception:
                                break

                        try:
                            anchors = page.locator("a").evaluate_all(
                                """els => els.map(a => ({
                                    href: a.href || "",
                                    text: (
                                        a.innerText ||
                                        a.textContent ||
                                        ""
                                    ).trim()
                                }))"""
                            )
                        except Exception:
                            anchors = []

                        before = len(discovered)

                        for a in anchors:
                            href = str(a.get("href") or "").strip()
                            title = re.sub(
                                r"\s+",
                                " ",
                                str(a.get("text") or ""),
                            ).strip()

                            if not href or not title:
                                continue

                            if "careers.marsh.com" not in href.lower():
                                continue

                            if not re.search(
                                r"/job/|/jobs/|jobdetail|job-detail",
                                href,
                                re.I,
                            ):
                                continue

                            key = href.split("#", 1)[0].rstrip("/").lower()

                            discovered[key] = {
                                "url": href.split("#", 1)[0],
                                "title": title,
                            }

                        if offset and len(discovered) == before:
                            break

                    if discovered:
                        break

                for key, seed in discovered.items():
                    detail = context.new_page()

                    try:
                        resp = detail.goto(
                            seed["url"],
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        detail.wait_for_timeout(700)

                        if resp and resp.status >= 400:
                            detail.close()
                            continue

                        body = detail.locator("body").inner_text(
                            timeout=10000
                        )
                    except Exception:
                        detail.close()
                        continue

                    body = re.sub(r"\r", "", body)

                    if re.search(
                        r"\bNorthern Ireland\b|\bBelfast\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    if not re.search(
                        r"\bIreland\b|\bDublin\b|\bCork\b|\bGalway\b|"
                        r"\bLimerick\b|\bWaterford\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    title = seed["title"]

                    try:
                        h1 = detail.locator("h1").first.inner_text(
                            timeout=2500
                        ).strip()
                        if h1:
                            title = h1
                    except Exception:
                        pass

                    title = re.sub(r"\s+", " ", title).strip()

                    if not title:
                        detail.close()
                        continue

                    top = "\n".join(body.splitlines()[:100])

                    location = "Ireland"

                    lm = re.search(
                        r"\b(Dublin|Cork|Galway|Limerick|Waterford)"
                        r"(?:[^,\n]{0,30})?,?\s*Ireland\b",
                        top,
                        re.I,
                    )

                    if lm:
                        location = lm.group(1).title() + ", Ireland"
                    elif re.search(r"\bDublin\b", top, re.I):
                        location = "Dublin, Ireland"
                    elif re.search(r"\bCork\b", top, re.I):
                        location = "Cork, Ireland"

                    results[key] = {
                        "company": company,
                        "ats": "phenom",
                        "title": title[:300],
                        "location": location,
                        "url": seed["url"],
                        "updated_at": None,
                        "description_text": body[:5000],
                    }

                    detail.close()

                context.close()
                browser.close()

        except Exception as exc:
            print(f"  ! Marsh McLennan browser fallback failed: {exc}")

    try:
        _mark_connector_health(
            company,
            bool(results),
            (
                f"Official Marsh Phenom board returned "
                f"{len(results)} verified Ireland jobs"
            ),
            source_url,
        )
    except Exception:
        pass

    print(
        f"  Marsh McLennan official Ireland careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())



# ============================================================================
# LAST BATCH: IRISH RAIL + FORVIS MAZARS + ESB + DPS GROUP
# ============================================================================

def scrape_irish_rail():
    """
    Iarnród Éireann / Irish Rail official careers page.

    Their official careers page is server-rendered and exposes current
    opportunity pages directly, so collect those links rather than inventing
    an ATS endpoint.
    """
    company = "Irish Rail (Iarnród Éireann)"
    source_url = (
        "https://www.irishrail.ie/en-ie/about-us/company-information/"
        "career-opportunities-at-iarnrod-eireann"
    )

    page = _fetch_html(source_url) or ""
    if not page:
        try:
            _mark_connector_health(
                company,
                False,
                "Official Irish Rail careers page could not be loaded",
                source_url,
            )
        except Exception:
            pass
        return []

    results = {}
    base = "https://www.irishrail.ie"

    # Restrict links to the Career Opportunities section.
    # Individual vacancy pages live beneath the same company-information area.
    for m in re.finditer(
        r'<a\b[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        page,
        re.I | re.S,
    ):
        href = html.unescape(m.group(1) or "").strip()
        title = re.sub(
            r"\s+",
            " ",
            html.unescape(_strip_html(m.group(2) or "")),
        ).strip()

        if not href or not title:
            continue

        low_title = title.lower()

        # Ignore navigation/programme/general informational links.
        if any(x in low_title for x in (
            "career opportunities",
            "graduate programme",
            "apprenticeship programme",
            "print page",
            "company information",
            "safety and security",
        )):
            continue

        # Vacancy detail pages must stay under the careers opportunity path.
        if "/career-opportunities-at-iarnrod-eireann/" not in href.lower():
            continue

        abs_url = _absolute_url(base, href)

        if "irishrail.ie" not in abs_url.lower():
            continue

        # Current vacancy pages are exposed from the career-opportunities area.
        evidence = f"{title} {href}".lower()

        role_like = bool(re.search(
            r"\b("
            r"analyst|architect|engineer|manager|specialist|officer|"
            r"administrator|supervisor|planner|technician|advisor|"
            r"executive|controller|accountant|lead|director|coordinator|"
            r"project|commercial|security|revenue"
            r")\b",
            evidence,
            re.I,
        ))

        if not role_like:
            continue

        key = abs_url.split("#", 1)[0].rstrip("/").lower()
        results[key] = {
            "company": company,
            "ats": "direct",
            "title": title[:300],
            "location": "Ireland",
            "url": abs_url.split("#", 1)[0],
            "updated_at": None,
            "description_text": title,
        }

    try:
        _mark_connector_health(
            company,
            bool(results),
            (
                f"Official Irish Rail careers page returned "
                f"{len(results)} current opportunity links"
            ),
            source_url,
        )
    except Exception:
        pass

    print(f"  Iarnród Éireann official careers: {len(results)} jobs")
    return list(results.values())


def scrape_esb():
    """
    ESB official SuccessFactors careers pages.

    Parse both result pages and retain Republic-of-Ireland jobs only.
    """
    company = "ESB"
    base = "https://careers.esb.ie"

    urls = [
        f"{base}/go/All-Jobs/882102/",
        f"{base}/go/All-Jobs/882102/20/",
        (
            f"{base}/search/"
            "?q=&q2=&alertId=&locationsearch=ireland"
            "&title=&shifttype=&department=&location=dublin&date="
        ),
    ]

    results = {}

    for url in urls:
        page = _fetch_html(url) or ""
        if not page:
            continue

        # SAP SuccessFactors job links.
        for m in re.finditer(
            r'<a\b[^>]+href=["\']([^"\']*/job/[^"\']+)["\'][^>]*>'
            r'(.*?)</a>',
            page,
            re.I | re.S,
        ):
            href = html.unescape(m.group(1) or "").strip()
            title = re.sub(
                r"\s+",
                " ",
                html.unescape(_strip_html(m.group(2) or "")),
            ).strip()

            if not href or not title:
                continue

            abs_url = _absolute_url(base, href)

            # Pull surrounding row/card text for location validation.
            start = max(0, m.start() - 1000)
            end = min(len(page), m.end() + 1800)
            card_html = page[start:end]
            card_text = re.sub(
                r"\s+",
                " ",
                html.unescape(_strip_html(card_html)),
            ).strip()

            # Republic of Ireland evidence from SuccessFactors locations.
            if not re.search(
                r"\b(?:IE|Ireland|Dublin|Cork|Galway|Limerick|"
                r"Waterford|Athlone|Portlaoise|Santry|Finglas|"
                r"Bandon|Leopardstown|Wilton)\b",
                card_text,
                re.I,
            ):
                continue

            # Exclude explicit UK / Northern Ireland-only jobs.
            if (
                re.search(r"\b(?:Belfast|Northern Ireland|\bGB\b)\b",
                          card_text, re.I)
                and not re.search(r"\b(?:IE|Ireland)\b", card_text, re.I)
            ):
                continue

            location = "Ireland"

            lm = re.search(
                r"\b("
                r"Dublin|Cork|Galway|Limerick|Waterford|Athlone|"
                r"Portlaoise|Santry|Finglas|Bandon|Leopardstown|Wilton"
                r")\b[^|<]{0,80}\b(?:IE|Ireland)\b",
                card_text,
                re.I,
            )
            if lm:
                city = lm.group(1).strip()
                location = f"{city}, Ireland"

            key = abs_url.split("?", 1)[0].rstrip("/").lower()
            results[key] = {
                "company": company,
                "ats": "successfactors",
                "title": title[:300],
                "location": location,
                "url": abs_url.split("?", 1)[0],
                "updated_at": None,
                "description_text": card_text[:5000],
            }

    try:
        _mark_connector_health(
            company,
            bool(results),
            f"Official ESB SuccessFactors board returned {len(results)} Ireland jobs",
            urls[0],
        )
    except Exception:
        pass

    print(f"  ESB official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_forvis_mazars():
    """
    Forvis Mazars Ireland official People First board.

    Use the user-validated Ireland search URL and collect only vacancy-detail
    links whose surrounding result card contains Irish location evidence.
    """
    company = "Forvis Mazars Ireland"
    source_url = (
        "https://mazars.jobs.people-first.com/jobs/search"
        "?distance=30&allLocations=false&q=&location=ireland"
    )

    page = _fetch_html(source_url) or ""

    # People First may render vacancy cards client-side. Capture the rendered
    # DOM when the plain HTTP response does not expose job links.
    if HAS_PLAYWRIGHT and (not page or not re.search(r'href=["\'][^"\']*/jobs?/', page, re.I)):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                bp = browser.new_page(locale="en-IE", viewport={"width": 1440, "height": 1600})
                bp.goto(source_url, wait_until="domcontentloaded", timeout=60000)
                bp.wait_for_timeout(2500)
                for _ in range(20):
                    bp.mouse.wheel(0, 2600)
                    bp.wait_for_timeout(300)
                page = bp.content() or page
                browser.close()
        except Exception as exc:
            print(f"  ! Forvis Mazars rendered search failed: {exc}")

    if not page:
        try:
            _mark_connector_health(company, False, "Official Forvis Mazars People First board could not be loaded", source_url)
        except Exception:
            pass
        return []

    results = {}
    base = "https://mazars.jobs.people-first.com"

    patterns = [
        r'<a\b[^>]+href=["\']([^"\']*/jobs/[^"\']+)["\'][^>]*>(.*?)</a>',
        r'<a\b[^>]+href=["\']([^"\']*/job/[^"\']+)["\'][^>]*>(.*?)</a>',
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, page, re.I | re.S):
            href = html.unescape(m.group(1) or "").strip()
            title = re.sub(
                r"\s+",
                " ",
                html.unescape(_strip_html(m.group(2) or "")),
            ).strip()

            if not href or not title:
                continue

            if re.search(
                r"\b(search|login|register|saved jobs|job alerts?)\b",
                title,
                re.I,
            ):
                continue

            start = max(0, m.start() - 1200)
            end = min(len(page), m.end() + 1800)
            card = re.sub(
                r"\s+",
                " ",
                html.unescape(_strip_html(page[start:end])),
            ).strip()

            evidence = f"{title} {card} {href}"

            if not re.search(
                r"\b(?:Ireland|Dublin|Cork|Galway|Limerick)\b",
                evidence,
                re.I,
            ):
                continue

            abs_url = _absolute_url(base, href)
            key = abs_url.split("?", 1)[0].rstrip("/").lower()

            location = "Ireland"
            lm = re.search(
                r"\b(Dublin|Cork|Galway|Limerick),?\s*(?:Ireland)?\b",
                evidence,
                re.I,
            )
            if lm:
                location = f"{lm.group(1).strip()}, Ireland"

            results[key] = {
                "company": company,
                "ats": "people_first",
                "title": title[:300],
                "location": location,
                "url": abs_url,
                "updated_at": None,
                "description_text": card[:5000],
            }

    try:
        _mark_connector_health(
            company,
            bool(results),
            (
                f"Official Forvis Mazars People First board returned "
                f"{len(results)} verified Ireland jobs"
            ),
            source_url,
        )
    except Exception:
        pass

    print(f"  Forvis Mazars official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_dps_group():
    """
    DPS Group official Ireland jobs page.

    Collect only actual /job/... detail URLs and read the real job title
    from each detail page instead of using generic 'SEE JOB DETAILS' text.
    """
    company = "DPS Group (Arcadis)"
    source_url = "https://www.dpsgroupglobal.com/careers/jobs/"

    if not HAS_PLAYWRIGHT:
        try:
            _mark_connector_health(
                company,
                False,
                "Official DPS Group jobs page requires JavaScript; Playwright unavailable",
                source_url,
            )
        except Exception:
            pass
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1400},
            )

            page = context.new_page()
            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(5000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            candidates = {}

            for item in links:
                href = str(item.get("href") or "").strip()

                # Real DPS vacancy pages only.
                if not re.match(
                    r"^https?://(?:www\.)?dpsgroupglobal\.com/job/[^/#?]+/?(?:[?#].*)?$",
                    href,
                    re.I,
                ):
                    continue

                canonical = href.split("#", 1)[0].split("?", 1)[0]
                candidates[canonical.rstrip("/").lower()] = canonical

            for canonical in candidates.values():
                detail = context.new_page()

                try:
                    resp = detail.goto(
                        canonical,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    detail.wait_for_timeout(800)

                    if resp and resp.status >= 400:
                        detail.close()
                        continue

                    body = detail.locator("body").inner_text(
                        timeout=10000
                    )
                    body = re.sub(r"\r", "", body)

                    # Republic of Ireland validation.
                    if not re.search(
                        r"\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford)\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                    title = ""

                    try:
                        title = detail.locator("h1").first.inner_text(
                            timeout=3000
                        ).strip()
                    except Exception:
                        pass

                    if not title:
                        try:
                            title = detail.title()
                        except Exception:
                            title = ""

                    title = re.sub(r"\s+", " ", title).strip()

                    # Clean common site-name suffixes.
                    title = re.sub(
                        r"\s*[\|\-–—]\s*(?:DPS Group|DPS Engineering).*$",
                        "",
                        title,
                        flags=re.I,
                    ).strip()

                    if not title:
                        detail.close()
                        continue

                    # Reject navigation/generic labels.
                    if title.lower() in {
                        "see job details",
                        "jobs",
                        "careers",
                        "dps group",
                    }:
                        detail.close()
                        continue

                    location = "Ireland"

                    lm = re.search(
                        r"\b(Dublin|Cork|Galway|Limerick|Waterford)"
                        r"(?:,\s*(?:Co\.\s*)?[A-Za-z ]+)?"
                        r"(?:,\s*Ireland)?\b",
                        body,
                        re.I,
                    )
                    if lm:
                        location = f"{lm.group(1).strip()}, Ireland"

                    key = canonical.rstrip("/").lower()

                    results[key] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": body[:5000],
                    }

                except Exception:
                    pass
                finally:
                    try:
                        detail.close()
                    except Exception:
                        pass

            context.close()
            browser.close()

    except Exception as exc:
        try:
            _mark_connector_health(
                company,
                False,
                f"Official DPS Group jobs page blocked/unavailable: {exc}",
                source_url,
            )
        except Exception:
            pass

        print(f"  ! DPS Group scrape failed: {exc}")
        return []

    try:
        _mark_connector_health(
            company,
            bool(results),
            f"Official DPS Group careers page returned {len(results)} verified Ireland jobs",
            source_url,
        )
    except Exception:
        pass

    print(f"  DPS Group official Ireland careers: {len(results)} jobs")
    return list(results.values())


def scrape_direct_company(company: str):
    # BEGIN SALE_READY_DIRECT_CONNECTORS
    # Canonical/alias names that must use their verified official collectors.
    _verified_direct_connectors = {
        'Iarnród Éireann': scrape_irish_rail,
        'Irish Rail (Iarnród Éireann)': scrape_irish_rail,
        'Irish Life': scrape_irish_life,
        'Forvis Mazars': scrape_forvis_mazars,
        'ESB': scrape_esb,
        'DPS Group': scrape_dps_group,
        'SMBC Group': scrape_smbc_group,
        'S&P Global': scrape_sp_global,
        'JPMorgan Chase': scrape_jpmorgan,
        'BlackRock': scrape_blackrock,
    }
    _direct_fn = _verified_direct_connectors.get(company)
    if _direct_fn is not None:
        return _direct_fn()
    # END SALE_READY_DIRECT_CONNECTORS
    if company in UNIVERSITY_CAREER_PAGES:
        return scrape_university_official(company)
    fn={
        "Alter Domus": scrape_alter_domus_ireland,
        "Baxter International": scrape_baxter_ireland,
        "Baker Tilly Ireland": scrape_baker_tilly_ireland,
        "Arcadis": scrape_arcadis_ireland,
        "DocuSign": scrape_docusign,
        "Broadcom": scrape_broadcom_ireland,
        "BT Ireland": scrape_bt_ireland,
        "Fenergo": scrape_fenergo_ireland,
        "Hewlett Packard Enterprise (HPE)": scrape_hpe_ireland,
        "IQVIA": scrape_iqvia_ireland,
        "Proofpoint": scrape_proofpoint_ireland,
        "Willis Towers Watson (WTW)": scrape_wtw_ireland,
        "AXA XL": scrape_axa_xl,
        "AtkinsRéalis": scrape_atkinsrealis,
        "Advanced Micro Devices (AMD)": scrape_amd,
        "Applied Materials": scrape_applied_materials,
        "Bausch + Lomb": scrape_bausch_lomb_ireland,
        "Walkers Ireland": scrape_walkers,
        "Heineken Ireland": scrape_heineken,
        "Heineken": scrape_heineken,
        "HEINEKEN": scrape_heineken,
        "Huawei Ireland": scrape_huawei,
        "Guidewire Software": scrape_guidewire,
        "Guidewire": scrape_guidewire,
        "Honeywell": scrape_honeywell,
        "HCLTech": scrape_hcltech,
        "Irish Life": scrape_irish_life,
        "Iarnród Éireann": scrape_irish_rail,
        "Irish Rail": scrape_irish_rail,
        "Irish Rail (Iarnrod Eireann)": scrape_irish_rail,
        "Forvis Mazars": scrape_forvis_mazars,
        "Forvis Mazars Ireland": scrape_forvis_mazars,
        "ESB": scrape_esb,
        "DPS Group": scrape_dps_group,
        "DPS Group (Arcadis)": scrape_dps_group,
        "Irish Revenue": scrape_revenue_ie,
        "Revenue": scrape_revenue_ie,
        "Revenue.ie": scrape_revenue_ie,
        "Medtronic": scrape_medtronic,
        "UPS Ireland": scrape_ups,
        "Three Ireland": scrape_three_ireland,
        "TK Maxx Ireland": scrape_tjx_ireland,
        "publicjobs": scrape_publicjobs,
        "Public Jobs": scrape_publicjobs,
        "publicjobs.ie": scrape_publicjobs,
        "permanent tsb": scrape_ptsb,
        "Permanent TSB": scrape_ptsb,
        "PTSB": scrape_ptsb,
        "Qualcomm": scrape_qualcomm,
        "NTT DATA Services": scrape_ntt_data,
        "NTT Data": scrape_ntt_data,
        "NTT DATA": scrape_ntt_data,
        "AXA Ireland": scrape_axa,
        "AXA": scrape_axa,
        "Laya": scrape_laya_healthcare,
        "Laya Healthcare": scrape_laya_healthcare,
        "AECOM": scrape_aecom,
        "ABB": scrape_abb,
        "S&P": scrape_sp_global,
        "S&P Global": scrape_sp_global,
        "Ryanair": scrape_ryanair,
        "Coca-Cola HBC": scrape_coca_cola,
        "The Coca-Cola Company": scrape_coca_cola,
        "Coca-Cola": scrape_coca_cola,
        "PepsiCo": scrape_pepsico,
        "FedEx": scrape_fedex,
        "Musgrave Group": scrape_musgrave,
        "Musgrave": scrape_musgrave,
        "Siemens": scrape_siemens,
        "SAP Ireland": scrape_sap,
        "SAP": scrape_sap,
        "Allianz Ireland": scrape_allianz_rewired,
        "Allianz": scrape_allianz_rewired,
        "Abbott Laboratories": scrape_abbott_rewired,
        "Abbott": scrape_abbott_rewired,
        "Accenture": scrape_accenture,
        "Citi": scrape_citi,
        "Apple": scrape_apple,
        "Fidelity International": scrape_fidelity_international,
        "Bloomberg": scrape_bloomberg,
        "BlackRock": scrape_blackrock,
        "Citco": scrape_citco,
        "Bank of Ireland": scrape_bank_of_ireland,
        "Google": scrape_google,
        "Microsoft": scrape_microsoft,
        "Meta": scrape_meta,
        "TikTok": scrape_tiktok,
        "Oracle": scrape_oracle,
        "Red Hat": scrape_redhat,
        "JPMorgan Chase": scrape_jpmorgan,
        "EY Ireland": scrape_ey,
        "KPMG Ireland": scrape_kpmg,
        "NetApp": scrape_netapp,
        "Version 1": scrape_version1,
        "Grant Thornton Ireland": scrape_grant_thornton,
        "HSBC Ireland": scrape_hsbc,
        "EXL": scrape_exl,
        "Dell Technologies": scrape_dell,
        "Tata Consultancy Services (TCS)": scrape_tcs,
        "RSM Ireland": scrape_rsm,
        "Infosys": scrape_infosys,
        "Wells Fargo": scrape_wells_fargo,
        "Vodafone": scrape_vodafone,
        "Wipro": scrape_wipro,
        "KPMG Ireland": scrape_kpmg_ireland,
        "IBM": scrape_ibm,
        "Hitachi Energy": scrape_hitachi_energy,
        "Aon": scrape_aon,
        "GE HealthCare": scrape_ge_healthcare,
        "Huawei": scrape_huawei,
        "Becton Dickinson (BD)": scrape_becton_dickinson,
        "AstraZeneca": scrape_astrazeneca,
        "Alexion Pharmaceuticals": scrape_alexion,
        "Aiven": scrape_aiven,
        "A&L Goodbody": scrape_algoodbody,
        "Agilent Technologies": scrape_agilent,
        "Jacobs": scrape_jacobs,
        "McKinsey & Company": scrape_mckinsey,
        "HP (Hewlett-Packard)": scrape_hp,
        "Arup": scrape_arup,
        "Deutsche Bank": scrape_deutsche_bank,
        "SMBC Group": scrape_smbc_group,
        "SMBC Aviation Capital": scrape_smbc_aviation_capital,
        "Harvey Nash": scrape_harvey_nash,
        "ING": scrape_ing,
        "Bank of America": scrape_bank_of_america,
        "Cognizant": scrape_cognizant,
        "AIB (Allied Irish Banks)": scrape_aib,
        "Central Bank of Ireland": scrape_central_bank_ireland,
        "BNP Paribas Ireland": scrape_bnp_paribas_ireland,
        "AIG": lambda: scrape_workday(
            "AIG",
            "aig",
            "wd1",
            "aig",
            max_pages=25,
            search_text="Ireland",
        ),
        "Barclays": scrape_barclays_official,
        "PM Group": scrape_pm_group_official,
        "Motorola Solutions": lambda: scrape_workday(
            "Motorola Solutions",
            "motorolasolutions",
            "wd5",
            "Careers",
            max_pages=25,
            search_text="Ireland",
        ),
        "AMCS Group": scrape_amcs_official,
        "Avolon": scrape_avolon_official,
        "ASL Aviation Holdings": scrape_asl_aviation_official,
        "Auxilion": scrape_auxilion_official,
        "BioMarin": scrape_biomarin_official,
        "BNP Paribas": scrape_bnp_paribas_rewired,
        "Capgemini": scrape_capgemini,
        "ServiceNow": scrape_servicenow,
        "Boston Scientific": scrape_boston_scientific,
        "DXC Technology": scrape_dxc,
        "Johnson & Johnson": scrape_johnson_johnson,
        "Johnson Controls": scrape_johnson_controls,
        "Dropbox": scrape_dropbox,
        "Zscaler": scrape_zscaler,
        "Public Jobs / Civil Service": scrape_publicjobs,
        "Coca-Cola HBC Ireland": scrape_coca_cola,
        "Musgrave Group (SuperValu / Centra)": scrape_musgrave,
        "Susquehanna International Group (SIG)": scrape_susquehanna,
        "Schneider Electric": scrape_schneider_electric,
        "CGI": scrape_cgi_ireland,
        "Dawn Meats": scrape_dawn_meats,
        "DHL Ireland": scrape_dhl_ireland_official,
        "Decathlon Ireland": scrape_decathlon_ireland,
            "Marsh McLennan": scrape_marsh_mclennan_official,
}.get(company)
    return fn() if fn else []


RESUME_MATCH_STOPWORDS = {
    "the","and","for","with","that","this","from","your","you","our","are","will","have","has","job","role","work","team","company","candidate","candidates","skills","skill","experience","years","year","including","within","across","using","into","about","more","their","they","them","who","what","when","where","which","while","also","all","any","but","not","can","may","must","should","would","could","a","an","as","at","be","by","in","is","it","of","on","or","to","we","i","us"
}

def resume_match_keywords(*parts, limit=60):
    """Return compact, generic searchable terms for browser-side CV/job matching.
    Descriptions are intentionally not shipped wholesale to keep data.json smaller.
    """
    text = " ".join(str(p or "") for p in parts).lower()
    tokens = re.findall(r"[a-z][a-z0-9+#.\-]{2,}", text)
    counts = {}
    for token in tokens:
        token = token.strip(".-")
        if len(token) < 3 or token in RESUME_MATCH_STOPWORDS or token.isdigit():
            continue
        counts[token] = counts.get(token, 0) + 1
    # Stable weighting: repeated description terms first, then alphabetically.
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def load_candidate_profile(path="profile.json"):
    """Load optional ranking profile. Collection remains profile-agnostic."""
    try:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        return profile if isinstance(profile, dict) else {}
    except Exception as e:
        print(f"profile: unavailable ({e}); candidate ranking disabled")
        return {}


def _norm_phrase(text):
    return re.sub(r"[^a-z0-9+#]+", " ", str(text or "").lower()).strip()


def normalized_title(title):
    text = _norm_phrase(title)
    replacements = {
        "business intelligence": "bi",
        "jr ": "junior ",
        "graduate programme": "graduate",
        "graduate program": "graduate",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


GENERIC_JOB_TITLES = {
    "careers", "categories", "degree", "experience", "filter", "filters",
    "job search", "job types", "jobs", "locations", "organizations",
    "roles", "search jobs", "skills qualifications", "sort by", "teams",
}


def is_real_job_title(title):
    return normalized_title(title) not in GENERIC_JOB_TITLES


def classify_role_family(title, description, profile):
    title_n = normalized_title(title)
    best = ("Other", "None", 0, [])
    for family, cfg in (profile.get("role_families") or {}).items():
        hits = []
        for phrase in cfg.get("titles", []):
            p = _norm_phrase(phrase)
            # Role identity comes from the title. Descriptions routinely mention
            # adjacent teams and were misclassifying sales/legal roles as data jobs.
            if p and p in title_n:
                hits.append(phrase)
        score = cfg.get("weight", 0) + min(8, len(hits) * 2) if hits else 0
        if score > best[2]:
            best = (family, cfg.get("tier", "C"), score, hits)
    return {"family": best[0], "tier": best[1], "role_score": best[2], "role_hits": best[3]}


def extract_profile_skills(text, profile):
    text_n = _norm_phrase(text)
    aliases = profile.get("skill_aliases") or {}
    canonical = {}
    for group, skills in (profile.get("skills") or {}).items():
        for skill in skills:
            canonical[_norm_phrase(skill)] = skill
    for alias, target in aliases.items():
        canonical[_norm_phrase(alias)] = target

    found = []
    for token, label in canonical.items():
        if token and re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text_n):
            if label not in found:
                found.append(label)
    return found


def parse_experience_range(text):
    text_n = str(text or "").lower()
    ranges = []
    patterns = [
        r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*\+?\s*years?",
        r"(\d+)\s*\+\s*years?",
        r"(?:minimum of |at least )(\d+)\s*years?",
        r"(\d+)\s*years?\s+(?:of )?experience",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text_n):
            nums = [int(x) for x in m.groups() if x is not None]
            if len(nums) == 2:
                ranges.append((nums[0], nums[1]))
            elif nums:
                ranges.append((nums[0], nums[0] + 2))
    if not ranges:
        return (None, None)
    # Prefer the lowest plausible requirement, since descriptions often mention multiple unrelated ranges.
    ranges.sort(key=lambda x: (x[0], x[1]))
    return ranges[0]


def experience_fit(title, description, candidate_years):
    title_n = normalized_title(title)
    minimum, maximum = parse_experience_range(description)
    senior_terms = ["director", "vice president", "vp", "head of", "principal", "staff", "senior manager"]
    if any(term in title_n for term in senior_terms):
        return "Too Senior", minimum, maximum
    if any(term in title_n for term in ["graduate", "entry", "junior", "associate", "analyst"]):
        if candidate_years >= 5 and "graduate" in title_n:
            return "Overqualified", minimum, maximum
        return "Strong", minimum, maximum
    if minimum is None:
        return "Possible", minimum, maximum
    if minimum <= candidate_years <= (maximum or candidate_years + 2):
        return "Strong", minimum, maximum
    if minimum <= candidate_years + 2:
        return "Possible", minimum, maximum
    if minimum <= candidate_years + 4:
        return "Stretch", minimum, maximum
    return "Too Senior", minimum, maximum


def candidate_match(job, description, profile):
    if not profile:
        return {
            "candidate_match_score": None, "match_reasons": [], "missing_skills": [],
            "matched_skills": [], "experience_fit": "Unknown"
        }

    title = job.get("title") or ""
    role = classify_role_family(title, description, profile)
    skills = extract_profile_skills(f"{title} {description}", profile)
    candidate_skills = []
    for values in (profile.get("skills") or {}).values():
        candidate_skills.extend(values)
    candidate_skill_set = set(candidate_skills)

    matched = [s for s in skills if s in candidate_skill_set]
    years = int(profile.get("experience_years") or 0)
    exp_fit, exp_min, exp_max = experience_fit(title, description, years)

    score = role["role_score"]
    # Skills refine a relevant role; they must not manufacture relevance for an
    # unrelated title that happens to mention Python, AWS or analytics.
    score += min(34, len(matched) * 4) if role["family"] != "Other" else min(8, len(matched) * 2)
    score += {"Strong": 16, "Possible": 9, "Stretch": 3, "Overqualified": -5, "Too Senior": -25, "Unknown": 0}.get(exp_fit, 0)

    loc_text = _norm_phrase(job.get("location"))
    if any(_norm_phrase(x) in loc_text for x in profile.get("preferred_locations", []) if x != "Ireland"):
        score += 5
    elif "ireland" in loc_text or job.get("country") == "Ireland":
        score += 3

    title_n = normalized_title(title)
    for term, penalty in (profile.get("seniority_penalties") or {}).items():
        if _norm_phrase(term) in title_n:
            score -= int(penalty)
            break

    # Noise penalty for clearly irrelevant job families, without deleting the job from the broad engine.
    irrelevant_title = False
    for term in profile.get("negative_title_terms", []):
        if _norm_phrase(term) in title_n:
            score -= 18
            irrelevant_title = True
            break

    if irrelevant_title or role["family"] == "Other":
        score = min(score, 40)

    score = max(0, min(100, int(round(score))))
    reasons = []
    if role["family"] != "Other":
        reasons.append(f"{role['family']} role family")
    reasons.extend(matched[:7])
    if exp_fit in {"Strong", "Possible"}:
        reasons.append(f"Experience fit: {exp_fit}")

    # Missing skills are candidate skills commonly referenced in the same role family but not present in this ad.
    priority_missing = ["SQL", "Power BI", "Python", "ERP", "UAT", "Requirements Gathering", "ETL", "Stakeholder Management"]
    missing = [x for x in priority_missing if x in candidate_skill_set and x not in matched][:4]

    return {
        "candidate_match_score": score,
        "match_reasons": reasons[:10],
        "missing_skills": missing,
        "matched_skills": matched[:15],
        "experience_fit": exp_fit,
        "experience_min": exp_min,
        "experience_max": exp_max,
        "role_family": role["family"],
        "role_tier": role["tier"],
        "normalized_title": normalized_title(title),
    }


def discovery_value(job, now_dt=None):
    """Value of discovering the listing, independent of candidate fit."""
    now_dt = now_dt or datetime.now(timezone.utc)
    score = 25
    source = (job.get("ats") or "").lower()
    directish = {"direct", "workday", "greenhouse", "lever", "ashby", "smartrecruiters",
                 "workable", "recruitee", "personio", "pinpoint", "phenom", "eightfold"}
    if source in directish:
        score += 20
    first_seen = job.get("first_seen_at")
    try:
        dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00")) if first_seen else None
    except Exception:
        dt = None
    if dt:
        hours = max(0, (now_dt - dt).total_seconds() / 3600)
        if hours <= 24:
            score += 25
        elif hours <= 72:
            score += 15
        elif hours <= 168:
            score += 7
    if job.get("new_since_last_check"):
        score += 12
    if job.get("closing_date"):
        try:
            close_dt = datetime.fromisoformat(str(job["closing_date"]).replace("Z", "+00:00"))
            days = (close_dt - now_dt).total_seconds() / 86400
            if 0 <= days <= 7:
                score += 15
        except Exception:
            pass
    return max(0, min(100, int(score)))


def job_state_identity(job):
    raw_url = str(job.get("url") or "").strip()

    if raw_url:
        try:
            parsed = urllib.parse.urlsplit(raw_url)
            host = parsed.netloc.lower()
            path = parsed.path.rstrip("/").lower()

            # CandidateManager job-detail URLs use one shared path for every
            # vacancy. The actual stable vacancy identity is carried in the
            # query string, primarily by `jid`. Stripping the query therefore
            # collapses every employer vacancy into one job.
            if "candidatemanager.net" in host:
                params = urllib.parse.parse_qs(
                    parsed.query,
                    keep_blank_values=True,
                )

                jid = (
                    params.get("jid")
                    or params.get("jobid")
                    or params.get("job_id")
                )

                if jid and jid[0]:
                    return (
                        f"{host}{path}"
                        f"?jid={str(jid[0]).strip().lower()}"
                    )

            stable_url = f"{host}{path}"

            if stable_url:
                return stable_url

        except Exception:
            stable_url = raw_url.split("?")[0].rstrip("/").lower()

            if stable_url:
                return stable_url

    return "|".join([
        _company_key(job.get("company", "")),
        normalized_title(job.get("title")),
        _norm_phrase(job.get("location")),
    ])

# ---------------------------------------------------------------------------
# Runtime modes
# FULL (default): all configured connectors + unresolved-company deep fallback.
# FAST: targeted development pass; set TARGET_COMPANIES comma-separated.
# ---------------------------------------------------------------------------
SCRAPE_MODE = os.environ.get("SCRAPE_MODE", "full").strip().lower()
SCRAPE_WORKERS = max(2, min(32, int(os.environ.get("SCRAPE_WORKERS", "16"))))
TARGET_COMPANIES = {
    _company_key(x) for x in os.environ.get("TARGET_COMPANIES", "").split(",") if x.strip()
}

def _targeted(company):
    if not TARGET_COMPANIES:
        return True
    key = _company_key(company)
    if key in TARGET_COMPANIES:
        return True
    # Allow ATS slugs/short brands such as "kpmg" to match "KPMG Ireland".
    return any(len(key) >= 4 and (key in target or target in key) for target in TARGET_COMPANIES)

def _parallel_collect(tasks, results, errors, workers=None):
    """Run independent collectors concurrently; each task=(label, company, callable)."""
    if not tasks:
        return
    with ThreadPoolExecutor(max_workers=workers or SCRAPE_WORKERS) as pool:
        future_map = {pool.submit(fn): (label, company) for label, company, fn in tasks}
        for fut in as_completed(future_map):
            label, company = future_map[fut]
            try:
                found = fut.result() or []
                results.extend(found)
                print(f"{label}/{company}: {len(found)} matches")
            except Exception as exc:
                errors.append(f"{label}/{company}: {exc}")

def _content_hash(job):
    raw = "|".join(str(job.get(k) or "") for k in ("company","title","location","url","updated_at","description_text"))
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def scrape_irish_life():
    company = "Irish Life"
    source = "https://life-careers.com/irishlife/go/irishlife/3805801"

    if not HAS_PLAYWRIGHT:
        print("  ! Irish Life: Playwright unavailable")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
            )

            page.goto(source, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            for item in links:
                href = str(item.get("href") or "").strip()
                title = re.sub(
                    r"\s+",
                    " ",
                    str(item.get("text") or ""),
                ).strip()

                if "/irishlife/job/" not in href.lower():
                    continue
                if not title:
                    continue

                m = re.search(r"/(\d+)/?(?:[?#].*)?$", href)
                if not m:
                    continue

                job_id = m.group(1)
                canonical = href.split("#")[0]

                path = urllib.parse.unquote(
                    urllib.parse.urlparse(canonical).path
                )

                location = "Ireland"

                if re.search(r"/job/Dublin-", path, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"/job/Dundalk-", path, re.I):
                    location = "Dundalk, Ireland"
                elif re.search(r"/job/Cork-", path, re.I):
                    location = "Cork, Ireland"
                elif re.search(r"/job/Galway-", path, re.I):
                    location = "Galway, Ireland"
                elif re.search(r"/job/Limerick-", path, re.I):
                    location = "Limerick, Ireland"
                elif re.search(r"/job/Nationwide-", path, re.I):
                    location = "Ireland"

                results[job_id] = {
                    "company": company,
                    "ats": "successfactors",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": "",
                }

            browser.close()

    except Exception as exc:
        print(f"  ! Irish Life scrape failed: {exc}")

    print(f"  Irish Life official careers: {len(results)} jobs")
    return list(results.values())


def scrape_ups():
    company = "UPS Ireland"

    source = (
        "https://www.jobs-ups.com/global/en/search-results"
        "?p=ChIJ5QX6zvnKd0gRYREw9umce3I"
        "&location=Ireland%2C%20Shefford%2C%20UK"
        "&latitude=53.40833676721639"
        "&longitude=-6.160288504069749"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! UPS Ireland: Playwright unavailable")
        return []

    results = {}
    discovered = {}

    def clean(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def normalize_location(text):
        text = clean(text)

        city_map = [
            ("Dublin", "Dublin, Ireland"),
            ("Swords", "Swords, Ireland"),
            ("Finglas", "Dublin, Ireland"),
            ("Santry", "Dublin, Ireland"),
            ("Ballymount", "Dublin, Ireland"),
            ("Blanchardstown", "Dublin, Ireland"),
            ("Cork", "Cork, Ireland"),
            ("Little Island", "Little Island, Cork, Ireland"),
            ("Galway", "Galway, Ireland"),
            ("Limerick", "Limerick, Ireland"),
            ("Shannon", "Shannon, Ireland"),
            ("Athlone", "Athlone, Ireland"),
            ("Kilkenny", "Kilkenny, Ireland"),
            ("Waterford", "Waterford, Ireland"),
            ("Wexford", "Wexford, Ireland"),
            ("Drogheda", "Drogheda, Ireland"),
            ("Dundalk", "Dundalk, Ireland"),
            ("Naas", "Naas, Ireland"),
            ("Kildare", "Kildare, Ireland"),
        ]

        for needle, normalized in city_map:
            if re.search(
                rf"\b{re.escape(needle)}\b",
                text,
                re.I,
            ):
                return normalized

        return "Ireland"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(4500)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            for item in links:
                href = clean(item.get("href"))
                title = clean(item.get("text"))

                m = re.search(
                    r"jobs-ups\.com/global/en/job/"
                    r"(R\d+)/",
                    href,
                    re.I,
                )

                if not m:
                    continue

                if not title:
                    continue

                job_id = m.group(1).upper()

                discovered[job_id] = {
                    "title": title,
                    "url": href.split("?")[0].split("#")[0],
                }

            page.close()

            for job_id, item in discovered.items():
                title = item["title"]
                canonical = item["url"]

                detail = context.new_page()

                body = ""
                html_text = ""

                try:
                    detail.goto(
                        canonical,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    detail.wait_for_timeout(1000)

                    body = detail.locator("body").inner_text(
                        timeout=15000
                    )

                    html_text = detail.content()

                except Exception:
                    detail.close()
                    continue

                # -------------------------------------------------
                # Prefer structured JobPosting location data.
                # -------------------------------------------------
                structured_location = ""
                ireland_confirmed = False

                scripts = re.findall(
                    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
                    r'(.*?)</script>',
                    html_text,
                    re.I | re.S,
                )

                for script in scripts:
                    raw = script.replace("\\/", "/")

                    # Explicit country validation.
                    if re.search(
                        r'"addressCountry"\s*:\s*'
                        r'(?:"IE"|"Ireland"|'
                        r'\{[^{}]*"name"\s*:\s*"Ireland")',
                        raw,
                        re.I | re.S,
                    ):
                        ireland_confirmed = True

                    # Capture useful city/locality text.
                    mloc = re.search(
                        r'"addressLocality"\s*:\s*"([^"]+)"',
                        raw,
                        re.I,
                    )

                    if mloc:
                        structured_location += " " + mloc.group(1)

                    mregion = re.search(
                        r'"addressRegion"\s*:\s*"([^"]+)"',
                        raw,
                        re.I,
                    )

                    if mregion:
                        structured_location += " " + mregion.group(1)

                # -------------------------------------------------
                # Fallback to visible detail text.
                # -------------------------------------------------

                # Republic of Ireland evidence.
                republic_evidence = re.search(
                    r"\bIreland\b|"
                    r"\bRepublic of Ireland\b|"
                    r"\bDublin\b|"
                    r"\bCork\b|"
                    r"\bGalway\b|"
                    r"\bLimerick\b|"
                    r"\bShannon\b|"
                    r"\bAthlone\b|"
                    r"\bKildare\b|"
                    r"\bNaas\b|"
                    r"\bSwords\b|"
                    r"\bDundalk\b|"
                    r"\bDrogheda\b|"
                    r"\bWaterford\b|"
                    r"\bKilkenny\b|"
                    r"\bWexford\b",
                    body,
                    re.I,
                )

                # Strong UK/NI-only evidence.
                uk_evidence = re.search(
                    r"\bUnited Kingdom\b|"
                    r"\bShefford\b|"
                    r"\bEngland\b|"
                    r"\bScotland\b|"
                    r"\bWales\b|"
                    r"\bBelfast\b|"
                    r"\bNorthern Ireland\b",
                    body,
                    re.I,
                )

                if not ireland_confirmed:
                    if not republic_evidence:
                        detail.close()
                        continue

                    # Reject pages whose only location evidence is UK/NI.
                    if uk_evidence and not re.search(
                        r"\bDublin\b|"
                        r"\bCork\b|"
                        r"\bGalway\b|"
                        r"\bLimerick\b|"
                        r"\bShannon\b|"
                        r"\bAthlone\b|"
                        r"\bKildare\b|"
                        r"\bNaas\b|"
                        r"\bSwords\b|"
                        r"\bDundalk\b|"
                        r"\bDrogheda\b|"
                        r"\bWaterford\b|"
                        r"\bKilkenny\b|"
                        r"\bWexford\b",
                        body,
                        re.I,
                    ):
                        detail.close()
                        continue

                location_source = (
                    structured_location + " " + body[:4000]
                )

                location = normalize_location(
                    location_source
                )

                results[job_id] = {
                    "company": company,
                    "ats": "phenom",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": body[:5000],
                }

                detail.close()

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! UPS Ireland scrape failed: {exc}")

    print(
        f"  UPS official Ireland careers: "
        f"{len(results)} jobs from "
        f"{len(discovered)} search results"
    )

    return list(results.values())


def scrape_three_ireland():
    company = "Three Ireland"
    source = (
        "https://three-ireland.csod.com/ux/ats/careersite/5/home"
        "?c=three-ireland"
        "&lq=Ireland"
        "&pl=ChIJ-ydAXOS6WUgRCPTbzjQSfM8"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! Three Ireland: Playwright unavailable")
        return []

    results = {}

    def clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(4000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            for item in links:
                href = clean(item.get("href"))
                title = clean(item.get("text"))

                m = re.search(
                    r"/careersite/5/home/requisition/(\d+)",
                    href,
                    re.I,
                )

                if not m or not title:
                    continue

                req_id = m.group(1)
                canonical = href.split("#")[0]

                location = "Ireland"

                # Titles expose many retail locations directly.
                location_map = [
                    ("Drogheda", "Drogheda, Ireland"),
                    ("Sligo", "Sligo, Ireland"),
                    ("Mary Street", "Dublin, Ireland"),
                    ("Navan", "Navan, Ireland"),
                    ("Limerick", "Limerick, Ireland"),
                    ("Athlone", "Athlone, Ireland"),
                    ("Patrick St", "Cork, Ireland"),
                    ("Tralee", "Tralee, Ireland"),
                    ("Bray", "Bray, Ireland"),
                    ("Mahon Point", "Cork, Ireland"),
                    ("Dublin", "Dublin, Ireland"),
                    ("Cork", "Cork, Ireland"),
                    ("Galway", "Galway, Ireland"),
                ]

                for needle, normalized in location_map:
                    if re.search(
                        rf"\b{re.escape(needle)}\b",
                        title,
                        re.I,
                    ):
                        location = normalized
                        break

                results[req_id] = {
                    "company": company,
                    "ats": "csod",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": "",
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! Three Ireland scrape failed: {exc}")

    print(
        f"  Three Ireland official careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())


def scrape_tjx_ireland():
    company = "TK Maxx Ireland"
    source = (
        "https://jobs.tjx.com/global/en/search-results"
        "?keywords="
        "&p=ChIJ-ydAXOS6WUgRCPTbzjQSfM8"
        "&location=Ireland"
    )

    if not HAS_PLAYWRIGHT:
        print("  ! TK Maxx Ireland: Playwright unavailable")
        return []

    results = {}
    discovered = {}

    def clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                viewport={"width": 1440, "height": 1600},
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(4000)

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || "").trim()
                }))"""
            )

            for item in links:
                href = clean(item.get("href"))
                title = clean(item.get("text"))

                m = re.search(
                    r"jobs\.tjx\.com/global/en/job/"
                    r"(REQ\d+)/",
                    href,
                    re.I,
                )

                if not m or not title:
                    continue

                job_id = m.group(1).upper()

                discovered[job_id] = {
                    "title": title,
                    "url": href.split("#")[0],
                }

            page.close()

            # Detail pages improve city/location accuracy.
            for job_id, item in discovered.items():
                title = item["title"]
                canonical = item["url"]

                location = "Ireland"
                description = ""

                detail = context.new_page()

                try:
                    detail.goto(
                        canonical,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    detail.wait_for_timeout(600)

                    body = detail.locator("body").inner_text(
                        timeout=10000
                    )
                    description = body[:5000]

                    city_map = [
                        ("Dublin", "Dublin, Ireland"),
                        ("Cork", "Cork, Ireland"),
                        ("Galway", "Galway, Ireland"),
                        ("Limerick", "Limerick, Ireland"),
                        ("Waterford", "Waterford, Ireland"),
                        ("Kilkenny", "Kilkenny, Ireland"),
                        ("Sligo", "Sligo, Ireland"),
                        ("Athlone", "Athlone, Ireland"),
                        ("Drogheda", "Drogheda, Ireland"),
                        ("Navan", "Navan, Ireland"),
                        ("Tralee", "Tralee, Ireland"),
                        ("Letterkenny", "Letterkenny, Ireland"),
                        ("Wexford", "Wexford, Ireland"),
                    ]

                    for needle, normalized in city_map:
                        if re.search(
                            rf"\b{re.escape(needle)}\b",
                            body,
                            re.I,
                        ):
                            location = normalized
                            break

                except Exception:
                    pass

                detail.close()

                results[job_id] = {
                    "company": company,
                    "ats": "phenom",
                    "title": title[:300],
                    "location": location,
                    "url": canonical,
                    "updated_at": None,
                    "description_text": description,
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! TK Maxx Ireland scrape failed: {exc}")

    print(
        f"  TK Maxx Ireland official careers: "
        f"{len(results)} jobs"
    )

    return list(results.values())

def main():
    profile = load_candidate_profile()
    results = []
    errors = []

    print(f"SCRAPE_MODE={SCRAPE_MODE} workers={SCRAPE_WORKERS} targets={len(TARGET_COMPANIES) or 'all'}")
    tasks = []
    for slug in GREENHOUSE_COMPANIES:
        if _targeted(slug): tasks.append(("greenhouse", slug, lambda slug=slug: scrape_greenhouse(slug)))
    for slug in LEVER_COMPANIES:
        if _targeted(slug): tasks.append(("lever", slug, lambda slug=slug: scrape_lever(slug)))
    for slug in ASHBY_COMPANIES:
        if _targeted(slug): tasks.append(("ashby", slug, lambda slug=slug: scrape_ashby(slug)))
    for company, tenant, wd_host, site in WORKDAY_COMPANIES:
        if _targeted(company): tasks.append(("workday", company, lambda company=company,tenant=tenant,wd_host=wd_host,site=site: scrape_workday(company,tenant,wd_host,site)))
    for company_id in SMARTRECRUITERS_COMPANIES:
        if _targeted(company_id): tasks.append(("smartrecruiters", company_id, lambda company_id=company_id: scrape_smartrecruiters(company_id)))
    for slug in WORKABLE_COMPANIES:
        if _targeted(slug): tasks.append(("workable", slug, lambda slug=slug: scrape_workable(slug)))
    for slug in RECRUITEE_COMPANIES:
        if _targeted(slug): tasks.append(("recruitee", slug, lambda slug=slug: scrape_recruitee(slug)))
    for slug in PERSONIO_COMPANIES:
        if _targeted(slug): tasks.append(("personio", slug, lambda slug=slug: scrape_personio(slug)))
    for slug in PINPOINT_COMPANIES:
        if _targeted(slug): tasks.append(("pinpoint", slug, lambda slug=slug: scrape_pinpoint(slug)))
    _parallel_collect(tasks, results, errors)

    # Exact enterprise-platform mappings (Phenom / Eightfold). Validate before
    # scraping so a stale mapping cannot silently pollute the dataset.
    enterprise_sess = _session()
    if enterprise_sess:
        for company, slug in KNOWN_EIGHTFOLD_MAPPINGS.items():
            if not _targeted(company):
                continue
            try:
                if _probe_platform("eightfold", slug, enterprise_sess):
                    found = _scrape_eightfold(company, slug, enterprise_sess)
                    _mark_connector_health(company, True, "Official Eightfold board loaded")
                    results.extend(found)
                    print(f"eightfold/{company}: {len(found)} Ireland jobs")
                else:
                    errors.append(f"eightfold/{company}: endpoint validation failed")
            except Exception as e:
                errors.append(f"eightfold/{company}: {e}")
        for company, slug in KNOWN_PHENOM_MAPPINGS.items():
            if not _targeted(company):
                continue
            try:
                if _probe_platform("phenom", slug, enterprise_sess):
                    found = _scrape_phenom(company, slug, enterprise_sess)
                    _mark_connector_health(company, True, "Official Phenom board loaded")
                    results.extend(found)
                    print(f"phenom/{company}: {len(found)} Ireland jobs")
                else:
                    errors.append(f"phenom/{company}: endpoint validation failed")
            except Exception as e:
                errors.append(f"phenom/{company}: {e}")

    # Browser-heavy proprietary boards belong to the nightly audit. A small
    # worker pool keeps that audit bounded without overwhelming the runner.
    if SCRAPE_MODE != "fast":
        direct_tasks = [
            ("direct", company, lambda company=company: scrape_direct_company(company))
            for company in DIRECT_COMPANY_CONNECTORS
            if _targeted(company)
        ]
        _parallel_collect(direct_tasks, results, errors, workers=3)

    # Suman-style dynamic ATS discovery for companies not already wired into a
    # known connector. Confirmed mappings persist in ats_platform_cache.json.
    initial_registry = build_company_registry(include_cache=False)
    if TARGET_COMPANIES:
        initial_registry = [x for x in initial_registry if _targeted(x.get("company", ""))]
    if SCRAPE_MODE != "fast":
        try:
            dynamic_found, _dynamic_mappings = discover_and_scrape_manual(initial_registry)
            results.extend(dynamic_found)
        except Exception as e:
            errors.append(f"dynamic ATS discovery: {e}")

    # The nightly full audit runs the universal structured-data fallback.
    if SCRAPE_MODE != "fast":
        jsonld_tasks = []
        for company, url, _source_type, _category in _load_company_master():
            if not url or not _targeted(company):
                continue
            jsonld_tasks.append(("jsonld", company, lambda company=company,url=url: scrape_jsonld(company, url)))
        _parallel_collect(jsonld_tasks, results, errors, workers=min(SCRAPE_WORKERS, 20))

    run_broad_aggregators = SCRAPE_MODE != "fast"
    for country in (ADZUNA_COUNTRIES if run_broad_aggregators else []):
        for query in DIRECT_QUERIES:
            try:
                found = scrape_adzuna(country, query)
                results.extend(found)
                if found:
                    print(f"adzuna/{country} ({query}): {len(found)} matches")
            except Exception as e:
                errors.append(f"adzuna/{country} ({query}): {e}")
            time.sleep(0.3)

    for locale in (CAREERJET_LOCALES if run_broad_aggregators else []):
        for query in DIRECT_QUERIES:
            try:
                found = scrape_careerjet(locale, query)
                results.extend(found)
                if found:
                    print(f"careerjet/{locale} ({query}): {len(found)} matches")
            except Exception as e:
                errors.append(f"careerjet/{locale} ({query}): {e}")
            time.sleep(0.3)

    for query in (DIRECT_QUERIES if run_broad_aggregators else []):
        try:
            found = scrape_jooble(query, "Ireland" if IRELAND_ONLY else "")
            results.extend(found)
            if found:
                print(f"jooble ({query}): {len(found)} matches")
        except Exception as e:
            errors.append(f"jooble ({query}): {e}")
        time.sleep(0.3)

    if SCRAPE_MODE != "fast" and _targeted("Amazon"):
        try:
            found = scrape_amazon("")
            results.extend(found)
            print(f"direct/Amazon: {len(found)} Ireland jobs")
        except Exception as e:
            errors.append(f"direct/Amazon: {e}")
        time.sleep(0.5)

    if SCRAPE_MODE != "fast" and _targeted("Netflix"):
        try:
            found = scrape_netflix("")
            results.extend(found)
            print(f"direct/Netflix: {len(found)} Ireland jobs")
        except Exception as e:
            errors.append(f"direct/Netflix: {e}")
        time.sleep(0.5)

    # Targeted second pass for configured companies that still returned zero.
    # This uses the already-configured free aggregator API, but searches by
    # employer name instead of relying on a single broad first page.
    try:
        # Priority rescue is cheap and important in FAST mode. The helper itself
        # respects TARGET_COMPANIES, so only the selected priority employer runs.
        priority_rescued = rescue_priority_ireland_employers(results)
        results.extend(priority_rescued)

        # The broader curated-company rescue remains FULL-only.
        if SCRAPE_MODE != "fast":
            rescue_registry = build_company_registry(include_cache=True)
            rescued = rescue_zero_companies_with_aggregators(results, rescue_registry)
            results.extend(rescued)
    except Exception as e:
        errors.append(f"zero-company targeted rescue: {e}")


    # The committed Harshit master CSV is the SINGLE source of truth for the
    # dashboard company universe.
    #
    # Apply this to EVERY source, including aggregators. Previously Jooble,
    # Adzuna and Careerjet were allowed to introduce adjacent employers that
    # were not present in the master CSV, which caused removed/unwanted
    # companies to leak back into data.json and the HTML company filter.
    # A fast run updates what it checked and carries the remaining jobs forward;
    # the nightly full audit remains responsible for removals and closures.
    if SCRAPE_MODE == "fast":
        try:
            with open("data.json", encoding="utf-8") as f:
                previous_jobs = (json.load(f) or {}).get("jobs", [])
            results.extend(previous_jobs)
            print(f"Fast refresh: carried forward {len(previous_jobs)} prior jobs")
        except (FileNotFoundError, json.JSONDecodeError, TypeError, AttributeError):
            pass

    curated_keys = curated_company_key_set()

    filtered_results = []
    dropped_non_curated = 0

    for j in results:
        if not is_real_job_title(j.get("title")):
            continue
        display_company = company_display_name(j.get("company", ""))
        ck = _company_key(display_company)

        if ck not in curated_keys:
            dropped_non_curated += 1
            continue

        j["company"] = display_company
        filtered_results.append(j)

    if dropped_non_curated:
        print(
            f"CSV company-universe filter: dropped "
            f"{dropped_non_curated} jobs from companies not in the master CSV"
        )


    results = filtered_results

    # ============================================================
    # GLOBAL REPUBLIC OF IRELAND EMPLOYMENT-LOCATION GATE
    #
    # Applies to EVERY company and EVERY source.
    #
    # IMPORTANT:
    # - Structured job location is authoritative.
    # - Description text must NEVER make a foreign job look Irish.
    # - Multi-location jobs stay if Republic of Ireland is one
    #   explicitly offered work location.
    # - Belfast / Northern Ireland alone is rejected.
    # - Generic EMEA/Europe/worldwide remote is NOT enough unless
    #   Ireland is explicitly present in the structured location.
    # ============================================================

    _ROI_PLACES = (
        "dublin", "cork", "galway", "limerick", "waterford",
        "kilkenny", "sligo", "athlone", "drogheda", "dundalk",
        "navan", "naas", "kildare", "wexford", "tralee", "bray",
        "westport", "mayo", "ringaskiddy", "shannon",
        "letterkenny", "swords", "clonee", "leixlip", "maynooth",
        "carlow", "tipperary", "clare", "meath", "wicklow",
        "laois", "offaly", "longford", "roscommon", "monaghan",
        "cavan", "donegal", "westmeath", "louth", "killarney",
        "ennis", "mullingar", "portlaoise", "tullamore",
        "ballina", "castlebar", "little island",
    )

    _SELF_EMPLOYED_MARKERS = (
        "self-employed",
        "self employed",
        "freelance",
        "freelancer",
        "independent contractor",
    )

    _REMOTE_MARKERS = (
        "remote",
        "home based",
        "home-based",
        "work from home",
        "virtual",
    )

    def _norm_structured_location(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip().lower()

    def _job_can_be_worked_from_ireland(job):
        loc = _norm_structured_location(job.get("location"))
        title = _norm_structured_location(job.get("title"))
        employment = _norm_structured_location(
            job.get("employment_type")
        )

        # Stamp 1G employee roles only; not self-employment.
        if any(
            marker in f"{title} {employment}"
            for marker in _SELF_EMPLOYED_MARKERS
        ):
            return False, "self-employed/freelance"

        if not loc:
            return False, "missing structured location"

        # Any explicit Republic of Ireland city/county is enough,
        # even where foreign alternatives also exist.
        #
        # KEEP examples:
        # London OR Dublin
        # Paris; Cork, Ireland
        # Amsterdam; Dublin
        if any(place in loc for place in _ROI_PLACES):
            return True, "Republic of Ireland location"

        if "republic of ireland" in loc:
            return True, "Republic of Ireland location"

        # Northern Ireland is outside the Republic.
        if "northern ireland" in loc or "belfast" in loc:
            return False, "Northern Ireland / UK"

        # ATS country value "Ireland" means Republic of Ireland
        # unless NI was explicitly detected above.
        if re.search(r"\bireland\b", loc):
            return True, "Ireland location"

        # Remote alone does not prove an Irish employing location.
        if any(marker in loc for marker in _REMOTE_MARKERS):
            return False, "remote without explicit Ireland"

        return False, "no Republic of Ireland work location"

    _ireland_kept = []
    _ireland_rejected = []

    for _job in results:
        _allowed, _reason = _job_can_be_worked_from_ireland(_job)

        if _allowed:
            _job["ireland_work_eligible"] = True
            _job["ireland_work_reason"] = _reason
            _ireland_kept.append(_job)
        else:
            _job["ireland_work_eligible"] = False
            _job["ireland_work_reason"] = _reason
            _ireland_rejected.append(_job)

    print(
        "Global Ireland employment-location gate: "
        f"{len(_ireland_kept)} kept, "
        f"{len(_ireland_rejected)} rejected"
    )

    if _ireland_rejected:
        for _job in _ireland_rejected[:40]:
            print(
                "  -",
                _job.get("company"),
                "|",
                _job.get("title"),
                "|",
                _job.get("location"),
                "|",
                _job.get("ireland_work_reason"),
            )

        if len(_ireland_rejected) > 40:
            print(
                f"  ... {len(_ireland_rejected) - 40} more rejected jobs"
            )

    results = _ireland_kept

    # ============================================================
    # STAMP 1G / REPUBLIC OF IRELAND EMPLOYMENT ELIGIBILITY GATE
    #
    # Dashboard policy:
    #
    # A job is retained only when its STRUCTURED location makes it
    # possible to perform the employment while based in the
    # Republic of Ireland.
    #
    # IMPORTANT:
    #   Description/body text is NEVER used to establish location.
    #   Boilerplate often mentions Dublin even for US/UK jobs.
    #
    # Examples:
    #   Dublin                         -> keep
    #   London OR Dublin               -> keep
    #   Paris; Cork, Ireland           -> keep
    #   Ireland / United Kingdom       -> keep
    #   San Jose                       -> drop
    #   Belfast                        -> drop
    #   Northern Ireland               -> drop
    #   Remote - Ireland               -> keep
    #   Remote EMEA                    -> ambiguous -> drop
    #
    # Graduate Stamp 1G also does not permit self-employment, so
    # explicitly freelance / self-employed roles are removed.
    # ============================================================

    _ROI_CITIES_COUNTIES = (
        "dublin",
        "cork",
        "galway",
        "limerick",
        "waterford",
        "kilkenny",
        "sligo",
        "athlone",
        "drogheda",
        "dundalk",
        "navan",
        "naas",
        "kildare",
        "wexford",
        "tralee",
        "bray",
        "westport",
        "mayo",
        "ringaskiddy",
        "shannon",
        "letterkenny",
        "swords",
        "clonee",
        "leixlip",
        "maynooth",
        "carlow",
        "tipperary",
        "clare",
        "meath",
        "wicklow",
        "laois",
        "offaly",
        "longford",
        "roscommon",
        "monaghan",
        "cavan",
        "donegal",
        "westmeath",
        "louth",
        "clare",
        "killarney",
        "ennis",
        "mullingar",
        "portlaoise",
        "tullamore",
        "ballina",
        "castlebar",
        "little island",
    )

    _SELF_EMPLOYED_MARKERS = (
        "self-employed",
        "self employed",
        "freelance",
        "freelancer",
        "independent contractor",
    )

    def _norm_job_location(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip().lower()

    def _roi_structured_location(location):
        """
        Return True only where the structured job location explicitly
        offers a Republic of Ireland work location.

        Foreign alternatives do NOT invalidate an otherwise valid Irish
        option:
            London OR Dublin       -> True
            Amsterdam; Dublin     -> True
            Paris; Cork           -> True
        """

        loc = _norm_job_location(location)

        if not loc:
            return False

        # Explicit ROI city/county beats foreign alternatives.
        if any(place in loc for place in _ROI_CITIES_COUNTIES):
            return True

        # "Republic of Ireland" is unambiguous.
        if "republic of ireland" in loc:
            return True

        # Northern Ireland / Belfast alone is outside ROI.
        if (
            "northern ireland" in loc
            or "belfast" in loc
        ):
            return False

        # Most ATS systems use the country value "Ireland" for ROI.
        #
        # This also deliberately retains:
        #     Ireland / United Kingdom
        #     Ireland or Germany
        #
        # because Ireland is an offered employment location.
        if re.search(r"\bireland\b", loc):
            return True

        return False

    def _explicit_ireland_remote(location):
        """
        Remote employment is accepted only where the STRUCTURED location
        itself explicitly associates the job with Ireland.

        We deliberately do NOT treat generic:
            Remote - EMEA
            Europe Remote
            Worldwide Remote
        as automatically Ireland-eligible because the employer may lack
        an Irish employing entity/payroll arrangement.
        """

        loc = _norm_job_location(location)

        if not loc:
            return False

        remote = bool(
            re.search(
                r"\bremote\b|"
                r"\bhome[- ]based\b|"
                r"\bwork from home\b|"
                r"\bvirtual\b",
                loc,
                re.I,
            )
        )

        if not remote:
            return False

        # Explicit Irish remote location.
        if (
            "ireland" in loc
            or any(place in loc for place in _ROI_CITIES_COUNTIES)
        ):
            # Again exclude NI-only.
            if (
                ("northern ireland" in loc or "belfast" in loc)
                and not any(
                    place in loc
                    for place in _ROI_CITIES_COUNTIES
                )
            ):
                return False

            return True

        return False

    def _stamp1g_employment_allowed(job):
        """
        Conservative dashboard eligibility test for a graduate Stamp 1G
        holder residing in the Republic of Ireland.

        This is an employment-location filter, not immigration/legal
        advice and not a guarantee that an employer will hire any
        particular candidate.
        """

        loc = _norm_job_location(job.get("location"))
        title = re.sub(
            r"\s+",
            " ",
            str(job.get("title") or ""),
        ).strip().lower()

        employment = re.sub(
            r"\s+",
            " ",
            str(job.get("employment_type") or ""),
        ).strip().lower()

        # Stamp 1G graduates may be employees but may not operate a
        # business / be self-employed.
        employment_text = f"{title} {employment}"

        if any(
            marker in employment_text
            for marker in _SELF_EMPLOYED_MARKERS
        ):
            return False, "self-employed/freelance"

        # Authoritative structured location says Ireland is available.
        if _roi_structured_location(loc):
            return True, "Ireland work location"

        # Explicit Ireland-based remote location.
        if _explicit_ireland_remote(loc):
            return True, "Ireland remote"

        # No description-text fallback. This is intentional.
        return False, "no explicit Republic of Ireland work location"

    _stamp1g_kept = []
    _stamp1g_rejected = []

    for _job in results:
        _allowed, _reason = _stamp1g_employment_allowed(_job)

        if _allowed:
            _job["stamp1g_eligible"] = True
            _job["stamp1g_reason"] = _reason
            _stamp1g_kept.append(_job)
        else:
            _job["stamp1g_eligible"] = False
            _job["stamp1g_reason"] = _reason
            _stamp1g_rejected.append(_job)

    print(
        "Stamp 1G Ireland-location gate: "
        f"{len(_stamp1g_kept)} kept, "
        f"{len(_stamp1g_rejected)} rejected"
    )

    if _stamp1g_rejected:
        print("  Rejected location examples:")

        for _job in _stamp1g_rejected[:30]:
            print(
                "   -",
                _job.get("company"),
                "|",
                _job.get("title"),
                "|",
                _job.get("location"),
                "|",
                _job.get("stamp1g_reason"),
            )

        if len(_stamp1g_rejected) > 30:
            print(
                f"   ... {len(_stamp1g_rejected) - 30} more"
            )

    results = _stamp1g_kept

    # Source-priority de-duplication. Direct employer/ATS records win over
    # aggregator copies of the same vacancy.
    source_priority = {
        "direct": 100, "workday": 95, "greenhouse": 95, "lever": 95, "ashby": 95,
        "smartrecruiters": 95, "workable": 94, "recruitee": 94, "personio": 94,
        "pinpoint": 94, "phenom": 93, "eightfold": 93, "oracle": 93, "jsonld": 90,
        "adzuna": 30, "jooble": 25, "careerjet": 20,
    }
    aggregator_sources = {"adzuna", "jooble", "careerjet"}
    results.sort(key=lambda j: source_priority.get((j.get("ats") or "").lower(), 50), reverse=True)

    seen_urls = set()
    seen_signatures = set()
    deduped = []
    for j in results:
        company_key = _company_key(company_display_name(j.get("company", "")))

        raw_url = (j.get("url") or "").strip()

        # Most tracking query strings should be ignored when deduplicating.
        # Accenture is an exception: its official branded job URLs encode the
        # requisition ID in ?id=, so stripping the full query would collapse
        # every Accenture vacancy into the same /jobdetails URL.
        if raw_url:
            try:
                parsed = urllib.parse.urlsplit(raw_url)
                params = urllib.parse.parse_qs(parsed.query)
                base_url = urllib.parse.urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
                ).lower()

                # Some employer sites encode the REAL vacancy ID entirely in
                # the query string. Stripping every query parameter collapses
                # dozens of distinct jobs into one URL.
                #
                # Examples:
                #   Stripe / Pinterest / MongoDB / Toast -> ?gh_jid=...
                #   Accenture -> ?id=...
                # Preserve only known identity-bearing parameters while still
                # dropping tracking parameters.
                identity_pairs = []

                for param in (
                    "gh_jid",        # Greenhouse custom career pages
                    "id",            # Accenture / generic requisition ID
                    "jobId",
                    "job_id",
                    "jobid",
                    "requisitionId",
                    "requisition_id",
                    "reqId",
                    "reqid",
                ):
                    vals = params.get(param) or []
                    if vals and str(vals[0]).strip():
                        identity_pairs.append(
                            (param.lower(), str(vals[0]).strip().lower())
                        )

                if identity_pairs:
                    identity_pairs.sort()
                    query_key = "&".join(
                        f"{k}={v}" for k, v in identity_pairs
                    )
                    url_key = f"{base_url}?{query_key}"

                elif "candidatemanager.net" in parsed.netloc.lower():
                    # CandidateManager vacancy pages share one path.
                    # The stable vacancy identity is the jid query parameter.
                    jid = (
                        params.get("jid")
                        or params.get("jobid")
                        or params.get("job_id")
                    )

                    if jid and jid[0]:
                        url_key = (
                            f"{base_url}"
                            f"?jid={str(jid[0]).strip().lower()}"
                        )
                    else:
                        url_key = base_url

                elif company_key == _company_key("Google"):
                    # Google collector currently uses a result-page URL for
                    # each visible job. Multiple vacancies therefore share
                    # the same URL. Include title in the dedupe identity so
                    # valid Google jobs are not collapsed.
                    title_part = normalized_title(j.get("title"))
                    url_key = f"{base_url}#title={title_part}"

                else:
                    url_key = base_url

            except Exception:
                url_key = raw_url.lower()
        else:
            url_key = ""

        title_key = normalized_title(j.get("title"))
        loc_key = _norm_phrase(j.get("location"))
        signature = (company_key, title_key, loc_key)
        source = (j.get("ats") or "").lower()

        if url_key and url_key in seen_urls:
            continue

        # Airbnb has repeatedly arrived through multiple sources with distinct
        # tracking/application URLs. For Airbnb only, treat identical
        # normalized title + location as one vacancy regardless of source.
        if company_key == _company_key("Airbnb") and signature in seen_signatures:
            continue

        if source in aggregator_sources and signature in seen_signatures:
            continue

        deduped.append(j)
        if url_key:
            seen_urls.add(url_key)
        if any(signature):
            seen_signatures.add(signature)

    results = deduped

    # Tag every job with a parsed posting date + recency bucket, so the
    # dashboard can filter by "last 24h / 7d / 30d" without re-parsing.
    for j in results:
        j["company"] = company_display_name(j.get("company", ""))
        posted_dt = parse_posted_date(j.get("updated_at"))
        j["posted_at_parsed"] = posted_dt.isoformat() if posted_dt else None
        j["recency"] = recency_bucket(posted_dt)
        j["employment_type"] = employment_type(j.get("title"))
        j["sector"] = sector_for(j.get("company"))
        j["country"] = "Ireland" if IRELAND_ONLY else country_from_location(j.get("location"))
        j["ireland_area"] = ireland_area(j.get("location"))
        description_text = j.get("description_text") or ""
        visa_status, visa_snippet = classify_visa_sponsorship(
            j.get("title"), j.get("location"), description_text,
        )
        j["visa_sponsorship"] = visa_status
        j["visa_snippet"] = visa_snippet
        # Generic CV/job matching metadata. No user-profile-specific title filtering.
        j["match_keywords"] = resume_match_keywords(
            j.get("title"), j.get("company"), j.get("sector"), j.get("location"), description_text
        )
        # Broad collection stays untouched; profile ranking is metadata only.
        j.update(candidate_match(j, description_text, profile))
        j.setdefault("work_mode", "remote" if "remote" in (j.get("location") or "").lower()
                     else "hybrid" if "hybrid" in (j.get("location") or "").lower() else "unspecified")
        j.setdefault("closing_date", None)
        j.setdefault("requisition_id", None)
        j.setdefault("salary", None)
        j["content_hash"] = _content_hash(j)
        if not j.get("source_type"):
            j["source_type"] = (
                "employer_direct"
                if (j.get("ats") or "").lower() in
                {"direct","workday","greenhouse","lever","ashby","smartrecruiters",
                 "workable","recruitee","personio","pinpoint","phenom","eightfold","oracle","jsonld"}
                else "aggregator" if (j.get("ats") or "").lower() in {"adzuna","jooble","careerjet"}
                else "other"
            )
        j.pop("description_text", None)

    # Persistent freshness state: supports old {id: "timestamp"} files and richer v2 objects.
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    try:
        with open("seen_jobs.json", encoding="utf-8") as f:
            seen_jobs = json.load(f)
        if not isinstance(seen_jobs, dict):
            seen_jobs = {}
    except Exception:
        seen_jobs = {}

    current_seen = dict(seen_jobs)
    current_ids = set()
    for j in results:
        identity = job_state_identity(j)
        current_ids.add(identity)
        prior = seen_jobs.get(identity)
        prior_obj = prior if isinstance(prior, dict) else {}
        if isinstance(prior, dict):
            first_seen = prior.get("first_seen") or prior.get("first_seen_at") or now_iso
        elif isinstance(prior, str):
            first_seen = prior
        else:
            first_seen = now_iso

        previous_hash = prior_obj.get("content_hash")
        changed = bool(previous_hash and previous_hash != j.get("content_hash"))
        j["new_since_last_check"] = prior is None
        j["updated_since_last_check"] = changed
        j["lifecycle_status"] = "new" if prior is None else "updated" if changed else "active"
        j["first_seen_at"] = first_seen
        j["last_seen_at"] = now_iso
        j["last_verified_at"] = now_iso
        j["active"] = True
        j["discovery_score"] = discovery_value(j, now_dt)

        current_seen[identity] = {
            "first_seen": first_seen, "last_seen": now_iso, "last_verified": now_iso,
            "company": j.get("company"), "title": j.get("title"),
            "location": j.get("location"), "url": j.get("url"), "ats": j.get("ats"),
            "updated_at": j.get("updated_at"), "content_hash": j.get("content_hash"),
            "active": True, "missing_runs": 0,
        }

    # Missing jobs are not immediately declared closed: transient ATS failures happen.
    # Only advance missing counters on FULL runs; targeted FAST tests never close jobs.
    if SCRAPE_MODE != "fast":
        for identity, prior in list(current_seen.items()):
            if identity in current_ids or not isinstance(prior, dict):
                continue
            misses = int(prior.get("missing_runs") or 0) + 1
            prior["missing_runs"] = misses
            prior["last_verified"] = now_iso
            if misses >= 3:
                prior["active"] = False
                prior.setdefault("closed_at", now_iso)
            current_seen[identity] = prior

    # Prune closed history after 30 days; active jobs are NEVER removed merely for age.
    history_cutoff = now_dt - timedelta(days=30)
    for identity, prior in list(current_seen.items()):
        if not isinstance(prior, dict) or prior.get("active", True):
            continue
        closed = parse_posted_date(prior.get("closed_at"))
        if closed and closed < history_cutoff:
            current_seen.pop(identity, None)

    with open("seen_jobs.json", "w", encoding="utf-8") as f:
        json.dump(current_seen, f, indent=2)

    company_registry = build_company_registry(include_cache=True)

    if MAX_AGE_DAYS is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        before = len(results)
        results = [
            j for j in results
            if not j["posted_at_parsed"] or datetime.fromisoformat(j["posted_at_parsed"]) >= cutoff
        ]
        print(f"MAX_AGE_DAYS={MAX_AGE_DAYS}: dropped {before - len(results)} stale postings")

    recency_counts = {"24h": 0, "7d": 0, "30d": 0, "older": 0, "unknown": 0}
    for j in results:
        recency_counts[j["recency"]] += 1

    source_counts = {}
    company_job_counts = {}
    for j in results:
        source_counts[j.get("ats") or "unknown"] = source_counts.get(j.get("ats") or "unknown", 0) + 1
        company_job_counts[j.get("company") or "Unknown"] = company_job_counts.get(j.get("company") or "Unknown", 0) + 1

    # A company with live jobs from an automatic source (including an aggregator)
    # should not still be presented as "manual-check". Match on normalized names.
    live_company_keys = {
        _company_key(company_display_name(j.get("company", "")))
        for j in results
        if j.get("company")
    }

    manual_check = []
    for item in company_registry:
        key = _company_key(item["company"])
        if item["automatic"] or key in live_company_keys:
            if key in live_company_keys and not item["automatic"]:
                item["automatic"] = True
                item["platform"] = "aggregator-covered"
            continue
        manual_check.append({
            "company": item["company"],
            "url": item["careers_url"],
            "platform": item["platform"],
            "status": "manual-check" if item["careers_url"] else "needs-careers-url",
        })
    manual_check.sort(key=lambda x: x["company"].lower())

    try:
        with open("company_history.json", "r", encoding="utf-8") as f:
            prior_history = json.load(f)
        prior_companies = prior_history.get("companies", prior_history)
        proven_company_keys = {
            _company_key(name)
            for name, record in prior_companies.items()
            if isinstance(record, dict) and record.get("ever_working")
        }
    except (FileNotFoundError, json.JSONDecodeError, TypeError, AttributeError):
        proven_company_keys = set()

    # Coverage diagnostics. "No live jobs" is not automatically the same as
    # "the company has no jobs"; distinguish missing connectors from configured
    # connectors that yielded no Ireland records.
    # live_company_keys already computed from normalized result company names.
    coverage_diagnostics = []
    for item in company_registry:
        key = _company_key(item["company"])
        if key in live_company_keys:
            state = "working"
            reason = "Ireland jobs returned in this run"
        elif (
            item["company"] in VERIFIED_LIVE_ZERO_COMPANIES
            and CONNECTOR_HEALTH.get(item["company"], {}).get("live")
        ):
            state = "live_zero"
            reason = "Official careers source independently verified live and currently has 0 qualifying Ireland jobs"
        elif key in proven_company_keys:
            state = "proven_zero"
            reason = "Connector previously returned verified Ireland jobs and returned 0 in this run"
        elif item.get("automatic"):
            state = "configured_zero"
            reason = "Connector is configured but returned no qualifying Ireland jobs; mapping/filter may need verification"
        else:
            state = "no_validated_connector"
            reason = "No validated automatic connector yet"
        coverage_diagnostics.append({
            "company": item["company"],
            "platform": item.get("platform"),
            "state": state,
            "reason": reason,
            "careers_url": item.get("careers_url"),
        })

    # ------------------------------------------------------------
    # Persistent connector/job history.
    #
    # A company becomes "proven working" once it has produced at least one
    # qualifying Ireland job.  That proof survives later zero-job runs.
    # company_history.json is intentionally separate from data.json so a new
    # scrape cannot erase historical positive evidence.
    # ------------------------------------------------------------
    history_path = "company_history.json"
    history_start_date = "2026-08-16"
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with open(history_path, "r") as f:
            company_history = json.load(f)
        if not isinstance(company_history, dict):
            company_history = {}
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        company_history = {}

    history_companies = company_history.setdefault("companies", {})
    company_history.setdefault("tracking_started", history_start_date)

    current_jobs_by_company = {}
    for job in results:
        company_name = job.get("company")
        if not company_name:
            continue
        current_jobs_by_company.setdefault(company_name, []).append(job)

    def _history_job_key(job):
        # Prefer stable IDs/URLs; fall back to a deterministic composite.
        for key in ("id", "job_id", "requisition_id", "url", "apply_url"):
            value = job.get(key)
            if value:
                return str(value)
        return " | ".join([
            str(job.get("company") or ""),
            str(job.get("title") or ""),
            str(job.get("location") or job.get("ireland_area") or ""),
        ])

    # Only positive evidence mutates "proven working".  Therefore a partial or
    # targeted run can never downgrade companies that were proven previously.
    for company_name, jobs_now in current_jobs_by_company.items():
        entry = history_companies.setdefault(company_name, {})
        entry.setdefault("first_working_seen", now_iso)
        entry["last_working_seen"] = now_iso
        entry["ever_working"] = True

        seen_jobs = entry.get("seen_job_keys", [])
        if not isinstance(seen_jobs, list):
            seen_jobs = []
        seen_set = set(str(x) for x in seen_jobs)

        for job in jobs_now:
            seen_set.add(_history_job_key(job))

        entry["seen_job_keys"] = sorted(seen_set)
        entry["distinct_jobs_seen"] = len(seen_set)
        entry["current_live_jobs"] = len(jobs_now)

    # Current count may become zero, but historical proof remains true.
    # Do this only for registry companies represented by this dashboard.
    for registry_item in company_registry:
        company_name = registry_item.get("company")
        if not company_name:
            continue
        entry = history_companies.get(company_name)
        if entry and entry.get("ever_working"):
            entry["current_live_jobs"] = len(current_jobs_by_company.get(company_name, []))

    proven_working_companies = sorted(
        name
        for name, entry in history_companies.items()
        if isinstance(entry, dict) and entry.get("ever_working")
    )

    historical_distinct_jobs_seen = sum(
        int(entry.get("distinct_jobs_seen", 0) or 0)
        for entry in history_companies.values()
        if isinstance(entry, dict)
    )

    company_history["updated_at"] = now_iso
    company_history["proven_working_company_count"] = len(proven_working_companies)
    company_history["historical_distinct_jobs_seen"] = historical_distinct_jobs_seen

    try:
        with open(history_path, "w") as f:
            json.dump(company_history, f, indent=2)
    except Exception as exc:
        print(f"  ! Could not write {history_path}: {exc}")

    # ------------------------------------------------------------
    # Persistent sponsorship history + official permit evidence.
    # Count UNIQUE postings, not every 15-minute scan, so history remains
    # meaningful as scrape frequency increases.
    # ------------------------------------------------------------
    sponsorship_history_path = "sponsorship_history.json"
    try:
        with open(sponsorship_history_path, encoding="utf-8") as f:
            sponsorship_history = json.load(f)
        if not isinstance(sponsorship_history, dict):
            sponsorship_history = {}
    except Exception:
        sponsorship_history = {}

    sponsorship_history.setdefault("tracking_started", now_iso)
    sponsorship_jobs = sponsorship_history.setdefault("jobs", {})

    for job in results:
        key = _history_job_key(job)
        status = job.get("visa_sponsorship") or "not_mentioned"
        rec = sponsorship_jobs.get(key)
        if not isinstance(rec, dict):
            rec = {
                "company": job.get("company"),
                "title": job.get("title"),
                "location": job.get("location"),
                "url": job.get("url"),
                "first_seen": job.get("first_seen_at") or now_iso,
            }
        rec.update({
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "url": job.get("url"),
            "status": status,
            "snippet": job.get("visa_snippet"),
            "last_seen": now_iso,
        })
        sponsorship_jobs[key] = rec

    sponsorship_company_counts = {}
    for rec in sponsorship_jobs.values():
        if not isinstance(rec, dict):
            continue
        company_name = str(rec.get("company") or "").strip()
        if not company_name:
            continue
        stats = sponsorship_company_counts.setdefault(company_name, {
            "sponsors": 0,
            "no_sponsorship": 0,
            "not_mentioned": 0,
            "total": 0,
        })
        status = rec.get("status") or "not_mentioned"
        if status not in {"sponsors", "no_sponsorship", "not_mentioned"}:
            status = "not_mentioned"
        stats[status] += 1
        stats["total"] += 1

    official_permit_stats = load_official_permit_stats()
    company_sponsorship_history = {}
    for company_name, counts in sponsorship_company_counts.items():
        summary = sponsorship_history_label(counts)
        permit = official_permit_stats.get(company_name) or {}
        total = max(1, int(counts.get("total", 0) or 0))
        explicit = int(counts.get("sponsors", 0) or 0) + int(counts.get("no_sponsorship", 0) or 0)
        company_sponsorship_history[company_name] = {
            **counts,
            "sponsor_rate": round(int(counts.get("sponsors", 0) or 0) / total, 4),
            "explicit_positive_rate": round(int(counts.get("sponsors", 0) or 0) / explicit, 4) if explicit else None,
            "label": summary["label"],
            "category": summary["category"],
            "official_permits_total": int(permit.get("total_permits", 0) or 0),
            "official_permits_by_year": permit.get("permits_by_year") or {},
            "official_matched_employer_names": permit.get("matched_employer_names") or [],
        }

    sponsorship_history["companies"] = company_sponsorship_history
    sponsorship_history["updated_at"] = now_iso
    sponsorship_history["unique_postings_tracked"] = len(sponsorship_jobs)

    try:
        with open(sponsorship_history_path, "w", encoding="utf-8") as f:
            json.dump(sponsorship_history, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"  ! Could not write {sponsorship_history_path}: {exc}")

    for job in results:
        company_name = job.get("company") or ""
        hist = company_sponsorship_history.get(company_name) or {
            "sponsors": 0, "no_sponsorship": 0, "not_mentioned": 0,
            "total": 0, "label": "No sponsorship history yet", "category": "no_data",
            "official_permits_total": 0, "official_permits_by_year": {},
        }
        job["employer_sponsorship_history"] = hist
        job["official_permits_total"] = int(hist.get("official_permits_total", 0) or 0)
        job["official_permits_by_year"] = hist.get("official_permits_by_year") or {}

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scrape_mode": SCRAPE_MODE,
        "target_companies": sorted(TARGET_COMPANIES),
        "focus": "ireland" if IRELAND_ONLY else "multi_region",
        "integrations": {
            "adzuna": bool(ADZUNA_APP_ID and ADZUNA_APP_KEY),
            "jooble": bool(JOOBLE_API_KEY),
            "careerjet": bool(CAREERJET_AFFID),
        },
        "ranking_profile": {
            "profile_id": profile.get("profile_id"),
            "version": profile.get("version"),
            "name": profile.get("name"),
        } if profile else None,
        "recency_counts": recency_counts,
        "total_companies_checked": len(company_registry),
        "registry_companies": company_registry,
        "total_matches": len(results),
        "new_since_last_check": sum(1 for j in results if j.get("new_since_last_check")),
        "source_counts": source_counts,
        "companies_with_live_jobs": len(company_job_counts),
        "company_job_counts": company_job_counts,
        "history_tracking_started": history_start_date,
        "proven_working_company_count": len(proven_working_companies),
        "proven_working_companies": proven_working_companies,
        "historical_distinct_jobs_seen": historical_distinct_jobs_seen,
        "company_history": {
            name: {
                "ever_working": bool(entry.get("ever_working")),
                "first_working_seen": entry.get("first_working_seen"),
                "last_working_seen": entry.get("last_working_seen"),
                "current_live_jobs": int(entry.get("current_live_jobs", 0) or 0),
                "distinct_jobs_seen": int(entry.get("distinct_jobs_seen", 0) or 0),
            }
            for name, entry in history_companies.items()
            if isinstance(entry, dict)
        },
        "sponsorship_history_tracking_started": sponsorship_history.get("tracking_started"),
        "sponsorship_unique_postings_tracked": len(sponsorship_jobs),
        "company_sponsorship_history": company_sponsorship_history,
        "official_permit_stats_company_count": len(official_permit_stats),
        "coverage_diagnostics": coverage_diagnostics,
        "connector_health": CONNECTOR_HEALTH,
        "live_zero_companies": [
            x for x in coverage_diagnostics if x.get("state") == "live_zero"
        ],
        "coverage_state_counts": {
            state: sum(1 for x in coverage_diagnostics if x["state"] == state)
            for state in ("working", "live_zero", "proven_zero", "configured_zero", "no_validated_connector")
        },
        "manual_check_companies": manual_check,
        "manual_check_count": len(manual_check),
        "automatic_company_count": sum(1 for x in company_registry if x["automatic"]),
        "companies_with_careers_url": sum(1 for x in company_registry if x["careers_url"]),
        "errors": errors,
        "jobs": results,
        "note": (
            "Broad Ireland job-data engine with persistent ATS discovery and optional "
            "profile-aware ranking metadata. Collection is profile-agnostic; personalization "
            "is applied after normalization so all jobs remain available."
        ),
    }

    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

    notify_github_issue(results)

    print(f"\nDone. {len(results)} matching jobs written to data.json ({len(errors)} companies errored).")


# === WORKING_IRELAND_BATCH_START ===

def _live_filtered_browser_board(
    company,
    source_url,
    job_href_pattern=r"/job/",
    max_pages=10,
):
    """
    Browser collector for an official careers page that is already filtered
    to Republic of Ireland.

    Structured/list-card location remains authoritative. Description text is
    not used to turn a foreign job into an Irish job.
    """
    if not HAS_PLAYWRIGHT:
        print(f"  ! {company}: Playwright unavailable")
        return []

    results = {}
    board_loaded = False

    def infer_location(text):
        text = str(text or "")

        places = (
            ("Letterkenny", "Letterkenny, Ireland"),
            ("Waterford", "Waterford, Ireland"),
            ("Castlebar", "Castlebar, Ireland"),
            ("Killarney", "Killarney, Ireland"),
            ("Wexford", "Wexford, Ireland"),
            ("Dundalk", "Dundalk, Ireland"),
            ("Leixlip", "Leixlip, Ireland"),
            ("Kildare", "Kildare, Ireland"),
            ("Limerick", "Limerick, Ireland"),
            ("Galway", "Galway, Ireland"),
            ("Dublin", "Dublin, Ireland"),
            ("Cork", "Cork, Ireland"),
        )

        for needle, normalized in places:
            if re.search(r"\b" + re.escape(needle) + r"\b", text, re.I):
                return normalized

        if re.search(r"\bIreland\b|\bIRL\b|,\s*IE\b", text, re.I):
            return "Ireland"

        return ""

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )

            page = browser.new_page(
                viewport={"width": 1440, "height": 1500},
                locale="en-IE",
            )

            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(3500)

            try:
                _dismiss_cookie_banner(page)
            except Exception:
                pass

            board_loaded = True

            for page_no in range(max_pages):
                for _scroll in range(8):
                    page.mouse.wheel(0, 2400)
                    page.wait_for_timeout(250)

                anchors = page.locator("a[href]")

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    try:
                        raw_href = a.get_attribute("href") or ""
                        href = urllib.parse.urljoin(
                            page.url,
                            raw_href,
                        ).split("#")[0]
                    except Exception:
                        continue

                    if not href:
                        continue

                    if not re.search(job_href_pattern, href, re.I):
                        continue

                    try:
                        anchor_text = re.sub(
                            r"\s+",
                            " ",
                            _browser_text(a) or "",
                        ).strip()
                    except Exception:
                        anchor_text = ""

                    node = a
                    card = anchor_text

                    for _up in range(8):
                        try:
                            candidate = _browser_text(node)
                        except Exception:
                            candidate = ""

                        if candidate and len(candidate) <= 6000:
                            card = candidate

                        if re.search(
                            r"\bIreland\b|\bIRL\b|,\s*IE\b|"
                            r"\bDublin\b|\bCork\b|\bGalway\b|"
                            r"\bLetterkenny\b|\bKildare\b|"
                            r"\bWexford\b|\bCastlebar\b|"
                            r"\bKillarney\b",
                            card,
                            re.I,
                        ):
                            break

                        try:
                            node = node.locator("..")
                        except Exception:
                            break

                    # Explicit NI-only job is outside dashboard scope.
                    if re.search(
                        r"\bBelfast\b|\bNorthern Ireland\b",
                        card,
                        re.I,
                    ) and not re.search(
                        r"\bDublin\b|\bCork\b|\bGalway\b|"
                        r"\bIreland\b(?!\s*North)",
                        card,
                        re.I,
                    ):
                        continue

                    location = infer_location(card)

                    # The board URL itself is Ireland-filtered, but keep the
                    # structured card safeguard wherever possible.
                    if not location:
                        continue

                    title = anchor_text

                    if (
                        not title
                        or title.lower() in {
                            "view job",
                            "view jobs",
                            "apply",
                            "apply now",
                            "job",
                        }
                    ):
                        lines = [
                            re.sub(r"\s+", " ", x).strip()
                            for x in str(card).splitlines()
                            if 3 <= len(x.strip()) <= 300
                        ]

                        skip = re.compile(
                            r"^(view job|apply|apply now|save job|"
                            r"full[- ]time|part[- ]time|location|"
                            r"posted|remote|hybrid)$",
                            re.I,
                        )

                        title = ""
                        for line in lines:
                            if skip.search(line):
                                continue
                            if re.search(
                                r"\bDublin\b|\bCork\b|\bGalway\b|"
                                r"\bIreland\b|,\s*IE\b|\bIRL\b",
                                line,
                                re.I,
                            ):
                                continue
                            title = line
                            break

                    if not title:
                        continue

                    canonical = href.split("?utm_")[0]
                    key = canonical.rstrip("/").lower()

                    if key in results:
                        continue

                    results[key] = {
                        "company": company,
                        "ats": "direct",
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": str(card)[:5000],
                    }

                before = len(results)

                # Try normal visible pagination.
                clicked = False

                for selector in (
                    "a:has-text('Next')",
                    "button:has-text('Next')",
                    "a[rel='next']",
                ):
                    try:
                        nxt = page.locator(selector).first

                        if (
                            nxt.count()
                            and nxt.is_visible()
                            and nxt.is_enabled()
                        ):
                            nxt.click(timeout=3000)
                            page.wait_for_timeout(1800)
                            clicked = True
                            break
                    except Exception:
                        pass

                if not clicked:
                    break

                if len(results) == before and page_no >= 1:
                    # Give one additional page a chance but avoid loops.
                    pass

            browser.close()

    except Exception as exc:
        print(f"  ! {company} browser collector failed: {exc}")

    try:
        _mark_connector_health(
            company,
            board_loaded,
            (
                f"Official Ireland careers board loaded and returned "
                f"{len(results)} qualifying jobs"
                if board_loaded
                else "Official Ireland careers board could not be verified"
            ),
            source_url,
        )
    except Exception:
        pass

    print(f"  {company} official Ireland careers: {len(results)} jobs")
    return list(results.values())

def scrape_irish_aviation_authority():
    company = "Irish Aviation Authority"
    source_url = "https://www.iaa.ie/careers"
    api_url = "https://career.recruitee.com/api/c/83823/widget/?widget=true"

    sess = _session()
    results = {}

    if sess:
        try:
            r = sess.get(api_url, timeout=30)
            r.raise_for_status()
            payload = r.json()

            offers = []

            if isinstance(payload, list):
                offers = payload
            elif isinstance(payload, dict):
                for key in (
                    "offers",
                    "jobs",
                    "items",
                    "results",
                ):
                    if isinstance(payload.get(key), list):
                        offers = payload[key]
                        break

            for row in offers:
                if not isinstance(row, dict):
                    continue

                title = str(
                    row.get("title")
                    or row.get("name")
                    or ""
                ).strip()

                location_obj = (
                    row.get("location")
                    or row.get("locations")
                    or ""
                )

                if isinstance(location_obj, dict):
                    location = " ".join(
                        str(x)
                        for x in location_obj.values()
                        if x
                    )
                elif isinstance(location_obj, list):
                    location = " ".join(
                        str(x) for x in location_obj
                    )
                else:
                    location = str(location_obj)

                blob = f"{title} {location}"

                if re.search(
                    r"\bBelfast\b|\bNorthern Ireland\b",
                    blob,
                    re.I,
                ):
                    continue

                if not re.search(
                    r"\bIreland\b|\bDublin\b|\bLeinster\b",
                    blob,
                    re.I,
                ):
                    continue

                url = str(
                    row.get("careers_url")
                    or row.get("url")
                    or row.get("apply_url")
                    or row.get("careersUrl")
                    or ""
                ).strip()

                if not title:
                    continue

                if not url:
                    slug = row.get("slug") or row.get("id")
                    if slug:
                        url = f"https://career.recruitee.com/o/{slug}"

                if not url:
                    continue

                canonical = urllib.parse.urljoin(
                    "https://career.recruitee.com/",
                    url,
                )

                results[canonical.lower()] = {
                    "company": company,
                    "ats": "recruitee",
                    "title": title[:300],
                    "location": (
                        "Dublin, Ireland"
                        if re.search(r"\bDublin\b", blob, re.I)
                        else "Ireland"
                    ),
                    "url": canonical,
                    "updated_at": (
                        row.get("published_at")
                        or row.get("created_at")
                    ),
                    "description_text": "",
                }

        except Exception as exc:
            print(f"  ! IAA Recruitee API failed: {exc}")

    # Site itself currently explicitly lists the two live vacancies.
    if not results and HAS_PLAYWRIGHT:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(locale="en-IE")
                page.goto(
                    source_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_timeout(1500)

                body = _browser_text(page.locator("body"))

                known = (
                    "Manager Aerodromes",
                    "Air Passenger Rights Officer",
                )

                for title in known:
                    if title.lower() in body.lower():
                        results[title.lower()] = {
                            "company": company,
                            "ats": "direct",
                            "title": title,
                            "location": "Dublin, Ireland",
                            "url": source_url,
                            "updated_at": None,
                            "description_text": "",
                        }

                browser.close()

        except Exception as exc:
            print(f"  ! IAA careers page fallback failed: {exc}")

    out = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official IAA careers source returned {len(out)} vacancies",
            source_url,
        )
    except Exception:
        pass

    print(f"  Irish Aviation Authority official careers: {len(out)} jobs")
    return out

def scrape_optum_ireland():
    return _live_filtered_browser_board(
        "Optum",
        (
            "https://careers.unitedhealthgroup.com/"
            "search-jobs/Ireland/34088/2/2963597/53/-8/50/2"
        ),
        r"/job/",
        max_pages=6,
    )

def scrape_palo_alto_ireland():
    return _live_filtered_browser_board(
        "Palo Alto Networks",
        (
            "https://jobs.paloaltonetworks.com/en/"
            "search-jobs/Ireland/47263/2/2963597/53/-8/50/2"
        ),
        r"/en/job/",
        max_pages=3,
    )

def scrape_primark_ireland():
    return _live_filtered_browser_board(
        "Primark / Penneys",
        (
            "https://careers.primark.com/en/location/"
            "ireland-jobs/1630/2963597/2"
        ),
        r"/en/job/",
        max_pages=8,
    )

def _ireland_final_clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def _ireland_final_loc(text):
    text = _ireland_final_clean(text)

    cities = (
        "Dublin", "Cork", "Galway", "Limerick", "Waterford",
        "Athlone", "Letterkenny", "Leixlip", "Castlebar",
        "Wexford", "Killarney", "Swords", "Carrigtwohill",
        "Kilkenny", "Naas", "Drogheda", "Dundalk", "Sligo",
        "Tralee", "Carlow", "Mullingar", "Navan", "Clonmel",
    )

    for city in cities:
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            return f"{city}, Ireland"

    if re.search(r"\bremote\b", text, re.I):
        return "Remote, Ireland"

    return "Ireland"

def _ireland_final_session():
    sess = _session()
    if sess:
        return sess

    try:
        import requests
        sess = requests.Session()
        return sess
    except Exception:
        return None

def _ireland_final_workday(company, wd, tenant, site, facet):
    sess = _ireland_final_session()
    if not sess:
        return []

    ireland_id = "04a05835925f45b3a59406a2a6b72c8a"

    origin = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{origin}/wday/cxs/{tenant}/{site}/jobs"

    source = (
        f"{origin}/{site}/?"
        f"{urllib.parse.urlencode({facet: ireland_id})}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": source,
    }

    out = {}
    offset = 0
    limit = 20

    try:
        while offset < 1000:
            payload = {
                "appliedFacets": {
                    facet: [ireland_id],
                },
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }

            r = sess.post(
                api,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if r.status_code != 200:
                print(
                    f"  ! {company} Workday HTTP "
                    f"{r.status_code}: {r.text[:250]}"
                )
                break

            data = r.json()
            rows = data.get("jobPostings") or []

            if not rows:
                break

            for row in rows:
                title = _ireland_final_clean(row.get("title"))
                path = _ireland_final_clean(row.get("externalPath"))
                locs = _ireland_final_clean(row.get("locationsText"))

                if not title or not path:
                    continue

                url = urllib.parse.urljoin(origin, path)

                bullets = row.get("bulletFields") or []
                req = _ireland_final_clean(
                    bullets[0] if bullets else ""
                )

                location = _ireland_final_loc(
                    f"{locs} {path.replace('-', ' ')}"
                )

                out[req or url.lower()] = {
                    "company": company,
                    "ats": "workday",
                    "title": title[:300],
                    "location": location,
                    "url": url,
                    "updated_at": None,
                    "description_text": locs[:5000],
                }

            total = data.get("total")
            offset += limit

            if isinstance(total, int) and offset >= total:
                break

    except Exception as exc:
        print(f"  ! {company} Workday failed: {exc}")

    jobs = list(out.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Ireland Workday returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(f"  {company} official Ireland careers: {len(jobs)} jobs")
    return jobs

def scrape_redhat():
    # Confirmed live API:
    # locationCountry => HTTP 400
    # a               => HTTP 200, total=1
    return _ireland_final_workday(
        "Red Hat",
        "wd5",
        "redhat",
        "jobs",
        "a",
    )

def _ireland_browser_title_from_url(url):
    try:
        path = urllib.parse.urlsplit(url).path.rstrip("/")
        bits = [x for x in path.split("/") if x]

        if not bits:
            return ""

        # M&S: .../<title-slug>/<numeric-id>
        if bits[-1].isdigit() and len(bits) >= 2:
            slug = bits[-2]

        # Phenom: .../job/<id>/<title-slug>
        elif len(bits) >= 2:
            slug = bits[-1]

        else:
            slug = bits[-1]

        slug = urllib.parse.unquote(slug)
        slug = re.sub(r"[_-]+", " ", slug)
        slug = re.sub(r"\s+", " ", slug).strip()

        return slug
    except Exception:
        return ""

def _ireland_browser_collect_pages(
    company,
    page_urls,
    job_regex,
    ats="official",
    stop_after_empty=True,
):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"  ! {company}: Playwright unavailable: {exc}")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/139.0 Safari/537.36"
                ),
                locale="en-IE",
            )

            page = context.new_page()

            consecutive_empty = 0

            for page_no, url in enumerate(page_urls, 1):
                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )

                    page.wait_for_timeout(1800)

                    # Trigger lazy-rendered cards.
                    for _ in range(5):
                        page.mouse.wheel(0, 1800)
                        page.wait_for_timeout(180)

                    page.mouse.wheel(0, -10000)
                    page.wait_for_timeout(250)

                except Exception as exc:
                    print(
                        f"  ! {company} browser page "
                        f"{page_no} load failed: {exc}"
                    )
                    break

                before = len(results)

                anchors = page.locator("a[href]")
                count = anchors.count()

                for i in range(count):
                    a = anchors.nth(i)

                    try:
                        href = a.get_attribute("href") or ""
                    except Exception:
                        continue

                    if not href:
                        continue

                    href = urllib.parse.urljoin(
                        page.url,
                        href,
                    ).split("#")[0]

                    if not re.search(job_regex, href, re.I):
                        continue

                    if "/apply?" in href.lower():
                        continue

                    # Strip search query from canonical job URLs.
                    parts = urllib.parse.urlsplit(href)

                    canonical = urllib.parse.urlunsplit((
                        parts.scheme,
                        parts.netloc,
                        parts.path,
                        "",
                        "",
                    ))

                    try:
                        anchor_text = re.sub(
                            r"\s+",
                            " ",
                            a.inner_text(timeout=1500) or "",
                        ).strip()
                    except Exception:
                        anchor_text = ""

                    # Try to capture surrounding card text.
                    try:
                        card_text = a.evaluate(
                            """el => {
                                let n = el;
                                for (let i = 0; i < 7 && n; i++, n = n.parentElement) {
                                    const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
                                    if (
                                        t.length > 20 &&
                                        t.length < 5000 &&
                                        (
                                            /location/i.test(t) ||
                                            /ireland/i.test(t) ||
                                            /full.?time/i.test(t) ||
                                            /job type/i.test(t) ||
                                            /reqid/i.test(t)
                                        )
                                    ) return t;
                                }
                                return (el.parentElement?.innerText || el.innerText || '')
                                    .replace(/\\s+/g, ' ').trim();
                            }"""
                        )
                    except Exception:
                        card_text = anchor_text

                    card_text = re.sub(
                        r"\s+",
                        " ",
                        str(card_text or ""),
                    ).strip()

                    title = anchor_text

                    generic_titles = {
                        "",
                        "view job",
                        "apply",
                        "apply now",
                        "save",
                        "save job",
                    }

                    if title.lower() in generic_titles:
                        title = _ireland_browser_title_from_url(
                            canonical
                        )

                    # TalentBrew/Phenom sometimes puts title + location +
                    # category all in one anchor. Prefer the URL slug when
                    # anchor text is obviously bloated.
                    if (
                        len(title) > 180
                        or re.search(
                            r"\bIreland\b.*\b(?:Sales|Engineering|"
                            r"Finance|Full-time|Global Customer Services)\b",
                            title,
                            re.I,
                        )
                    ):
                        slug_title = _ireland_browser_title_from_url(
                            canonical
                        )
                        if slug_title:
                            title = slug_title

                    title = re.sub(
                        r"\s+",
                        " ",
                        str(title or ""),
                    ).strip()

                    if not title:
                        continue

                    location_source = " ".join([
                        card_text,
                        canonical.replace("-", " "),
                    ])

                    location = _ireland_final_loc(
                        location_source
                    )

                    results[canonical] = {
                        "company": company,
                        "ats": ats,
                        "title": title[:300],
                        "location": location,
                        "url": canonical,
                        "updated_at": None,
                        "description_text": card_text[:5000],
                    }

                added = len(results) - before

                print(
                    f"    {company} page {page_no}: "
                    f"+{added} / total {len(results)}"
                )

                if added == 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0

                if (
                    stop_after_empty
                    and page_no > 1
                    and consecutive_empty >= 1
                ):
                    break

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! {company} browser collector failed: {exc}")

    jobs = list(results.values())

    print(
        f"  {company} official rendered Ireland careers: "
        f"{len(jobs)} jobs"
    )

    return jobs

def scrape_opentext():
    base = (
        "https://careers.opentext.com/us/en/search-results"
        "?p=ChIJ-ydAXOS6WUgRCPTbzjQSfM8"
        "&location=Ireland"
        "&s=1"
    )

    urls = [base]

    for offset in range(10, 100, 10):
        urls.append(
            base + f"&from={offset}"
        )

    jobs = _ireland_browser_collect_pages(
        "OpenText",
        urls,
        r"/us/en/job/\d+/",
        ats="phenom",
    )

    try:
        _mark_connector_health(
            "OpenText",
            True,
            f"Official rendered Ireland search returned {len(jobs)} jobs",
            base,
        )
    except Exception:
        pass

    return jobs

def scrape_marks_spencer_ireland():
    base = (
        "https://jobs.marksandspencer.com/job-search"
        "?country%5B0%5D=Republic%20of%20Ireland"
    )

    urls = [
        base + f"&page={page_no}"
        for page_no in range(1, 20)
    ]

    jobs = _ireland_browser_collect_pages(
        "Marks & Spencer Ireland",
        urls,
        r"/job-search/(?:.+/)?\d{8,}(?:\?|$)",
        ats="official",
    )

    try:
        _mark_connector_health(
            "Marks & Spencer Ireland",
            True,
            f"Official rendered Republic of Ireland search returned {len(jobs)} jobs",
            base,
        )
    except Exception:
        pass

    return jobs

def _working_batch_base_scrape_direct_company(company: str):
    # BEGIN SALE_READY_DIRECT_CONNECTORS
    # Canonical/alias names that must use their verified official collectors.
    _verified_direct_connectors = {
        'Alter Domus': scrape_alter_domus_ireland,
        'Baxter International': scrape_baxter_ireland,
        'Aer Lingus': scrape_aer_lingus,
        'Iarnród Éireann': scrape_irish_rail,
        'Irish Rail (Iarnród Éireann)': scrape_irish_rail,
        'Irish Life': scrape_irish_life,
        'Forvis Mazars': scrape_forvis_mazars,
        'ESB': scrape_esb,
        'DPS Group': scrape_dps_group,
        'SMBC Group': scrape_smbc_group,
        'S&P Global': scrape_sp_global,
        'JPMorgan Chase': scrape_jpmorgan,
        'BlackRock': scrape_blackrock,
    }
    _direct_fn = _verified_direct_connectors.get(company)
    if _direct_fn is not None:
        return _direct_fn()
    # END SALE_READY_DIRECT_CONNECTORS
    if company in UNIVERSITY_CAREER_PAGES:
        return scrape_university_official(company)
    fn={
        "Baker Tilly Ireland": scrape_baker_tilly_ireland,
        "Arcadis": scrape_arcadis_ireland,
        "DocuSign": scrape_docusign,
        "Broadcom": scrape_broadcom_ireland,
        "BT Ireland": scrape_bt_ireland,
        "Fenergo": scrape_fenergo_ireland,
        "Hewlett Packard Enterprise (HPE)": scrape_hpe_ireland,
        "IQVIA": scrape_iqvia_ireland,
        "Proofpoint": scrape_proofpoint_ireland,
        "Willis Towers Watson (WTW)": scrape_wtw_ireland,
        "AXA XL": scrape_axa_xl,
        "AtkinsRéalis": scrape_atkinsrealis,
        "Advanced Micro Devices (AMD)": scrape_amd,
        "Applied Materials": scrape_applied_materials,
        "Bausch + Lomb": scrape_bausch_lomb_ireland,
        "Walkers Ireland": scrape_walkers,
        "Heineken Ireland": scrape_heineken,
        "Heineken": scrape_heineken,
        "HEINEKEN": scrape_heineken,
        "Huawei Ireland": scrape_huawei,
        "Guidewire Software": scrape_guidewire,
        "Guidewire": scrape_guidewire,
        "Honeywell": scrape_honeywell,
        "HCLTech": scrape_hcltech,
        "Irish Life": scrape_irish_life,
        "Iarnród Éireann": scrape_irish_rail,
        "Irish Rail": scrape_irish_rail,
        "Irish Rail (Iarnrod Eireann)": scrape_irish_rail,
        "Forvis Mazars": scrape_forvis_mazars,
        "Forvis Mazars Ireland": scrape_forvis_mazars,
        "ESB": scrape_esb,
        "DPS Group": scrape_dps_group,
        "DPS Group (Arcadis)": scrape_dps_group,
        "Irish Revenue": scrape_revenue_ie,
        "Revenue": scrape_revenue_ie,
        "Revenue.ie": scrape_revenue_ie,
        "Medtronic": scrape_medtronic,
        "UPS Ireland": scrape_ups,
        "Three Ireland": scrape_three_ireland,
        "TK Maxx Ireland": scrape_tjx_ireland,
        "publicjobs": scrape_publicjobs,
        "Public Jobs": scrape_publicjobs,
        "publicjobs.ie": scrape_publicjobs,
        "permanent tsb": scrape_ptsb,
        "Permanent TSB": scrape_ptsb,
        "PTSB": scrape_ptsb,
        "Qualcomm": scrape_qualcomm,
        "NTT DATA Services": scrape_ntt_data,
        "NTT Data": scrape_ntt_data,
        "NTT DATA": scrape_ntt_data,
        "AXA Ireland": scrape_axa,
        "AXA": scrape_axa,
        "Laya": scrape_laya_healthcare,
        "Laya Healthcare": scrape_laya_healthcare,
        "AECOM": scrape_aecom,
        "ABB": scrape_abb,
        "S&P": scrape_sp_global,
        "S&P Global": scrape_sp_global,
        "Ryanair": scrape_ryanair,
        "Coca-Cola HBC": scrape_coca_cola,
        "The Coca-Cola Company": scrape_coca_cola,
        "Coca-Cola": scrape_coca_cola,
        "PepsiCo": scrape_pepsico,
        "FedEx": scrape_fedex,
        "Musgrave Group": scrape_musgrave,
        "Musgrave": scrape_musgrave,
        "Siemens": scrape_siemens,
        "SAP Ireland": scrape_sap,
        "SAP": scrape_sap,
        "Allianz Ireland": scrape_allianz_rewired,
        "Allianz": scrape_allianz_rewired,
        "Abbott Laboratories": scrape_abbott_rewired,
        "Abbott": scrape_abbott_rewired,
        "Accenture": scrape_accenture,
        "Citi": scrape_citi,
        "Apple": scrape_apple,
        "Fidelity International": scrape_fidelity_international,
        "Bloomberg": scrape_bloomberg,
        "BlackRock": scrape_blackrock,
        "Citco": scrape_citco,
        "Bank of Ireland": scrape_bank_of_ireland,
        "Google": scrape_google,
        "Microsoft": scrape_microsoft,
        "Meta": scrape_meta,
        "TikTok": scrape_tiktok,
        "Oracle": scrape_oracle,
        "Red Hat": scrape_redhat,
        "JPMorgan Chase": scrape_jpmorgan,
        "EY Ireland": scrape_ey,
        "KPMG Ireland": scrape_kpmg,
        "NetApp": scrape_netapp,
        "Version 1": scrape_version1,
        "Grant Thornton Ireland": scrape_grant_thornton,
        "HSBC Ireland": scrape_hsbc,
        "EXL": scrape_exl,
        "Dell Technologies": scrape_dell,
        "Tata Consultancy Services (TCS)": scrape_tcs,
        "RSM Ireland": scrape_rsm,
        "Infosys": scrape_infosys,
        "Wells Fargo": scrape_wells_fargo,
        "Vodafone": scrape_vodafone,
        "Wipro": scrape_wipro,
        "KPMG Ireland": scrape_kpmg_ireland,
        "IBM": scrape_ibm,
        "Hitachi Energy": scrape_hitachi_energy,
        "Aon": scrape_aon,
        "GE HealthCare": scrape_ge_healthcare,
        "Huawei": scrape_huawei,
        "Becton Dickinson (BD)": scrape_becton_dickinson,
        "AstraZeneca": scrape_astrazeneca,
        "Alexion Pharmaceuticals": scrape_alexion,
        "Aiven": scrape_aiven,
        "A&L Goodbody": scrape_algoodbody,
        "Agilent Technologies": scrape_agilent,
        "Jacobs": scrape_jacobs,
        "McKinsey & Company": scrape_mckinsey,
        "HP (Hewlett-Packard)": scrape_hp,
        "Arup": scrape_arup,
        "Deutsche Bank": scrape_deutsche_bank,
        "SMBC Group": scrape_smbc_group,
        "SMBC Aviation Capital": scrape_smbc_aviation_capital,
        "Harvey Nash": scrape_harvey_nash,
        "ING": scrape_ing,
        "Bank of America": scrape_bank_of_america,
        "Cognizant": scrape_cognizant,
        "AIB (Allied Irish Banks)": scrape_aib,
        "Central Bank of Ireland": scrape_central_bank_ireland,
        "BNP Paribas Ireland": scrape_bnp_paribas_ireland,
        "AIG": lambda: scrape_workday(
            "AIG",
            "aig",
            "wd1",
            "aig",
            max_pages=25,
            search_text="Ireland",
        ),
        "Barclays": scrape_barclays_official,
        "PM Group": scrape_pm_group_official,
        "Motorola Solutions": lambda: scrape_workday(
            "Motorola Solutions",
            "motorolasolutions",
            "wd5",
            "Careers",
            max_pages=25,
            search_text="Ireland",
        ),
        "AMCS Group": scrape_amcs_official,
        "Avolon": scrape_avolon_official,
        "ASL Aviation Holdings": scrape_asl_aviation_official,
        "Auxilion": scrape_auxilion_official,
        "BioMarin": scrape_biomarin_official,
        "BNP Paribas": scrape_bnp_paribas_rewired,
        "Capgemini": scrape_capgemini,
        "ServiceNow": scrape_servicenow,
        "Boston Scientific": scrape_boston_scientific,
        "DXC Technology": scrape_dxc,
        "Johnson & Johnson": scrape_johnson_johnson,
        "Johnson Controls": scrape_johnson_controls,
        "Dropbox": scrape_dropbox,
        "Zscaler": scrape_zscaler,
        "Public Jobs / Civil Service": scrape_publicjobs,
        "Coca-Cola HBC Ireland": scrape_coca_cola,
        "Musgrave Group (SuperValu / Centra)": scrape_musgrave,
        "Susquehanna International Group (SIG)": scrape_susquehanna,
        "Schneider Electric": scrape_schneider_electric,
        "CGI": scrape_cgi_ireland,
        "Dawn Meats": scrape_dawn_meats,
        "DHL Ireland": scrape_dhl_ireland_official,
        "Decathlon Ireland": scrape_decathlon_ireland,
            "Marsh McLennan": scrape_marsh_mclennan_official,
}.get(company)
    return fn() if fn else []

def scrape_direct_company(company, *args, **kwargs):
    _working_batch = {
        'Irish Aviation Authority': scrape_irish_aviation_authority,
        'OpenText': scrape_opentext,
        'Optum': scrape_optum_ireland,
        'Palo Alto Networks': scrape_palo_alto_ireland,
        'Primark / Penneys': scrape_primark_ireland,
        'Red Hat': scrape_redhat,
        'Marks & Spencer Ireland': scrape_marks_spencer_ireland,
    }

    fn = _working_batch.get(company)

    if fn is not None:
        return fn()

    return _working_batch_base_scrape_direct_company(
        company,
        *args,
        **kwargs,
    )

# === WORKING_IRELAND_BATCH_END ===

# === UVWT_FINAL_START ===

def _uvwt_clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _uvwt_canonical(url):
    try:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit(
            (p.scheme, p.netloc, p.path, "", "")
        )
    except Exception:
        return url


def _uvwt_location(text):
    text = _uvwt_clean(text)

    for city in (
        "Dublin",
        "Kilkenny",
        "Cork",
        "Galway",
        "Limerick",
        "Waterford",
        "Swords",
        "Blanchardstown",
        "Liffey Valley",
        "Tallaght",
        "Naas",
    ):
        if re.search(
            rf"\b{re.escape(city)}\b",
            text,
            re.I,
        ):
            return f"{city}, Ireland"

    if re.search(r"\bremote\b", text, re.I):
        return "Remote, Ireland"

    return "Ireland"


def _uvwt_browser_jobs(
    company,
    source_url,
    job_pattern,
    max_pages=20,
):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"  ! {company}: Playwright unavailable: {exc}")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/139.0 Safari/537.36"
                ),
                locale="en-IE",
            )

            page = context.new_page()

            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            page.wait_for_timeout(2500)

            try:
                _dismiss_cookie_banner(page)
            except Exception:
                pass

            seen_signatures = set()

            for page_no in range(1, max_pages + 1):
                for _ in range(4):
                    page.mouse.wheel(0, 1800)
                    page.wait_for_timeout(200)

                before = len(results)
                page_urls = []

                anchors = page.locator("a[href]")

                for i in range(anchors.count()):
                    a = anchors.nth(i)

                    try:
                        raw = a.get_attribute("href") or ""
                    except Exception:
                        continue

                    if not raw:
                        continue

                    href = urllib.parse.urljoin(
                        page.url,
                        raw,
                    ).split("#")[0]

                    if not re.search(
                        job_pattern,
                        href,
                        re.I,
                    ):
                        continue

                    if "/apply?" in href.lower():
                        continue

                    canonical = _uvwt_canonical(href)
                    page_urls.append(canonical)

                    try:
                        title = _uvwt_clean(
                            a.inner_text(timeout=1000)
                        )
                    except Exception:
                        title = ""

                    if title.lower() in {
                        "",
                        "view job",
                        "apply",
                        "apply now",
                        "details",
                        "learn more",
                    }:
                        path = urllib.parse.urlsplit(
                            canonical
                        ).path.rstrip("/")

                        slug = (
                            path.split("/")[-1]
                            if path
                            else ""
                        )

                        title = _uvwt_clean(
                            urllib.parse.unquote(slug)
                            .replace("-", " ")
                            .replace("_", " ")
                        )

                    if not title:
                        continue

                    try:
                        card = a.evaluate(
                            """el => {
                                let n = el;

                                for (
                                    let i = 0;
                                    i < 8 && n;
                                    i++, n = n.parentElement
                                ) {
                                    const t = (n.innerText || '')
                                        .replace(/\\s+/g, ' ')
                                        .trim();

                                    if (
                                        t.length > 20 &&
                                        t.length < 5000
                                    ) {
                                        return t;
                                    }
                                }

                                return '';
                            }"""
                        )
                    except Exception:
                        card = title

                    text = _uvwt_clean(card)

                    results[canonical] = {
                        "company": company,
                        "ats": "official",
                        "title": title[:300],
                        "location": _uvwt_location(text),
                        "url": canonical,
                        "updated_at": None,
                        "description_text": text[:5000],
                    }

                signature = tuple(sorted(set(page_urls)))

                print(
                    f"    {company} page {page_no}: "
                    f"+{len(results)-before} "
                    f"/ total {len(results)}"
                )

                if not signature:
                    break

                if signature in seen_signatures:
                    break

                seen_signatures.add(signature)

                next_link = None

                selectors = (
                    '[data-ph-at-id="pagination-next-link"]',
                    'a[rel="next"]',
                    'a[aria-label*="next" i]',
                )

                for selector in selectors:
                    loc = page.locator(selector)

                    if not loc.count():
                        continue

                    for j in range(loc.count()):
                        try:
                            if loc.nth(j).is_visible():
                                next_link = loc.nth(j)
                                break
                        except Exception:
                            pass

                    if next_link is not None:
                        break

                if next_link is None:
                    try:
                        loc = page.get_by_role(
                            "link",
                            name=re.compile(
                                r"^\s*Next\s*$",
                                re.I,
                            ),
                        )

                        if loc.count():
                            next_link = loc.first
                    except Exception:
                        pass

                if next_link is None:
                    break

                try:
                    next_link.click(
                        force=True,
                        timeout=10000,
                    )
                    page.wait_for_timeout(1800)
                except Exception:
                    break

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! {company} browser scrape failed: {exc}")

    jobs = list(results.values())

    print(
        f"  {company} official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


def scrape_walkers():
    company = "Walkers Ireland"

    source = (
        "https://careers.walkersglobal.com/search/"
        "?createNewAlert=false"
        "&q="
        "&optionsFacetsDD_location="
        "Dublin%2C+IE%2C+D01+W213"
        "&optionsFacetsDD_title="
    )

    sess = _session()

    if not sess:
        print("  ! Walkers Ireland: HTTP session unavailable")
        return []

    results = {}

    try:
        from bs4 import BeautifulSoup

        r = sess.get(
            source,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
            timeout=30,
        )

        if r.status_code != 200:
            print(
                f"  ! Walkers Ireland HTTP "
                f"{r.status_code}"
            )
            return []

        soup = BeautifulSoup(
            r.text,
            "html.parser",
        )

        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(
                source,
                a.get("href") or "",
            )

            if "/job/" not in href.lower():
                continue

            title = _uvwt_clean(
                a.get_text(" ", strip=True)
            )

            if not title:
                continue

            canonical = _uvwt_canonical(href)

            results[canonical] = {
                "company": company,
                "ats": "successfactors",
                "title": title[:300],
                "location": "Dublin, Ireland",
                "url": canonical,
                "updated_at": None,
                "description_text": "Dublin, IE, D01 W213",
            }

    except Exception as exc:
        print(f"  ! Walkers Ireland failed: {exc}")

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Walkers Dublin board returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(
        f"  Walkers Ireland official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


def scrape_ups():
    company = "UPS Ireland"

    source = (
        "https://www.jobs-ups.com/global/en/search-results"
        "?p=ChIJL6wn6oAOZ0gRoHExl6nHAAo"
        "&location=Dublin%2C%20Ireland"
    )

    jobs = _uvwt_browser_jobs(
        company,
        source,
        r"/global/en/job/",
        max_pages=20,
    )

    cleaned = {}

    for j in jobs:
        text = " ".join([
            str(j.get("location") or ""),
            str(j.get("description_text") or ""),
            str(j.get("url") or ""),
        ])

        if not re.search(
            r"\bIreland\b|\bDublin\b",
            text,
            re.I,
        ):
            continue

        cleaned[j["url"]] = j

    jobs = list(cleaned.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official UPS Dublin board returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(
        f"  UPS Ireland official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


def scrape_three_ireland():
    company = "Three Ireland"

    source = (
        "https://three-ireland.csod.com/"
        "ux/ats/careersite/5/home"
        "?c=three-ireland"
        "&country=ie"
    )

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"  ! Three Ireland: Playwright unavailable: {exc}")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/139.0 Safari/537.36"
                ),
                locale="en-IE",
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            page.wait_for_timeout(3500)

            try:
                _dismiss_cookie_banner(page)
            except Exception:
                pass

            for _ in range(6):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(250)

            anchors = page.locator("a[href]")

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    raw = a.get_attribute("href") or ""
                except Exception:
                    continue

                if not raw:
                    continue

                href = urllib.parse.urljoin(
                    page.url,
                    raw,
                ).split("#")[0]

                # Cornerstone detail routes generally expose requisition/
                # job-specific route parameters.
                if not re.search(
                    r"(?:job|requisition|position|ats)"
                    r".*(?:id|req|job|position)",
                    href,
                    re.I,
                ):
                    continue

                canonical = _uvwt_canonical(href)

                try:
                    title = _uvwt_clean(
                        a.inner_text(timeout=1000)
                    )
                except Exception:
                    title = ""

                if not title:
                    continue

                if title.lower() in {
                    "home",
                    "careers",
                    "search jobs",
                    "job search",
                    "three ireland",
                    "view all jobs",
                }:
                    continue

                try:
                    card = a.evaluate(
                        """el => {
                            let n = el;

                            for (
                                let i = 0;
                                i < 8 && n;
                                i++, n = n.parentElement
                            ) {
                                const t = (n.innerText || '')
                                    .replace(/\\s+/g, ' ')
                                    .trim();

                                if (
                                    t.length > 20 &&
                                    t.length < 5000
                                ) {
                                    return t;
                                }
                            }

                            return '';
                        }"""
                    )
                except Exception:
                    card = title

                text = _uvwt_clean(card)

                results[canonical] = {
                    "company": company,
                    "ats": "cornerstone",
                    "title": title[:300],
                    "location": _uvwt_location(text),
                    "url": canonical,
                    "updated_at": None,
                    "description_text": text[:5000],
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! Three Ireland scrape failed: {exc}")

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Three Ireland CSOD returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(
        f"  Three Ireland official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


def scrape_vhi():
    company = "Vhi"

    source = "https://www1.vhi.ie/about/careers"

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"  ! Vhi: Playwright unavailable: {exc}")
        return []

    results = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/139.0 Safari/537.36"
                ),
                locale="en-IE",
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            page.wait_for_timeout(3000)

            try:
                _dismiss_cookie_banner(page)
            except Exception:
                pass

            frames = []

            for frame in page.frames:
                if frame not in frames:
                    frames.append(frame)

            for frame in frames:
                try:
                    anchors = frame.locator("a[href]")
                    count = anchors.count()
                except Exception:
                    continue

                for i in range(count):
                    a = anchors.nth(i)

                    try:
                        raw = a.get_attribute("href") or ""
                    except Exception:
                        continue

                    if not raw:
                        continue

                    href = urllib.parse.urljoin(
                        frame.url or source,
                        raw,
                    ).split("#")[0]

                    if (
                        "candidatemanager.net"
                        not in href.lower()
                    ):
                        continue

                    try:
                        title = _uvwt_clean(
                            a.inner_text(timeout=1000)
                        )
                    except Exception:
                        title = ""

                    if not title:
                        continue

                    canonical = _uvwt_canonical(href)

                    try:
                        card = a.evaluate(
                            """el => {
                                let n = el;

                                for (
                                    let i = 0;
                                    i < 7 && n;
                                    i++, n = n.parentElement
                                ) {
                                    const t = (n.innerText || '')
                                        .replace(/\\s+/g, ' ')
                                        .trim();

                                    if (
                                        t.length > 20 &&
                                        t.length < 4000
                                    ) {
                                        return t;
                                    }
                                }

                                return '';
                            }"""
                        )
                    except Exception:
                        card = title

                    text = _uvwt_clean(card)

                    # Ignore generic CandidateManager account/nav links.
                    if not (
                        re.search(
                            r"(vacanc|job|role|position|recruit)",
                            canonical,
                            re.I,
                        )
                        or re.search(
                            r"(advisor|manager|analyst|engineer|"
                            r"specialist|executive|nurse|doctor|"
                            r"developer|consultant|officer|"
                            r"administrator|associate)",
                            text,
                            re.I,
                        )
                    ):
                        continue

                    results[canonical] = {
                        "company": company,
                        "ats": "candidatemanager",
                        "title": title[:300],
                        "location": _uvwt_location(text),
                        "url": canonical,
                        "updated_at": None,
                        "description_text": text[:5000],
                    }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! Vhi scrape failed: {exc}")

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Vhi careers returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(
        f"  Vhi official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


# Preserve the currently tested dispatcher.
_uvwt_previous_direct = scrape_direct_company


def scrape_direct_company(company, *args, **kwargs):
    overrides = {
        "UPS Ireland": scrape_ups,
        "UPS": scrape_ups,
        "Vhi": scrape_vhi,
        "VHI": scrape_vhi,
        "Vhi Healthcare": scrape_vhi,
        "Walkers Ireland": scrape_walkers,
        "Walkers": scrape_walkers,
        "Three Ireland": scrape_three_ireland,
    }

    fn = overrides.get(company)

    if fn is not None:
        return fn()

    return _uvwt_previous_direct(
        company,
        *args,
        **kwargs,
    )


# === UVWT_FINAL_END ===

# === VIATEL_APPLEGREEN_START ===

def _va_clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def _va_location(text):
    text = _va_clean(text)

    places = (
        "Dublin",
        "Dundalk",
        "Limerick",
        "Cork",
        "Galway",
        "Wicklow",
        "Carlow",
        "Cavan",
        "Clonmel",
        "Drogheda",
        "Enfield",
        "Ennis",
        "Gorey",
        "Kilcullen",
        "Kilkenny",
        "Leixlip",
        "Letterkenny",
        "Lusk",
        "Mallow",
        "Naas",
        "Navan",
        "Rathcoole",
        "Rathnew",
        "Swords",
        "Tralee",
        "Birdhill",
        "Duleek",
        "Dunshaughlin",
        "Foxford",
        "Hollyhill",
        "Lemybrien",
    )

    for place in places:
        if re.search(
            rf"\b{re.escape(place)}\b",
            text,
            re.I,
        ):
            return f"{place}, Ireland"

    if re.search(r"\bIreland\b", text, re.I):
        return "Ireland"

    return "Ireland"


def scrape_viatel():
    """
    Viatel Technology Group official careers page.

    Current live board exposes PeopleHR job-opening URLs directly.
    """
    company = "Viatel"

    source = (
        "https://www.viatel.com/"
        "about/careers-at-viatel/#Jobs"
    )

    sess = _session()

    if not sess:
        print("  ! Viatel: HTTP session unavailable")
        return []

    results = {}

    try:
        from bs4 import BeautifulSoup

        r = sess.get(
            source.split("#")[0],
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-IE,en;q=0.9",
            },
            timeout=30,
        )

        r.raise_for_status()

        soup = BeautifulSoup(
            r.text,
            "html.parser",
        )

        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(
                r.url,
                a.get("href") or "",
            )

            if not re.search(
                r"^https://viatel\.peoplehr\.net/"
                r"Pages/JobBoard/Opening\.aspx\?v="
                r"[0-9a-f-]+$",
                href,
                re.I,
            ):
                continue

            title = ""

            # Try card/container text first because link itself says
            # only "Learn More".
            node = a

            for _ in range(7):
                node = getattr(node, "parent", None)

                if node is None:
                    break

                text = _va_clean(
                    node.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not text:
                    continue

                # Current official page displays:
                # <job title> Learn More
                m = re.search(
                    r"(.{3,200}?)\s+Learn More\b",
                    text,
                    re.I,
                )

                if m:
                    candidate = _va_clean(
                        m.group(1)
                    )

                    # If parent contains several job cards,
                    # take the tail nearest this link.
                    candidate = re.split(
                        r"(?:Our Open Roles|"
                        r"Check out our Open Roles)",
                        candidate,
                        flags=re.I,
                    )[-1]

                    # Known displayed titles are short;
                    # use final plausible line/chunk.
                    chunks = [
                        _va_clean(x)
                        for x in re.split(
                            r"\s{2,}|\n",
                            candidate,
                        )
                        if _va_clean(x)
                    ]

                    if chunks:
                        title = chunks[-1]

                    if title:
                        break

            if not title or len(title) > 250:
                # Resolve the PeopleHR detail page.
                try:
                    dr = sess.get(
                        href,
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Referer": source,
                        },
                        timeout=25,
                    )

                    if dr.status_code == 200:
                        ds = BeautifulSoup(
                            dr.text,
                            "html.parser",
                        )

                        for tag in ds.find_all(
                            ["h1", "h2", "h3"]
                        ):
                            candidate = _va_clean(
                                tag.get_text(
                                    " ",
                                    strip=True,
                                )
                            )

                            if (
                                candidate
                                and candidate.lower()
                                not in {
                                    "job opening",
                                    "job details",
                                }
                            ):
                                title = candidate
                                break
                except Exception:
                    pass

            if not title:
                continue

            results[href] = {
                "company": company,
                "ats": "peoplehr",
                "title": title[:300],
                "location": _va_location(title),
                "url": href,
                "updated_at": None,
                "description_text": "",
            }

    except Exception as exc:
        print(f"  ! Viatel scrape failed: {exc}")

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Viatel PeopleHR board returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(
        f"  Viatel official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


def scrape_applegreen():
    """
    Applegreen official Rezoomo careers board.

    The page initially renders 15 roles and exposes the remaining roles
    through its Show More control, so use the rendered official board.
    """
    company = "Applegreen"

    source = (
        "https://applegreen-stores.rezoomo.com/jobs/"
    )

    results = {}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True
            )

            context = browser.new_context(
                locale="en-IE",
                user_agent=(
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/139.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            page.wait_for_timeout(2500)

            # Rezoomo progressively reveals additional jobs.
            for _ in range(20):
                before = page.locator(
                    'a[href*="/job/"]'
                ).count()

                buttons = [
                    page.get_by_text(
                        re.compile(
                            r"Show more jobs",
                            re.I,
                        )
                    ),
                    page.get_by_role(
                        "button",
                        name=re.compile(
                            r"Show more",
                            re.I,
                        ),
                    ),
                ]

                clicked = False

                for candidate in buttons:
                    try:
                        if candidate.count():
                            for i in range(
                                candidate.count()
                            ):
                                c = candidate.nth(i)

                                if c.is_visible():
                                    c.click(
                                        force=True,
                                        timeout=5000,
                                    )
                                    clicked = True
                                    break
                    except Exception:
                        pass

                    if clicked:
                        break

                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(700)

                after = page.locator(
                    'a[href*="/job/"]'
                ).count()

                if not clicked and after <= before:
                    break

                if after <= before:
                    # one extra wait for async load
                    page.wait_for_timeout(1200)

                    after2 = page.locator(
                        'a[href*="/job/"]'
                    ).count()

                    if after2 <= before:
                        break

            anchors = page.locator(
                'a[href*="/job/"]'
            )

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    raw = a.get_attribute(
                        "href"
                    ) or ""
                except Exception:
                    continue

                href = urllib.parse.urljoin(
                    page.url,
                    raw,
                ).split("#")[0]

                m = re.match(
                    r"^https://applegreen-stores\.rezoomo\.com/"
                    r"job/(\d+)/?$",
                    href,
                    re.I,
                )

                if not m:
                    continue

                canonical = (
                    "https://applegreen-stores.rezoomo.com/"
                    f"job/{m.group(1)}/"
                )

                try:
                    text = _va_clean(
                        a.inner_text(
                            timeout=1000
                        )
                    )
                except Exception:
                    text = ""

                if not text:
                    continue

                # Anchor text contains title + location + employment
                # metadata. Strip from first obvious Irish location marker.
                title = text

                loc_match = re.search(
                    r"\b("
                    r"Dublin|Cork|Galway|Wicklow|Carlow|"
                    r"Cavan|Clonmel|Drogheda|Enfield|Ennis|"
                    r"Gorey|Hollyhill|Kilcullen|Kilkenny|"
                    r"Leixlip|Lemybrien|Letterkenny|Lusk|"
                    r"Mallow|Naas|Navan|Rathcoole|Rathnew|"
                    r"Swords|Tralee|Birdhill|Duleek|"
                    r"Dunshaughlin|Foxford|Ireland"
                    r")\b",
                    text,
                    re.I,
                )

                if loc_match:
                    title = _va_clean(
                        text[:loc_match.start()]
                    )

                if not title:
                    continue

                results[canonical] = {
                    "company": company,
                    "ats": "rezoomo",
                    "title": title[:300],
                    "location": _va_location(
                        text
                    ),
                    "url": canonical,
                    "updated_at": None,
                    "description_text": text[:5000],
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(
            f"  ! Applegreen scrape failed: "
            f"{exc}"
        )

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            (
                "Official Applegreen Rezoomo board "
                f"returned {len(jobs)} jobs"
            ),
            source,
        )
    except Exception:
        pass

    print(
        f"  Applegreen official careers: "
        f"{len(jobs)} jobs"
    )

    return jobs


_va_previous_direct = scrape_direct_company


def scrape_direct_company(company, *args, **kwargs):
    overrides = {
        "Viatel": scrape_viatel,
        "Viatel Technology Group": scrape_viatel,

        "Applegreen": scrape_applegreen,
        "Applegreen Ireland": scrape_applegreen,
    }

    fn = overrides.get(company)

    if fn is not None:
        return fn()

    return _va_previous_direct(
        company,
        *args,
        **kwargs,
    )


# === VIATEL_APPLEGREEN_END ===

# === VIATEL_FINAL_START ===

def scrape_viatel():
    company = "Viatel"
    source = "https://www.viatel.com/about/careers-at-viatel/#Jobs"

    results = {}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            context = browser.new_context(
                locale="en-IE",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            page.goto(
                source,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            page.wait_for_timeout(2500)

            # Scroll through the open-roles section.
            for _ in range(6):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(250)

            anchors = page.locator(
                'a[href*="viatel.peoplehr.net/Pages/JobBoard/Opening.aspx"]'
            )

            for i in range(anchors.count()):
                a = anchors.nth(i)

                try:
                    href = a.get_attribute("href") or ""
                except Exception:
                    continue

                if not href:
                    continue

                href = urllib.parse.urljoin(
                    page.url,
                    href,
                ).split("#")[0]

                if not re.search(
                    r"^https://viatel\.peoplehr\.net/"
                    r"Pages/JobBoard/Opening\.aspx\?v="
                    r"[0-9a-f-]+$",
                    href,
                    re.I,
                ):
                    continue

                title = ""

                # The anchor text is just "Learn More"; inspect nearby card.
                try:
                    title = a.evaluate(
                        """el => {
                            let n = el;
                            for (let i = 0; i < 7 && n; i++, n = n.parentElement) {
                                const t = (n.innerText || '')
                                  .replace(/\\s+/g, ' ')
                                  .trim();

                                if (!t) continue;

                                const m = t.match(/(.{3,180}?)\\s+Learn More\\b/i);

                                if (m && m[1]) {
                                    const x = m[1]
                                      .replace(/^.*?(Our Open Roles|Check out our Open Roles)\\s*/i, '')
                                      .trim();

                                    if (x) return x;
                                }
                            }
                            return '';
                        }"""
                    )
                except Exception:
                    title = ""

                title = re.sub(
                    r"\s+",
                    " ",
                    str(title or ""),
                ).strip()

                # Fallback: load the PeopleHR detail page in the same browser.
                if not title or len(title) > 220:
                    detail = context.new_page()

                    try:
                        detail.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=40000,
                        )

                        detail.wait_for_timeout(1000)

                        for selector in (
                            "h1",
                            "h2",
                            "h3",
                            ".job-title",
                            "[class*='title']",
                        ):
                            try:
                                loc = detail.locator(selector)

                                for j in range(min(loc.count(), 10)):
                                    candidate = re.sub(
                                        r"\s+",
                                        " ",
                                        loc.nth(j).inner_text(timeout=800) or "",
                                    ).strip()

                                    if (
                                        candidate
                                        and candidate.lower()
                                        not in {
                                            "job opening",
                                            "job details",
                                            "careers",
                                        }
                                        and len(candidate) < 220
                                    ):
                                        title = candidate
                                        break
                            except Exception:
                                pass

                            if title:
                                break

                    except Exception:
                        pass

                    detail.close()

                if not title:
                    continue

                loc_text = title

                try:
                    card_text = a.evaluate(
                        """el => {
                            let n = el;
                            for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
                                const t = (n.innerText || '')
                                  .replace(/\\s+/g, ' ')
                                  .trim();

                                if (t.length > 5 && t.length < 1000) {
                                    return t;
                                }
                            }
                            return '';
                        }"""
                    )
                    loc_text += " " + str(card_text or "")
                except Exception:
                    pass

                location = "Ireland"

                if re.search(r"\bDundalk\b", loc_text, re.I):
                    location = "Dundalk, Ireland"
                elif re.search(r"\bDublin\b", loc_text, re.I):
                    location = "Dublin, Ireland"
                elif re.search(r"\bLimerick\b", loc_text, re.I):
                    location = "Limerick, Ireland"

                results[href] = {
                    "company": company,
                    "ats": "peoplehr",
                    "title": title[:300],
                    "location": location,
                    "url": href,
                    "updated_at": None,
                    "description_text": str(loc_text)[:5000],
                }

            context.close()
            browser.close()

    except Exception as exc:
        print(f"  ! Viatel browser scrape failed: {exc}")

    jobs = list(results.values())

    try:
        _mark_connector_health(
            company,
            True,
            f"Official Viatel PeopleHR board returned {len(jobs)} jobs",
            source,
        )
    except Exception:
        pass

    print(f"  Viatel official careers: {len(jobs)} jobs")
    return jobs


# === VIATEL_FINAL_END ===

if __name__ == "__main__":
    main()

# =====================================================================
# Targeted Ireland connectors: Oracle / IBM / Marsh
# =====================================================================
