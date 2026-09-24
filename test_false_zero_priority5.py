import scrape

PRIORITY = {
    "Infosys",
    "PTSB (Permanent TSB)",
    "Nokia",
    "Siemens Healthineers",
    "Deutsche Bank",
}

# These employers must never be a static healthy-zero declaration. A completed
# official check may classify a current zero as verified for that refresh.
assert PRIORITY.isdisjoint(scrape.KNOWN_HEALTHY_ZERO_COMPANIES)

registry = {row["company"]: row for row in scrape.build_company_registry(include_cache=False)}
for company in PRIORITY:
    assert company in registry, company
    assert registry[company]["automatic"], (company, registry[company])

assert scrape.scrape_direct_company.__name__ == "scrape_direct_company"
assert callable(scrape.scrape_infosys)
assert callable(scrape.scrape_ptsb)
assert callable(scrape.scrape_nokia)
assert callable(scrape.scrape_siemens_healthineers)
assert callable(scrape.scrape_deutsche_bank)

print("PASS: priority five are active connectors, not static healthy-zero")
