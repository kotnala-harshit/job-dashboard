# Ireland Job Radar

A personal job-search dashboard for discovering and prioritising roles across Ireland.

The project collects jobs directly from employer career pages and supported job sources, normalises them into a consistent dataset, ranks them against the target profile, and publishes a static dashboard through GitHub Pages.

## What the dashboard does

The dashboard is designed to make a high-volume Ireland job search easier to manage.

It includes:

- Live jobs collected from employer career pages and supported job sources
- Company-level career-page coverage
- Job recency and newly discovered roles
- Candidate match scoring
- Employment-type classification
- Source and connector diagnostics
- Company states such as working, proven zero, configured zero, no validated connector, and false-zero/broken cases
- Browser-local Saved and Applied states for lightweight tracking

Saved and Applied status is stored locally in the browser. It is not a server-side application-tracking system and does not create separate backend records.

## Current dashboard views

The web interface includes views for:

- Live jobs
- Careers pages
- Manual search needed
- No live jobs
- False zero / broken
- Companies with live jobs
- Proven working

The job table can also be filtered by application state, including Saved and Applied.

## Data pipeline

The scraper:

1. Loads the employer registry and connector configuration.
2. Checks supported employer career systems and job feeds.
3. Normalises job titles, locations, URLs, dates, employment types, and other available fields.
4. Scores jobs against the target profile.
5. Deduplicates and merges results.
6. Writes the dashboard dataset.
7. Builds the static encrypted dashboard payload.
8. Commits refreshed output back to the repository when data changes.

## Automation schedule

The scheduler checks at `:07`, `:22`, `:37`, and `:52`, collecting when the
last completed refresh is at least 55 minutes old. GitHub may delay scheduled
runs. Collection has a 45-minute limit within a 65-minute workflow.

New links are checked on each collection; previous checks are reused for up to
24 hours. A bounded audit (10 minutes plus 2 minutes of retries) keeps slow
employers from preventing publication. Pending checks remain visible. Only
repeat-confirmed unavailable links are removed; browser blocks and timeouts
are labelled for manual checking. Deduplication uses vacancy URLs/requisition
IDs, preserving distinct requisitions with the same title.

An open, unlocked dashboard checks the newest encrypted payload every five
minutes and when returning to the tab. New published listings appear without
logging in again; saved/applied state and filters remain local. This refreshes
published collections, not employer listings in real time. No plaintext job
JSON or additional stored credentials are needed.

Batch 1 adds Accenture, EY Ireland, KPMG Ireland, Oracle, SAP, Auxilion,
Capgemini, Cognizant, Dell Technologies, and IBM.

Batch 2 adds Infosys, NTT DATA, Tata Consultancy Services (TCS), Wipro,
Bloomberg, Musgrave Group, Ryanair, A&L Goodbody, AECOM, and Agilent Technologies.

Batch 3 adds AIB, Allianz Ireland, AMCS Group, Aon, Arup, ASL Aviation Holdings,
AstraZeneca, Bank of Ireland, BioMarin, and BNP Paribas Ireland.

Batch 4 adds DPS Group (Arcadis), ESB, Grant Thornton Ireland, Honeywell,
Huawei Ireland, Irish Life, Irish Rail, Jacobs, Johnson Controls, and NetApp.

Batches 5-14 complete the active direct-company connector set. The current
295-company board contains 136 direct connectors; they run in groups of up to
10 while the remaining companies continue through their existing ATS/core
collectors.

Each direct collector runs once in an isolated process, with four collectors
at a time and a three-minute limit per company. Their jobs pass through the same Ireland validation,
deduplication, ranking, history, and graduate processing as the core boards.
The Proven working tab shows batch membership and unsuccessful checks.

Link/refresh regression checks: `python3 test_job_quality.py` and
`python3 test_secure_refresh.py`. The browser check needs the existing Playwright
Chromium runtime plus cryptography, and uses disposable test credentials.
