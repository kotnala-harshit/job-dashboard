# Ireland Job Radar

Ireland Job Radar is an automated Republic-of-Ireland job discovery system that collects vacancies from employer career sites and ATS platforms, normalizes them into a single dataset, preserves source/history diagnostics, enriches jobs with candidate-fit and sponsorship evidence, and serves the result through a fast static dashboard.

The project is built around a simple rule:

> **Collect broadly. Normalize centrally. Personalize at ranking time.**

The active scrape universe is **250 employers** selected from a **600-employer master registry**. The remaining employers stay in reserve and can be activated later without rebuilding the registry.

## System overview

```text
600-company master registry
        │
        ├── 250 active employers
        │
        ▼
ATS / employer / aggregator discovery
        │
        ▼
Republic-of-Ireland validation
        │
        ▼
Normalization + deduplication
        │
        ├── candidate-fit metadata
        ├── posting recency
        ├── visa wording
        ├── sponsorship history
        └── official permit history
        │
        ▼
Persistent job + connector history
        │
        ▼
data.json
        │
        ▼
Encrypted GitHub Pages dashboard
```

## What the project does

The scraper reads the active employer registry, discovers job-level sources, collects vacancies, restricts results to genuine Ireland opportunities, normalizes inconsistent source fields, deduplicates equivalent vacancies, tracks newly seen jobs, calculates ranking metadata, records sponsorship evidence and writes the current dashboard dataset plus coverage diagnostics.

The browser dashboard then provides keyword search, company/location/sector/source filters, posting-age filters, employment type and experience-level filters, visa evidence, new-posting filtering and a **Match my profile** option. Job cards link back to the original vacancy source. Users can also ignore jobs locally in their browser.

The dashboard deliberately does **not** maintain Saved or Applications views. Those features were removed to keep the UI and client-side state focused on discovery and prioritisation.

## Current architecture

### Employer registry

`ireland_job_radar_HARSHIT_MASTER.csv` is the source of truth for the employer universe. The `include_in_scrape_registry` column controls whether an employer participates in the active scrape.

The current registry contains 600 employers, with 250 enabled. Reserve companies remain in the same file for future testing or replacement of low-value active sources.

### Collection and connectors

`scrape.py` contains the collection and normalization pipeline. It combines reusable ATS logic with source-specific handling because employers frequently change career platforms, URL structures and anti-bot behavior.

The project contains support and discovery logic for ATS/source families including Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Pinpoint and direct employer sources, together with browser-rendered and structured-data fallbacks where required.

Connector discovery and expensive fallback work use persistent caches so every 15-minute refresh does not need to rediscover unchanged source behavior.

### Ireland-only validation

Collection is intentionally broad, but dashboard output is restricted to qualifying Republic-of-Ireland vacancies. Location evidence is normalized before jobs enter the final dataset so global jobs from multinational employers do not leak into the Ireland view merely because the employer itself operates in Ireland.

### Deduplication and history

The system persists previously seen vacancies and company/source history. This allows it to distinguish a genuinely new job from a vacancy that simply reappeared in a later scrape and prevents one temporary source failure from erasing knowledge that a connector has worked before.

Historical counters are based on job/source evidence rather than raw workflow-run count. This matters because the main scraper is scheduled every 15 minutes.

## Coverage states

A zero-job result is not automatically trustworthy. Coverage diagnostics use explicit source state rather than treating every configured connector as a genuine zero.

| State | Meaning |
|---|---|
| **Working** | The current source returned qualifying Ireland jobs. |
| **True zero jobs** (`live_zero`) | An authoritative/proven live source is working but currently has zero qualifying Ireland vacancies. |
| **Needs verification** (`configured_zero`) | A connector is configured and returned zero, but that zero is not independently trusted yet. |
| **Manual search needed** (`no_validated_connector`) | No validated job-level automatic connector is currently available. |
| **Proven working** | Historical evidence shows the employer/source has successfully produced valid jobs. |

Historical success alone does not create a True Zero entry. True Zero is driven by the authoritative current `live_zero` state.

## Candidate matching

Candidate matching is enrichment and ranking metadata, not a collection gate. Low-scoring jobs remain available in the main dataset.

`profile.json` supplies the backend profile used by the scoring pipeline. Relevant fields written to jobs include:

