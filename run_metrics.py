#!/usr/bin/env python3
"""
Lightweight scraper-run metrics writer.

The scraper/workflow can populate these values through environment variables.
Missing values are represented safely rather than causing a scrape failure.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

METRICS_DIR = Path("metrics")
LATEST = METRICS_DIR / "latest.json"
HISTORY = METRICS_DIR / "history.jsonl"


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def collect() -> dict:
    now = datetime.now(timezone.utc).isoformat()

    return {
        "run_id": os.environ.get("GITHUB_RUN_ID", now),
        "workflow_run": os.environ.get("GITHUB_RUN_NUMBER"),
        "mode": os.environ.get("SCRAPE_MODE", "unknown"),
        "started_at": os.environ.get("SCRAPE_STARTED_AT"),
        "completed_at": now,
        "duration_seconds": _int("SCRAPE_DURATION_SECONDS"),
        "jobs_before": _int("JOBS_BEFORE"),
        "jobs_after": _int("JOBS_AFTER"),
        "new_jobs": _int("NEW_JOBS"),
        "updated_jobs": _int("UPDATED_JOBS"),
        "removed_jobs": _int("REMOVED_JOBS"),
        "sources_attempted": _int("SOURCES_ATTEMPTED"),
        "sources_successful": _int("SOURCES_SUCCESSFUL"),
        "sources_failed": _int("SOURCES_FAILED"),
        "errors": _int("SCRAPE_ERRORS"),
    }


def write_metrics(data: dict) -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    LATEST.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    write_metrics(collect())
    print(json.dumps(collect(), indent=2))
