# Ireland Job Search Engine

A free, GitHub-hosted job search engine focused on **Ireland**.

The project continuously checks a large registry of employers, collects publicly available Ireland job postings from supported ATS platforms and direct career sites, deduplicates them, and publishes the results to a searchable GitHub Pages dashboard.

**Live dashboard:** https://kotnala-harshit.github.io/job-dashboard/

**Repository:** https://github.com/kotnala-harshit/job-dashboard

## What it does

The pipeline is designed as a broad Ireland job aggregator rather than a profile-specific shortlist.

It:
- tracks a large Ireland-focused company registry;
- collects **all discoverable Ireland vacancies**, rather than filtering only for selected job titles;
- checks multiple ATS platforms and direct employer career sites;
- automatically discovers ATS mappings for previously unresolved companies;
- caches successful ATS discoveries for later runs;
- applies a strict Ireland location filter;
- deduplicates postings across sources;
- tracks newly discovered jobs between runs;
- exposes companies that still require manual checking;
- exposes automatically checked companies that currently return zero Ireland postings;
- publishes everything to a searchable/filterable GitHub Pages dashboard.

## Dashboard features

The dashboard provides:
- free-text search across job title, company, and location;
- **All companies** filter populated from the complete company registry;
- Ireland location/area filtering;
- sector filtering;
- source / ATS filtering;
- posted-within filters for 1, 3, 6, 12, and 24 hours, plus 7 and 30 days;
- employment-type filtering;
- visa/sponsorship indicators where data is available;
- sorting by newest, company, title, and resume-match relevance;
- a careers-page directory;
- a **Manual search needed** diagnostic list;
- a **Zero jobs scraped** diagnostic list.

### Resume matching

A resume can be loaded directly in the browser and compared against the current job corpus.

Supported formats include PDF, DOCX, TXT, and Markdown.

Resume processing is local to the browser. The uploaded resume is **not** committed to the repository and is not written to `data.json`.

The current matcher is a transparent keyword-overlap aid, not an automated hiring decision or recruiter score.

## Data-source architecture

### Standard ATS connectors

Supported or discoverable platforms include:
- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- Workable
- Recruitee
- Personio
- Pinpoint
- Eightfold
- Phenom

Not every company on one of these platforms is guaranteed to expose a usable public endpoint.

### Direct / proprietary career-site connectors

The current scraper includes best-effort direct support for companies such as:
- Apple
- Google
- Microsoft
- Meta
- TikTok
- Oracle
- Amazon
- Netflix

These direct connectors are more fragile than public ATS APIs because proprietary career sites can change their HTML, JavaScript, or internal endpoints without notice.

### Automatic ATS discovery

Previously unresolved companies are progressively tested against supported ATS patterns.

Successful mappings are stored in:

```text
ats_platform_cache.json
```

This allows the system to improve coverage over time instead of requiring every company to be permanently hard-coded.

A company is only promoted to automatic coverage when the relevant source can be validated.

## Ireland filtering

The project intentionally favors **Ireland accuracy over inflated job counts**.

A job is retained only when its location can reasonably be identified as Ireland or an Ireland location such as Dublin, Cork, Galway, Limerick, Waterford, etc.

This matters because ATS systems can expose ambiguous locations such as:

```text
Dublin, CA
Dublin, United States
UK / Ireland
EMEA
Multiple Locations
```

The pipeline attempts to avoid counting these as Ireland-only jobs unless the source data genuinely supports that interpretation.

## Company coverage states

### Live / automatic
A working ATS or direct connector exists and Ireland jobs are being retrieved.

### Zero jobs scraped
The company has an automatic connector/check, but the latest run returned zero qualifying Ireland jobs.

Possible reasons:
- the company currently has no Ireland vacancies;
- its careers endpoint changed;
- its job data is temporarily unavailable;
- the connector needs updating.

These companies appear in the dashboard's **Zero jobs scraped** tab.

### Manual search needed
No validated job-level connector is currently available.

The company remains visible in the dashboard with a direct careers-page link and appears under **Manual search needed**.

## Main files

| File | Purpose |
|---|---|
| `index.html` | GitHub Pages dashboard |
| `scrape.py` | Main Ireland job collection pipeline |
| `ireland_companies.csv` | Master Ireland company registry |
| `data.json` | Latest generated dashboard dataset |
| `seen_jobs.json` | Persistent job-seen state for NEW detection |
| `ats_platform_cache.json` | Cached ATS discoveries |
| `.github/workflows/scrape.yml` | Scheduled job-refresh workflow |

