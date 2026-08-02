#!/usr/bin/env python3
"""
Free, unlimited job scraper for Sri's job dashboard.
Hits public, unauthenticated ATS JSON APIs directly (Greenhouse, Lever, Ashby) -
no Apify, no API key, no cost, no rate cap beyond each ATS's own fair-use limits.

Run by GitHub Actions on a daily schedule. Writes data.json for the dashboard
(index.html) to read.
"""

import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Company list: (slug, ats) -- expand this over time as we confirm more boards
# ---------------------------------------------------------------------------

GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "doordash", "pinterest", "squarespace", "dropbox",
    "twilio", "docusign", "robinhood", "reddit", "coinbase", "gitlab",
    "github", "hubspot", "indeed", "zendesk", "trustpilot", "workhuman",
    "wayflyer", "intercom", "wise", "asana", "cloudflare", "datadog",
    "snowflake", "databricks", "instacart", "lyft", "fenergo", "affirm",
    "airtable", "algolia", "amplitude", "betterup", "box", "buffer",
    "calendly", "carta", "chime", "classpass", "coursera", "discord",
    "doximity", "elastic", "envoy", "faire", "figma", "flexport", "gusto",
    "handshake", "hashicorp", "honeycomb", "justworks", "klaviyo", "lattice",
    "mixpanel", "mongodb", "mural", "okta", "opendoor", "patreon", "peloton",
    "pilot", "postman", "procore", "quora", "rippling", "samsara", "segment",
    "sendgrid", "sourcegraph", "sprinklr", "strava", "tanium", "thumbtack",
    "toast", "turo", "udemy", "verkada", "webflow", "wework", "yelp",
    "zapier", "zoominfo", "getyourguide", "trivago", "deliveryhero",
    "babbel", "contentful", "celonis", "flixbus", "tiermobility", "gorillas",
    "typeform", "glovo", "cabify", "blablacar", "backmarket", "doctolib",
    "qonto", "alan", "payfit", "gocardless", "truelayer", "thoughtmachine",
    "cazoo", "octopusenergy", "farfetch", "starlingbank", "revolut",
    "darktrace", "graphcore", "onfido", "fundingcircle", "tines", "flipdish",
    "letsgetchecked", "genesys", "grab", "sea", "carousell", "razer",
    "lazada", "careem", "noon", "talabat", "propertyfinder", "razorpay",
    "swiggy", "freshworks", "browserstack", "meesho", "cred", "groww",
    "urbancompany", "chargebee", "clevertap",
    # Australia / New Zealand
    "canva", "cultureamp", "safetyculture", "employmenthero", "airwallex",
    "deputy", "linktree", "go1", "halter", "judobank",
]

LEVER_COMPANIES = [
    "netflix", "spotify", "plaid", "brex", "checkout", "deliveroo", "monzo",
    "wolt", "bolt", "pipedrive", "zopa", "gojek", "traveloka",
]

ASHBY_COMPANIES = [
    "notion", "linear", "ramp", "elevenlabs", "openai", "anthropic",
    "vercel", "scale", "deel", "partly",
]

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

WORKDAY_COMPANIES = [
    ("nvidia", "wd5", "NVIDIAExternalCareerSite"),
    ("paypal", "wd1", "jobs"),
    ("accenture", "wd103", "AccentureCareers"),
]

# ---------------------------------------------------------------------------
# SmartRecruiters has a genuinely documented public Postings API --
# https://api.smartrecruiters.com/v1/companies/{companyId}/postings -- but
# it's a per-customer toggle, so not every SmartRecruiters customer has it
# switched on. "smartrecruiters" itself (their own careers page) is
# SmartRecruiters' own documented example and confirmed working. Add more by
# checking https://api.smartrecruiters.com/v1/companies/{guess}/postings
# directly in a browser -- a 200 with JSON means it's enabled for that company.
# ---------------------------------------------------------------------------

SMARTRECRUITERS_COMPANIES = [
    "smartrecruiters",
]

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
    # https://{slug}.jobs.personio.de/xml?language=en -- add slugs here
    # (Personio skews German/DACH SMB -- useful if expanding Germany/Austria coverage)
]

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

