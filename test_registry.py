import csv
import unittest


REGISTRY_PATH = "ireland_job_radar_HARSHIT_MASTER.csv"


class RegistryTests(unittest.TestCase):
    def test_active_registry_is_unique_and_profile_focused(self):
        with open(REGISTRY_PATH, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))

        active = {
            row["company_name"]
            for row in rows
            if row["include_in_scrape_registry"].lower() == "true"
        }
        self.assertEqual(262, len(active))

        expected = {
            "ActionPoint", "Teneo Ireland", "Aer Lingus", "Ornua",
            "Expleo", "Eir", "Dublin Port Company",
        }
        excluded = {
            "ABP Food Group", "Circle K Ireland", "Dawn Meats",
            "Decathlon Ireland", "Harvey Nash Ireland", "JD Sports Ireland",
            "Primark / Penneys",
        }
        self.assertTrue(expected <= active)
        self.assertFalse(excluded & active)


if __name__ == "__main__":
    unittest.main()
