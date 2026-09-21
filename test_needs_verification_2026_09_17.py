import scrape


def main():
    # Figma remains on the Greenhouse route.
    assert "figma" in scrape.GREENHOUSE_COMPANIES

    # Historical Greenhouse route no longer active.
    assert "teneolinkedin" not in scrape.GREENHOUSE_COMPANIES

    # Historical Ashby routes no longer active.
    for slug in ("quantexa", "trading212"):
        assert slug not in scrape.ASHBY_COMPANIES, slug

    # WuXi Biologics remains a direct company connector.
    assert "WuXi Biologics" in scrape.DIRECT_COMPANY_CONNECTORS

    # These historical direct routes have been removed or migrated.
    for company in ("Teneo Ireland", "Figma", "Nucleo"):
        assert company not in scrape.DIRECT_COMPANY_CONNECTORS, company

    print("PASS: 2026-09-17 current connector classifications")


if __name__ == "__main__":
    main()
