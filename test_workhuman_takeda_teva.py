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

all_names = [
    name
    for batch in scrape.PROVEN_REFRESH_BATCHES
    for name in batch
]

assert len(all_names) == len(set(all_names))
assert all(
    1 <= len(batch) <= 10
    for batch in scrape.PROVEN_REFRESH_BATCHES
)
assert all(
    len(batch) == 10
    for batch in scrape.PROVEN_REFRESH_BATCHES[:-1]
)

registry = scrape.build_company_registry()

active_direct_keys = {
    scrape._company_key(row["company"])
    for row in registry
    if scrape.is_active_registry_company(row["company"])
    and scrape._company_key(row["company"]) in {
        scrape._company_key(
            scrape.company_display_name(name)
        )
        for name in scrape.DIRECT_COMPANY_CONNECTORS
    }
}

batched_keys = {
    scrape._company_key(
        scrape.company_display_name(name)
    )
    for name in all_names
}

assert active_direct_keys == batched_keys


print("PASS: Workhuman + Takeda + Teva routing")
print("PASS: proven refresh batches cover all active direct connectors")
