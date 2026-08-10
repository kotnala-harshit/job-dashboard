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

GREENHOUSE_COMPANIES = ['stripe', 'airbnb', 'doordash', 'pinterest', 'squarespace', 'twilio', 'docusign', 'robinhood', 'reddit', 'coinbase', 'gitlab', 'github', 'hubspotjobs', 'indeed', 'zendesk', 'trustpilot', 'workhuman', 'wayflyer', 'intercom', 'wise', 'asana', 'cloudflare', 'datadog', 'snowflake', 'instacart', 'lyft', 'fenergo', 'affirm', 'airtable', 'algolia', 'amplitude', 'betterup', 'buffer', 'calendly', 'carta', 'chime', 'classpass', 'coursera', 'discord', 'doximity', 'elastic', 'envoy', 'faire', 'flexport', 'gusto', 'handshake', 'hashicorp', 'honeycomb', 'justworks', 'klaviyo', 'lattice', 'mixpanel', 'mongodb', 'qualtrics', 'mural', 'okta', 'opendoor', 'patreon', 'peloton', 'pilot', 'postman', 'procore', 'quora', 'rippling', 'samsara', 'segment', 'sendgrid', 'sourcegraph', 'sprinklr', 'strava', 'tanium', 'thumbtack', 'toast', 'turo', 'udemy', 'verkada', 'webflow', 'wework', 'yelp', 'zapier', 'zoominfo', 'getyourguide', 'trivago', 'deliveryhero', 'babbel', 'contentful', 'celonis', 'flixbus', 'tiermobility', 'gorillas', 'typeform', 'glovo', 'cabify', 'blablacar', 'backmarket', 'doctolib', 'qonto', 'alan', 'payfit', 'gocardless', 'truelayer', 'thoughtmachine', 'cazoo', 'octopusenergy', 'farfetch', 'starlingbank', 'revolut', 'darktrace', 'graphcore', 'onfido', 'fundingcircle', 'tines', 'flipdish', 'letsgetchecked', 'genesys', 'grab', 'sea', 'carousell', 'razer', 'lazada', 'careem', 'noon', 'talabat', 'propertyfinder', 'razorpay', 'swiggy', 'freshworks', 'browserstack', 'meesho', 'cred', 'groww', 'urbancompany', 'chargebee', 'clevertap', 'cultureamp', 'safetyculture', 'employmenthero', 'airwallex', 'deputy', 'linktree', 'go1', 'halter', 'judobank']

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

WORKDAY_COMPANIES = [('Salesforce', 'salesforce', 'wd12', 'External_Career_Site'), ('Workday', 'workday', 'wd5', 'Workday'), ('Genesys', 'genesys', 'wd1', 'Genesys'), ('Slack', 'salesforce', 'wd12', 'Slack'), ('Mastercard', 'mastercard', 'wd1', 'CorporateCareers'), ('PayPal', 'paypal', 'wd1', 'jobs'), ('Adobe', 'adobe', 'wd5', 'external_experienced'), ('Autodesk', 'autodesk', 'wd1', 'Ext'), ('Cadence Design Systems', 'cadence', 'wd1', 'External_Careers'), ('Analog Devices', 'analogdevices', 'wd1', 'External'), ('NVIDIA', 'nvidia', 'wd5', 'NVIDIAExternalCareerSite'), ('Broadcom', 'broadcom', 'wd1', 'External_Career'), ('NXP Semiconductors', 'nxp', 'wd3', 'careers'), ('Rockwell Automation', 'rockwellautomation', 'wd1', 'External_Rockwell_Automation'), ('Eaton', 'eaton', 'wd5', 'Eaton'), ('Pfizer', 'pfizer', 'wd1', 'PfizerCareers'), ('Sanofi', 'sanofi', 'wd3', 'SanofiCareers'), ('MSD (Merck Sharp & Dohme)', 'msd', 'wd5', 'SearchJobs'), ('Bausch + Lomb', 'bauschhealth', 'wd1', 'BauschHealthCareers'), ('Takeda', 'takeda', 'wd3', 'External'), ('Gilead Sciences', 'gilead', 'wd1', 'gileadcareers'), ('Edwards Lifesciences', 'edwards', 'wd1', 'EdwardsCareers'), ('Teleflex', 'teleflex', 'wd1', 'TeleflexCareers'), ('Zimmer Biomet', 'zimmerbiomet', 'wd1', 'Zimmer_Biomet_Careers'), ('Viatris', 'viatris', 'wd1', 'ViatrisCareers'), ('Teva Pharmaceuticals', 'teva', 'wd1', 'Teva_Careers'), ('Jazz Pharmaceuticals', 'jazzpharma', 'wd5', 'Jazz_Careers'), ('ResMed', 'resmed', 'wd1', 'ResMed_External_Careers'), ('Becton Dickinson (BD)', 'bd', 'wd1', 'BD_External'), ('Illumina', 'illumina', 'wd1', 'illumina-careers'), ('Catalent', 'catalent', 'wd1', 'External'), ('State Street', 'statestreet', 'wd1', 'Global'), ('Elavon', 'usbank', 'wd1', 'Elavon_Careers'), ('Northern Trust', 'ntrs', 'wd1', 'northerntrust'), ('Deloitte Ireland', 'deloitteie', 'wd3', 'experienced_professionals'), ('PwC Ireland', 'pwc', 'wd3', 'Global_Experienced_Careers'), ('Grant Thornton Ireland', 'iegt', 'wd3', 'GTI_External_Careers_Experienced_Hires_ROI'), ('Aon', 'aon', 'wd1', 'AonCareers'), ('Willis Towers Watson (WTW)', 'wtw', 'wd1', 'WTWCareers'), ('Mercer', 'mmc', 'wd1', 'MMC'), ('Marsh McLennan', 'mmc', 'wd1', 'MMC'), ('Diageo Ireland', 'diageo', 'wd3', 'Diageo_Careers'), ('PIMCO', 'pimco', 'wd1', 'pimco-careers')]

# ---------------------------------------------------------------------------
# SmartRecruiters has a genuinely documented public Postings API --
# https://api.smartrecruiters.com/v1/companies/{companyId}/postings -- but
# it's a per-customer toggle, so not every SmartRecruiters customer has it
# switched on. "smartrecruiters" itself (their own careers page) is
# SmartRecruiters' own documented example and confirmed working. Add more by
# checking https://api.smartrecruiters.com/v1/companies/{guess}/postings
# directly in a browser -- a 200 with JSON means it's enabled for that company.
# ---------------------------------------------------------------------------

SMARTRECRUITERS_COMPANIES = ['smartrecruiters', 'servicenow', 'aristanetworks', 'abbvie', 'eurofins', 'version1']

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

PINPOINT_COMPANIES = ['ericsson', 'ptsb', 'kpmg', 'greencore', 'arcadis', 'zendesk', 'synopsys', 'nutanix', 'virgin', 'terumo', 'smith']

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

