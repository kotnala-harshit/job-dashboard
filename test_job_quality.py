"""Run with python3 test_job_quality.py (requests and beautifulsoup4)."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from audit_links import classify_response, check_url
from job_quality import apply_quality, canonical_url, deduplicate

j = {'company':'Example','title':'Analyst','location':'Dublin','url':'https://example.com/job/123?utm_source=test','ats':'direct'}
other = {**j,'url':'https://example.com/job/124'}
kept, duplicates = deduplicate([j, {**j,'url':'https://example.com/job/123'}, other])
assert len(kept) == 2 and len(duplicates) == 1
assert 'https://example.com/job/123' in kept[0]['duplicate_urls']
assert canonical_url('https://x.myworkdayjobs.com/en-US/site/job/Dublin/Title_R_123/apply') == canonical_url('https://x.myworkdayjobs.com/site/job/Dublin/Other_R_123')
assert canonical_url('https://x/job?jobId=1') != canonical_url('https://x/job?jobId=2')
assert canonical_url('https://x/job?position=1') != canonical_url('https://x/job?position=2')
assert classify_response(200, '<script>job not found</script><p>Apply now</p>', j['url'], j['url'])['status'] == 'reachable'
assert classify_response(200, '<p>This job is no longer accepting applications</p>', j['url'], j['url'])['status'] == 'unreachable'
assert classify_response(403, '', j['url'], j['url'])['status'] == 'blocked'
assert classify_response(200, '<title>Just a moment</title>', j['url'], j['url'])['status'] == 'blocked'
assert classify_response(200, '<p>Browse jobs</p>', j['url'], 'https://example.com/jobs')['status'] == 'unverified'
assert check_url('mailto:recruit@example.com')['status'] == 'unverified'
now = datetime.now(timezone.utc)
for status, failures, age, expected in [('blocked',2,0,1),('error',2,0,1),('unreachable',1,0,1),('unreachable',2,0,0),('unreachable',2,25,1)]:
    data={'jobs':[deepcopy(j)],'graduate_early_careers':{'jobs':[deepcopy(j)]}}
    report={'urls':{j['url']:{'status':status,'reason':'test','failure_checks':failures,'checked_at':(now-timedelta(hours=age)).isoformat()}}}
    apply_quality(data,report)
    assert len(data['jobs']) == expected
    assert data['graduate_early_careers']['live_job_count'] == expected
print('Job link classification, conservative removal, metadata and deduplication passed')