JSONLD_CAREER_PAGES = [
        ("Google (Ireland)", "https://www.google.com/about/careers/applications/jobs/results/?location=Dublin%2C%20Ireland"),
    ("Meta (Ireland)", "https://www.metacareers.com/locations/dublin"),
    ("Amazon (Ireland)", "https://www.amazon.jobs/en/locations/dublin-ireland"),
    ("Microsoft (Ireland)", "https://jobs.careers.microsoft.com/global/en/search?lc=Dublin%2C%20Ireland"),
    ("LinkedIn (Ireland)", "https://careers.linkedin.com/"),
    ("Workday (Ireland)", "https://workday.wd5.myworkdayjobs.com/Workday"),
    ("Salesforce (Ireland)", "https://careers.salesforce.com/en/"),
    ("Indeed (Ireland)", "https://www.indeed.jobs/"),
    ("TikTok (Ireland)", "https://careers.tiktok.com/"),
    ("Mastercard (Ireland)", "https://careers.mastercard.com/"),
    ("AIB", "https://aib.ie/careers"),
    ("Bank of Ireland", "https://careers.bankofireland.com/"),
    ("Deloitte Ireland", "https://www2.deloitte.com/ie/en/careers.html"),
    ("PwC Ireland", "https://www.pwc.ie/careers.html"),
    ("KPMG Ireland", "https://home.kpmg/ie/en/home/careers.html"),
    ("EY Ireland", "https://www.ey.com/en_ie/careers"),
    ("IBM Ireland", "https://www.ibm.com/ie-en/employment"),
    ("SAP Ireland", "https://jobs.sap.com/"),
    ("Version 1", "https://www.version1.com/careers/"),
    ("eBay/PayPal Ireland ops", "https://www.paypal.com/us/webapps/mpp/jobs"),
    ("Citi (Ireland)", "https://jobs.citi.com/"),
    ("State Street (Ireland)", "https://careers.statestreet.com/"),
    ("J.P. Morgan (Ireland)", "https://careers.jpmorgan.com/"),
    ("Three Ireland", "https://careers.three.ie/"),
    ("eir", "https://www.eir.ie/careers/"),
    ("Tesco Ireland", "https://www.tesco.ie/careers/"),
    ("Dunnes Stores", "https://www.dunnesstoresjobs.ie/"),
    ("SuperValu / Musgrave", "https://careers.musgravegroup.com/"),
    ("Ryanair", "https://careers.ryanair.com/"),
    ("Aer Lingus", "https://careers.aerlingus.com/"),
    ("Concentrix (Ireland)", "https://www.concentrix.com/careers/"),
    ("Teleperformance (Ireland)", "https://www.teleperformance.com/en-us/careers/"),
    ("Apple (Ireland)", "https://jobs.apple.com/en-ie"),
    ("Oracle (Ireland)", "https://www.oracle.com/careers/"),
    ("Emirates Group", "https://www.emiratesgroupcareers.com/"),
    ("Emaar Properties", "https://www.emaar.com/en/careers/"),
    ("ADNOC", "https://careers.adnoc.ae/"),
    ("e& (Etisalat)", "https://www.eand.com/en/careers.html"),
    ("DP World", "https://www.dpworld.com/careers"),
    ("Emirates NBD", "https://www.emiratesnbd.com/en/careers"),
    ("First Abu Dhabi Bank (FAB)", "https://www.bankfab.com/en-ae/careers"),
    ("Careem", "https://www.careem.com/careers/"),
    ("noon", "https://careers.noon.com/"),
    ("Mashreq Bank", "https://www.mashreq.com/en/uae/careers/"),
    ("Majid Al Futtaim", "https://careers.majidalfuttaim.com/"),
    ("Chalhoub Group", "https://www.chalhoubgroup.com/careers"),
    ("Deloitte UAE", "https://www2.deloitte.com/xe/en/careers.html"),
    ("PwC UAE", "https://www.pwc.com/m1/en/careers.html"),
    ("Amazon UAE", "https://www.amazon.jobs/en/locations/united-arab-emirates"),
    ("Microsoft UAE", "https://jobs.careers.microsoft.com/global/en/search?lc=United%20Arab%20Emirates"),
    ("Dubai Duty Free", "https://www.dubaidutyfree.com/en/careers"),
    ("LuLu Group (UAE)", "https://www.lulugroupinternational.com/careers"),
    ("Etihad Airways", "https://careers.etihad.com/"),
    ("du (EITC)", "https://www.du.ae/about-us/careers"),
    ("EY UAE", "https://www.ey.com/en_ae/careers"),
    ("KPMG UAE", "https://home.kpmg/ae/en/home/careers.html"),
    ("Google (UAE)", "https://www.google.com/about/careers/applications/jobs/results/?location=United%20Arab%20Emirates"),
    ("Meta (UAE)", "https://www.metacareers.com/locations/dubai"),
    ("Salesforce (UAE)", "https://careers.salesforce.com/en/"),
    ("Allegro", "https://about.allegro.eu/careers"),
    ("InPost", "https://grupainpost.pl/en/careers/"),
    ("CD Projekt", "https://www.cdprojekt.com/en/careers/"),
    ("mBank", "https://www.mbank.pl/kariera/"),
    ("PKO Bank Polski", "https://www.pkobp.pl/kariera/"),
    ("Santander Bank Polska", "https://www.santander.pl/kariera"),
    ("ING Poland", "https://www.ing.pl/kariera"),
    ("State Street (Krakow GBS)", "https://careers.statestreet.com/"),
    ("Capgemini Poland", "https://www.capgemini.com/pl-en/careers/"),
    ("IBM Poland", "https://www.ibm.com/pl-pl/employment"),
    ("HSBC GSC Krakow", "https://www.hsbc.com/careers"),
    ("Shell Business Operations Krakow", "https://www.shell.pl/careers.html"),
    ("Google Poland", "https://www.google.com/about/careers/applications/jobs/results/?location=Warsaw%2C%20Poland"),
    ("Amazon Poland", "https://www.amazon.jobs/en/locations/poland"),
    ("Luxoft (DXC)", "https://www.dxc.com/us/en/careers"),
    ("Comarch", "https://www.comarch.pl/kariera/"),
    ("Nordea Poland (GBS)", "https://www.nordea.com/en/careers"),
    ("Credit Suisse/UBS (Krakow GBS)", "https://www.ubs.com/careers"),
    ("Cisco Poland", "https://jobs.cisco.com/"),
    ("PZU", "https://kariera.pzu.pl/"),
    ("Orange Polska", "https://kariera.orange.pl/"),
    ("Zabka", "https://zabkagroup.com/en/careers/"),
    ("Deloitte Poland", "https://www2.deloitte.com/pl/en/careers.html"),
    ("PwC Poland", "https://www.pwc.pl/en/careers.html"),
    ("EY Poland", "https://www.ey.com/pl_pl/careers"),
    ("KPMG Poland", "https://home.kpmg/pl/en/home/careers.html"),
    ("Microsoft Poland", "https://jobs.careers.microsoft.com/global/en/search?lc=Warsaw%2C%20Poland"),
    ("Critical TechWorks (BMW)", "https://www.criticaltechworks.com/careers/"),
    ("Talkdesk", "https://www.talkdesk.com/careers/"),
    ("OutSystems", "https://www.outsystems.com/careers/"),
    ("Natixis (Porto GBS)", "https://www.natixis.com/natixis/en/careers"),
    ("Mercedes-Benz.io", "https://www.mercedes-benz.io/careers"),
    ("Cisco Portugal", "https://jobs.cisco.com/"),
    ("Deloitte Portugal", "https://www2.deloitte.com/pt/en/careers.html"),
    ("Vodafone Portugal", "https://careers.vodafone.com/"),
    ("EDP", "https://www.edp.com/en/careers"),
    ("Jeronimo Martins", "https://www.jeronimomartins.com/careers/"),
    ("Feedzai", "https://feedzai.com/careers/"),
    ("Teleperformance Portugal", "https://www.teleperformance.com/en-us/careers/"),
    ("Concentrix Portugal", "https://www.concentrix.com/careers/"),
    ("Sonae", "https://www.sonae.pt/en/careers/"),
    ("PwC Portugal", "https://www.pwc.pt/en/careers.html"),
    ("EY Portugal", "https://www.ey.com/pt_pt/careers"),
    ("KPMG Portugal", "https://home.kpmg/pt/en/home/careers.html"),
    ("Capgemini Portugal", "https://www.capgemini.com/pt-en/careers/"),
    ("HSBC (Hong Kong)", "https://www.hsbc.com/careers"),
    ("Standard Chartered (HK)", "https://www.sc.com/en/careers/"),
    ("Bank of China (Hong Kong)", "https://www.bochk.com/en/aboutus/careeropp.html"),
    ("AIA Group", "https://careers.aia.com/"),
    ("Prudential Hong Kong", "https://www.prudential.com.hk/en/careers/"),
    ("Jardine Matheson", "https://www.jardines.com/en/careers"),
    ("CLP Group", "https://www.clpgroup.com/en/careers"),
    ("Cathay Pacific", "https://careers.cathaypacific.com/"),
    ("PCCW", "https://www.pccw.com/en/careers.html"),
    ("Hang Seng Bank", "https://www.hangseng.com/en-hk/about-hang-seng/careers/"),
    ("DBS (Hong Kong)", "https://www.dbs.com/careers/"),
    ("Deloitte Hong Kong", "https://www2.deloitte.com/hk/en/careers.html"),
    ("PwC Hong Kong", "https://www.pwchk.com/en/careers.html"),
    ("Manulife Hong Kong", "https://careers.manulife.com/"),
    ("PARKnSHOP / AS Watson Group", "https://careers.aswatson.com/"),
    ("EY Hong Kong", "https://www.ey.com/en_hk/careers"),
    ("KPMG Hong Kong", "https://home.kpmg/cn/en/home/careers.html"),
    ("Google (Hong Kong)", "https://www.google.com/about/careers/applications/jobs/results/?location=Hong%20Kong"),
    ("Microsoft (Hong Kong)", "https://jobs.careers.microsoft.com/global/en/search?lc=Hong%20Kong"),
    ("Amazon (Hong Kong)", "https://www.amazon.jobs/en/locations/hong-kong"),
    ("Maybank", "https://www.maybank.com/en/careers.page"),
    ("CIMB Group", "https://www.cimb.com/en/careers.html"),
    ("Public Bank", "https://www.pbebank.com/careers.html"),
    ("AirAsia", "https://careers.airasia.com/"),
    ("Petronas", "https://www.petronas.com/careers"),
    ("Grab Malaysia", "https://grab.careers/"),
    ("Shopee Malaysia", "https://careers.shopee.com/"),
    ("DXC Technology Malaysia", "https://dxc.com/my/en/careers"),
    ("IBM Malaysia", "https://www.ibm.com/my-en/employment"),
    ("HSBC Electronic Data Processing (Malaysia)", "https://www.hsbc.com/careers"),
    ("AIA Malaysia", "https://careers.aia.com/"),
    ("Genting Group", "https://www.genting.com/careers/"),
    ("AEON Malaysia", "https://www.aeonretail.com.my/careers/"),
    ("Deloitte Malaysia", "https://www2.deloitte.com/my/en/careers.html"),
    ("PwC Malaysia", "https://www.pwc.com/my/en/careers.html"),
    ("EY Malaysia", "https://www.ey.com/en_my/careers"),
    ("KPMG Malaysia", "https://home.kpmg/my/en/home/careers.html"),
    ("Microsoft Malaysia", "https://jobs.careers.microsoft.com/global/en/search?lc=Malaysia"),
    ("Google Malaysia", "https://www.google.com/about/careers/applications/jobs/results/?location=Malaysia"),
    ("ASML", "https://www.asml.com/en/careers"),
    ("Philips", "https://www.careers.philips.com/"),
    ("ING", "https://www.ing.jobs/"),
    ("Booking.com", "https://careers.booking.com/"),
    ("Adyen", "https://www.adyen.com/careers"),
    ("Shell (NL)", "https://www.shell.com/careers.html"),
    ("Ahold Delhaize", "https://www.aholddelhaize.com/en/careers/"),
    ("Heineken", "https://www.theheinekencompany.com/careers"),
    ("KLM", "https://werkenbijklm.com/en/"),
    ("Rabobank", "https://www.rabobank.jobs/en/"),
    ("ABN AMRO", "https://www.abnamro.com/en/careers"),
    ("Randstad", "https://www.randstad.com/careers/"),
    ("Wolters Kluwer", "https://www.wolterskluwer.com/en/careers"),
    ("Mollie", "https://jobs.mollie.com/"),
    ("Bol.com", "https://werkenbij.bol.com/"),
    ("Coolblue", "https://werkenbij.coolblue.nl/"),
    ("Uber (Netherlands ops)", "https://www.uber.com/us/en/careers/"),
    ("Deloitte Netherlands", "https://www2.deloitte.com/nl/en/careers.html"),
    ("Capgemini Netherlands", "https://www.capgemini.com/nl-en/careers/"),
    ("KPN", "https://www.werkenbijkpn.com/"),
    ("Jumbo Supermarkten", "https://werkenbijjumbo.nl/"),
    ("TomTom", "https://www.tomtom.com/careers/"),
    ("PwC Netherlands", "https://www.pwc.nl/en/careers.html"),
    ("EY Netherlands", "https://www.ey.com/nl_nl/careers"),
    ("KPMG Netherlands", "https://home.kpmg/nl/en/home/careers.html"),
    ("Microsoft Netherlands", "https://jobs.careers.microsoft.com/global/en/search?lc=Netherlands"),
    ("SAP", "https://jobs.sap.com/"),
    ("Siemens", "https://jobs.siemens.com/"),
    ("Bosch", "https://careers.bosch.com/"),
    ("BMW Group", "https://www.bmwgroup.jobs/"),
    ("Mercedes-Benz Group", "https://career.mercedes-benz.com/"),
    ("Volkswagen Group", "https://www.volkswagenag.com/en/career.html"),
    ("Deutsche Bank", "https://careers.db.com/"),
    ("Allianz", "https://careers.allianz.com/"),
    ("Deutsche Telekom", "https://www.telekom.com/en/careers"),
    ("N26", "https://n26.com/en/careers"),
    ("Personio", "https://www.personio.com/career/"),
    ("HelloFresh", "https://careers.hellofresh.com/"),
    ("Trade Republic", "https://traderepublic.com/en-de/careers"),
    ("DHL / Deutsche Post", "https://careers.dhl.com/"),
    ("BASF", "https://www.basf.com/global/en/careers.html"),
    ("Continental", "https://www.continental.com/en/career/"),
    ("Commerzbank", "https://www.commerzbank.de/en/karriere/"),
    ("Lufthansa", "https://www.lufthansagroup.careers/"),
    ("Munich Re", "https://careers.munichre.com/"),
    ("E.ON", "https://careers.eon.com/"),
    ("Infineon", "https://www.infineon.com/cms/en/careers/"),
    ("Software AG", "https://www.softwareag.com/en_corporate/company/careers.html"),
    ("Deloitte Germany", "https://www2.deloitte.com/de/en/careers.html"),
    ("Capgemini Germany", "https://www.capgemini.com/de-en/careers/"),
    ("REWE Group", "https://karriere.rewe-group.com/"),
    ("Lidl / Schwarz Group", "https://jobs.lidl.com/"),
    ("Aldi", "https://karriere.aldi-sued.de/"),
    ("Deutsche Bahn", "https://www.deutschebahn.com/en/career"),
    ("Apple (Germany)", "https://jobs.apple.com/en-de"),
    ("PwC Germany", "https://www.pwc.de/en/careers.html"),
    ("EY Germany", "https://www.ey.com/de_de/careers"),
    ("KPMG Germany", "https://home.kpmg/de/en/home/careers.html"),
    ("Google (Germany)", "https://www.google.com/about/careers/applications/jobs/results/?location=Munich%2C%20Germany"),
    ("Microsoft Germany", "https://jobs.careers.microsoft.com/global/en/search?lc=Germany"),
    ("Amazon (Germany)", "https://www.amazon.jobs/en/locations/germany"),
    ("Salesforce Germany", "https://careers.salesforce.com/en/"),
    ("Erste Group", "https://www.erstegroup.com/en/about-us/careers"),
    ("Raiffeisen Bank International", "https://www.rbinternational.com/en/careers.html"),
    ("OMV", "https://www.omv.com/en/careers"),
    ("Voestalpine", "https://www.voestalpine.com/group/en/careers/"),
    ("Red Bull", "https://jobs.redbull.com/"),
    ("A1 Telekom Austria", "https://a1.jobs/"),
    ("Andritz", "https://www.andritz.com/careers-en/"),
    ("BAWAG Group", "https://www.bawaggroup.com/BAWAGGROUP/BG/EN/Careers"),
    ("Verbund", "https://www.verbund.com/en-at/about-verbund/career"),
    ("Spar Austria", "https://www.spar.at/karriere"),
    ("Rewe Austria (Billa/Merkur)", "https://karriere.rewe-group.at/"),
    ("Deloitte Austria", "https://www2.deloitte.com/at/en/careers.html"),
    ("PwC Austria", "https://www.pwc.at/en/careers.html"),
    ("EY Austria", "https://www.ey.com/de_at/careers"),
    ("KPMG Austria", "https://home.kpmg/at/en/home/careers.html"),
    ("Saudi Aramco", "https://careers.aramco.com/"),
    ("STC (Saudi Telecom)", "https://www.stc.com.sa/wps/wcm/connect/english/individual/aboutus/careers"),
    ("SABIC", "https://www.sabic.com/en/careers"),
    ("Al Rajhi Bank", "https://www.alrajhibank.com.sa/en/careers"),
    ("NEOM", "https://www.neom.com/en-us/careers"),
    ("Riyad Bank", "https://www.riyadbank.com/en/careers"),
    ("Saudi National Bank (SNB)", "https://www.alahli.com/en-us/about-us/careers"),
    ("Almarai", "https://www.almarai.com/en/careers/"),
    ("Jahez", "https://www.jahez.net/en/careers/"),
    ("Deloitte Saudi Arabia", "https://www2.deloitte.com/xe/en/careers.html"),
    ("PwC Saudi Arabia", "https://www.pwc.com/m1/en/careers.html"),
    ("Red Sea Global", "https://www.redseaglobal.com/en/careers"),
    ("Qiddiya", "https://www.qiddiya.com/careers"),
    ("Panda Retail Company", "https://www.pandaretailcompany.com/careers/"),
    ("Extra (United Electronics)", "https://www.extra.com/en-sa/careers"),
    ("Saudia (airline)", "https://www.saudia.com/about-saudia/careers"),
    ("flynas", "https://www.flynas.com/en/about-flynas/careers"),
    ("EY Saudi Arabia", "https://www.ey.com/en_sa/careers"),
    ("KPMG Saudi Arabia", "https://home.kpmg/sa/en/home/careers.html"),
    ("Microsoft Saudi Arabia", "https://jobs.careers.microsoft.com/global/en/search?lc=Saudi%20Arabia"),
    ("Amazon (Saudi Arabia)", "https://www.amazon.jobs/en/locations/saudi-arabia"),
    ("Nokia", "https://www.nokia.com/careers/"),
    ("KONE", "https://www.kone.com/en/careers/"),
    ("Wartsila", "https://www.wartsila.com/careers"),
    ("Nordea (Finland)", "https://www.nordea.com/en/careers"),
    ("OP Financial Group", "https://www.op.fi/en/careers"),
    ("Fortum", "https://www.fortum.com/about-us/careers"),
    ("Kesko", "https://www.kesko.fi/en/careers/"),
    ("Neste", "https://www.neste.com/careers"),
    ("Supercell", "https://supercell.com/en/careers/"),
    ("Wolt (DoorDash)", "https://careers.wolt.com/"),
    ("S Group (S-ryhma)", "https://www.s-kanava.fi/web/s/tyopaikat"),
    ("Finnair", "https://careers.finnair.com/"),
    ("Accenture Finland", "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"),
    ("Deloitte Finland", "https://www2.deloitte.com/fi/en/careers.html"),
    ("PwC Finland", "https://www.pwc.fi/en/careers.html"),
    ("EY Finland", "https://www.ey.com/fi_fi/careers"),
    ("KPMG Finland", "https://home.kpmg/fi/en/home/careers.html"),
    ("KBC Group", "https://www.kbc.com/en/careers.html"),
    ("ING Belgium", "https://www.ing.jobs/belgium"),
    ("Belfius", "https://www.belfius.be/about-us/en/careers"),
    ("Proximus", "https://jobs.proximus.com/"),
    ("Colruyt Group", "https://www.jobat.be/en/employers/colruyt-group"),
    ("AB InBev", "https://www.ab-inbev.com/careers/"),
    ("Solvay", "https://www.solvay.com/en/careers"),
    ("UCB", "https://www.ucb.com/careers"),
    ("bpost", "https://career.bpost.be/"),
    ("Deloitte Belgium", "https://www2.deloitte.com/be/en/careers.html"),
    ("PwC Belgium", "https://www.pwc.be/en/careers.html"),
    ("EY Belgium", "https://www.ey.com/en_be/careers"),
    ("KPMG Belgium", "https://home.kpmg/be/en/home/careers.html"),
    ("Euroclear", "https://www.euroclear.com/careers/"),
    ("SWIFT", "https://www.swift.com/careers"),
    ("Delhaize Belgium", "https://www.delhaizegroup.com/en/careers"),
    ("Infosys", "https://www.infosys.com/careers.html"),
    ("Amazon (India)", "https://www.amazon.jobs/en/locations/india"),
    ("JPMorgan Chase (India)", "https://careers.jpmorgan.com/"),
    ("SAP Labs India", "https://jobs.sap.com/"),
    ("TCS", "https://www.tcs.com/careers"),
    ("Wipro", "https://careers.wipro.com/"),
    ("HCLTech", "https://www.hcltech.com/careers"),
    ("Cognizant (India)", "https://careers.cognizant.com/"),
    ("Capgemini India", "https://www.capgemini.com/in-en/careers/"),
    ("IBM India", "https://www.ibm.com/in-en/employment"),
    ("Deloitte India", "https://www2.deloitte.com/in/en/careers.html"),
    ("EY India", "https://www.ey.com/en_in/careers"),
    ("PwC India", "https://www.pwc.in/careers.html"),
    ("KPMG India", "https://home.kpmg/in/en/home/careers.html"),
    ("Flipkart", "https://www.flipkartcareers.com/"),
    ("Zomato", "https://www.zomato.com/careers"),
    ("Myntra", "https://careers.myntra.com/"),
    ("Zoho", "https://www.zoho.com/careers/"),
    ("Microsoft (India)", "https://jobs.careers.microsoft.com/global/en/search?lc=India"),
    ("HDFC Bank", "https://www.hdfcbank.com/personal/about-us/careers"),
    ("ICICI Bank", "https://www.icicicareers.com/"),
    ("Reliance Retail", "https://www.ril.com/careers"),
    ("Genpact", "https://www.genpact.com/careers"),
    ("Concentrix India", "https://www.concentrix.com/careers/"),
    ("Teleperformance India", "https://www.teleperformance.com/en-us/careers/"),
    ("Byju's", "https://byjus.com/careers/"),
    ("Ola", "https://www.olacabs.com/careers"),
    ("PhonePe", "https://www.phonepe.com/careers/"),
    ("Google (India)", "https://www.google.com/about/careers/applications/jobs/results/?location=India"),
    ("Apple (India)", "https://jobs.apple.com/en-in"),
    ("Salesforce (India)", "https://careers.salesforce.com/en/"),
    ("Oracle (India)", "https://www.oracle.com/careers/"),
    ("Barclays", "https://search.jobs.barclays/"),
    ("HSBC", "https://www.hsbc.com/careers"),
    ("Lloyds Banking Group", "https://www.lloydsbankinggroup.com/careers.html"),
    ("NatWest Group", "https://jobs.natwestgroup.com/"),
    ("Mastercard (UK)", "https://careers.mastercard.com/"),
    ("Amadeus", "https://amadeus.com/en/careers"),
    ("Softcat", "https://careers.softcat.com/"),
    ("Bloomberg (London)", "https://careers.bloomberg.com/"),
    ("Amazon (UK)", "https://www.amazon.jobs/en/locations/uk"),
    ("Google (UK)", "https://www.google.com/about/careers/applications/jobs/results/?location=United%20Kingdom"),
    ("Microsoft (UK)", "https://jobs.careers.microsoft.com/global/en/search?lc=United%20Kingdom"),
    ("Apple (UK)", "https://jobs.apple.com/en-gb"),
    ("Meta (UK)", "https://www.metacareers.com/locations/london"),
    ("Deloitte UK", "https://www2.deloitte.com/uk/en/careers.html"),
    ("PwC UK", "https://www.pwc.co.uk/careers.html"),
    ("EY UK", "https://www.ey.com/en_uk/careers"),
    ("KPMG UK", "https://home.kpmg/uk/en/home/careers.html"),
    ("Capgemini UK", "https://www.capgemini.com/gb-en/careers/"),
    ("IBM UK", "https://www.ibm.com/uk-en/employment"),
    ("BT Group", "https://www.bt.com/careers"),
    ("Vodafone UK", "https://careers.vodafone.com/"),
    ("Tesco", "https://www.tesco-careers.com/"),
    ("Sainsbury's", "https://www.sainsburys.jobs/"),
    ("Asda", "https://www.asda.jobs/"),
    ("Morrisons", "https://www.morrisons.jobs/"),
    ("Ocado", "https://www.ocadogroup.com/careers"),
    ("Experian", "https://www.experianplc.com/careers"),
    ("JPMorgan Chase (UK)", "https://careers.jpmorgan.com/"),
    ("Goldman Sachs (UK)", "https://www.goldmansachs.com/careers/"),
    ("BAE Systems", "https://www.baesystems.com/en/careers"),
    ("Rolls-Royce", "https://careers.rolls-royce.com/"),
    ("AstraZeneca", "https://careers.astrazeneca.com/"),
    ("GSK", "https://jobs.gsk.com/"),
    ("BT Openreach", "https://www.openreach.co.uk/careers"),
    ("Centrica / British Gas", "https://www.centrica.com/careers/"),
    ("National Grid", "https://www.nationalgrid.com/careers"),
    ("Marks & Spencer", "https://careers.marksandspencer.com/"),
    ("John Lewis Partnership", "https://www.jlpjobs.com/"),
    ("Capita", "https://careers.capita.com/"),
    ("Teleperformance UK", "https://www.teleperformance.com/en-us/careers/"),
    ("Salesforce (UK)", "https://careers.salesforce.com/en/"),
    ("Oracle (UK)", "https://www.oracle.com/careers/"),
    ("Inditex (Zara)", "https://www.inditexcareers.com/"),
    ("Santander", "https://www.santandercareers.com/"),
    ("BBVA", "https://www.bbva.com/en/careers/"),
    ("Telefonica", "https://www.telefonica.com/en/careers/"),
    ("Iberdrola", "https://www.iberdrola.com/careers"),
    ("CaixaBank", "https://www.caixabank.com/en/careers.html"),
    ("Repsol", "https://www.repsol.com/en/careers/"),
    ("Amadeus (Spain)", "https://amadeus.com/en/careers"),
    ("Indra", "https://www.indracompany.com/en/careers"),
    ("Mercadona", "https://empleo.mercadona.es/"),
    ("Grifols", "https://www.grifols.com/en/careers"),
    ("Deloitte Spain", "https://www2.deloitte.com/es/en/careers.html"),
    ("Capgemini Spain", "https://www.capgemini.com/es-en/careers/"),
    ("El Corte Ingles", "https://www.elcorteingles.es/empleo/"),
    ("Teleperformance Spain", "https://www.teleperformance.com/en-us/careers/"),
    ("PwC Spain", "https://www.pwc.es/en/careers.html"),
    ("EY Spain", "https://www.ey.com/es_es/careers"),
    ("KPMG Spain", "https://home.kpmg/es/en/home/careers.html"),
    ("Amazon (Spain)", "https://www.amazon.jobs/en/locations/spain"),
    ("Klarna", "https://www.klarna.com/careers/"),
    ("Ericsson", "https://www.ericsson.com/en/careers"),
    ("Volvo Group", "https://www.volvogroup.com/en/careers.html"),
    ("H&M Group", "https://hmgroup.com/careers/"),
    ("IKEA (Sweden)", "https://www.ikea.com/careers"),
    ("SEB", "https://sebgroup.com/careers"),
    ("Swedbank", "https://www.swedbank.com/about-swedbank/careers.html"),
    ("Nordea (Sweden)", "https://www.nordea.com/en/careers"),
    ("Sinch", "https://www.sinch.com/careers/"),
    ("King (Activision Blizzard)", "https://king.com/jobs"),
    ("ICA Gruppen", "https://www.icagruppen.se/en/career/"),
    ("Telia Company", "https://www.teliacompany.com/en/careers/"),
    ("Accenture Sweden", "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"),
    ("Deloitte Sweden", "https://www2.deloitte.com/se/en/careers.html"),
    ("PwC Sweden", "https://www.pwc.se/en/careers.html"),
    ("EY Sweden", "https://www.ey.com/sv_se/careers"),
    ("KPMG Sweden", "https://home.kpmg/se/en/home/careers.html"),
    ("Amazon (Sweden)", "https://www.amazon.jobs/en/locations/sweden"),
    ("Qatar Airways", "https://careers.qatarairways.com/"),
    ("QNB Group", "https://www.qnb.com/sites/qnb/qnbcareers"),
    ("Ooredoo", "https://careers.ooredoo.qa/"),
    ("QatarEnergy", "https://qatarenergy.qa/en/Careers/"),
    ("Commercial Bank of Qatar", "https://www.cbq.qa/en/personal/pages/careers.aspx"),
    ("Doha Bank", "https://www.dohabank.com.qa/careers"),
    ("Vodafone Qatar", "https://careers.vodafone.com/"),
    ("Msheireb Properties", "https://www.msheireb.com/careers/"),
    ("Hamad International Airport (MATAR)", "https://www.dohahamadairport.com/corporate/careers"),
    ("LuLu Hypermarket Qatar", "https://www.luluhypermarket.com/en-qa/careers"),
    ("Accenture Qatar", "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"),
    ("Deloitte Qatar", "https://www2.deloitte.com/qa/en/careers.html"),
    ("PwC Qatar", "https://www.pwc.com/m1/en/careers.html"),
    ("EY Qatar", "https://www.ey.com/en_qa/careers"),
    ("KPMG Qatar", "https://home.kpmg/qa/en/home/careers.html"),
    ("Shopify", "https://www.shopify.com/careers"),
    ("RBC (Royal Bank of Canada)", "https://jobs.rbc.com/"),
    ("TD Bank Group", "https://jobs.td.com/"),
    ("Scotiabank", "https://jobs.scotiabank.com/"),
    ("BMO Financial Group", "https://jobs.bmo.com/"),
    ("CIBC", "https://jobs.cibc.com/"),
    ("Manulife", "https://careers.manulife.com/"),
    ("Sun Life", "https://jobs.sunlife.com/"),
    ("Telus", "https://www.telus.com/en/careers"),
    ("Bell Canada", "https://jobs.bell.ca/"),
    ("Rogers Communications", "https://jobs.rogers.com/"),
    ("CGI Group", "https://www.cgi.com/en/careers"),
    ("Loblaw Companies", "https://www.loblaw.ca/en/careers.html"),
    ("Deloitte Canada", "https://www2.deloitte.com/ca/en/careers.html"),
    ("Amazon Canada", "https://www.amazon.jobs/en/locations/canada"),
    ("Wealthsimple", "https://www.wealthsimple.com/en-ca/careers"),
    ("Lightspeed Commerce", "https://www.lightspeedhq.com/careers/"),
    ("Air Canada", "https://careers.aircanada.com/"),
    ("Canadian Tire", "https://corp.canadiantire.ca/English/careers/default.aspx"),
    ("Metro Inc.", "https://carrieres.metro.ca/en"),
    ("CN Rail", "https://www.cn.ca/en/careers/"),
    ("Sobeys / Empire Company", "https://www.empireco.ca/careers/"),
    ("PwC Canada", "https://www.pwc.com/ca/en/careers.html"),
    ("EY Canada", "https://www.ey.com/en_ca/careers"),
    ("KPMG Canada", "https://home.kpmg/ca/en/home/careers.html"),
    ("IBM Canada", "https://www.ibm.com/ca-en/employment"),
    ("Google (Canada)", "https://www.google.com/about/careers/applications/jobs/results/?location=Canada"),
    ("Microsoft Canada", "https://jobs.careers.microsoft.com/global/en/search?lc=Canada"),
    ("Salesforce Canada", "https://careers.salesforce.com/en/"),
    ("Commonwealth Bank", "https://www.commbank.com.au/careers.html"),
    ("Westpac", "https://www.westpac.com.au/about-westpac/careers/"),
    ("NAB", "https://www.nab.com.au/about-us/careers"),
    ("ANZ Bank", "https://www.anz.com.au/about-us/careers/"),
    ("Telstra", "https://careers.telstra.com/"),
    ("Woolworths Group", "https://www.wowcareers.com.au/"),
    ("Coles Group", "https://www.colescareers.com.au/"),
    ("Atlassian", "https://www.atlassian.com/company/careers"),
    ("Qantas", "https://www.qantas.com/careers/"),
    ("BHP", "https://www.bhp.com/careers"),
    ("Wesfarmers", "https://www.wesfarmers.com.au/careers"),
    ("Deloitte Australia", "https://www2.deloitte.com/au/en/careers.html"),
    ("Amazon Australia", "https://www.amazon.jobs/en/locations/australia"),
    ("Rio Tinto", "https://www.riotinto.com/careers"),
    ("Bunnings (Wesfarmers)", "https://www.bunnings.com.au/careers"),
    ("Optus", "https://www.optus.com.au/about/careers"),
    ("Australia Post", "https://auspost.com.au/about-us/careers"),
    ("PwC Australia", "https://www.pwc.com.au/careers.html"),
    ("EY Australia", "https://www.ey.com/en_au/careers"),
    ("KPMG Australia", "https://home.kpmg/au/en/home/careers.html"),
    ("Google (Australia)", "https://www.google.com/about/careers/applications/jobs/results/?location=Australia"),
    ("Microsoft Australia", "https://jobs.careers.microsoft.com/global/en/search?lc=Australia"),
    ("Salesforce Australia", "https://careers.salesforce.com/en/"),
    ("DBS Bank", "https://www.dbs.com/careers/"),
    ("OCBC Bank", "https://www.ocbc.com/group/careers/"),
    ("UOB", "https://www.uobgroup.com/careers/"),
    ("Sea Limited (Shopee/Garena)", "https://www.sea.com/career"),
    ("Grab", "https://grab.careers/"),
    ("Singtel", "https://www.singtel.com/about-us/careers"),
    ("ByteDance / TikTok (APAC)", "https://careers.tiktok.com/"),
    ("Google (APAC HQ)", "https://www.google.com/about/careers/applications/jobs/results/?location=Singapore"),
    ("Microsoft (APAC HQ)", "https://jobs.careers.microsoft.com/global/en/search?lc=Singapore"),
    ("Goldman Sachs (Singapore)", "https://www.goldmansachs.com/careers/"),
    ("Barclays (Singapore)", "https://search.jobs.barclays/"),
    ("PropertyGuru", "https://www.propertygurugroup.com/careers/"),
    ("NTUC FairPrice", "https://careers.fairprice.com.sg/"),
    ("Deloitte Singapore", "https://www2.deloitte.com/sg/en/careers.html"),
    ("Apple (Singapore)", "https://jobs.apple.com/en-sg"),
    ("Meta (Singapore)", "https://www.metacareers.com/locations/singapore"),
    ("Amazon (Singapore)", "https://www.amazon.jobs/en/locations/singapore"),
    ("PwC Singapore", "https://www.pwc.com/sg/en/careers.html"),
    ("EY Singapore", "https://www.ey.com/en_sg/careers"),
    ("KPMG Singapore", "https://home.kpmg/sg/en/home/careers.html"),
    ("Salesforce Singapore", "https://careers.salesforce.com/en/"),
    ("Xero", "https://www.xero.com/careers/"),
    ("Fisher & Paykel Healthcare", "https://careers.fphcare.com/"),
    ("Air New Zealand", "https://careers.airnewzealand.co.nz/"),
    ("ANZ New Zealand", "https://www.anz.co.nz/about-us/careers/"),
    ("ASB Bank", "https://careers.asb.co.nz/"),
    ("Spark New Zealand", "https://careers.sparknz.co.nz/"),
    ("Trade Me", "https://www.trademe.co.nz/careers"),
    ("Datacom", "https://careers.datacom.com/"),
    ("Fonterra", "https://www.fonterra.com/careers"),
    ("Foodstuffs NZ", "https://careers.foodstuffs.co.nz/"),
    ("Countdown/Woolworths NZ", "https://careers.woolworths.co.nz/"),
    ("Accenture New Zealand", "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"),
    ("Deloitte New Zealand", "https://www2.deloitte.com/nz/en/careers.html"),
    ("PwC New Zealand", "https://www.pwc.co.nz/careers.html"),
    ("EY New Zealand", "https://www.ey.com/en_nz/careers"),
    ("KPMG New Zealand", "https://home.kpmg/nz/en/home/careers.html"),
    ("Automattic (WordPress.com)", "https://automattic.com/work-with-us/"),
    ("Toptal", "https://www.toptal.com/careers"),
    ("Doist", "https://doist.com/careers"),
]

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

