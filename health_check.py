#!/usr/bin/env python3
"""Validate the Ireland Job Radar's core data and registry integrity."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
errors: list[str] = []
warnings: list[str] = []


def require_file(name: str) -> Path:
    path = ROOT / name
    if not path.exists():
        errors.append(f"Missing required file: {name}")
    return path


# Core files
registry_path = require_file("ireland_job_radar_HARSHIT_MASTER.csv")
data_path = require_file("data.json")

# Registry validation
if registry_path.exists():
    with registry_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    required = {"company_name", "include_in_scrape_registry"}
    missing = required - set(rows[0].keys() if rows else [])
    if missing:
        errors.append(f"Registry missing columns: {sorted(missing)}")

    active = {
        row["company_name"].strip()
        for row in rows
        if row.get("include_in_scrape_registry", "").strip().lower() == "true"
        and row.get("company_name", "").strip()
    }

    if len(active) < 235:
        errors.append(f"Expected at least 235 active companies, found {len(active)}")

    if "Deutsche Bank" not in active:
        errors.append("Deutsche Bank is not active")

    if "Tesco Ireland" in active:
        errors.append("Tesco Ireland must remain inactive")

    if "SMBC Aviation Capital" not in active:
        errors.append("SMBC Aviation Capital is not active")

# JSON validation
if data_path.exists():
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload

        if not isinstance(jobs, list):
            errors.append("data.json jobs payload is not a list")
        else:
            ids = []
            for job in jobs:
                if not isinstance(job, dict):
                    errors.append("data.json contains a non-object job")
                    continue

                job_id = job.get("job_id") or job.get("id")
                if job_id:
                    ids.append(str(job_id))

                url = job.get("url") or job.get("apply_url")
                if url:
                    parsed = urlparse(str(url))
                    if parsed.scheme not in {"http", "https", "mailto"}:
                        errors.append(f"Invalid job URL scheme: {url}")

            duplicates = len(ids) - len(set(ids))
            if duplicates:
                warnings.append(f"{duplicates} duplicate job IDs detected")
    except Exception as exc:
        errors.append(f"data.json is invalid JSON: {exc}")

# Latest metrics, if present
metrics = ROOT / "metrics" / "latest.json"
if metrics.exists():
    try:
        json.loads(metrics.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"metrics/latest.json is invalid JSON: {exc}")

if warnings:
    print("=== WARNINGS ===")
    for warning in warnings:
        print(f"WARNING: {warning}")

if errors:
    print("=== HEALTH CHECK FAILED ===")
    for error in errors:
        print(f"ERROR: {error}")
    sys.exit(1)

print("=== HEALTH CHECK PASSED ===")
print(f"Registry: {len(active)} active companies")
print("Deutsche Bank: ACTIVE")
print("Tesco Ireland: INACTIVE")
print("SMBC Aviation Capital: ACTIVE")
print("Core JSON: valid")
