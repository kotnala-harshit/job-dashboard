#!/usr/bin/env python3
import scrape

new_true_zero = {
    "NVIDIA",
    "NXP Semiconductors",
    "STMicroelectronics",
    "Seagate",
    "Storm Technology",
}

assert new_true_zero <= set(scrape.KNOWN_HEALTHY_ZERO_COMPANIES)
assert set(scrape.KNOWN_HEALTHY_ZERO_COMPANIES) <= scrape.VERIFIED_LIVE_ZERO_COMPANIES

for company in new_true_zero:
    info = scrape.KNOWN_HEALTHY_ZERO_COMPANIES[company]
    assert info.get("url")
    assert "2026-09-19" in info.get("note", "")

for company in {"Texas Instruments", "FactSet", "TransferMate"}:
    assert company in scrape.VERIFIED_LIVE_ZERO_COMPANIES
    assert company not in scrape.KNOWN_HEALTHY_ZERO_COMPANIES

print("PASS: true-zero classification has one strict source of truth")
print("PASS: five newly verified Republic-of-Ireland zeros are classified")
