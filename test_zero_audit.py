"""Run offline with python test_zero_audit.py."""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import scrape
import zero_audit


def main():
    assert zero_audit.complete_feed_zero('greenhouse', {'jobs': []})
    assert not zero_audit.complete_feed_zero('greenhouse', {})
    assert not zero_audit.complete_feed_zero('unknown', {'jobs': []})
    for location, expected in [('Berlin, Germany', True), ('Dublin, Ireland', False), ('Remote EMEA', False), ('', False)]:
        assert zero_audit.complete_feed_zero('greenhouse', {'jobs': [{'location': {'name': location}}]}) == expected
    assert not zero_audit.complete_feed_zero('ashby', {'jobs': [{'location': 'Berlin', 'secondaryLocations': [{'location': 'Dublin, Ireland'}]}]})
    assert not zero_audit.complete_feed_zero('ashby', {'jobs': [{'location': 'Berlin', 'isRemote': True}]})
    assert zero_audit.complete_feed_zero('lever', [{'categories': {'location': 'London, UK'}}])
    assert not zero_audit.complete_feed_zero('lever', [{'categories': {'location': 'Remote EMEA'}}])
    assert zero_audit.workday_country_zero({'total': 2, 'jobPostings': [{}], 'facets': [{'facetParameter': 'locationHierarchy1', 'values': [{'descriptor': 'Germany', 'id': '1'}]}]})
    assert not zero_audit.workday_country_zero({'total': 2, 'jobPostings': [{}], 'facets': [{'facetParameter': 'locationHierarchy1', 'values': [{'descriptor': 'Ireland', 'id': '1'}]}]})
    session = Mock()
    session.get.return_value = Mock(status_code=200, text='<script src="https://boards.greenhouse.io/embed/job_board/js?for=smartling"></script>', url='https://example.com/careers')
    assert scrape._careers_page_ats_candidates('Test', 'https://example.com/careers', session) == [('greenhouse', 'smartling')]
    session.get.side_effect = RuntimeError('blocked HTML')
    assert scrape._careers_page_ats_candidates('Test', 'https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite', session) == [('workday', 'nvidia|wd5|NVIDIAExternalCareerSite')]
    html = '<a class="sr-job-link" href="/job/1"><h2>Engineer</h2><span class="job-location">Dublin, Ireland</span></a><a class="sr-job-link" href="/job/2"><h2>Engineer</h2><span class="job-location">Bengaluru, India</span></a>'
    jobs = zero_audit.official_page_jobs('Synopsys', html)
    assert len(jobs) == 1 and jobs[0]['url'].endswith('/job/1')
    with patch.object(scrape, 'scrape_amazon', return_value=[{'title': 'Engineer'}]) as amazon:
        assert scrape.scrape_direct_company('Amazon') == [{'title': 'Engineer'}]
        amazon.assert_called_once_with('')
    # Simulate the separate module instance used by a script-mode child.
    health = {'Test': {'live': True, 'verified_zero': True}}
    with tempfile.TemporaryDirectory() as tmp, patch.object(zero_audit, 'collect', return_value=[]), patch.object(zero_audit, 'scrape', Mock(CONNECTOR_HEALTH=health)):
        result = str(Path(tmp) / 'result.json')
        scrape._run_isolated_task_child({'type': 'audit', 'company': 'Test'}, result)
        assert json.loads(Path(result).read_text())['connector_health']['Test']['verified_zero']
    report = json.loads(Path('zero_audit.json').read_text())['companies']
    assert [r['number'] for r in report] == list(range(1, 149))
    assert all(r['batch'] == (r['number'] - 1) // 10 + 1 for r in report)
    print('PASS: audit numbering, source discovery, Ireland filtering, zero evidence, dispatch and child health')


if __name__ == '__main__':
    main()