- `candidate_match_score`
- `discovery_score`
- `match_reasons`
- `matched_skills`
- `missing_skills`
- `experience_fit`
- `role_family`
- `role_tier`

The dashboard's **Match my profile** checkbox reuses the backend candidate score and currently filters at **55% or higher**. It does not calculate a separate browser-side matching model.

## Visa and sponsorship intelligence

Visa information is separated into three evidence layers because each answers a different question.

### Current vacancy wording

The scraper scans current job text for explicit sponsorship/work-permit language and classifies it as:

- `sponsors`
- `no_sponsorship`
- `not_mentioned`

Negative wording is evaluated carefully so phrases such as “no visa sponsorship” are not interpreted as positive evidence. Silence remains neutral.

### Employer sponsorship history

`sponsorship_history.json` stores sponsorship-language evidence from **unique postings**, rather than counting the same vacancy again on every scrape. This avoids inflating employer history because of the 15-minute refresh cadence.

### Official Irish employment-permit history

`official_permit_stats.json` stores employer-level historical permit evidence produced by `visa_stats.py`. This is a prioritisation signal, not a promise that a specific current vacancy will sponsor a permit.

The dashboard can therefore show current vacancy wording, historical employer wording and official permit history without conflating them.

## Dashboard performance

`index.html` is intentionally a static, dependency-light frontend.

To keep several thousand live vacancies responsive:

- the initial Live Jobs view creates only **200 job cards**;
- **Load more** adds another **200** at a time;
- secondary tabs are rendered only when selected;
- the previous document-wide `MutationObserver` was removed;
- card-overlap protection is applied directly during card creation;
- visa/employer-history metadata is allowed to use the full card width so text remains readable.

Filtering still operates over the complete in-memory job dataset; the 200-job limit controls DOM rendering, not search coverage.

## Dashboard views

The current interface contains:

- **Live matches** — current qualifying Ireland jobs;
- **Careers pages** — employer career-page directory/fallbacks;
- **Manual search needed** — employers without a validated automatic job-level connector;
- **True zero jobs** — authoritative current zero-vacancy sources;
- **Needs verification** — configured zero results that are not yet trusted;
- **Companies with live jobs** — employers currently returning vacancies;
- **Proven working** — employers with successful historical source evidence.

The main company filter is intentionally restricted to the 250 active employers rather than exposing all 600 registry rows.

## Secure deployment

The public GitHub Pages artifact is built by `secure_build.py`; the repository's raw dashboard data is not copied directly into the Pages artifact.

The secure build:

1. reads `index.html` and required local JSON data;
2. injects an in-memory fetch layer for protected JSON;
3. encrypts the complete dashboard payload with **AES-256-GCM**;
4. derives the encryption key with **PBKDF2-HMAC-SHA256** using 600,000 iterations and the configured site credentials;
5. writes a minimal `secure_site/` artifact containing the login shell and encrypted payload;
6. verifies in CI that protected plaintext files are absent before deployment.

Deployment credentials are supplied through GitHub Actions secrets `SITE_USERNAME` and `SITE_PASSWORD`. The password must be at least 16 characters.

## Automation

Three GitHub Actions workflows maintain the project.

### Job refresh — `.github/workflows/scrape.yml`

Runs on demand and requests a refresh every 15 minutes:

```yaml
schedule:
  - cron: '*/15 * * * *'
```

It installs the scraper/browser dependencies, runs `scrape.py`, preserves generated outputs across remote races, rebases the generated state onto the latest `origin/main`, and retries the push when another workflow or manual change lands first.

GitHub scheduled workflows are not real-time guarantees; runs can start later than the requested cron time.

### Secure Pages deployment — `.github/workflows/deploy-secure-pages.yml`

Runs when dashboard/security/data inputs change or when manually dispatched. It builds the encrypted site, verifies that protected plaintext files are absent and deploys the resulting artifact through GitHub Pages.

### Permit-stat refresh — `.github/workflows/refresh-visa-stats.yml`

Runs monthly (and on demand), refreshes official Irish employment-permit statistics with `visa_stats.py`, and safely commits the resulting `official_permit_stats.json`.

## Important files