Optional files may include:
- `sponsorship_history.json`
- `official_permit_stats.json`
- `visa_stats.py`

## How a job reaches the dashboard

```text
Ireland company registry
        ↓
known connector?
   ┌────┴────┐
  yes        no
   ↓          ↓
scrape    ATS discovery
              ↓
       validated mapping?
          ┌───┴───┐
         yes      no
          ↓        ↓
       scrape   careers-page fallback
          ↓
    strict Ireland validation
          ↓
       normalize
          ↓
      deduplicate
          ↓
     NEW-job tracking
          ↓
        data.json
          ↓
      GitHub Pages
```

## GitHub Actions

The repository can be refreshed automatically with GitHub Actions and manually through the Actions tab.

The workflow contains:

```yaml
workflow_dispatch: {}
```

so a refresh can be triggered with:

**GitHub → Actions → Scrape jobs → Run workflow**

The workflow should commit every state file modified by the scraper together, including:
- `data.json`
- `seen_jobs.json`
- `ats_platform_cache.json`

A concurrency guard is recommended so long-running scraper jobs do not overlap.

## Local run

Python 3.11+ is recommended.

Typical dependencies:

```bash
pip install requests beautifulsoup4
```

Run:

```bash
python scrape.py
```

For local dashboard testing:

```bash
python -m http.server 8000
```

then open:

```text
http://localhost:8000/
```

## Deployment

1. Keep the repository public.
2. Place the workflow at `.github/workflows/scrape.yml`.
3. Go to **Settings → Pages**.
4. Set **Source: Deploy from a branch**, branch `main`, folder `/ (root)`.
5. Run the workflow once manually.
6. After `data.json` is committed, GitHub Pages will republish the dashboard.

## Optional aggregator APIs

Company career sites and ATS endpoints should remain the preferred source because they are usually the freshest and most direct.

Aggregator APIs can be added as a fallback for breadth:
- Adzuna
- Jooble
- Careerjet

API credentials should **never be hard-coded** into the repository.

Use **Settings → Secrets and variables → Actions** and reference them through GitHub Actions secrets.

Suggested secret names:

```text
ADZUNA_APP_ID
ADZUNA_APP_KEY
JOOBLE_API_KEY
CAREERJET_AFFID
```

## Known limitations

No free scraper can guarantee 100% coverage of every employer.

Common limitations include:
- proprietary JavaScript-heavy career sites;
- bot protection;
- ATS endpoint changes;
- renamed job-board slugs;
- Oracle / SuccessFactors / custom enterprise recruiting systems;
- jobs where the employer exposes only vague multi-country locations;
- closed or expired jobs that remain indexed briefly;
- companies with no current Ireland vacancy.

Direct connectors such as Apple, Google, Microsoft, Meta, TikTok, and Oracle should therefore be considered **best effort**, not permanent APIs.

The dashboard's diagnostics are designed to make these gaps visible rather than hide them.

## Coverage philosophy

The goal is not to maximize a headline job count by accepting questionable results.

Priority:

```text
1. Direct employer / ATS source
2. Accurate Ireland validation
3. Broad company coverage
4. Automatic discovery and caching
5. Aggregator fallback
6. Manual careers-page fallback
```

## Privacy

The dashboard is static and hosted through GitHub Pages.

Resume matching is performed locally in the user's browser. Resume files should not be committed to the repository.

Do not commit:
- API keys
- access tokens
- passwords
- private resumes
- browser cookies
- personal authentication credentials

Use GitHub Actions Secrets for API credentials.

## Project direction

The current focus is **Ireland only**.

Future improvements can include:
- broader proprietary-site connectors;
- stronger Phenom / Eightfold / Oracle / SuccessFactors coverage;
- richer job descriptions for resume matching;
- skill extraction and semantic matching;
- duplicate detection across aggregator + employer sources;
- job alerts / GitHub Issue notifications;
- official Irish employment-permit statistics;
- application tracking;
- richer company metadata;
- health checks for broken connectors.

## Disclaimer

This project aggregates publicly available job-listing information for discovery purposes.

Job availability, location, sponsorship, salary, and eligibility should always be verified on the employer's official application page before applying.
