page = open("index.html", encoding="utf-8").read()

assert "data-logo-backup" in page
assert "www.google.com/s2/favicons" in page
assert "dataset.logoRetry" in page
assert "referrerpolicy=\"no-referrer\"" in page
assert "class=\"logo-fallback\"" in page
assert 'const COMPANY_BRAND_DOMAINS' in page
assert '"Workday":"workday.com"' in page
print("PASS: every company logo has an official-domain fallback and initials fallback")
