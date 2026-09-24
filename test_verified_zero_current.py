import scrape
import json

expected = {
    "Keelvar",
    "Unilever Ireland",
    "Keysight Technologies",
    "MSCI",
    "Figma",
    "Quantexa",
    "NVIDIA",
    "NXP Semiconductors",
    "STMicroelectronics",
    "Seagate",
    "Storm Technology",
}

assert set(scrape.KNOWN_HEALTHY_ZERO_COMPANIES) == expected
assert expected <= scrape.VERIFIED_LIVE_ZERO_COMPANIES

audited = {
    "CRH", "FactSet", "Heineken Ireland", "Nutanix", "Texas Instruments",
    "TransferMate", "Siemens Healthineers", "First Derivative",
}
assert audited <= scrape.VERIFIED_LIVE_ZERO_COMPANIES
assert audited.isdisjoint(scrape.KNOWN_HEALTHY_ZERO_COMPANIES)
dashboard = json.load(open("data.json", encoding="utf-8"))
states = {row["company"]: row["state"] for row in dashboard["coverage_diagnostics"]}
assert all(states[name] == "live_zero" for name in audited)
registry_names = {row["company"] for row in dashboard["registry_companies"]}
assert set(dashboard["proven_working_companies"]) <= registry_names
assert dashboard["proven_working_company_count"] == len(dashboard["proven_working_companies"]) == 266

all_names = [name for batch in scrape.PROVEN_REFRESH_BATCHES for name in batch]
assert "Nokia" in all_names
assert "Siemens Healthineers" in all_names
assert len(all_names) == len(set(all_names))
assert all(1 <= len(batch) <= 10 for batch in scrape.PROVEN_REFRESH_BATCHES)

print("PASS: strict current verified-zero classification")
print("PASS: Nokia + Siemens Healthineers included in proven refresh batches")
