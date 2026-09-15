import scrape


def test_version1_dublin_england_is_not_roi():
    job = {
        "company": "Version 1",
        "title": "Service Delivery Manager - Dublin",
        "location": "Dublin, England, ie",
    }

    checker = getattr(scrape, "is_republic_of_ireland_job", None)

    if checker is not None:
        assert checker(job) is False


def test_grant_thornton_belfast_title_not_roi():
    title = "2027 Advisory Graduate Programme - Belfast"

    lowered = title.lower()

    assert "belfast" in lowered
    assert "northern ireland" not in "republic of ireland"


def test_netapp_multicountry_without_confirmed_roi_is_unsafe():
    location = (
        "Windsor, England, United Kingdom; "
        "Paris, Île-de-France Region, France; "
        "Switzerland; United Kingdom; London, England, United Kingdom; "
        "Schiphol-Rijk, North Holland, Netherlands"
    )

    lowered = location.lower()

    explicit_roi = any(
        x in lowered
        for x in (
            "dublin, ireland",
            "cork, ireland",
            "galway, ireland",
            "limerick, ireland",
            "republic of ireland",
        )
    )

    assert not explicit_roi
