from pathlib import Path
import scrape

source = Path("scrape.py").read_text(encoding="utf-8")

assert "workhuman" not in scrape.GREENHOUSE_COMPANIES

assert not any(
    row[0] == "Takeda"
    for row in scrape.WORKDAY_COMPANIES
)

assert not any(
    row[0] == "Teva Pharmaceuticals"
    for row in scrape.WORKDAY_COMPANIES
)

assert callable(scrape.scrape_workhuman_official)
assert callable(scrape.scrape_takeda_official)
assert callable(scrape.scrape_teva_official)

assert '"Workhuman",' in source
assert '"Takeda",' in source
assert '"Teva Pharmaceuticals",' in source
assert "supplemental_direct_companies" in source

assert len(scrape.PROVEN_REFRESH_BATCHES) == 14
assert sum(len(batch) for batch in scrape.PROVEN_REFRESH_BATCHES) == 136

print("PASS: Workhuman + Takeda + Teva routing")
print("PASS: fixed 14 batches / 136 direct connectors unchanged")
