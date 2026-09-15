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
        assert len(group) == 10
        assert all(name in scrape.DIRECT_COMPANY_CONNECTORS for name in group)
        assert all(registry[name]["refresh_batch"] == number for name in group)
    with patch.object(scrape, "scrape_oracle_candidate_experience", return_value=[{"title": "Analyst"}]) as oracle:
        assert scrape.scrape_oracle() == [{"title": "Analyst"}]
        oracle.assert_called_once_with(max_pages=5)
    with patch.object(scrape, "_scrape_accenture_with_retry", return_value=[{"title": "Analyst"}]), patch.object(scrape, "scrape_workday") as workday:
        assert scrape.scrape_accenture() == [{"title": "Analyst"}]
        workday.assert_not_called()
    session = Mock()
    for location, expected in (("Singapore, Singapore", False), ("Belfast, Northern Ireland", False), ("Dublin, Ireland", True)):
        session.get.return_value = Mock(status_code=200, text=(
            f"<title>Analyst in {location} | Aon Corporation</title>"
            "<h1>Analyst</h1><nav>Jobs in Ireland</nav>"
        ))
        with redirect_stdout(io.StringIO()), patch.object(scrape, "_session", return_value=session):
            assert bool(scrape.scrape_aon()) is expected

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
