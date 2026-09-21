import scrape


def main():
    for slug in ("esw", "smartling", "sumup", "teneolinkedin", "figma"):
        assert slug in scrape.GREENHOUSE_COMPANIES, slug

    for slug in ("cubic3", "quantexa", "trading212"):
        assert slug in scrape.ASHBY_COMPANIES, slug


    for company in (
        "CRH", "FBD Insurance", "Waystone", "Amgen", "Fidelity Investments",
        "Nucleo", "Teneo Ireland", "Figma", "Lam Research", "Novartis",
        "Zurich Insurance", "WuXi Biologics", "LinkedIn",
    ):
        assert company in scrape.DIRECT_COMPANY_CONNECTORS, company

    batched = {
        scrape._company_key(scrape.company_display_name(name))
        for group in scrape.PROVEN_REFRESH_BATCHES
        for name in group
    }
    for company in ("Lam Research", "Nucleo", "Teneo Ireland", "Figma", "LinkedIn"):
        assert scrape._company_key(company) in batched, company

    print("PASS: Needs Verification live routes/classifications")


if __name__ == "__main__":
    main()