ADZUNA_APP_ID = ""    # fill in after free signup at developer.adzuna.com
ADZUNA_APP_KEY = ""
ADZUNA_COUNTRIES = ["gb", "ie", "de", "nl", "at", "es", "pl", "in", "sg", "au", "nz", "ca"]

CAREERJET_AFFID = ""  # fill in after free signup at careerjet.com/partners
CAREERJET_LOCALES = ["en_GB", "en_IE", "en_US", "en_AU", "en_CA", "en_SG", "en_IN"]

JOOBLE_API_KEY = ""   # fill in after free signup at jooble.org/api/about

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

DIRECT_QUERIES = [
    "data analyst", "data scientist", "business intelligence",
    "business analyst", "consultant", "customer service",
]

# ---------------------------------------------------------------------------
# Role keyword filter (title must contain at least one of these)
# ---------------------------------------------------------------------------

TITLE_KEYWORDS = [
    "data analyst", "data scientist", "business intelligence",
    "business analyst", "consultant", "erp", "retail sales",
    "customer service", "store assistant",
]

# ---------------------------------------------------------------------------
# Region filter: everything below is kept in full; US listings are kept
# ONLY if they're remote (Sri isn't relocating to the US on spec).
# ---------------------------------------------------------------------------

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
    t = (title or "").lower()
    return any(k in t for k in TITLE_KEYWORDS)


