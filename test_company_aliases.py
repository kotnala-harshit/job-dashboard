import scrape

assert scrape._company_key("AMD") == scrape._company_key(
    "Advanced Micro Devices (AMD)"
)

assert scrape._company_key("Diageo") == scrape._company_key(
    "Diageo Ireland"
)

assert "Deutsche Bank" not in scrape.KNOWN_HEALTHY_ZERO_COMPANIES
assert "Deutsche Bank" not in scrape.VERIFIED_LIVE_ZERO_COMPANIES

print("PASS: AMD + Diageo aliases and Deutsche Bank active-source configuration")
