import csv
import unittest

from unittest.mock import patch

from scrape import (
    DIRECT_COMPANY_CONNECTORS,
    KNOWN_PHENOM_MAPPINGS,
    KNOWN_EIGHTFOLD_MAPPINGS,
    REJECTED_DYNAMIC_MAPPINGS,
    WORKDAY_COMPANIES,
    VERIFIED_LIVE_ZERO_COMPANIES,
    _parse_yello_jobs,
    scrape_grant_thornton,
)


REGISTRY_PATH = "ireland_job_radar_HARSHIT_MASTER.csv"


class RegistryTests(unittest.TestCase):
    def test_repaired_official_company_mappings_are_registered(self):
        self.assertEqual("aer_lingus_talentsoft", DIRECT_COMPANY_CONNECTORS["Aer Lingus"])
        self.assertEqual(
            "careers.hpe.com|HPE1US",
            KNOWN_PHENOM_MAPPINGS["Hewlett Packard Enterprise (HPE)"],
        )
        self.assertIn("DXC Technology", VERIFIED_LIVE_ZERO_COMPANIES)
        self.assertIn("CGI", VERIFIED_LIVE_ZERO_COMPANIES)
        for company in (
            "Advanced Micro Devices (AMD)",
            "Applied Materials",
            "Bausch + Lomb",
            "AXA XL",
            "AtkinsRéalis",
            "Citco",
            "HCLTech",
            "McKinsey & Company",
            "OpenText",
            "SMBC Aviation Capital",
            "Veeam",
            "Chubb",
        ):
            self.assertIn(company, DIRECT_COMPANY_CONNECTORS)
        self.assertEqual("jobs.ebayinc.com|EBAEBAUS", KNOWN_PHENOM_MAPPINGS["eBay"])
        self.assertIn(
            ("Bristol Myers Squibb", "bristolmyerssquibb", "wd5", "BMS"),
            WORKDAY_COMPANIES,
        )
        self.assertIn(("Stryker", "stryker", "wd1", "StrykerCareers"), WORKDAY_COMPANIES)
        self.assertEqual(
            "careers.dexcom.com|dexcom.com",
            KNOWN_EIGHTFOLD_MAPPINGS["Dexcom"],
        )
        self.assertIn(
            ("Enterprise Ireland", "recruitee", "enterprise"),
            REJECTED_DYNAMIC_MAPPINGS,
        )

    @patch("scrape._scrape_grant_thornton_board")
    def test_grant_thornton_scans_experienced_and_graduate_boards(self, collect):
        collect.side_effect = lambda url: [{"url": url}]
        jobs = scrape_grant_thornton()
        self.assertEqual(2, len(jobs))
        self.assertTrue(any("GraduateProgramme/jobs" in job["url"] for job in jobs))

    def test_yello_graduate_parser_keeps_job_identity(self):
        jobs = _parse_yello_jobs(
            "EY Ireland",
            '<li><a href="/jobs/abc?job_board_id=board">AI &amp; Data Graduate Programme 2027</a></li>',
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("AI & Data Graduate Programme 2027", jobs[0]["title"])
        self.assertEqual("Ireland", jobs[0]["location"])
        self.assertIn("/jobs/abc", jobs[0]["url"])

    def test_active_registry_is_unique_and_profile_focused(self):
        with open(REGISTRY_PATH, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))

        active = {
            row["company_name"]
            for row in rows
            if row["include_in_scrape_registry"].lower() == "true"
        }
        self.assertEqual(263, len(active))

        expected = {
            "ActionPoint", "Teneo Ireland", "Aer Lingus", "Ornua",
            "Expleo", "Eir", "Dublin Port Company",
            "Hewlett Packard Enterprise (HPE)", "IQVIA", "Proofpoint",
            "Willis Towers Watson (WTW)", "BNY", "Goldman Sachs",
            "Guidewire", "Figma",
            "RSM Ireland",
        }
        excluded = {
            "ABP Food Group", "Circle K Ireland", "Dawn Meats",
            "Decathlon Ireland", "Harvey Nash Ireland", "JD Sports Ireland",
            "Primark / Penneys",
            "LetsGetChecked", "Bayer", "Brown Brothers Harriman",
            "BT Ireland", "CACEIS", "Catalent",
            "Charles River Laboratories", "Eaton",
        }
        self.assertTrue(expected <= active)
        self.assertFalse(excluded & active)


if __name__ == "__main__":
    unittest.main()
