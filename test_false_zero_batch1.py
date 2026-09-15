import scrape

expected = {
    "Synopsys": scrape.scrape_synopsys_official,
    "Riot Games": scrape.scrape_riot_games_official,
    "Nucleo": scrape.scrape_nucleo_official,
    "Concentrix (Ireland)": scrape.scrape_concentrix_official,
    "LearnUpon": scrape.scrape_learnupon_official,
}

assert "nucleo-consulting" not in scrape.WORKABLE_COMPANIES
assert "synopsys" not in scrape.PINPOINT_COMPANIES

for company, fn in expected.items():
    assert callable(fn), company

print("PASS: false-zero batch-1 routing configured")