JSONLD_CAREER_PAGES = [('A&L Goodbody', 'https://www.algoodbody.com/careers'), ('ABB', 'https://careers.abb/global/en'), ('Abbott', 'https://www.jobs.abbott/us/en/search-results?m=3&location=Ireland'), ('AbbVie', 'https://careers.abbvie.com/en/jobs?q=&options=&page=1&ln=Ireland&lr=100&li=IE'), ('Accenture', 'https://accenture.wd103.myworkdayjobs.com/AccentureCareers'), ('ActionPoint', 'https://www.actionpoint.ie/careers/'), ('Adobe', 'https://adobe.wd5.myworkdayjobs.com/external_experienced'), ('Advanced Micro Devices (AMD)', 'https://jobs.amd.com/go/Jobs-in-Ireland/8844800/'), ('AECOM', 'https://aecom.jobs/search-jobs/Ireland'), ('Aer Lingus', 'https://www.aerlingus.com/about-us/careers/'), ('AerCap', 'https://www.aercap.com/careers/'), ('Agilent Technologies', 'https://careers.agilent.com/'), ('AIB (Allied Irish Banks)', 'https://jobs.aib.ie/'), ('AIG', 'https://www.aig.com/careers'), ('Airbnb', 'https://careers.airbnb.com/'), ('AirNav Ireland', 'https://www.airnav.ie/careers'), ('Aiven', 'https://aiven.io/careers'), ('Akamai', 'https://www.akamai.com/careers'), ('Alexion Pharmaceuticals', 'https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2'), ('Alkermes', 'https://www.alkermes.com/careers'), ('Allianz Ireland', 'https://www.allianz.ie/about-allianz/careers.html'), ('Alter Domus', 'https://careers.alterdomus.com/'), ('Alvarez & Marsal', 'https://www.alvarezandmarsal.com/careers'), ('Amazon', 'https://www.amazon.jobs/en/locations/dublin-ireland'), ('AMCS Group', 'https://www.amcsgroup.com/careers/'), ('Amgen', 'https://careers.amgen.com/search-jobs/Ireland'), ('Amundi', 'https://about.amundi.com/Careers'), ('An Post', 'https://www.anpost.com/About/Careers'), ('Analog Devices', 'https://analogdevices.wd1.myworkdayjobs.com/External'), ('Anthropic', 'https://www.anthropic.com/careers'), ('Aon', 'https://aon.wd1.myworkdayjobs.com/AonCareers'), ('Apex Group', 'https://www.apexgroup.com/careers/'), ('Apple', 'https://jobs.apple.com/en-ie/search?location=ireland-IRL'), ('Applied Materials', 'https://www.appliedmaterials.com/us/en/careers.html'), ('Aptiv', 'https://www.aptiv.com/en/jobs/working-here/global-locations/ireland'), ('Arcadis', 'https://www.arcadis.com/en/careers'), ('Arista Networks', 'https://www.arista.com/en/careers'), ('Arthur Cox', 'https://www.arthurcox.com/careers/'), ('Arup', 'https://www.arup.com/careers'), ('ARYZTA Ireland', 'https://www.aryzta.com/careers/'), ('Asana', 'https://asana.com/careers'), ('ASL Aviation Holdings', 'https://www.aslaviationholdings.com/careers/'), ('ASML', 'https://www.asml.com/en/careers'), ('Astellas Pharma', 'https://www.astellas.com/en/careers'), ('AstraZeneca', 'https://careers.astrazeneca.com/search-jobs/Ireland'), ('AtkinsRéalis', 'https://careers.atkinsrealis.com/'), ('Atlas Copco Ireland', 'https://www.atlascopcogroup.com/en/careers'), ('Atlassian', 'https://www.atlassian.com/company/careers/jobs?location=Dublin'), ('Autodesk', 'https://autodesk.wd1.myworkdayjobs.com/Ext'), ('Auxilion', 'https://www.auxilion.com/auxilion-careers'), ('Avanade', 'https://www.avanade.com/en/career'), ('Aviva Ireland', 'https://www.aviva.ie/about/careers/'), ('Avolon', 'https://www.avolon.aero/careers'), ('AXA Ireland', 'https://www.axa.ie/careers/'), ('AXA XL', 'https://axaxl.com/careers'), ('Baker Tilly Ireland', 'https://www.bakertilly.ie/careers/'), ('Bank of America', 'https://careers.bankofamerica.com'), ('Bank of Ireland', 'https://www.bankofireland.com/about-bank-of-ireland/careers/'), ('Barclays', 'https://search.jobs.barclays/search-jobs/Ireland'), ('Bausch + Lomb', 'https://bauschhealth.wd1.myworkdayjobs.com/BauschHealthCareers'), ('Baxter International', 'https://jobs.baxter.com/search-jobs/Ireland'), ('Bayer', 'https://career.bayer.com/en/search-jobs/Ireland'), ('BDO Ireland', 'https://www.bdo.ie/en-gb/careers'), ('BearingPoint', 'https://bearingpoint.com/en/careers'), ('Becton Dickinson (BD)', 'https://bd.wd1.myworkdayjobs.com/BD_External'), ('BioMarin', 'https://www.biomarin.com/careers/jobs/'), ('BlackRock', 'https://careers.blackrock.com/search-jobs'), ('Block', 'https://block.xyz/careers'), ('BNP Paribas Ireland', 'https://group.bnpparibas/en/careers'), ('BNY', 'https://careers.bny.com'), ('Boehringer Ingelheim', 'https://www.boehringer-ingelheim.com/ie/careers'), ('Bord Gáis Energy', 'https://www.bordgaisenergy.ie/about-us/careers'), ('Bord na Móna', 'https://www.bordnamona.ie/careers/'), ('Boston Scientific', 'https://jobs.bostonscientific.com/search/?q=&locationsearch=Ireland'), ('Bristol Myers Squibb', 'https://careers.bms.com/us/en/search-results?m=3&location=Ireland'), ('Broadcom', 'https://broadcom.wd1.myworkdayjobs.com/External_Career'), ('Brown Brothers Harriman', 'https://careers.bbh.com/'), ('BT Ireland', 'https://www.bt.com/careers'), ('Bus Éireann', 'https://careers.buseireann.ie/'), ('ByrneWallace', 'https://byrnewallace.com/careers/'), ('C&C Group', 'https://www.candcgroupplc.com/careers/'), ('CACEIS', 'https://www.caceis.com/careers'), ('Cadence Design Systems', 'https://cadence.wd1.myworkdayjobs.com/External_Careers'), ('Cairn Homes', 'https://www.cairnhomes.com/careers/'), ('Canto', 'https://www.canto.com/careers/'), ('Cantor Fitzgerald Ireland', 'https://cantorfitzgerald.ie/about-us/careers/'), ('Capgemini', 'https://www.capgemini.com/careers/'), ('Carne Group', 'https://www.carnegroup.com/careers/'), ('CarTrawler', 'https://www.cartrawler.com/careers/'), ('Catalent', 'https://catalent.wd1.myworkdayjobs.com/External'), ('CBRE Ireland', 'https://www.cbre.ie/careers'), ('CDB Aviation', 'https://cdbaviation.aero/careers'), ('Central Bank of Ireland', 'https://www.centralbank.ie/careers'), ('CGI', 'https://cgi.com/en/careers'), ('Chargebee', 'https://www.chargebee.com/careers/'), ('Charles River Laboratories', 'https://jobs.criver.com/search-jobs/Ireland'), ('Check Point Software', 'https://www.checkpoint.com/careers/'), ('Chubb', 'https://careers.chubb.com/'), ('Cisco', 'https://jobs.cisco.com/main/jobs?location=Ireland'), ('Citco', 'https://www.citco.com/careers'), ('Citi', 'https://jobs.citi.com/search-jobs/Ireland'), ('Citrix', 'https://jobs.citrix.com/'), ('CitySwift', 'https://www.cityswift.com/careers'), ('ClickUp', 'https://clickup.com/careers'), ('Clio', 'https://www.clio.com/about/careers/'), ('Cloudflare', 'https://www.cloudflare.com/careers/jobs/'), ('CluneTech', 'https://www.clunetech.com/careers/'), ('Coca-Cola HBC Ireland', 'https://ie.coca-colahellenic.com/en/careers'), ('Codec', 'https://www.codec.ie/careers'), ('Cognizant', 'https://careers.cognizant.com/global/en'), ('Cohesity', 'https://www.cohesity.com/company/careers/'), ('Coillte', 'https://www.coillte.ie/about-us/careers/'), ('Coinbase', 'https://www.coinbase.com/careers/positions?location=dublin'), ('Coloplast', 'https://www.coloplast.com/about-us/careers/'), ('Concentrix (Ireland)', 'https://www.concentrix.com/careers/'), ('Convatec', 'https://www.convatecgroup.com/careers/'), ('Cook Medical', 'https://www.cookmedical.eu/careers/'), ('CRH', 'https://www.crh.com/careers'), ('Crusoe', 'https://www.crusoe.ai/careers'), ('Cubic³', 'https://www.cubic3.com/careers/'), ('Cushman & Wakefield Ireland', 'https://www.cushmanwakefield.com/en/ireland/careers'), ('CWSI', 'https://cwsisecurity.com/careers/'), ('daa (Dublin Airport Authority)', 'https://www.daa.ie/careers/'), ('DAE Capital', 'https://dubaiaerospace.com/careers'), ('Dalata Hotel Group', 'https://dalatahotelgroup.com/careers/'), ('Danaher Corporation', 'https://jobs.danaher.com/global/en/search-results?m=3&location=Ireland'), ('Daon', 'https://www.daon.com/careers/'), ('Datadog', 'https://www.datadoghq.com/careers/'), ('Datalex', 'https://datalex.com/careers'), ('DataStax', 'https://www.datastax.com/company/careers'), ('Davy', 'https://www.davy.ie/working-at-davy/opportunities'), ('DCC plc', 'https://www.dcc.ie/careers'), ('Dedalus', 'https://www.dedalus.com/global/en/careers/'), ('Dell Technologies', 'https://jobs.dell.com/location/ireland-jobs/375/2963597/2'), ('Deloitte Ireland', 'https://deloitteie.wd3.myworkdayjobs.com/experienced_professionals'), ('DePuy Synthes', 'https://jobs.jnj.com/en/jobs/?search=Ireland'), ('Deutsche Bank', 'https://careers.db.com'), ('Dexcom', 'https://www.dexcom.com/en-IE/careers'), ('DHL Ireland', 'https://www.dhl.com/ie-en/home/careers.html'), ('Diageo Ireland', 'https://diageo.wd3.myworkdayjobs.com/Diageo_Careers'), ('Dillon Eustace', 'https://www.dilloneustace.com/careers'), ('DNV', 'https://www.dnv.com/careers/'), ('DocuSign', 'https://www.docusign.com/company/careers/jobs?location=Dublin'), ('DPS Group (Arcadis)', 'https://www.dpsgroupglobal.com/careers'), ('DraftKings', 'https://careers.draftkings.com'), ('Dropbox', 'https://www.dropbox.com/jobs/all-jobs'), ('DSV Ireland', 'https://www.dsv.com/en/careers'), ('Dublin Bus', 'https://www.dublinbus.ie/careers'), ('Dublin Port Company', 'https://www.dublinport.ie/careers/'), ('DXC Technology', 'https://dxc.wd1.myworkdayjobs.com/DXC_Jobs'), ('Dynatrace', 'https://www.dynatrace.com/careers/'), ('Eaton', 'https://eaton.wd5.myworkdayjobs.com/Eaton'), ('eBay', 'https://jobs.ebayinc.com/'), ('Edwards Lifesciences', 'https://edwards.wd1.myworkdayjobs.com/EdwardsCareers'), ('Eir', 'https://www.eir.ie/careers/'), ('EirGrid', 'https://www.eirgrid.ie/careers'), ('Ekco', 'https://www.ek.co/careers/'), ('Elavon', 'https://usbank.wd1.myworkdayjobs.com/Elavon_Careers'), ('Eli Lilly', 'https://be.gatekeeper.lilly.com/careers/search-jobs?location=Ireland'), ('Emerald Airlines', 'https://www.emeraldairlines.com/careers'), ('Emerson', 'https://www.emerson.com/en-us/careers'), ('Energia Group', 'https://www.energiagroup.com/careers'), ('Enterprise Ireland', 'https://www.enterprise-ireland.com/en/About-Us/Careers/'), ('Ergo', 'https://ergo.ie/careers'), ('Ericsson', 'https://jobs.ericsson.com/search/?q=&locationsearch=Ireland'), ('ESB', 'https://careers.esb.ie/'), ('ESW', 'https://esw.com/careers/'), ('Etsy', 'https://careers.etsy.com/global/en'), ('Eurofins Scientific', 'https://careers.eurofins.com/ie/'), ('Eversheds Sutherland Ireland', 'https://www.eversheds-sutherland.com/en/ireland/careers'), ('EXL', 'https://www.exlservice.com/careers'), ('Expleo', 'https://careers.expleo.com/'), ('Exyte', 'https://www.exyte.net/Careers'), ('EY Ireland', 'https://www.ey.com/en_ie/careers'), ('FactSet', 'https://careers.factset.com/'), ('Fastway Couriers Ireland', 'https://www.fastway.ie/careers/'), ('FBD Insurance', 'https://www.fbd.ie/about/careers/'), ('FedEx Express Ireland', 'https://careers.fedex.com/fedex/'), ('Fenergo', 'https://www.fenergo.com/careers'), ('Fidelity International', 'https://careers.fidelityinternational.com/'), ('Fidelity Investments', 'https://jobs.fidelity.com/location/ireland-jobs/2324/2963597/2'), ('FINEOS', 'https://www.fineos.com/careers/'), ('Fiserv', 'https://www.careers.fiserv.com/search-jobs/Ireland'), ('Fitch Ratings', 'https://www.fitchratings.com/careers'), ('Fixify', 'https://www.fixify.com/careers'), ('Flipdish', 'https://www.flipdish.com/ie/careers'), ('Flutter Entertainment', 'https://flutter.com/careers/'), ('Forcepoint', 'https://www.forcepoint.com/company/work-with-us'), ('Fortinet', 'https://jobs.fortinet.com/'), ('Forvis Mazars Ireland', 'https://www.mazars.ie/Home/Join-us/Our-job-offers'), ('Franklin Templeton', 'https://careers.franklintempleton.com/'), ('Freudenberg Medical', 'https://careers.freudenberg.com/'), ('FTI Consulting', 'https://www.fticonsulting.com/careers'), ('Fujitsu', 'https://fujitsu.com/ie/about/careers'), ('Fáilte Ireland', 'https://www.failteireland.ie/About-Us/Careers.aspx'), ('Gartner', 'https://jobs.gartner.com/locations/dublin/'), ('Gas Networks Ireland', 'https://www.gasnetworks.ie/about-us/careers/'), ('GE HealthCare', 'https://careers.gehealthcare.com/'), ('Gemini', 'https://www.gemini.com/careers'), ('Genesys', 'https://genesys.wd1.myworkdayjobs.com/Genesys'), ('Gilead Sciences', 'https://gilead.wd1.myworkdayjobs.com/gileadcareers'), ('Glanbia', 'https://glanbia.com/careers'), ('Glanbia / Tirlán', 'https://www.tirlan.com/careers'), ('GlaxoSmithKline (GSK)', 'https://jobs.gsk.com/search-jobs/Ireland'), ('Glen Dimplex', 'https://www.glendimplex.com/careers'), ('Glenveagh Properties', 'https://glenveagh.ie/careers'), ('Global Payments', 'https://jobs.globalpayments.com/'), ('Goldman Sachs', 'https://www.goldmansachs.com/careers/'), ('Gong', 'https://www.gong.io/careers/'), ('Goodbody', 'https://www.goodbody.ie/careers'), ('Google', 'https://www.google.com/about/careers/applications/jobs/results/?location=Ireland'), ('Grant Thornton Ireland', 'https://iegt.wd3.myworkdayjobs.com/GTI_External_Careers_Experienced_Hires_ROI'), ('Greencore', 'https://www.greencore.com/careers/'), ('GridBeyond', 'https://gridbeyond.com/careers/'), ('Guidewire', 'https://www.guidewire.com/about/careers'), ('Haleon', 'https://careers.haleon.com/careers/*/ireland_ireland?domain=haleon.com'), ('Harvey', 'https://www.harvey.ai/careers'), ('HCLTech', 'https://www.hcltech.com/careers'), ('Heineken Ireland', 'https://www.heinekenireland.ie/careers/'), ('Hewlett Packard Enterprise (HPE)', 'https://careers.hpe.com/us/en/search-results?m=3&location=Ireland'), ('HIQA', 'https://www.hiqa.ie/about-us/careers'), ('Hitachi Energy', 'https://www.hitachienergy.com/careers'), ('Hollister Incorporated', 'https://www.hollister.com/en/careers'), ('Honeywell', 'https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Honeywell/jobs'), ('Hostelworld', 'https://careers.hostelworldgroup.com/'), ('HP (Hewlett-Packard)', 'https://jobs.hp.com/search-jobs/Ireland'), ('HSBC Ireland', 'https://www.about.hsbc.ie/careers'), ('HSE (Health Service Executive)', 'https://about.hse.ie/jobs/job-search/'), ('Huawei Ireland', 'https://career.huawei.com/'), ('HubSpot', 'https://www.hubspot.com/careers/jobs?location=dublin'), ('IBM', 'https://www.ibm.com/careers/search?field_keyword_05[0]=Ireland'), ('ICON plc', 'https://careers.iconplc.com/search-jobs/Ireland'), ('IDA Ireland', 'https://www.idaireland.com/about-ida-ireland/careers'), ('Illumina', 'https://illumina.wd1.myworkdayjobs.com/illumina-careers'), ('Indeed', 'https://www.indeed.jobs/'), ('Infineon Technologies', 'https://www.infineon.com/cms/en/careers/'), ('Infosys', 'https://www.infosys.com/careers.html'), ('Insulet Corporation', 'https://www.insulet.com/careers'), ('Integer Holdings', 'https://integer.net/careers/'), ('Integra LifeSciences', 'https://www.integralife.com/careers'), ('Integrity360', 'https://www.integrity360.com/careers'), ('Intel', 'https://jobs.intel.com/en/search-jobs/Ireland'), ('Intercom', 'https://www.intercom.com/careers'), ('Introba', 'https://www.introba.com/careers'), ('Invesco', 'https://careers.invesco.com/'), ('IQ-EQ', 'https://iqeq.com/careers/'), ('IQVIA', 'https://jobs.iqvia.com/search-jobs/Ireland'), ('Irish Aviation Authority', 'https://www.iaa.ie/careers'), ('Irish Distillers (Pernod Ricard)', 'https://www.irishdistillers.ie/careers/'), ('Irish Ferries', 'https://www.irishferries.com/uk-en/careers/'), ('Irish Life', 'https://www.irishlife.ie/about-us/careers'), ('Irish Rail (Iarnród Éireann)', 'https://www.irishrail.ie/en-ie/about-us/careers'), ('Isla Health', 'https://www.isla.health/careers'), ('Jabil', 'https://careers.jabil.com/'), ('Jacobs', 'https://www.jacobs.com/careers'), ('Jamf', 'https://www.jamf.com/careers/'), ('Jazz Pharmaceuticals', 'https://jazzpharma.wd5.myworkdayjobs.com/Jazz_Careers'), ('John Sisk & Son (Sisk Group)', 'https://www.johnsiskandson.com/careers'), ('Johnson & Johnson', 'https://jobs.jnj.com/en/jobs/?search=Ireland'), ('Johnson Controls', 'https://jobs.johnsoncontrols.com/'), ('JPMorgan Chase', 'https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions?location=Ireland'), ('Keelings', 'https://www.keelings.com/careers/'), ('Keeper Security', 'https://www.keepersecurity.com/company/careers/'), ('Kerry Group', 'https://jobs.kerry.com/search/?q=&locationsearch=Ireland'), ('Keysight Technologies', 'https://about.keysight.com/en/careers/'), ('Keywords Studios', 'https://www.keywordsstudios.com/en/careers/'), ('Kingspan Group', 'https://www.kingspan.com/group/careers'), ('Kirby Group Engineering', 'https://kirbygroup.com/careers/'), ('Kitman Labs', 'https://www.kitmanlabs.com/careers/'), ('Klaviyo', 'https://www.klaviyo.com/careers'), ('Korn Ferry', 'https://www.kornferry.com/careers'), ('KPMG Ireland', 'https://kpmg.com/ie/en/home/careers.html'), ('Kuehne+Nagel Ireland', 'https://jobs.kuehne-nagel.com/global/en/search-results?m=3&location=Ireland'), ('Kyndryl', 'https://www.kyndryl.com/us/en/careers'), ('Labcorp', 'https://careers.labcorp.com/global/en'), ('Lam Research', 'https://www.lamresearch.com/careers/'), ('Laya Healthcare', 'https://www.layahealthcare.ie/aboutus/careers/'), ('LearnUpon', 'https://www.learnupon.com/careers/'), ('LetsGetChecked', 'https://www.letsgetchecked.com/careers/'), ('Linesight', 'https://www.linesight.com/careers/'), ('LinkedIn', 'https://careers.linkedin.com/Locations/Dublin'), ('LK Shields', 'https://www.lkshields.ie/careers'), ('Logitech', 'https://www.logitech.com/en-us/careers'), ('Macquarie Group', 'https://www.macquarie.com/au/en/careers.html'), ('Maples Group Ireland', 'https://maples.com/careers'), ('Mars Ireland', 'https://careers.mars.com/'), ('Marsh McLennan', 'https://mmc.wd1.myworkdayjobs.com/MMC'), ('Marvell Technology', 'https://www.marvell.com/company/careers.html'), ('Mason Hayes & Curran', 'https://www.mhc.ie/careers'), ('Mastercard', 'https://mastercard.wd1.myworkdayjobs.com/CorporateCareers'), ('Matheson', 'https://www.matheson.com/careers'), ('McCann FitzGerald', 'https://www.mccannfitzgerald.com/careers'), ('McKinsey & Company', 'https://www.mckinsey.com/careers/search-jobs?locations=Dublin'), ('Mediahuis Ireland', 'https://www.mediahuis.ie/careers/'), ('Mediolanum International Funds', 'https://www.mifl.ie/careers/open-positions'), ('Medpace', 'https://www.medpace.com/careers/'), ('Medtronic', 'https://jobs.medtronic.com/search/?q=&locationsearch=Ireland'), ('Mercer', 'https://mmc.wd1.myworkdayjobs.com/MMC'), ('Merck Group', 'https://jobs.vibrantm.com/merck/go/Jobs-in-Ireland/8330701/'), ('Mercury Engineering', 'https://www.mercuryeng.com/careers/'), ('Merit Medical', 'https://www.merit.com/careers/'), ('Meta', 'https://www.metacareers.com/jobs?locations[0]=Dublin%2C%20Ireland'), ('Microchip Technology', 'https://careers.microchip.com/'), ('Microsoft', 'https://jobs.careers.microsoft.com/global/en/search?lc=Ireland'), ('MongoDB', 'https://www.mongodb.com/careers/jobs?location=Dublin%2C%20Ireland'), ('Monzo', 'https://monzo.com/careers'), ("Moody's", 'https://careers.moodys.com/'), ('Moonshot', 'https://moonshotteam.com/careers/'), ('Morgan Stanley', 'https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/user-home'), ('Morningstar', 'https://www.morningstar.com/careers'), ('Motorola Solutions', 'https://www.motorolasolutions.com/en_us/about/careers.html'), ('Mott MacDonald', 'https://www.mottmac.com/careers'), ('MSCI', 'https://www.msci.com/careers'), ('MSD', 'https://jobs.msd.com/ireland'), ('MSD (Merck Sharp & Dohme)', 'https://msd.wd5.myworkdayjobs.com/SearchJobs'), ('MUFG Investor Services', 'https://www.mufg-investorservices.com/careers/'), ('Musgrave Group (SuperValu / Centra)', 'https://www.musgravegroup.com/careers/'), ('Nestlé Ireland', 'https://www.nestlejobs.com/'), ('NetApp', 'https://www.netapp.com/company/careers/'), ('Noesis', 'https://www.noesis.pt/en/careers'), ('Nokia', 'https://www.nokia.com/careers/'), ('Nordic Aviation Capital', 'https://nordicaviationcapital.com/careers'), ('Northern Trust', 'https://northerntrust.wd1.myworkdayjobs.com/External_Careers'), ('Notion', 'https://www.notion.so/careers'), ('Novartis', 'https://www.novartis.com/careers/career-search?country%5B0%5D=IE'), ('NTMA', 'https://www.ntma.ie/about-the-ntma/careers/current-opportunities'), ('NTT DATA', 'https://careers.nttdata.com/'), ('Nutanix', 'https://www.nutanix.com/careers'), ('NXP Semiconductors', 'https://nxp.wd3.myworkdayjobs.com/careers'), ('OFX', 'https://www.ofx.com/en-ie/careers/'), ('Okta', 'https://www.okta.com/careers/'), ('Oliver Wyman', 'https://www.oliverwyman.com/careers.html'), ('One Identity', 'https://www.oneidentity.com/careers/'), ('OpenAI', 'https://openai.com/careers/'), ('OpenText', 'https://careers.opentext.com/'), ('Optum', 'https://www.optum.ie/careers.html'), ('Oracle', 'https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions?location=Ireland'), ('Ornua', 'https://www.ornua.com/careers/'), ('PA Consulting', 'https://www.paconsulting.com/careers'), ('Palo Alto Networks', 'https://jobs.paloaltonetworks.com/en/jobs/'), ('Park Place Technologies', 'https://www.parkplacetechnologies.com/company/careers/'), ('PayPal', 'https://paypal.wd1.myworkdayjobs.com/jobs'), ('Payrails', 'https://www.payrails.com/careers'), ('PepsiCo', 'https://www.pepsicojobs.com/'), ('Perrigo', 'https://careers.perrigo.com/'), ('Personio', 'https://www.personio.com/about-personio/careers/locations/dublin/'), ('Pfizer', 'https://pfizer.wd1.myworkdayjobs.com/PfizerCareers?locationCountry=0878e1d528b846e38b3940173bc5b43a'), ('Philip Lee', 'https://www.philiplee.ie/careers/'), ('PIMCO', 'https://careers.pimco.com/'), ('Ping Identity', 'https://www.pingidentity.com/en/company/careers.html'), ('Pinterest', 'https://www.pinterestcareers.com/en/jobs/?location=Dublin'), ('PM Group', 'https://www.pmgroup-global.com/careers/'), ('Port of Cork Company', 'https://www.portofcork.ie/careers/'), ('Proofpoint', 'https://www.proofpoint.com/us/company/careers'), ('Protiviti', 'https://www.protiviti.com/us-en/careers'), ('PTSB (Permanent TSB)', 'https://www.ptsb.ie/about-us/careers/'), ('Public Jobs / Civil Service', 'https://publicjobs.ie'), ('Publift', 'https://www.publift.com/careers'), ('PwC Ireland', 'https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers'), ('Qashio', 'https://www.qashio.com/careers'), ('QIAGEN', 'https://www.qiagen.com/us/about-us/careers'), ('Qorvo', 'https://www.qorvo.com/careers'), ('Qualcomm', 'https://www.qualcomm.com/company/careers'), ('Qualtrics', 'https://www.qualtrics.com/careers/us/en/search-results?keywords=Dublin'), ('Quantexa', 'https://www.quantexa.com/careers/'), ('Quest Software', 'https://careers.quest.com/'), ('Qumulo', 'https://careers.qumulo.com/'), ('Rapid7', 'https://www.rapid7.com/careers/jobs/'), ('Red Hat', 'https://www.redhat.com/en/jobs'), ('Reddit', 'https://www.redditinc.com/careers'), ('Refinitiv (LSEG)', 'https://www.lseg.com/en/careers'), ('Regeneron', 'https://careers.regeneron.com/en/jobs/?location=Ireland'), ('Renesas Electronics', 'https://www.renesas.com/us/en/about/careers'), ('Research Ireland', 'https://www.researchireland.ie/'), ('ResMed', 'https://resmed.wd1.myworkdayjobs.com/ResMed_External_Careers'), ('Revenue', 'https://www.revenue.ie/en/corporate/information-about-revenue/careers/index.aspx'), ('Revvity (PerkinElmer)', 'https://jobs.revvity.com/'), ('Riot Games', 'https://www.riotgames.com/en/work-with-us/offices/dublin'), ('Rippling', 'https://www.rippling.com/careers'), ('Roche', 'https://www.roche.com/careers/jobs?country=Ireland'), ('Rockwell Automation', 'https://rockwellautomation.wd1.myworkdayjobs.com/External_Rockwell_Automation'), ('RoviSys', 'https://www.rovisys.com/careers'), ('RSA Insurance Ireland', 'https://www.rsagroup.ie/careers/'), ('RTÉ (Raidió Teilifís Éireann)', 'https://about.rte.ie/working-with-rte/vacancies/'), ('Rubrik', 'https://www.rubrik.com/company/careers'), ('RxSense', 'https://www.rxsense.com/careers/'), ('Ryanair', 'https://careers.ryanair.com/'), ('S&P Global', 'https://www.spglobal.com/en/careers/overview'), ('Sage', 'https://sage.com/en-ie/company/careers'), ('Salesforce', 'https://salesforce.wd12.myworkdayjobs.com/External_Career_Site'), ('Sanofi', 'https://sanofi.wd3.myworkdayjobs.com/SanofiCareers'), ('SAP', 'https://jobs.sap.com/search/?q=&locationsearch=Ireland'), ('Savills Ireland', 'https://careers.savills.ie/'), ('Schneider Electric', 'https://www.se.com/ww/en/about-us/careers/overview.jsp'), ('Seagate', 'https://www.seagate.com/careers/'), ('ServiceNow', 'https://careers.servicenow.com/jobs?location=Dublin%2C%20Ireland'), ('Shannon Airport Group', 'https://www.shannonairport.ie/about-us/careers/'), ('SHEIN', 'https://careers.sheingroup.com/'), ('Siemens', 'https://www.siemens.com/ie/en/company/jobs.html'), ('Siemens Healthineers', 'https://www.siemens-healthineers.com/careers'), ('Sky Ireland', 'https://careers.sky.com/job-search/?location=Ireland'), ('Slack', 'https://salesforce.wd12.myworkdayjobs.com/Slack'), ('Slalom', 'https://www.slalom.com/en/careers'), ('Smartling', 'https://www.smartling.com/careers/'), ('Smarttech247', 'https://www.smarttech247.com/careers/'), ('SMBC Aviation Capital', 'https://www.smbc.com/careers'), ('Smith & Nephew', 'https://www.smith-nephew.com/en-gb/careers'), ('Smurfit Westrock', 'https://www.smurfitwestrock.com/careers'), ('Snowflake', 'https://careers.snowflake.com/us/en/search-results?m=3&location=Ireland'), ('Societe Generale', 'https://careers.societegenerale.com/'), ('SolarWinds', 'https://jobs.solarwinds.com/'), ('Sophos', 'https://www.sophos.com/en-us/company/careers'), ('Spectrum.Life', 'https://www.spectrum.life/careers'), ('Splunk', 'https://www.splunk.com/en_us/careers.html'), ('Squarespace', 'https://www.squarespace.com/careers/jobs'), ('SSE Airtricity / SSE', 'https://careers.sse.com/search-jobs/Ireland'), ('Stantec', 'https://www.stantec.com/en/careers'), ('State Street', 'https://statestreet.wd1.myworkdayjobs.com/Global'), ('Stena Line Ireland', 'https://www.stenaline.com/careers/'), ('STMicroelectronics', 'https://www.st.com/content/st_com/en/about/careers.html'), ('Stripe', 'https://stripe.com/jobs'), ('Stryker', 'https://careers.stryker.com/en-US/search?keywords=&location=Ireland'), ('SumUp', 'https://www.sumup.com/careers/'), ('Sun Life Ireland', 'https://www.sunlife.ie/en/careers/'), ('Supply Wisdom', 'https://www.supplywisdom.com/careers'), ('Susquehanna International Group (SIG)', 'https://sig.com/careers/jobs/?location=dublin'), ('Syneos Health', 'https://www.syneoshealth.com/careers'), ('Synopsys', 'https://careers.synopsys.com/search-jobs'), ('Takeda', 'https://takeda.wd3.myworkdayjobs.com/External'), ('Taoglas', 'https://www.taoglas.com/careers/'), ('Tata Consultancy Services (TCS)', 'https://www.tcs.com/careers'), ('Taxback International', 'https://www.taxbackinternational.com/careers/'), ('Teagasc', 'https://www.teagasc.ie/about/opportunities/careers/'), ('Teamwork.com', 'https://www.teamwork.com/careers/'), ('Tech Mahindra', 'https://careers.techmahindra.com/'), ('Teleflex', 'https://teleflex.wd1.myworkdayjobs.com/TeleflexCareers'), ('Teleperformance (Ireland)', 'https://www.teleperformance.com/en-us/careers/'), ('Tenable', 'https://www.tenable.com/careers'), ('Teneo Ireland', 'https://www.teneo.com/careers/'), ('Terumo', 'https://www.terumo.com/careers'), ('Tesco Ireland', 'https://www.tesco-careers.com/search-jobs/?location=Ireland'), ('Tetra Tech', 'https://www.tetratech.com/careers'), ('Teva Pharmaceuticals', 'https://teva.wd1.myworkdayjobs.com/Teva_Careers'), ('Texas Instruments', 'https://careers.ti.com/'), ('The Doyle Collection', 'https://www.doylecollection.com/careers'), ('The Irish Times', 'https://www.irishtimes.com/about-us/careers/'), ('Thermo Fisher Scientific', 'https://jobs.thermofisher.com/global/en/search-results?m=3&location=Ireland'), ('Three Ireland', 'https://www.three.ie/about/careers.html'), ('TikTok', 'https://careers.tiktok.com/position?keyword=&location=Dublin%2C+Ireland'), ('Tines', 'https://www.tines.com/careers/'), ('TK Maxx Ireland', 'https://www.tjxjobs.com/'), ('Toast', 'https://pos.toasttab.com/careers'), ('Tourism Ireland', 'https://www.tourismireland.com/about-us/careers'), ('Trading 212', 'https://www.trading212.com/careers'), ('Trane Technologies', 'https://jobs.tranetechnologies.com/'), ('TransferMate', 'https://www.transfermate.com/careers/'), ('Transport Infrastructure Ireland', 'https://www.tii.ie/about/careers/'), ('Travelers', 'https://careers.travelers.com/'), ('Trellix', 'https://careers.trellix.com/'), ('Trend Micro', 'https://www.trendmicro.com/en_ie/about/careers.html'), ('Tricentis', 'https://www.tricentis.com/company/careers'), ('Twilio', 'https://www.twilio.com/en-us/company/jobs'), ('UBS', 'https://www.ubs.com/ie/en/careers.html'), ('Udemy', 'https://about.udemy.com/careers/'), ('Uisce Éireann (Irish Water)', 'https://www.water.ie/about/careers/'), ('Unilever Ireland', 'https://careers.unilever.com/'), ('Uniphar Group', 'https://uniphar.com/pharma/careers/'), ('UPS Ireland', 'https://www.jobs-ups.com/search-jobs/Ireland'), ('Veolia Ireland', 'https://www.veolia.ie/careers'), ('Version 1', 'https://www.version1.com/careers/'), ('VHI Healthcare', 'https://www.vhi.ie/about-us/careers'), ('Viatris', 'https://viatris.wd1.myworkdayjobs.com/ViatrisCareers'), ('Virgin Media Ireland', 'https://www.virginmedia.ie/careers/'), ('Visa', 'https://search.visa.com/careers?location=Ireland'), ('Vodafone Ireland', 'https://jobs.vodafone.com/search-jobs/Ireland'), ('Walkers Ireland', 'https://www.walkersglobal.com/index.php/careers'), ('Waters Corporation', 'https://www.waters.com/nextgen/ie/en/about-waters/careers.html'), ('Wayflyer', 'https://wayflyer.com/careers'), ('Waystone', 'https://www.waystone.com/careers/'), ('Wells Fargo', 'https://www.wellsfargojobs.com/'), ('West Pharmaceutical Services', 'https://careers.westpharma.com/'), ('William Fry', 'https://www.williamfry.com/careers/'), ('Willis Towers Watson (WTW)', 'https://wtw.wd1.myworkdayjobs.com/WTWCareers'), ('Winthrop Technologies', 'https://www.win-tech.ie/careers/'), ('Wipro', 'https://careers.wipro.com/'), ("Woodie's", 'https://www.woodies.ie/careers'), ('Workato', 'https://www.workato.com/careers'), ('Workday', 'https://workday.wd5.myworkdayjobs.com/Workday'), ('WorkFusion', 'https://www.workfusion.com/careers/'), ('Workhuman', 'https://workhuman.com/careers'), ('Workvivo', 'https://www.workvivo.com/careers/'), ('WSP', 'https://www.wsp.com/en-gb/careers'), ('WuXi Biologics', 'https://www.wuxibiologics.com/careers/'), ('Xenon arc', 'https://www.xenonarc.com/careers'), ('Zara / Inditex Ireland', 'https://www.inditexcareers.com/'), ('Zendesk', 'https://jobs.zendesk.com/us/en/search-results?keywords=Ireland'), ('Zimmer Biomet', 'https://zimmerbiomet.wd1.myworkdayjobs.com/Zimmer_Biomet_Careers'), ('Zscaler', 'https://www.zscaler.com/careers'), ('Zurich Insurance', 'https://www.zurich.ie/about-us/careers/')]

