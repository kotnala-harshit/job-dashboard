import inspect
from unittest.mock import patch

import scrape


def test_dps_does_not_relabel_arcadis_jobs():
    scrape.CONNECTOR_HEALTH.clear()

    fake_arcadis_job = {
        "company": "Arcadis",
        "title": "Graduate Engineer",
        "location": "Dublin, Ireland",
        "url": "https://jobs.arcadis.com/careers/job/123?domain=arcadis.com",
        "ats": "eightfold",
    }

    with patch.object(
        scrape,
        "scrape_arcadis_ireland",
        return_value=[fake_arcadis_job],
    ) as arcadis:
        jobs = scrape.scrape_dps_group()

    assert jobs == []
    assert arcadis.call_count == 0

    health = scrape.CONNECTOR_HEALTH.get("DPS Group (Arcadis)")
    assert health is not None
    assert health["live"] is True
    assert "published under Arcadis" in health["note"]


def test_arcadis_remains_independent_direct_connector():
    source = inspect.getsource(scrape.scrape_direct_company)

    assert '"Arcadis": scrape_arcadis_ireland' in source
    assert '"DPS Group (Arcadis)": scrape_dps_group' in source


def test_dps_connector_does_not_call_arcadis_collector():
    source = inspect.getsource(scrape.scrape_dps_group)

    assert "scrape_arcadis_ireland()" not in source
    assert "return []" in source
