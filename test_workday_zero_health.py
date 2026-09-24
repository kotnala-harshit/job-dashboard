import scrape

assert ("Marvell Technology", "marvell", "wd1", "MarvellCareers") in scrape.WORKDAY_COMPANIES
assert {"Kyndryl", "Marvell Technology", "Rockwell Automation"} <= scrape.VERIFIED_LIVE_ZERO_COMPANIES
print("PASS: audited Workday zero sources are refreshed and classified correctly")
