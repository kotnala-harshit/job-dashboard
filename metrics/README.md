# Scraper Metrics

`latest.json` contains the latest scraper-run summary.

`history.jsonl` is intended for append-only historical run metrics.

Metrics are kept separate from the main job dataset so operational monitoring does not require rewriting the large dashboard JSON files.
