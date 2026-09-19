#!/usr/bin/env python3
import scrape

expected = {
    "Ekco",
    "AirNav Ireland",
    "Amundi",
    "Aviva Ireland",
    "CRH",
}
assert set(scrape.FALSE_ZERO_REPAIRS_2026_09_19) == expected

for name, fn in scrape.FALSE_ZERO_REPAIRS_2026_09_19.items():
    assert callable(fn), name
    assert name not in scrape.VERIFIED_LIVE_ZERO_COMPANIES, name

print("PASS: five independently verified false-zero employers use repaired official collectors")
