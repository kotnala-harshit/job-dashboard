#!/usr/bin/env python3
from pathlib import Path
import re

SCRAPE = Path("scrape.py")
TEST = Path("test_verified_zero_current.py")

TRUE_ZERO = {
    "NVIDIA": {
        "url": "https://www.nvidia.com/en-eu/contact/",
        "note": "Official NVIDIA worldwide office directory verified 2026-09-19; Europe list contains no Republic-of-Ireland office/location",
    },
    "NXP Semiconductors": {
        "url": "https://www.nxp.com/company/about-nxp/worldwide-locations:GLOBAL_SITES",
        "note": "Official NXP Worldwide Locations verified 2026-09-19; Europe/Middle East locations do not include Ireland",
    },
    "STMicroelectronics": {
        "url": "https://www.st.com/content/st_com/en/about/careers/career-benefits.html",
        "note": "Official ST careers location list verified 2026-09-19; current Europe locations do not include Ireland",
    },
    "Seagate": {
        "url": "https://www.seagate.com/gb/en/careers/meet-seagate/where-we-work/",
        "note": "Official Seagate global careers footprint verified 2026-09-19; island-of-Ireland careers location is Derry/Londonderry, Northern Ireland, not Republic of Ireland",
    },
    "Storm Technology": {
        "url": "https://www.storm.ie/about/careers/",
        "note": "Official Storm Technology careers page verified 2026-09-19; Open Positions section currently contains no listed vacancies",
    },
}

def find_dict_end(text, start):
    brace = text.index("{", start)
    depth = 0
    quote = None
    esc = False
    for i in range(brace, len(text)):
        c = text[i]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
            continue
        if c in ("'", '"'):
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return brace, i
    raise RuntimeError("unterminated dict")

text = SCRAPE.read_text(encoding="utf-8")

marker = "KNOWN_HEALTHY_ZERO_COMPANIES = {"
start = text.index(marker)
brace, end = find_dict_end(text, start)
body = text[brace+1:end]

for company, info in TRUE_ZERO.items():
    if re.search(r'["\']' + re.escape(company) + r'["\']\s*:', body):
        continue
    entry = (
        "\n    " + repr(company) + ": {\n"
        "        \"url\": " + repr(info["url"]) + ",\n"
        "        \"note\": " + repr(info["note"]) + ",\n"
        "    },\n"
    )
    body = body.rstrip() + entry

text = text[:brace+1] + body + text[end:]

pattern = re.compile(
    r'VERIFIED_LIVE_ZERO_COMPANIES\s*=\s*\{.*?\n\}',
    re.S,
)
replacement = "VERIFIED_LIVE_ZERO_COMPANIES = set(KNOWN_HEALTHY_ZERO_COMPANIES)"
text, n = pattern.subn(replacement, text, count=1)
if n != 1:
    raise SystemExit("Could not replace VERIFIED_LIVE_ZERO_COMPANIES block")

SCRAPE.write_text(text, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
EXPECTED_OLD = 'expected = {\n    "Keelvar",\n    "Unilever Ireland",\n    "Keysight Technologies",\n    "MSCI",\n    "Figma",\n    "Quantexa",\n}'
EXPECTED_NEW = 'expected = {\n    "Keelvar",\n    "Unilever Ireland",\n    "Keysight Technologies",\n    "MSCI",\n    "Figma",\n    "Quantexa",\n    "NVIDIA",\n    "NXP Semiconductors",\n    "STMicroelectronics",\n    "Seagate",\n    "Storm Technology",\n}'
OLD_STALE = 'for stale in {\n    "NVIDIA", "Visa", "Texas Instruments", "Seagate",\n    "FactSet", "Morningstar", "TransferMate", "Fitch Ratings",\n}:'
NEW_STALE = 'for stale in {\n    "Visa", "Texas Instruments", "FactSet", "Morningstar",\n    "TransferMate", "Fitch Ratings",\n}:'

if EXPECTED_OLD in test:
    test = test.replace(EXPECTED_OLD, EXPECTED_NEW)
elif EXPECTED_NEW not in test:
    raise SystemExit("Unexpected expected-set block in test_verified_zero_current.py")

if OLD_STALE in test:
    test = test.replace(OLD_STALE, NEW_STALE)
elif NEW_STALE not in test:
    raise SystemExit("Unexpected stale-set block in test_verified_zero_current.py")

TEST.write_text(test, encoding="utf-8")

print("PASS: strict true-zero batch applied")
print("Verified additions:", ", ".join(sorted(TRUE_ZERO)))
print("PASS: stale broad VERIFIED_LIVE_ZERO_COMPANIES allow-list removed")