# ---------------------------------------------------------------------------
# Ireland company registry
#
# This is separate from the ATS connector lists. Every employer in this
# registry remains visible even when its ATS returns zero jobs or errors.
# Registry expanded with the uploaded 100-company Ireland career-page list.
# ireland_companies.csv is the runtime source of truth; this embedded list is the fallback.

# This gives the dashboard the same "live matches + manual-check companies"
# behaviour as the reference Job Radar.
# ---------------------------------------------------------------------------

IRELAND_COMPANY_REGISTRY = ['A&L Goodbody', 'ABB', 'Abbott', 'AbbVie', 'Accenture', 'ActionPoint', 'Adobe', 'Advanced Micro Devices (AMD)', 'AECOM', 'Aer Lingus', 'AerCap', 'Agilent Technologies', 'AIB (Allied Irish Banks)', 'AIG', 'Airbnb', 'AirNav Ireland', 'Aiven', 'Akamai', 'Alexion Pharmaceuticals', 'Alkermes', 'Allianz Ireland', 'Alter Domus', 'Alvarez & Marsal', 'Amazon', 'AMCS Group', 'Amgen', 'Amundi', 'An Post', 'Analog Devices', 'Anthropic', 'Aon', 'Apex Group', 'Apple', 'Applied Materials', 'Aptiv', 'Arcadis', 'Arista Networks', 'Arthur Cox', 'Arup', 'ARYZTA Ireland', 'Asana', 'ASL Aviation Holdings', 'ASML', 'Astellas Pharma', 'AstraZeneca', 'AtkinsRéalis', 'Atlas Copco Ireland', 'Atlassian', 'Autodesk', 'Auxilion', 'Avanade', 'Aviva Ireland', 'Avolon', 'AXA Ireland', 'AXA XL', 'Baker Tilly Ireland', 'Bank of America', 'Bank of Ireland', 'Barclays', 'Bausch + Lomb', 'Baxter International', 'Bayer', 'BDO Ireland', 'BearingPoint', 'Becton Dickinson (BD)', 'BioMarin', 'BlackRock', 'Block', 'BNP Paribas Ireland', 'BNY', 'Boehringer Ingelheim', 'Bord Gáis Energy', 'Bord na Móna', 'Boston Scientific', 'Bristol Myers Squibb', 'Broadcom', 'Brown Brothers Harriman', 'BT Ireland', 'Bus Éireann', 'ByrneWallace', 'C&C Group', 'CACEIS', 'Cadence Design Systems', 'Cairn Homes', 'Canto', 'Cantor Fitzgerald Ireland', 'Capgemini', 'Carne Group', 'CarTrawler', 'Catalent', 'CBRE Ireland', 'CDB Aviation', 'Central Bank of Ireland', 'CGI', 'Chargebee', 'Charles River Laboratories', 'Check Point Software', 'Chubb', 'Cisco', 'Citco', 'Citi', 'Citrix', 'CitySwift', 'ClickUp', 'Clio', 'Cloudflare', 'CluneTech', 'Coca-Cola HBC Ireland', 'Codec', 'Cognizant', 'Cohesity', 'Coillte', 'Coinbase', 'Coloplast', 'Concentrix (Ireland)', 'Convatec', 'Cook Medical', 'CRH', 'Crusoe', 'Cubic³', 'Cushman & Wakefield Ireland', 'CWSI', 'daa (Dublin Airport Authority)', 'DAE Capital', 'Dalata Hotel Group', 'Danaher Corporation', 'Daon', 'Datadog', 'Datalex', 'DataStax', 'Davy', 'DCC plc', 'Dedalus', 'Dell Technologies', 'Deloitte Ireland', 'DePuy Synthes', 'Deutsche Bank', 'Dexcom', 'DHL Ireland', 'Diageo Ireland', 'Dillon Eustace', 'DNV', 'DocuSign', 'DPS Group (Arcadis)', 'DraftKings', 'Dropbox', 'DSV Ireland', 'Dublin Bus', 'Dublin Port Company', 'DXC Technology', 'Dynatrace', 'Eaton', 'eBay', 'Edwards Lifesciences', 'Eir', 'EirGrid', 'Ekco', 'Elavon', 'Eli Lilly', 'Emerald Airlines', 'Emerson', 'Energia Group', 'Enterprise Ireland', 'Ergo', 'Ericsson', 'ESB', 'ESW', 'Etsy', 'Eurofins Scientific', 'Eversheds Sutherland Ireland', 'EXL', 'Expleo', 'Exyte', 'EY Ireland', 'FactSet', 'Fastway Couriers Ireland', 'FBD Insurance', 'FedEx Express Ireland', 'Fenergo', 'Fidelity International', 'Fidelity Investments', 'FINEOS', 'Fiserv', 'Fitch Ratings', 'Fixify', 'Flipdish', 'Flutter Entertainment', 'Forcepoint', 'Fortinet', 'Forvis Mazars Ireland', 'Franklin Templeton', 'Freudenberg Medical', 'FTI Consulting', 'Fujitsu', 'Fáilte Ireland', 'Gartner', 'Gas Networks Ireland', 'GE HealthCare', 'Gemini', 'Genesys', 'Gilead Sciences', 'Glanbia', 'Glanbia / Tirlán', 'GlaxoSmithKline (GSK)', 'Glen Dimplex', 'Glenveagh Properties', 'Global Payments', 'Goldman Sachs', 'Gong', 'Goodbody', 'Google', 'Grant Thornton Ireland', 'Greencore', 'GridBeyond', 'Guidewire', 'Haleon', 'Harvey', 'HCLTech', 'Heineken Ireland', 'Hewlett Packard Enterprise (HPE)', 'HIQA', 'Hitachi Energy', 'Hollister Incorporated', 'Honeywell', 'Hostelworld', 'HP (Hewlett-Packard)', 'HSBC Ireland', 'HSE (Health Service Executive)', 'Huawei Ireland', 'HubSpot', 'IBM', 'ICON plc', 'IDA Ireland', 'Illumina', 'Indeed', 'Infineon Technologies', 'Infosys', 'Insulet Corporation', 'Integer Holdings', 'Integra LifeSciences', 'Integrity360', 'Intel', 'Intercom', 'Introba', 'Invesco', 'IQ-EQ', 'IQVIA', 'Irish Aviation Authority', 'Irish Distillers (Pernod Ricard)', 'Irish Ferries', 'Irish Life', 'Irish Rail (Iarnród Éireann)', 'Isla Health', 'Jabil', 'Jacobs', 'Jamf', 'Jazz Pharmaceuticals', 'John Sisk & Son (Sisk Group)', 'Johnson & Johnson', 'Johnson Controls', 'JPMorgan Chase', 'Keelings', 'Keeper Security', 'Kerry Group', 'Keysight Technologies', 'Keywords Studios', 'Kingspan Group', 'Kirby Group Engineering', 'Kitman Labs', 'Klaviyo', 'Korn Ferry', 'KPMG Ireland', 'Kuehne+Nagel Ireland', 'Kyndryl', 'Labcorp', 'Lam Research', 'Laya Healthcare', 'LearnUpon', 'LetsGetChecked', 'Linesight', 'LinkedIn', 'LK Shields', 'Logitech', 'Macquarie Group', 'Maples Group Ireland', 'Mars Ireland', 'Marsh McLennan', 'Marvell Technology', 'Mason Hayes & Curran', 'Mastercard', 'Matheson', 'McCann FitzGerald', 'McKinsey & Company', 'Mediahuis Ireland', 'Mediolanum International Funds', 'Medpace', 'Medtronic', 'Mercer', 'Merck Group', 'Mercury Engineering', 'Merit Medical', 'Meta', 'Microchip Technology', 'Microsoft', 'MongoDB', 'Monzo', "Moody's", 'Moonshot', 'Morgan Stanley', 'Morningstar', 'Motorola Solutions', 'Mott MacDonald', 'MSCI', 'MSD', 'MSD (Merck Sharp & Dohme)', 'MUFG Investor Services', 'Musgrave Group (SuperValu / Centra)', 'Nestlé Ireland', 'NetApp', 'Noesis', 'Nokia', 'Nordic Aviation Capital', 'Northern Trust', 'Notion', 'Novartis', 'NTMA', 'NTT DATA', 'Nutanix', 'NXP Semiconductors', 'OFX', 'Okta', 'Oliver Wyman', 'One Identity', 'OpenAI', 'OpenText', 'Optum', 'Oracle', 'Ornua', 'PA Consulting', 'Palo Alto Networks', 'Park Place Technologies', 'PayPal', 'Payrails', 'PepsiCo', 'Perrigo', 'Personio', 'Pfizer', 'Philip Lee', 'PIMCO', 'Ping Identity', 'Pinterest', 'PM Group', 'Port of Cork Company', 'Proofpoint', 'Protiviti', 'PTSB (Permanent TSB)', 'Public Jobs / Civil Service', 'Publift', 'PwC Ireland', 'Qashio', 'QIAGEN', 'Qorvo', 'Qualcomm', 'Qualtrics', 'Quantexa', 'Quest Software', 'Qumulo', 'Rapid7', 'Red Hat', 'Reddit', 'Refinitiv (LSEG)', 'Regeneron', 'Renesas Electronics', 'Research Ireland', 'ResMed', 'Revenue', 'Revvity (PerkinElmer)', 'Riot Games', 'Rippling', 'Roche', 'Rockwell Automation', 'RoviSys', 'RSA Insurance Ireland', 'RTÉ (Raidió Teilifís Éireann)', 'Rubrik', 'RxSense', 'Ryanair', 'S&P Global', 'Sage', 'Salesforce', 'Sanofi', 'SAP', 'Savills Ireland', 'Schneider Electric', 'Seagate', 'ServiceNow', 'Shannon Airport Group', 'SHEIN', 'Siemens', 'Siemens Healthineers', 'Sky Ireland', 'Slack', 'Slalom', 'Smartling', 'Smarttech247', 'SMBC Aviation Capital', 'Smith & Nephew', 'Smurfit Westrock', 'Snowflake', 'Societe Generale', 'SolarWinds', 'Sophos', 'Spectrum.Life', 'Splunk', 'Squarespace', 'SSE Airtricity / SSE', 'Stantec', 'State Street', 'Stena Line Ireland', 'STMicroelectronics', 'Stripe', 'Stryker', 'SumUp', 'Sun Life Ireland', 'Supply Wisdom', 'Susquehanna International Group (SIG)', 'Syneos Health', 'Synopsys', 'Takeda', 'Taoglas', 'Tata Consultancy Services (TCS)', 'Taxback International', 'Teagasc', 'Teamwork.com', 'Tech Mahindra', 'Teleflex', 'Teleperformance (Ireland)', 'Tenable', 'Teneo Ireland', 'Terumo', 'Tesco Ireland', 'Tetra Tech', 'Teva Pharmaceuticals', 'Texas Instruments', 'The Doyle Collection', 'The Irish Times', 'Thermo Fisher Scientific', 'Three Ireland', 'TikTok', 'Tines', 'TK Maxx Ireland', 'Toast', 'Tourism Ireland', 'Trading 212', 'Trane Technologies', 'TransferMate', 'Transport Infrastructure Ireland', 'Travelers', 'Trellix', 'Trend Micro', 'Tricentis', 'Twilio', 'UBS', 'Udemy', 'Uisce Éireann (Irish Water)', 'Unilever Ireland', 'Uniphar Group', 'UPS Ireland', 'Veolia Ireland', 'Version 1', 'VHI Healthcare', 'Viatris', 'Virgin Media Ireland', 'Visa', 'Vodafone Ireland', 'Walkers Ireland', 'Waters Corporation', 'Wayflyer', 'Waystone', 'Wells Fargo', 'West Pharmaceutical Services', 'William Fry', 'Willis Towers Watson (WTW)', 'Winthrop Technologies', 'Wipro', "Woodie's", 'Workato', 'Workday', 'WorkFusion', 'Workhuman', 'Workvivo', 'WSP', 'WuXi Biologics', 'Xenon arc', 'Zara / Inditex Ireland', 'Zendesk', 'Zimmer Biomet', 'Zscaler', 'Zurich Insurance']

