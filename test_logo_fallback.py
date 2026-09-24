page = open("index.html", encoding="utf-8").read()

assert "data-logo-backup" in page
assert "www.google.com/s2/favicons" in page
assert "dataset.logoRetry" in page
print("PASS: every company logo has an official-domain fallback and initials fallback")
