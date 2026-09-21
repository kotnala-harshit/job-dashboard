import scrape


def main():
    # Current Greenhouse route retained from the original verification set.
    assert "figma" in scrape.GREENHOUSE_COMPANIES

    # These companies still use direct company connectors.
    for company in (
        "CRH",
        "FBD Insurance",
        "Waystone",
        "Amgen",
        "Fidelity Investments",
        "Novartis",
        "Zurich Insurance",
        "WuXi Biologics",
    ):
        assert company in scrape.DIRECT_COMPANY_CONNECTORS, company

    # Historical routes removed or migrated from their old connector groups
    # should not be required by this regression test.
    for slug in ("esw", "smartling", "sumup", "teneolinkedin"):
        assert slug not in scrape.GREENHOUSE_COMPANIES, slug

    for slug in ("cubic3", "quantexa", "trading212"):
        assert slug not in scrape.ASHBY_COMPANIES, slug

    for company in (
        "Nucleo",
        "Teneo Ireland",
        "Figma",
        "Lam Research",
        "LinkedIn",
    ):
        assert company not in scrape.DIRECT_COMPANY_CONNECTORS, company

    print("PASS: Needs Verification current routes/classifications")


if __name__ == "__main__":
    main()
