import scrape

expected = {
    "Visa", "Morningstar", "Deutsche Bank", "UBS", "Nokia", "PTSB (Permanent TSB)"
}

assert expected <= set(scrape._PRIORITY_OFFICIAL_CONNECTORS)
assert all(scrape.DIRECT_COMPANY_CONNECTORS[name] == "official_priority" for name in expected)
assert {"Visa", "Morningstar", "PTSB (Permanent TSB)"} <= set(scrape.PROVEN_REFRESH_BATCHES[-1])
print("PASS: priority employers use official collectors and are scheduled for refresh")
