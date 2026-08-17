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
