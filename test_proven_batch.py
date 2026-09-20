"""Offline regression check: python test_proven_batch.py."""
import json
import io
import threading
import time
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import scrape


def main():
    batch = scrape.PROVEN_REFRESH_BATCHES[0]
    registry = {row["company"]: row for row in scrape.build_company_registry()}
    all_names = [name for group in scrape.PROVEN_REFRESH_BATCHES for name in group]
    assert len(all_names) == len(set(all_names))
    for number, group in enumerate(scrape.PROVEN_REFRESH_BATCHES, 1):
        assert 1 <= len(group) <= 10
        if number < len(scrape.PROVEN_REFRESH_BATCHES):
            assert len(group) == 10
        assert all(name in scrape.DIRECT_COMPANY_CONNECTORS for name in group)
        assert all(registry[name]["refresh_batch"] == number for name in group)

    active_direct_keys = {
        scrape._company_key(row["company"])
        for row in scrape.build_company_registry()
        if scrape.is_active_registry_company(row["company"])
        and scrape._company_key(row["company"]) in {
            scrape._company_key(scrape.company_display_name(name))
            for name in scrape.DIRECT_COMPANY_CONNECTORS
        }
    }

    batched_keys = {
        scrape._company_key(scrape.company_display_name(name))
        for group in scrape.PROVEN_REFRESH_BATCHES
        for name in group
    }

    assert active_direct_keys == batched_keys, (
        "Direct batch coverage mismatch: "
        f"missing={sorted(active_direct_keys - batched_keys)}, "
        f"extra={sorted(batched_keys - active_direct_keys)}"
    )
    with patch.object(scrape, "scrape_oracle_candidate_experience", return_value=[{"title": "Analyst"}]) as oracle:
        assert scrape.scrape_oracle() == [{"title": "Analyst"}]
        oracle.assert_called_once_with(max_pages=5)
    with patch.object(scrape, "_scrape_accenture_with_retry", return_value=[{"title": "Analyst"}]), patch.object(scrape, "scrape_workday") as workday:
        assert scrape.scrape_accenture() == [{"title": "Analyst"}]
        workday.assert_not_called()
    with patch.object(scrape, "HAS_PLAYWRIGHT", False):
        scrape.CONNECTOR_HEALTH.clear()
        assert scrape.scrape_aon() == []
        health = scrape.CONNECTOR_HEALTH.get("Aon")
        assert health is not None
        assert health["live"] is False

    import inspect
    aon_source = inspect.getsource(scrape.scrape_aon)
    assert "jobs.aon.com/jobs" in aon_source
    assert "aon.wd1.myworkdayjobs.com" not in aon_source
    assert "zero vacancies not trusted" in aon_source

    submitted, paths = set(), set()
    lock = threading.Lock()
    active = peak = 0

    class CheckedPool(ThreadPoolExecutor):
        def submit(self, fn, spec, path):
            # Fail immediately if the old queue keeps submitting its first task.
            assert spec["company"] not in submitted, "Company submitted twice"
            assert path not in paths, "Result file reused"
            submitted.add(spec["company"])
            paths.add(path)
            return super().submit(fn, spec, path)

    def worker(spec, path, timeout):
        nonlocal active, peak
        name = spec["company"]
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        if name == batch[0]:
            return {"status": "timeout"}
        if name == batch[1]:
            return {"status": "error", "stderr": "source failed", "returncode": 1}
        jobs = [] if name == batch[2] else [{"company": name, "title": "Analyst"}]
        health = {name: {"live": False, "note": "Unconfirmed zero"}} if not jobs else {}
        Path(path).write_text(json.dumps({"jobs": jobs, "connector_health": health}))
        return {"status": "ok"}

    scrape.CONNECTOR_HEALTH.clear()
    results, errors = [], []
    with redirect_stdout(io.StringIO()), patch.object(scrape, "ThreadPoolExecutor", CheckedPool), patch.object(
        scrape, "_isolated_subprocess_worker", worker
    ):
        scrape._parallel_collect_isolated(
            [("direct", name) for name in batch], results, errors, workers=3, timeout_seconds=2
        )
    assert submitted == set(batch)
    assert 1 <= peak <= 3
    assert len(results) == 7 and len(errors) == 2
    assert all(not scrape.CONNECTOR_HEALTH[name]["live"] for name in batch[:3])
    assert all(scrape.CONNECTOR_HEALTH[name]["live"] for name in batch[3:])
    print("PASS: batch routing, unique workers, concurrency, failures, and hub health")


if __name__ == "__main__":
    main()
