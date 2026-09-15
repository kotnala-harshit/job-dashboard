import scrape

assert "monzo" in scrape.GREENHOUSE_COMPANIES
assert "monzo" not in scrape.LEVER_COMPANIES

assert "Keelvar" in scrape.VERIFIED_LIVE_ZERO_COMPANIES
assert "Keelvar" in scrape.KNOWN_HEALTHY_ZERO_COMPANIES

info = scrape.KNOWN_HEALTHY_ZERO_COMPANIES["Keelvar"]
assert "personio.com" in info["url"]
assert "0 qualifying Ireland jobs" in info["note"]

print("PASS: Monzo Greenhouse + Keelvar healthy-zero configuration")