CAREERS_URL_OVERRIDES = {
    "Apple": "https://jobs.apple.com/en-ie/search",
    "EY Ireland": "https://careers.ey.com/ey",
    "Accenture": "https://www.accenture.com/ie-en/careers/jobsearch",
    "Citi": "https://jobs.citi.com/location/dublin-jobs/287/2963597/2",
}

def _company_key(value: str) -> str:
    value = (value or "").lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)

def _registry_url_map():
    out = {}
    for company, url in JSONLD_CAREER_PAGES:
        key = _company_key(company)
        if key:
            out[key] = url
    for company, url in CAREERS_URL_OVERRIDES.items():
        out[_company_key(company)] = url
    return out

def _load_company_master():
    """Load the Ireland master registry. CSV is intentionally editable without touching Python."""
    try:
        import csv
        with open("ireland_companies.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            return [
                (
                    (r.get("company_name") or "").strip(),
                    (r.get("career_url") or "").strip(),
                    (r.get("source_type") or "employer").strip() or "employer",
                    (r.get("category") or "").strip(),
                )
                for r in rows
            ]
    except Exception as exc:
        print(f"  ! ireland_companies.csv unavailable, using embedded registry: {exc}")
    return [(name, None, "employer", "") for name in IRELAND_COMPANY_REGISTRY]

