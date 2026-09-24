import json

page = open("index.html", encoding="utf-8").read()
data = json.load(open("data.json", encoding="utf-8"))

assert "Live jobs &amp; graduates" not in page
assert "Live jobs & graduates" in page
assert "Graduate vacancies are already part of data.jobs" in page
jobs = {job.get("url") for job in data["jobs"]}
assert all(job.get("url") in jobs for job in data["graduate_early_careers"]["jobs"])
print("PASS: graduate vacancies are included in the live-jobs feed without a separate pane")
