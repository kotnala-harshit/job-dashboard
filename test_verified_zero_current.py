import scrape

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

for stale in {
    "Visa", "Texas Instruments", "FactSet", "Morningstar",
    "TransferMate", "Fitch Ratings",
}:
    assert stale not in scrape.VERIFIED_LIVE_ZERO_COMPANIES, stale

all_names = [name for batch in scrape.PROVEN_REFRESH_BATCHES for name in batch]
assert "Nokia" in all_names
assert "Siemens Healthineers" in all_names
assert len(all_names) == len(set(all_names))
assert all(1 <= len(batch) <= 10 for batch in scrape.PROVEN_REFRESH_BATCHES)

print("PASS: strict current verified-zero classification")
print("PASS: Nokia + Siemens Healthineers included in proven refresh batches")
