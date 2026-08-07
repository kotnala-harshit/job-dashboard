# Ireland All-Jobs Upgrade

This upgrade turns the Ireland-only dashboard into a broad job aggregator rather than a target-title scraper.

## Replace/add these files in the GitHub repo

- `scrape.py` <- `scrape_ireland_all.py`
- `index.html` <- `index_ireland_all.html`
- `.github/workflows/scrape.yml` <- `scrape_ireland_all.yml`
- add `ireland_companies.csv`
- add `seen_jobs.json` with `{}` on the first deployment

## Key changes

- 397-company Ireland master registry.
- All Ireland jobs are ingested; target-title keywords no longer delete jobs.
- Target roles are tagged as `target_role_match` and filterable in the UI.
- Expanded Workday coverage from 3 to 45 configured tenants.
- Expanded SmartRecruiters and Ashby coverage.
- Added Personio and Pinpoint connectors.
- Strict Ireland location matching remains in place.
- New-job tracking persists across runs via `seen_jobs.json`.
- Better deduplication and source/company coverage statistics in `data.json`.
- Manual careers-page directory remains available for companies without a working job-level connector.

## Important

The first live GitHub Actions run is the real validation step because ATS endpoints can change, block requests, or have no Ireland openings on a given day. `automatic_company_count` means configured connector coverage, not a guarantee that every configured board returns jobs on every run.
