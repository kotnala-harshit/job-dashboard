from pathlib import Path


def main():
    source = Path("scrape.py").read_text()

    amazon = (
        'if SCRAPE_MODE == "full" and '
        '_runs_phase("core") and _targeted("Amazon"):'
    )
    netflix = (
        'if SCRAPE_MODE == "full" and '
        '_runs_phase("core") and _targeted("Netflix"):'
    )

    assert amazon in source, "Amazon official collector is not in core refresh"
    assert netflix in source, "Netflix official collector is not in core refresh"

    assert (
        '_runs_phase("direct") and _targeted("Amazon")'
        not in source
    )

    print("PASS: Amazon official collector participates in core refresh")


if __name__ == "__main__":
    main()