def region_ok(location: str) -> bool:
    loc = (location or "").lower()
    if any(k in loc for k in REGION_KEYWORDS):
        return True
    if any(k in loc for k in US_KEYWORDS):
        return "remote" in loc
    if "remote" in loc:
        # No country specified alongside "remote" -- likely globally open, keep it.
        return True
    return False


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (job-dashboard-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        print(f"  ! fetch failed for {url}: {e}")
        return None


def scrape_greenhouse(slug: str):
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        title = j.get("title", "")
        location = (j.get("location") or {}).get("name", "")
        if title_matches(title) and region_ok(location):
            out.append({
                "company": slug,
                "ats": "greenhouse",
                "title": title,
                "location": location,
                "url": j.get("absolute_url"),
                "updated_at": j.get("updated_at"),
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
        if title_matches(title) and region_ok(location):
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
        if title_matches(title) and region_ok(location):
            out.append({
                "company": slug,
                "ats": "ashby",
                "title": title,
                "location": location,
                "url": j.get("jobUrl") or j.get("applyUrl"),
                "updated_at": j.get("publishedAt"),
            })
    return out


def scrape_workday(tenant: str, wd_host: str, site: str, max_pages: int = 15):
    base = f"https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    out = []
    offset = 0
    page_size = 20  # Workday hard-caps at 20 per page
    for _ in range(max_pages):
        payload = json.dumps({
            "appliedFacets": {},
            "limit": page_size,
            "offset": offset,
            "searchText": "",
        }).encode("utf-8")
        req = urllib.request.Request(
            base,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (job-dashboard-bot)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            print(f"  ! fetch failed for {base} (offset {offset}): {e}")
            break

        postings = (data or {}).get("jobPostings") or []
        if not postings:
            break

        for j in postings:
            title = j.get("title", "")
            location = j.get("locationsText", "") or j.get("bulletFields", [""])[0]
            if title_matches(title) and region_ok(location):
                path = j.get("externalPath", "")
                out.append({
                    "company": tenant,
                    "ats": "workday",
                    "title": title,
                    "location": location,
                    "url": f"https://{tenant}.{wd_host}.myworkdayjobs.com/{site}{path}" if path else None,
                    "updated_at": j.get("postedOn"),
                })

        if len(postings) < page_size:
            break
        offset += page_size
        time.sleep(0.3)

    return out


def scrape_smartrecruiters(company_id: str, max_pages: int = 15):
    out = []
    offset = 0
    page_size = 100
    for _ in range(max_pages):
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
            f"?limit={page_size}&offset={offset}"
        )
        data = fetch_json(url)
        if not data or "content" not in data:
            break

        postings = data.get("content") or []
        for j in postings:
            title = j.get("name", "")
            loc = j.get("location") or {}
            location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
            if loc.get("remote"):
                location = f"{location} (Remote)".strip(", ")
            if title_matches(title) and region_ok(location):
                out.append({
                    "company": company_id,
                    "ats": "smartrecruiters",
                    "title": title,
                    "location": location,
                    "url": (j.get("applyUrl") or (j.get("ref", {}) or {}).get("jobAd")),
                    "updated_at": j.get("releasedDate"),
                })

        if len(postings) < page_size:
            break
        offset += page_size
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
        if title_matches(title) and region_ok(loc_str):
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
        if title_matches(title) and region_ok(location):
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
        if title_matches(title) and region_ok(location):
            out.append({
                "company": slug,
                "ats": "personio",
                "title": title,
                "location": location,
                "url": field("careerSiteUrl") or None,
                "updated_at": field("createdAt"),
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


def scrape_jsonld(company: str, url: str):
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

            if title_matches(title) and region_ok(location):
                out.append({
                    "company": company,
                    "ats": "jsonld",
                    "title": title,
                    "location": location,
                    "url": c.get("url") or url,
                    "updated_at": c.get("datePosted"),
                })
    return out


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
        if title_matches(title) and region_ok(location):
            out.append({
                "company": (j.get("company") or {}).get("display_name", "unknown"),
                "ats": "adzuna",
                "title": title,
                "location": location,
                "url": j.get("redirect_url"),
                "updated_at": j.get("created"),
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
        if title_matches(title) and region_ok(location):
            out.append({
                "company": j.get("company", "unknown"),
                "ats": "careerjet",
                "title": title,
                "location": location,
                "url": j.get("url"),
                "updated_at": j.get("date"),
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
        if title_matches(title) and region_ok(loc):
            out.append({
                "company": j.get("company", "unknown"),
                "ats": "jooble",
                "title": title,
                "location": loc,
                "url": j.get("link"),
                "updated_at": j.get("updated"),
            })
    return out


def scrape_amazon(query: str):
    url = f"https://www.amazon.jobs/en/search.json?base_query={urllib.parse.quote(query)}&result_limit=50&offset=0"
    data = fetch_json(url)
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        title = j.get("title", "")
        location = j.get("normalized_location", "") or j.get("location", "")
        if title_matches(title) and region_ok(location):
            path = j.get("job_path", "")
            out.append({
                "company": "amazon",
                "ats": "direct",
                "title": title,
                "location": location,
                "url": f"https://www.amazon.jobs{path}" if path else None,
                "updated_at": j.get("posted_date"),
            })
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
        if title_matches(title) and region_ok(location):
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


def main():
    results = []
    errors = []

    for slug in GREENHOUSE_COMPANIES:
        try:
            found = scrape_greenhouse(slug)
            results.extend(found)
            print(f"greenhouse/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"greenhouse/{slug}: {e}")
        time.sleep(0.3)

    for slug in LEVER_COMPANIES:
        try:
            found = scrape_lever(slug)
            results.extend(found)
            print(f"lever/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"lever/{slug}: {e}")
        time.sleep(0.3)

    for slug in ASHBY_COMPANIES:
        try:
            found = scrape_ashby(slug)
            results.extend(found)
            print(f"ashby/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"ashby/{slug}: {e}")
        time.sleep(0.3)

    for tenant, wd_host, site in WORKDAY_COMPANIES:
        try:
            found = scrape_workday(tenant, wd_host, site)
            results.extend(found)
            print(f"workday/{tenant}: {len(found)} matches")
        except Exception as e:
            errors.append(f"workday/{tenant}: {e}")
        time.sleep(0.3)

    for company_id in SMARTRECRUITERS_COMPANIES:
        try:
            found = scrape_smartrecruiters(company_id)
            results.extend(found)
            print(f"smartrecruiters/{company_id}: {len(found)} matches")
        except Exception as e:
            errors.append(f"smartrecruiters/{company_id}: {e}")
        time.sleep(0.3)

    for slug in WORKABLE_COMPANIES:
        try:
            found = scrape_workable(slug)
            results.extend(found)
            print(f"workable/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"workable/{slug}: {e}")
        time.sleep(0.3)

    for slug in RECRUITEE_COMPANIES:
        try:
            found = scrape_recruitee(slug)
            results.extend(found)
            print(f"recruitee/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"recruitee/{slug}: {e}")
        time.sleep(0.3)

    for slug in PERSONIO_COMPANIES:
        try:
            found = scrape_personio(slug)
            results.extend(found)
            print(f"personio/{slug}: {len(found)} matches")
        except Exception as e:
            errors.append(f"personio/{slug}: {e}")
        time.sleep(0.3)

    for company, url in JSONLD_CAREER_PAGES:
        try:
            found = scrape_jsonld(company, url)
            results.extend(found)
            print(f"jsonld/{company}: {len(found)} matches")
        except Exception as e:
            errors.append(f"jsonld/{company}: {e}")
        time.sleep(0.3)

    for country in ADZUNA_COUNTRIES:
        for query in DIRECT_QUERIES:
            try:
                found = scrape_adzuna(country, query)
                results.extend(found)
                if found:
                    print(f"adzuna/{country} ({query}): {len(found)} matches")
            except Exception as e:
                errors.append(f"adzuna/{country} ({query}): {e}")
            time.sleep(0.3)

    for locale in CAREERJET_LOCALES:
        for query in DIRECT_QUERIES:
            try:
                found = scrape_careerjet(locale, query)
                results.extend(found)
                if found:
                    print(f"careerjet/{locale} ({query}): {len(found)} matches")
            except Exception as e:
                errors.append(f"careerjet/{locale} ({query}): {e}")
            time.sleep(0.3)

    for query in DIRECT_QUERIES:
        try:
            found = scrape_jooble(query)
            results.extend(found)
            if found:
                print(f"jooble ({query}): {len(found)} matches")
        except Exception as e:
            errors.append(f"jooble ({query}): {e}")
        time.sleep(0.3)

    for query in DIRECT_QUERIES:
        try:
            found = scrape_amazon(query)
            results.extend(found)
            print(f"direct/amazon ({query}): {len(found)} matches")
        except Exception as e:
            errors.append(f"direct/amazon ({query}): {e}")
        time.sleep(0.5)

    for query in DIRECT_QUERIES:
        try:
            found = scrape_netflix(query)
            results.extend(found)
            print(f"direct/netflix ({query}): {len(found)} matches")
        except Exception as e:
            errors.append(f"direct/netflix ({query}): {e}")
        time.sleep(0.5)

    # De-dupe (Amazon/Netflix queries overlap and can return the same job twice)
    seen = set()
    deduped = []
    for j in results:
        key = (j.get("company"), j.get("url") or j.get("title"))
        if key not in seen:
            seen.add(key)
            deduped.append(j)
    results = deduped

    # Tag every job with a parsed posting date + recency bucket, so the
    # dashboard can filter by "last 24h / 7d / 30d" without re-parsing.
    for j in results:
        posted_dt = parse_posted_date(j.get("updated_at"))
        j["posted_at_parsed"] = posted_dt.isoformat() if posted_dt else None
        j["recency"] = recency_bucket(posted_dt)

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

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recency_counts": recency_counts,
        "total_companies_checked": (
            len(GREENHOUSE_COMPANIES) + len(LEVER_COMPANIES) + len(ASHBY_COMPANIES)
            + len(WORKDAY_COMPANIES) + len(SMARTRECRUITERS_COMPANIES)
            + len(WORKABLE_COMPANIES) + len(RECRUITEE_COMPANIES) + len(PERSONIO_COMPANIES)
            + len(JSONLD_CAREER_PAGES) + 2
        ),
        "total_matches": len(results),
        "errors": errors,
        "jobs": results,
        "note": "Google, Apple, and Meta are not scraped here (require heavier reverse-engineering / anti-bot handling) -- pull those from the Apify FAANG actor separately.",
    }

    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone. {len(results)} matching jobs written to data.json ({len(errors)} companies errored).")


if __name__ == "__main__":
    main()
