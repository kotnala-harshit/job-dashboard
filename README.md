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
- Visa-sponsorship signals where available
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

The main GitHub Actions scraper currently runs **every two hours**, at minute `17` of the hour.

The effective UTC schedule is:

```text
00:17
02:17
04:17
06:17
08:17
10:17
12:17
14:17
16:17
18:17
20:17
22:17
