import scrape

def main():
    for slug in ("teneolinkedin", "figma"):
        assert slug in scrape.GREENHOUSE_COMPANIES, slug
    for slug in ("quantexa", "trading212"):
        assert slug in scrape.ASHBY_COMPANIES, slug
    for company in ("Teneo Ireland", "Figma", "Nucleo", "WuXi Biologics"):
        assert company in scrape.DIRECT_COMPANY_CONNECTORS, company

    batched = {
        scrape._company_key(scrape.company_display_name(name))
        for group in scrape.PROVEN_REFRESH_BATCHES
        for name in group
    }
    for company in ("Teneo Ireland", "Figma", "Nucleo", "WuXi Biologics"):
        assert scrape._company_key(company) in batched, company
    print("PASS: 2026-09-17 zero/verification connector fixes")

if __name__ == "__main__":
    main()
