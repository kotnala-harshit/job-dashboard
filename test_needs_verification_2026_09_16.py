import scrape

for slug in ("esw", "smartling", "sumup", "teneolinkedin", "figma"):
    assert slug in scrape.GREENHOUSE_COMPANIES, slug

assert "cubic3" in scrape.ASHBY_COMPANIES

for company in (
    "CRH",
    "FBD Insurance",
    "Waystone",
    "Amgen",
    "Fidelity Investments",
    "Nucleo",
):
    assert company in scrape.DIRECT_COMPANY_CONNECTORS, company

print("PASS: Needs Verification routes/classifications")
