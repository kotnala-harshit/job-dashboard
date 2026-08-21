# Ireland Job Radar

The engine follows:

> **Collect broadly. Normalize centrally. Personalize at ranking time.**

## Personalization modes

### Default profile
If the visitor does nothing, the server-generated `candidate_match_score` from `profile.json` is used.

### Personal profile
The frontend can build a private local profile from:

- uploaded resume/CV: PDF, DOCX, TXT, or Markdown;
- LinkedIn profile URL (stored as metadata);
- pasted LinkedIn About / Experience / Skills / project text.

The generated profile is saved only in browser `localStorage`. It is not committed to GitHub and does not change the shared `data.json`.

The local profile extracts:

- frequent professional terms;
- known skills;
- likely role families;
- approximate years of experience when clearly stated.

It then recalculates the visible **Personal Match** score for every job using job title, role family, normalized job keywords, sector and experience requirements.

## LinkedIn limitation

A LinkedIn URL can be entered and retained, but the static GitHub Pages frontend does **not** attempt to scrape LinkedIn automatically.

LinkedIn commonly requires authentication and blocks cross-origin/profile scraping. For reliable personalization, paste LinkedIn profile text into the Profile Builder or upload a resume.

This design also avoids collecting LinkedIn credentials, cookies, or private data.

## Privacy

Resume and LinkedIn text are processed in the user's browser.

The site does not upload these materials to the repository or job scraper.

## Broad job engine

The underlying Ireland collection remains profile-agnostic. Personalization only changes ranking/filtering in the frontend.

Users can always switch to **All Ireland jobs** to see the unfiltered corpus.

<!-- REGISTRY_STATUS_START -->
## 🇮🇪 Republic of Ireland Employer Registry

The Ireland Job Radar currently uses a focused **250-company active employer registry** for Republic of Ireland opportunities.

### Current registry

| Category | Count |
|---|---:|
| Total companies in master registry | 600 |
| Active companies | **250** |
| Proven employers preserved | **173** |
| Additional ROI target employers | **77** |
| Inactive / reserve companies | 350 |

The active registry was deliberately reduced from the full 600-company universe to improve relevance and focus while preserving every employer in the proven set.

### Proven employer set

All **173 proven employers** from the validated working set remain enabled. These are employers already demonstrated to return relevant Republic of Ireland vacancies through the job-radar pipeline.

### Additional target employers

A further **77 Republic of Ireland target employers** are enabled to expand coverage across areas including:

- Data, analytics, AI and software
- Technology and cybersecurity
- Banking, financial services and fintech
- Consulting and professional services
- Pharma, biotechnology and medical devices
- Engineering and manufacturing
- Aviation, transport and infrastructure
- Energy and utilities
- Retail and major Irish employers
- Public-sector and enterprise organizations

This gives a final active universe of:

**173 proven employers + 77 additional ROI targets = 250 active employers**

### Scraping

The scraper reads the `include_in_scrape_registry` field in:

`ireland_job_radar_HARSHIT_MASTER.csv`

Only companies enabled in that registry are included in the active scraping universe.

The remaining companies stay in the master CSV as a reserve universe and can be re-enabled later without rebuilding the company database.

### Deployment

The project uses automated job-data refreshes while keeping the employer registry separately controlled through the master CSV.

Registry configuration changes should therefore be reviewed independently from generated files such as `data.json` and `seen_jobs.json`.

_Last registry configuration update: 21 August 2026._
<!-- REGISTRY_STATUS_END -->
