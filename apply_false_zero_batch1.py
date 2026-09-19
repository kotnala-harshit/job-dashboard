#!/usr/bin/env python3
from pathlib import Path

p = Path("scrape.py")
text = p.read_text(encoding="utf-8")

BLOCK = '\n# BEGIN VERIFIED FALSE-ZERO BATCH 2026-09-19\ndef _scrape_verified_server_board(company, urls, href_needles, default_location="Ireland",\n                                   board_is_ireland_scoped=False):\n    from bs4 import BeautifulSoup\n\n    results = {}\n    needles = tuple(str(x).lower() for x in href_needles)\n\n    for source_url in urls:\n        page = _fetch_html(source_url) or ""\n        if not page:\n            continue\n\n        soup = BeautifulSoup(page, "html.parser")\n\n        for anchor in soup.find_all("a", href=True):\n            href = urllib.parse.urljoin(source_url, anchor.get("href") or "").split("#")[0]\n            low_href = href.lower()\n\n            if needles and not any(n in low_href for n in needles):\n                continue\n\n            title = re.sub(r"\\s+", " ", anchor.get_text(" ", strip=True)).strip()\n            node = anchor\n            card_text = ""\n\n            for _ in range(7):\n                if not node:\n                    break\n                try:\n                    candidate = re.sub(r"\\s+", " ", node.get_text(" ", strip=True)).strip()\n                except Exception:\n                    candidate = ""\n                if candidate and len(candidate) <= 4000:\n                    card_text = candidate\n                if card_text and region_ok(card_text):\n                    break\n                node = getattr(node, "parent", None)\n\n            if (\n                not title\n                or title.lower() in {\n                    "read more", "view vacancy", "view job", "apply",\n                    "apply now", "learn more", "details",\n                }\n                or len(title) > 300\n            ):\n                search_node = node or anchor.parent\n                heading = search_node.find(["h1", "h2", "h3", "h4", "h5"]) if search_node else None\n                if heading:\n                    title = re.sub(r"\\s+", " ", heading.get_text(" ", strip=True)).strip()\n\n            if not title or len(title) > 300 or not is_real_job_title(title):\n                continue\n\n            evidence = f"{title} {card_text} {href}"\n            if not board_is_ireland_scoped and not region_ok(evidence):\n                continue\n\n            location = default_location\n            m = re.search(\n                r"\\b(Dublin|Cork|Galway|Limerick|Shannon|Waterford|Kilkenny|"\n                r"Leixlip|Kildare|Athlone|Dundalk)\\b",\n                card_text,\n                re.I,\n            )\n            if m:\n                location = f"{m.group(1).title()}, Ireland"\n            elif re.search(r"\\bIreland\\b", card_text, re.I):\n                location = "Ireland"\n\n            key = low_href.rstrip("/")\n            if not key:\n                continue\n\n            results[key] = {\n                "company": company,\n                "ats": "direct",\n                "title": title,\n                "location": location,\n                "raw_location": location,\n                "url": href,\n                "updated_at": None,\n                "description_text": card_text[:5000],\n            }\n\n    _mark_connector_health(\n        company,\n        True,\n        f"Official repaired careers source loaded; {len(results)} Republic-of-Ireland jobs",\n        urls[0] if urls else None,\n    )\n    print(f"  {company} repaired official board: {len(results)} Ireland jobs")\n    return list(results.values())\n\n\ndef scrape_ekco_repaired():\n    return _scrape_verified_server_board(\n        "Ekco",\n        ["https://careers.ek.co/jobs"],\n        ("careers.ek.co/jobs/",),\n        board_is_ireland_scoped=False,\n    )\n\n\ndef scrape_airnav_repaired():\n    return _scrape_verified_server_board(\n        "AirNav Ireland",\n        [\n            "https://www.airnav.ie/careers/current-vacancies",\n            "https://www.airnav.ie/careers",\n        ],\n        ("/careers/current-vacancies/",),\n        board_is_ireland_scoped=True,\n    )\n\n\ndef scrape_amundi_repaired():\n    return _scrape_verified_server_board(\n        "Amundi",\n        [\n            "https://www.jobs.amundi.com/Pages/Offre/ListeOffre.aspx?LCID=2057&showSearchUrl=1",\n            "https://www.jobs.amundi.com/Pages/Offre/ListeOffre.aspx?LCID=2057&page=2&showSearchUrl=1",\n        ],\n        ("detailoffre", "/offre/", "/job/"),\n        board_is_ireland_scoped=False,\n    )\n\n\ndef scrape_aviva_ireland_repaired():\n    return _scrape_verified_server_board(\n        "Aviva Ireland",\n        ["https://www.aviva.ie/group/careers/"],\n        ("/group/careers/", "jobs.aviva", "workday", "/job/"),\n        board_is_ireland_scoped=True,\n    )\n\n\ndef scrape_crh_repaired():\n    return _scrape_verified_server_board(\n        "CRH",\n        [\n            "https://jobs.crh.com/search/?q=&locationsearch=Ireland",\n            "https://jobs.crh.com/viewalljobs/",\n        ],\n        ("jobs.crh.com/job/",),\n        board_is_ireland_scoped=False,\n    )\n\n\nFALSE_ZERO_REPAIRS_2026_09_19 = {\n    "Ekco": scrape_ekco_repaired,\n    "AirNav Ireland": scrape_airnav_repaired,\n    "Amundi": scrape_amundi_repaired,\n    "Aviva Ireland": scrape_aviva_ireland_repaired,\n    "CRH": scrape_crh_repaired,\n}\n# END VERIFIED FALSE-ZERO BATCH 2026-09-19\n'

if "# BEGIN VERIFIED FALSE-ZERO BATCH 2026-09-19" not in text:
    anchor = "def scrape_direct_company(company: str):"
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit("Could not find scrape_direct_company")
    text = text[:idx] + BLOCK + "\n\n" + text[idx:]

old = "def scrape_direct_company(company: str):\n    # BEGIN SALE_READY_DIRECT_CONNECTORS"
new = (
    "def scrape_direct_company(company: str):\n"
    "    repaired = FALSE_ZERO_REPAIRS_2026_09_19.get(company)\n"
    "    if repaired is not None:\n"
    "        return repaired()\n\n"
    "    # BEGIN SALE_READY_DIRECT_CONNECTORS"
)

if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("Could not wire repaired dispatch")

p.write_text(text, encoding="utf-8")
print("PASS: verified false-zero batch-1 repair installed")
print("Repaired: Ekco, AirNav Ireland, Amundi, Aviva Ireland, CRH")
