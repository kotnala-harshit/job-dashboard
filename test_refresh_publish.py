"""Run with python test_refresh_publish.py; no network or dependencies needed."""
import pathlib
import shlex
import subprocess
import tempfile

workflow = (pathlib.Path(__file__).parent / ".github/workflows/scrape.yml").read_text()
stage = next(line.strip() for line in workflow.splitlines() if line.strip().startswith("git add "))
outputs = "data.json seen_jobs.json company_history.json sponsorship_history.json last_full_refresh.json graduate_programme_history.json ats_platform_cache.json jsonld_cache.json browser_scrape_cache.json".split()

with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    def git(*args):
        return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Refresh test")
    git("config", "user.email", "test@example.invalid")
    for name in outputs:
        (root / name).write_text("{}\n")
    git("add", ".")
    git("commit", "-qm", "Initial data")
    for name in outputs:
        (root / name).write_text('{"refreshed": true}\n')
    git(*shlex.split(stage)[1:])
    assert not git("diff", "--name-only"), "Scraper outputs left unstaged; rebase will fail"
    git("commit", "-qm", "Refresh")
    assert not git("status", "--porcelain"), "Publication must leave a clean worktree"
print("PASS: every generated history/cache file is committed before rebase")
