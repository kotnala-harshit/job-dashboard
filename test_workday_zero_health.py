import scrape

assert ("Marvell Technology", "marvell", "wd1", "MarvellCareers") in scrape.WORKDAY_COMPANIES
assert {"Kyndryl", "Marvell Technology", "Rockwell Automation"} <= scrape.VERIFIED_LIVE_ZERO_COMPANIES
assert set(scrape.PRIORITY_EXPANSION_OFFICIAL_BOARDS) <= set(scrape._PRIORITY_OFFICIAL_CONNECTORS)
print("PASS: audited Workday zero sources are refreshed and classified correctly")
