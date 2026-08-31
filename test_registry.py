import csv
import unittest

from unittest.mock import patch

from scrape import _parse_yello_jobs, scrape_grant_thornton


REGISTRY_PATH = "ireland_job_radar_HARSHIT_MASTER.csv"


class RegistryTests(unittest.TestCase):
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
