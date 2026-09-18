#!/usr/bin/env python3
import csv
from pathlib import Path
import scrape

MASTER = Path("ireland_job_radar_HARSHIT_MASTER.csv")
EXPECTED_EXISTING = {
    "Introba", "ActionPoint", "Avanade", "DXC Technology", "Ekco", "Fujitsu",
    "Integrity360", "Noesis", "Akamai", "AirNav Ireland", "Alkermes", "Amundi",
    "An Post", "Aviva Ireland", "ASML", "ARYZTA Ireland",
}
EXPECTED_NEW = {"Storm Technology", "Ergo", "Expleo Ireland"}
EXPECTED = EXPECTED_EXISTING | EXPECTED_NEW

with MASTER.open("r", encoding="utf-8-sig", newline="") as f:
    rows = {r["company_name"].strip(): r for r in csv.DictReader(f)}

missing = EXPECTED - set(rows)
assert not missing, f"Missing master rows: {sorted(missing)}"

inactive = {
    name for name in EXPECTED
    if str(rows[name].get("include_in_scrape_registry", "")).strip().lower()
       not in {"1", "true", "yes"}
}
assert not inactive, f"Still inactive in master: {sorted(inactive)}"

registry = {r["company"]: r for r in scrape.build_company_registry()}
not_registered = EXPECTED - set(registry)
assert not not_registered, f"Missing from runtime registry: {sorted(not_registered)}"

generic_expected = EXPECTED - {"DXC Technology"}
missing_direct = generic_expected - set(scrape.DIRECT_COMPANY_CONNECTORS)
assert not missing_direct, f"Missing direct connector mapping: {sorted(missing_direct)}"

manual = {name for name in EXPECTED if registry[name].get("platform") == "manual-check"}
assert not manual, f"Still manual-check after activation: {sorted(manual)}"

all_batched = {
    scrape._company_key(scrape.company_display_name(name))
    for batch in scrape.PROVEN_REFRESH_BATCHES
    for name in batch
}
missing_batches = {
    name for name in EXPECTED
    if scrape._company_key(scrape.company_display_name(name)) not in all_batched
}
assert not missing_batches, f"Missing from proven refresh batches: {sorted(missing_batches)}"

assert all(1 <= len(batch) <= 10 for batch in scrape.PROVEN_REFRESH_BATCHES)
assert all(len(batch) == 10 for batch in scrape.PROVEN_REFRESH_BATCHES[:-1])

for name in EXPECTED_NEW:
    assert rows[name]["priority_tier"].startswith("P1")
    assert rows[name]["dashboard_default_visibility"] == "visible"

print("PASS: selected employers active in master/runtime registry")
print("PASS: Storm Technology, Ergo and Expleo Ireland added as P1 employers")
print("PASS: generic official-board connectors wired")
print("PASS: proven refresh batches bounded and complete")