| File | Role |
|---|---|
| `scrape.py` | Main collection, connector, normalization, ranking, history and enrichment pipeline. |
| `index.html` | Static dashboard UI, filtering, diagnostics and paged card rendering. |
| `data.json` | Generated current jobs and dashboard diagnostics. |
| `ireland_job_radar_HARSHIT_MASTER.csv` | 600-employer master registry and 250-employer active-set control. |
| `profile.json` | Candidate profile used for backend match scoring. |
| `seen_jobs.json` | Persistent seen-job state for new/returning vacancy tracking. |
| `company_history.json` | Historical company/source evidence used by connector diagnostics. |
| `sponsorship_history.json` | Unique-posting sponsorship-language history. |
| `official_permit_stats.json` | Historical employer-level Irish permit evidence. |
| `ats_platform_cache.json` | Persisted ATS/platform discovery cache. |
| `browser_scrape_cache.json` | Cache for browser-rendered source discovery/results. |
| `jsonld_cache.json` | Cache for structured-data discovery/results. |
| `visa_stats.py` | Official permit-stat ingestion/update utility. |
| `secure_build.py` | Builds the encrypted GitHub Pages artifact. |
| `.github/workflows/scrape.yml` | 15-minute automated job refresh. |
| `.github/workflows/deploy-secure-pages.yml` | Encrypted Pages build/deployment. |
| `.github/workflows/refresh-visa-stats.yml` | Monthly permit-stat refresh. |

Generated state files are committed intentionally because the scraper relies on persisted history between ephemeral GitHub Actions runners.

## Local development

Python 3.11 matches the CI environment.

Install the main scraper dependencies:

```bash
python3 -m pip install requests beautifulsoup4 curl_cffi playwright
python3 -m playwright install chromium
```

Run syntax validation and the scraper:

```bash
python3 -m py_compile scrape.py secure_build.py visa_stats.py
python3 scrape.py
```

Run the dashboard locally from the repository root with any static HTTP server, for example:

```bash
python3 -m http.server 8765
```

Then open `http://localhost:8765/`.

For permit-stat maintenance:

```bash
python3 visa_stats.py \
  --companies ireland_job_radar_HARSHIT_MASTER.csv \
  --output official_permit_stats.json
```

To test the encrypted site locally, install `cryptography` and provide credentials:

```bash
python3 -m pip install cryptography
SITE_USERNAME='your-user' \
SITE_PASSWORD='a-long-test-password' \
SECURE_OUTPUT_DIR='secure_site' \
python3 secure_build.py
```

Do not commit real site credentials.

## Optional scraper credentials

The refresh workflow can provide API credentials through repository secrets for supported aggregator/discovery sources:

- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `JOOBLE_API_KEY`
- `CAREERJET_API_KEY`

`GITHUB_TOKEN` is supplied by GitHub Actions for workflow operations. Secrets belong in GitHub Actions secrets, not source files.

## Safe manual Git workflow

Automated refreshes can update `main` while a manual change is being prepared. Never overwrite newer generated state with an older local copy.

Before editing or committing:

```bash
git fetch origin main
git status -sb
git rev-list --left-right --count HEAD...origin/main
```

If the working tree is clean and the branch is only behind:

```bash
git pull --ff-only origin main
```

Before pushing a manual commit, fetch again. If `origin/main` advanced, integrate the latest remote state first rather than force-pushing.

The automated scrape and permit workflows already contain retry logic specifically to coexist with concurrent updates to `main`.

## Maintenance principles

When changing the project:

- preserve the 250-company active-registry boundary unless intentionally changing registry membership;
- do not classify `configured_zero` as True Zero;
- do not use historical success alone to manufacture a current True Zero state;
- preserve generated history files unless deliberately resetting history;
- keep candidate matching as ranking/filter metadata rather than a collection gate;
- keep sponsorship silence neutral;
- prefer original employer/ATS vacancy URLs for applications;
- avoid expensive document-wide DOM observers or rendering thousands of cards at once;
- test a connector directly before treating its zero result as authoritative;
- do not force-push over automated refresh commits.

## Repository hygiene

The repository intentionally keeps generated JSON history/cache files that are required by scheduled runs. Temporary backups, Python bytecode and local OS files are ignored through `.gitignore`.

Obsolete Saved/Application dashboard code and unused Supabase configuration have been removed. The duplicate `.github/README.md` copy is also unnecessary; this root `README.md` is the single project documentation source.

## Disclaimer

Job availability, source behavior, visa wording and permit evidence can change at any time. The dashboard is a discovery and prioritisation tool. Always verify the current vacancy, eligibility requirements and application instructions on the original employer source before applying.
