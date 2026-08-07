# Harshit's Job Dashboard

A free, fully automated job board that scrapes real company career pages every hour and shows the results on a live web dashboard. No paid API, no manual checking, no subscription — GitHub's free tier runs everything.

**Live dashboard:** `https://kotnala-harshit.github.io/job-dashboard/`

## What it does

1. `scrape.py` hits ~700 companies' career pages (via their public ATS APIs — Greenhouse, Lever, Ashby, Workday, SmartRecruiters, plus a universal JSON-LD scraper for everyone else, plus optional aggregator APIs) once an hour.
2. It filters results down to roles that match Harshit's target titles and target regions/countries, tags each one with recency, employment type, sector, and country, and writes everything to `data.json`.
3. GitHub Actions commits that file automatically. GitHub Pages republishes the site automatically. `index.html` (the dashboard) reads `data.json` and renders it — searchable, filterable, sortable.

No step above requires a human. Once set up, it just runs.

## Files

| File | What it is |
|---|---|
| `index.html` | The dashboard itself — the page GitHub Pages serves. Pure HTML/CSS/JS, no build step. |
| `scrape.py` | The scraper. Source of truth — this is what GitHub Actions actually runs every hour. |
| `scrape.ipynb` | The same scraper as a Jupyter notebook (for running by hand in Colab or locally, cell by cell). Regenerated from `scrape.py` — edit the `.py`, not the notebook. |
| `data.json` | The scraper's output. Overwritten every run. This is what `index.html` fetches and displays. |
| `.github/workflows/scrape.yml` | The automation: tells GitHub to run `scrape.py` every hour and commit the result. |
| `company_shortlist_by_region.xlsx` | The master list of ~700 target companies by region, with sector, career page URL, and whether each one is already wired into `scrape.py`. This is the list to edit when adding/removing target companies. |
| `region_shortlist.ipynb` | The research behind *which* countries/regions were chosen and why (visa difficulty, earning potential, career fit). |
| `SETUP.md` | Step-by-step deployment instructions (how to stand this whole thing up from zero) and troubleshooting. |
| `PROJECT_CONTEXT.txt` | Full narrative history of this project — every decision made and why. Read this first if you're picking the project up fresh (a new chat session, a different person, etc.). |

## How the automation actually runs

- **Trigger:** `.github/workflows/scrape.yml` schedules `python scrape.py` to run every hour, at :17 past the hour (`cron: "17 * * * *"`). It can also be triggered manually from the repo's **Actions** tab.
- **Cost:** completely free. GitHub Actions minutes are uncapped on public repositories (the 2,000 min/month cap only applies to private repos), and this repo has to be public anyway for free GitHub Pages.
- **Runtime:** each run takes roughly 15-20 minutes (most of that is the JSON-LD scraper politely crawling ~490 individual career pages one at a time).
- **Reliability caveat:** GitHub's own scheduler doesn't guarantee your cron fires exactly on time — on a low-traffic public repo, scheduled runs can slip by anywhere from a few minutes to a few hours during quiet periods. In practice this means "roughly hourly, several times an hour during the day, with occasional multi-hour gaps overnight" rather than a metronome. There's always at least one fresh batch waiting by morning, but if you need a guaranteed run at a specific time, use **Run workflow** manually from the Actions tab.
- **Publishing:** every successful scrape commits an updated `data.json` to `main`. GitHub Pages watches `main` and automatically rebuilds/republishes the site after every commit — this is the separate "pages build and deployment" workflow you'll see in the Actions tab, usually finishing in under a minute after the scrape's commit lands.
- **If the dashboard looks stale:** hard-refresh the page (browser caching), then check the Actions tab for the latest "Scrape jobs" and "pages build and deployment" runs — both should show green checkmarks after the timestamp you expect.

## Using the dashboard

- **Search box** — free text across title, company, and location.
- **Company / Country / Sector / Source filters** — these dropdowns are populated automatically from whatever's actually in the current `data.json`, so they stay accurate as the company list grows; no manual maintenance needed.
- **Recency filter** — Last 24 hours / 7 days / 30 days, computed live in the browser so it's accurate to the second you're looking, not to when the data was last scraped.
- **Employment type filter** — Full-time / Part-time / Internship, matched by keyword against the job title.

## Making changes

- **Add a target company:** add its row to `company_shortlist_by_region.xlsx`, then wire it into `scrape.py` — a slug in `GREENHOUSE_COMPANIES` / `LEVER_COMPANIES` / `ASHBY_COMPANIES` / etc. if it's on one of those ATS platforms, or a `(company, career_page_url)` tuple in `JSONLD_CAREER_PAGES` as a fallback.
- **Add/edit a sector for filtering:** update the `Sector` column in the xlsx, then re-run the small script that rebuilds `SECTOR_BY_COMPANY` in `scrape.py` (ask Claude to do this — it's a few lines).
- **Change which countries/roles count as a match:** edit `TITLE_KEYWORDS` and `REGION_KEYWORDS` near the top of `scrape.py`.
- **Change the schedule:** edit the `cron` line in `scrape.yml`.
- After editing `scrape.py`, regenerate `scrape.ipynb` from it (don't hand-edit the notebook — it'll drift).

## Known limits

- Google, Apple, and Meta aren't scraped here — their career sites actively block this style of access. They'd need a paid scraping service (e.g. Apify) to cover reliably.
- Some large employers (big banks, telcos, national champions) run enterprise ATS platforms (SAP SuccessFactors, Oracle Taleo) that also block unauthenticated access — these stay `manual-check` in the spreadsheet.
- The JSON-LD fallback only works if a company's career page happens to include structured job-posting markup — hit rate varies by company.

See `SETUP.md` for deployment steps and troubleshooting, and `PROJECT_CONTEXT.txt` for the full history of why this was built this way.