def build_company_registry(include_cache: bool = False):
    url_map = _registry_url_map()
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
        registry.append({
            "company": name,
            "country": "Ireland",
            "platform": platform,
            "careers_url": url,
            "automatic": platform != "manual-check",
            "source_type": source_type,
            "category": category,
        })
    return registry

def curated_company_key_set():
    return {_company_key(name) for name, _url, _source_type, _category in _load_company_master()}

def is_curated_company_name(name: str) -> bool:
    key = _company_key(company_display_name(name))
    return key in curated_company_key_set()

def company_display_name(raw: str) -> str:
    key = _company_key(raw)
    for name in IRELAND_COMPANY_REGISTRY:
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
    }
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
    "Central Bank of Ireland",
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
    "Grant Thornton Ireland": "grantthornton_browser",
    "HSBC Ireland": "hsbc_browser",
    "Bank of America": "bank_of_america_browser",
    "Cognizant": "cognizant_browser",
    "AIB (Allied Irish Banks)": "aib_browser",
    "Central Bank of Ireland": "central_bank_browser",
    "BNP Paribas": "bnp_paribas_browser",
    "Capgemini": "capgemini_browser",
    "Boston Scientific": "boston_scientific_browser",
    "DXC Technology": "dxc_browser",
    "Johnson & Johnson": "jnj_browser",
    "Johnson Controls": "johnson_controls_browser",
    "Dropbox": "dropbox_browser",
    "Zscaler": "zscaler",
}

# Exact enterprise-platform mappings learned from validated public career-site
# hosts. Unlike guessed ATS slugs, these are revalidated at runtime before use.
KNOWN_EIGHTFOLD_MAPPINGS = {
    "NetApp": "netapp",
    "STMicroelectronics": "stmicroelectronics",
    "Bayer": "bayer",
}

KNOWN_PHENOM_MAPPINGS = {
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

VISA_SPONSOR_KEYWORDS = [
    "visa sponsorship", "sponsor visa", "will sponsor", "sponsorship available",
    "employment permit", "work permit sponsorship", "stamp 1g", "stamp 1",
]
VISA_NO_SPONSOR_KEYWORDS = [
    "no visa sponsorship", "no sponsorship", "unable to sponsor",
    "will not sponsor", "cannot sponsor", "without sponsorship",
    "must have the right to work", "right to work in ireland without restriction",
    "eligible to work in ireland without",
]

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


def visa_sponsorship_from_text(*parts: str) -> str:
    text = " ".join(_strip_html(p) for p in parts if p).lower()
    if not text.strip():
        return "not_mentioned"
    if any(k in text for k in VISA_NO_SPONSOR_KEYWORDS):
        return "no_sponsorship"
    if any(k in text for k in VISA_SPONSOR_KEYWORDS):
        return "sponsors"
    return "not_mentioned"


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
                "location": location,
                "url": url,
                "updated_at": j.get("postedOn"),
            })

        if len(postings) < page_size:
            break
        offset += page_size
        time.sleep(0.25)

    return out


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
                ref = j.get("ref") or {}
                out.append({
                    "company": company_id,
                    "ats": "smartrecruiters",
                    "title": title,
                    "location": location,
                    "url": j.get("applyUrl") or ref.get("jobAd") or f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id','')}",
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

ATS_PROBE_VERSION = 35
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
    company: str,
    host: str,
    site_number: str,
    country_code: str = "IE",
    max_pages: int = 12,
):
    """Collect jobs from Oracle Recruiting Candidate Experience.

    Oracle's public Candidate Experience UI is JavaScript-heavy, but its job
    search uses the public recruitingCEJobRequisitions REST resource. This
    adapter keeps the collection company-specific and Ireland-specific.
    """
    base = host.rstrip("/")
    endpoint = base + "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    out = []
    seen = set()
    limit = 100

    for page in range(max_pages):
        offset = page * limit
        finder = (
            f"findReqs;siteNumber={site_number},"
            f"workLocationCountryCode={country_code},"
            f"limit={limit},offset={offset}"
        )
        params = {
            "onlyData": "true",
            "expand": "requisitionList",
            "finder": finder,
        }
        url = endpoint + "?" + urllib.parse.urlencode(params, safe=";,")
        data = fetch_json(url)
        if not data:
            break

        rows = []
        # Oracle CE commonly returns one search container whose requisitionList
        # contains the visible jobs. Be tolerant of tenants that flatten it.
        for item in data.get("items") or []:
            reqs = item.get("requisitionList")
            if isinstance(reqs, list):
                rows.extend(reqs)
            elif item.get("Title"):
                rows.append(item)

        if not rows:
            break

        for j in rows:
            title = str(j.get("Title") or j.get("title") or "").strip()
            location = str(
                j.get("PrimaryLocation")
                or j.get("Location")
                or j.get("location")
                or ""
            ).strip()
            country = str(j.get("PrimaryLocationCountry") or "").upper()

            # Keep explicit IE rows and any location that independently passes
            # the project's strict Republic-of-Ireland location check.
            if country not in {"IE", "IRL"} and not region_ok(location):
                continue

            req_id = (
                j.get("Id")
                or j.get("RequisitionId")
                or j.get("RequisitionNumber")
                or j.get("JobId")
            )
            if not title or req_id is None:
                continue

            req_id = str(req_id)
            key = req_id
            if key in seen:
                continue
            seen.add(key)

            job_url = (
                f"{base}/hcmUI/CandidateExperience/en/sites/"
                f"{site_number}/job/{urllib.parse.quote(req_id)}/"
            )

            out.append({
                "company": company,
                "ats": "oracle",
                "title": title,
                "location": location or "Ireland",
                "url": job_url,
                "updated_at": j.get("PostedDate") or j.get("PostingStartDate"),
                "closing_date": j.get("PostingEndDate"),
                "description_text": j.get("ShortDescriptionStr") or "",
                "requisition_id": req_id,
            })

        has_more = bool(data.get("hasMore"))
        if not has_more and len(rows) < limit:
            break

    return out


def scrape_jpmorgan():
    return scrape_oracle_candidate_experience(
        "JPMorgan Chase",
        "https://jpmc.fa.oraclecloud.com",
        "CX_1001",
        "IE",
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
                hs = page.locator("h3")
                for i in range(hs.count()):
                    h = hs.nth(i)
                    title = _browser_text(h)
                    if not title or len(title) > 220:
                        continue
                    low = title.lower().strip()
                    if low in {"jobs", "careers", "search jobs", "locations", "teams"} or low in seen:
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
                    seen.add(low)
                    out.append({
                        "company": "Google", "ats": "direct", "title": title,
                        "location": _browser_location(card, "Ireland"), "url": url,
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
    return _scrape_ey_playwright()


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



def _browser_board_collect(company, urls, href_patterns, default_location="Ireland", max_scrolls=20,
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
                    results[href] = {
                        "company": "TikTok", "ats": "direct", "title": title[:300],
                        "location": _browser_location(card, "Dublin, Ireland"),
                        "url": href, "updated_at": None, "description_text": card[:5000],
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
    return _browser_board_collect(
        "DXC Technology",
        [
            "https://careers.dxc.com/job-search-results/?location=Ireland",
            "https://careers.dxc.com/job-search-results/?keyword=&location=Ireland",
        ],
        ("careers.dxc.com/job/",),
        default_location="Ireland",
        max_scrolls=30,
        require_ireland=True,
    )


def _static_official_jobs(company, url, href_pattern, default_location="Ireland"):
    """Parse server-rendered official career pages with requests/BeautifulSoup."""
    results = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="ignore")
        _mark_connector_health(company, True, "Official careers page loaded", url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a.get("href") or "")
            if href_pattern not in href:
                continue
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
            if not title or len(title) < 3:
                continue
            node = a
            card = title
            for _ in range(5):
                node = node.parent if getattr(node, "parent", None) else None
                if not node:
                    break
                txt = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
                if txt and len(txt) <= 3000:
                    card = txt
            evidence = f"{title} {card} {href}".lower()
            if not re.search(r"\b(ireland|dublin|cork|galway|limerick|waterford|athlone)\b", evidence):
                continue
            location = "Dublin, Ireland" if "dublin" in evidence else default_location
            results[href] = {
                "company": company, "ats": "direct", "title": title[:300],
                "location": location, "url": href, "updated_at": None,
                "description_text": card[:5000],
            }
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), url)
        print(f"  ! {company} static scrape failed: {exc}")
    return list(results.values())


def scrape_bank_of_america():
    """Temporarily withheld: local validation returned non-Ireland false positives."""
    company = "Bank of America"
    url = "https://careers.bankofamerica.com/en-us/job-search/ireland"
    _mark_connector_health(
        company,
        False,
        "Needs verification: previous collector returned non-Ireland jobs as Dublin",
        url,
    )
    print("  Bank of America: withheld from live jobs pending Ireland-only connector verification")
    return []

def scrape_cognizant():
    """Cognizant: use server-rendered global job results and verify detail metadata for Ireland."""
    company = "Cognizant"
    search_url = "https://careers.cognizant.com/global-en/jobs/"
    results = {}
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="ignore")
        _mark_connector_health(company, True, "Official Cognizant careers board loaded", search_url)
        soup = BeautifulSoup(html, "html.parser")
        links=[]
        for a in soup.find_all("a", href=True):
            href=urllib.parse.urljoin(search_url,a.get("href") or "")
            if re.search(r"/global-en/jobs/\d+/[^/]+/?$", href):
                links.append((href, re.sub(r"\s+"," ",a.get_text(" ",strip=True)).strip()))
        # Current page can be global and paginated; inspect visible detail links and retain only Ireland.
        for href, anchor_title in links[:250]:
            try:
                req2=urllib.request.Request(href, headers={"User-Agent":"Mozilla/5.0"})
                with urllib.request.urlopen(req2, timeout=15) as r2:
                    h2=r2.read().decode("utf-8",errors="ignore")
                soup2=BeautifulSoup(h2,"html.parser")
                text=re.sub(r"\s+"," ",soup2.get_text(" ",strip=True)).strip()
                low=text.lower()
                if not re.search(r"\b(ireland|dublin|cork|limerick|galway|waterford)\b", low):
                    continue
                title=anchor_title
                if not title:
                    h=soup2.find(["h1","h2"])
                    title=re.sub(r"\s+"," ",h.get_text(" ",strip=True)).strip() if h else "Cognizant role"
                loc="Dublin, Ireland" if "dublin" in low else ("Cork, Ireland" if "cork" in low else "Ireland")
                results[href]={"company":company,"ats":"direct","title":title[:300],"location":loc,"url":href,"updated_at":None,"description_text":text[:5000]}
            except Exception:
                continue
    except Exception as exc:
        _mark_connector_health(company, False, str(exc), search_url)
        print(f"  ! Cognizant official careers failed: {exc}")
    print(f"  Cognizant official careers: {len(results)} Ireland jobs")
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
    """Temporarily withheld: local validation returned navigation pages, not job records."""
    company = "Capgemini"
    url = "https://www.capgemini.com/careers/join-capgemini/job-search/"
    _mark_connector_health(
        company,
        False,
        "Needs verification: previous collector returned careers/navigation links instead of jobs",
        url,
    )
    print("  Capgemini: withheld from live jobs pending job-detail connector verification")
    return []

def scrape_blackrock():
    jobs = _browser_board_collect(
        "BlackRock",
        [
            "https://careers.blackrock.com/location/dublin-jobs/45831/2963597-7521314-2964574/4",
            "https://careers.blackrock.com/search-jobs?location=Dublin%2C%20Ireland",
        ],
        ("careers.blackrock.com/job/dublin/",),
        default_location="Dublin, Ireland",
        max_scrolls=30,
        require_ireland=False,
    )
    for j in jobs:
        title = (j.get("title") or "").strip()
        j["title"] = re.split(r"\s*Location:\s*", title, maxsplit=1, flags=re.I)[0].strip()
        j["location"] = "Dublin, Ireland"
    return jobs


def scrape_bank_of_ireland():
    jobs = _browser_board_collect(
        "Bank of Ireland",
        ["https://careers.bankofireland.com/jobs/search"],
        ("careers.bankofireland.com/jobs/",),
        default_location="Ireland",
        max_scrolls=20,
        require_ireland=False,
    )
    cleaned=[]; seen=set()
    for j in jobs:
        title=(j.get("title") or "").strip(); url=(j.get("url") or "").strip()
        text=f"{title} {j.get('description_text') or ''} {url}".lower()
        if not title or title.lower().startswith("skip to") or "#jobs_search_results" in url:
            continue
        irish=bool(re.search(r"\b(dublin|cork|galway|limerick|waterford|kilkenny|ireland)\b", text))
        uk_only=bool(re.search(r"\b(bristol|london|belfast|england|scotland|wales|united kingdom|\buk\b)\b", text)) and not bool(re.search(r"\b(dublin|cork|galway|limerick|waterford|kilkenny|ireland)\b", text))
        if not irish or uk_only: continue
        key=url.split("#",1)[0].rstrip("/").lower()
        if key in seen: continue
        seen.add(key)
        if "dublin" in text: j["location"]="Dublin, Ireland"
        elif "cork" in text: j["location"]="Cork, Ireland"
        elif "galway" in text: j["location"]="Galway, Ireland"
        else: j["location"]="Ireland"
        cleaned.append(j)
    return cleaned


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
    return _browser_board_collect(
        "Johnson Controls",
        [
            "https://jobs.johnsoncontrols.com/search-jobs/Ireland",
            "https://jobs.johnsoncontrols.com/",
        ],
        ("jobs.johnsoncontrols.com/job/",),
        default_location="Ireland",
        max_scrolls=35,
        require_ireland=True,
    )


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


def scrape_grant_thornton():
    """Grant Thornton Ireland official careers collector.

    The historical iegt.wd3 Workday board is no longer dependable.
    Use the current Grant Thornton Ireland careers pages instead.
    """

    urls = [
        "https://www.grantthornton.ie/careers/",
        "https://www.grantthornton.ie/careers/experienced-hires/",
        "https://www.grantthornton.ie/careers/early-careers/",
    ]

    results = []
    seen = set()

    for url in urls:
        try:
            rows = _scrape_public_careers_page(
                "Grant Thornton Ireland",
                url,
                (
                    "/careers/",
                    "/job/",
                    "/jobs/",
                    "vacanc",
                    "opportunit",
                    "experienced-hires",
                    "graduate",
                    "undergrad",
                ),
                default_location="Ireland",
            )
        except Exception as exc:
            print(f"  ! Grant Thornton Ireland page failed {url}: {exc}")
            continue

        for job in rows:
            title = (job.get("title") or "").strip()
            href = (job.get("url") or "").strip()

            if not title or not href:
                continue

            low_title = title.lower()

            # Remove obvious navigation/information links.
            blocked = (
                "why grant thornton",
                "our benefits",
                "working at grant thornton",
                "careers",
                "experienced hires",
                "early careers",
                "graduate programme",
                "undergrad programme",
                "contact us",
            )

            if low_title in blocked:
                continue

            key = href.split("?")[0].rstrip("/").lower()
            if key in seen:
                continue

            seen.add(key)
            job["company"] = "Grant Thornton Ireland"
            job["ats"] = "direct"
            results.append(job)

    print(
        f"  Grant Thornton Ireland official careers: "
        f"{len(results)} candidate Ireland opportunities"
    )

    return results


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


def scrape_direct_company(company: str):
    fn={
        "Accenture": scrape_accenture,
        "Citi": scrape_citi,
        "Apple": scrape_apple,
        "BlackRock": scrape_blackrock,
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
        "Bank of America": scrape_bank_of_america,
        "Cognizant": scrape_cognizant,
        "AIB (Allied Irish Banks)": scrape_aib,
        "Central Bank of Ireland": scrape_central_bank_ireland,
        "BNP Paribas": scrape_bnp_paribas,
        "Capgemini": scrape_capgemini,
        "Boston Scientific": scrape_boston_scientific,
        "DXC Technology": scrape_dxc,
        "Johnson & Johnson": scrape_jnj,
        "Johnson Controls": scrape_johnson_controls,
        "Dropbox": scrape_dropbox,
        "Zscaler": scrape_zscaler,
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


def classify_role_family(title, description, profile):
    title_n = normalized_title(title)
    text = f"{title_n} {_norm_phrase(description)}"
    best = ("Other", "None", 0, [])
    for family, cfg in (profile.get("role_families") or {}).items():
        hits = []
        for phrase in cfg.get("titles", []):
            p = _norm_phrase(phrase)
            if p and (p in title_n or (len(p.split()) >= 2 and p in text)):
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
    score += min(34, len(matched) * 4)
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
    for term in profile.get("negative_title_terms", []):
        if _norm_phrase(term) in title_n:
            score -= 18
            break

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
    stable_url = (job.get("url") or "").split("?")[0].rstrip("/").lower()
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
                    results.extend(found)
                    print(f"phenom/{company}: {len(found)} Ireland jobs")
                else:
                    errors.append(f"phenom/{company}: endpoint validation failed")
            except Exception as e:
                errors.append(f"phenom/{company}: {e}")

    # Proprietary/direct company search surfaces. These are deliberately
    # conservative and only emit records with local Ireland context.
    for company in ("Accenture", "Citi", "Apple", "BlackRock", "Bank of Ireland", "Google", "Microsoft", "Meta", "TikTok", "Oracle", "Red Hat", "JPMorgan Chase", "EY Ireland", "KPMG Ireland", "NetApp", "Version 1", "Grant Thornton Ireland", "HSBC Ireland", "Bank of America", "Cognizant", "AIB (Allied Irish Banks)", "Central Bank of Ireland", "BNP Paribas", "Capgemini", "Johnson & Johnson", "Johnson Controls", "Zscaler"):
        if not _targeted(company):
            continue
        try:
            found = scrape_direct_company(company)
            results.extend(found)
            print(f"direct/{company}: {len(found)} Ireland jobs")
        except Exception as e:
            errors.append(f"direct/{company}: {e}")
        time.sleep(0.4)

    # Suman-style dynamic ATS discovery for companies not already wired into a
    # known connector. Confirmed mappings persist in ats_platform_cache.json.
    initial_registry = build_company_registry(include_cache=False)
    if TARGET_COMPANIES:
        initial_registry = [x for x in initial_registry if _targeted(x.get("company", ""))]
    try:
        dynamic_found, _dynamic_mappings = discover_and_scrape_manual(initial_registry)
        results.extend(dynamic_found)
    except Exception as e:
        errors.append(f"dynamic ATS discovery: {e}")

    # Universal structured-data fallback over the CURRENT registry. Run concurrently.
    # FULL still checks every curated careers page each run; FAST checks targets only.
    jsonld_tasks = []
    for company, url, _source_type, _category in _load_company_master():
        if not url or not _targeted(company):
            continue
        jsonld_tasks.append(("jsonld", company, lambda company=company,url=url: scrape_jsonld(company, url)))
    _parallel_collect(jsonld_tasks, results, errors, workers=min(SCRAPE_WORKERS, 20))

    run_broad_aggregators = SCRAPE_MODE != "fast" or not TARGET_COMPANIES
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

    if _targeted("Amazon"):
        try:
            found = scrape_amazon("")
            results.extend(found)
            print(f"direct/Amazon: {len(found)} Ireland jobs")
        except Exception as e:
            errors.append(f"direct/Amazon: {e}")
        time.sleep(0.5)

    if _targeted("Netflix"):
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

        # The broader 500-company rescue remains FULL-only.
        if SCRAPE_MODE != "fast":
            rescue_registry = build_company_registry(include_cache=True)
            rescued = rescue_zero_companies_with_aggregators(results, rescue_registry)
            results.extend(rescued)
    except Exception as e:
        errors.append(f"zero-company targeted rescue: {e}")


    # ireland_companies.csv is the SINGLE source of truth for the dashboard
    # company universe.
    #
    # Apply this to EVERY source, including aggregators. Previously Jooble,
    # Adzuna and Careerjet were allowed to introduce adjacent employers that
    # were not present in ireland_companies.csv, which caused removed/unwanted
    # companies to leak back into data.json and the HTML company filter.
    curated_keys = curated_company_key_set()

    filtered_results = []
    dropped_non_curated = 0

    for j in results:
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
            f"{dropped_non_curated} jobs from companies not in ireland_companies.csv"
        )

    results = filtered_results

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
        if company_key == _company_key("Accenture") and raw_url:
            try:
                parsed = urllib.parse.urlsplit(raw_url)
                params = urllib.parse.parse_qs(parsed.query)
                requisition_id = (params.get("id") or [""])[0].strip().lower()
                base_url = urllib.parse.urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
                ).lower()
                url_key = (
                    f"{base_url}?id={requisition_id}"
                    if requisition_id
                    else base_url
                )
            except Exception:
                url_key = raw_url.lower()
        else:
            url_key = raw_url.split("?")[0].rstrip("/").lower()

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
        j["visa_sponsorship"] = visa_sponsorship_from_text(
            j.get("title"), j.get("location"), description_text,
        )
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
        "coverage_diagnostics": coverage_diagnostics,
        "connector_health": CONNECTOR_HEALTH,
        "live_zero_companies": [
            x for x in coverage_diagnostics if x.get("state") == "live_zero"
        ],
        "coverage_state_counts": {
            state: sum(1 for x in coverage_diagnostics if x["state"] == state)
            for state in ("working", "live_zero", "configured_zero", "no_validated_connector")
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

    print(f"\nDone. {len(results)} matching jobs written to data.json ({len(errors)} companies errored).")


if __name__ == "__main__":
    main()
