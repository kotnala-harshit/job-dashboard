import csv
import unittest
from datetime import date
from pathlib import Path

from unittest.mock import patch

from scrape import (
    DIRECT_COMPANY_CONNECTORS,
    KNOWN_PHENOM_MAPPINGS,
    KNOWN_EIGHTFOLD_MAPPINGS,
    REJECTED_DYNAMIC_MAPPINGS,
    WORKABLE_COMPANIES,
    WORKDAY_COMPANIES,
    VERIFIED_LIVE_ZERO_COMPANIES,
    _parse_yello_jobs,
    _parse_gradireland_listing,
    _scrape_public_careers_page,
    company_display_name,
    scrape_grant_thornton,
    scrape_goldman_sachs,
    scrape_bny,
    scrape_workable,
)


REGISTRY_PATH = "ireland_job_radar_HARSHIT_MASTER.csv"


class RegistryTests(unittest.TestCase):
    def test_gong_greenhouse_slug_maps_to_curated_company(self):
        self.assertEqual("Gong", company_display_name("gongio"))
        self.assertEqual("EirGrid", company_display_name("EirGrid Group"))

    def test_refresh_workflow_is_bounded(self):
        workflow = Path(".github/workflows/scrape.yml").read_text(encoding="utf-8")
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("03 * * * *", workflow)
        self.assertIn("23 * * * *", workflow)
        self.assertIn("43 * * * *", workflow)
        self.assertNotIn("17 * * * *", workflow)
        self.assertNotIn("37 * * * *", workflow)
        self.assertNotIn("57 * * * *", workflow)
        self.assertNotIn("17 */4 * * *", workflow)
        self.assertNotIn("hour % 4", workflow)
        self.assertIn("github.event.schedule", workflow)
        self.assertNotIn('minute="$(date -u +%M)"', workflow)
        self.assertNotIn('if [ "$minute" = "17" ]; then', workflow)
        self.assertIn("'23 * * * *') mode=full", workflow)
        self.assertIn("'03 * * * *'|'43 * * * *') mode=fast", workflow)
        self.assertIn("limit=75m", workflow)
        self.assertEqual(1, workflow.count("concurrency:"))
        self.assertNotIn("while true", workflow)
        self.assertNotIn("queue: max", workflow)

    def test_dashboard_keeps_recently_discovered_roles_visible(self):
        dashboard = Path("index.html").read_text(encoding="utf-8")
        self.assertIn("Discovered in past 24h", dashboard)
        self.assertIn("firstSeenWithin", dashboard)

    def test_repaired_official_company_mappings_are_registered(self):
        self.assertEqual("aer_lingus_talentsoft", DIRECT_COMPANY_CONNECTORS["Aer Lingus"])
        for company in ("daa (Dublin Airport Authority)", "Vodafone Ireland", "VHI Healthcare"):
            self.assertIn(company, DIRECT_COMPANY_CONNECTORS)
        for company in ("Astellas Pharma", "Eir", "Ornua"):
            self.assertIn(company, DIRECT_COMPANY_CONNECTORS)
        self.assertEqual(
            "careers.hpe.com|HPE1US",
            KNOWN_PHENOM_MAPPINGS["Hewlett Packard Enterprise (HPE)"],
        )
        self.assertIn("DXC Technology", VERIFIED_LIVE_ZERO_COMPANIES)
        self.assertIn("DXC Technology", DIRECT_COMPANY_CONNECTORS)
        self.assertIn("CGI", VERIFIED_LIVE_ZERO_COMPANIES)
        self.assertIn("Red Hat", VERIFIED_LIVE_ZERO_COMPANIES)
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
        self.assertIn(("Clio", "clio", "wd3", "cliocareersite"), WORKDAY_COMPANIES)
        for mapping in (
            ("KLA Corporation", "kla", "wd1", "Search"),
            ("Medtronic", "medtronic", "wd1", "MedtronicCareers"),
            ("Tricentis", "tricentis", "wd1", "Tricentis_Careers"),
        ):
            self.assertIn(mapping, WORKDAY_COMPANIES)
        for company in ("CRH", "DCC plc", "Dublin Port Company", "Glanbia / Tirlán"):
            self.assertIn(company, DIRECT_COMPANY_CONNECTORS)
        self.assertEqual("goldman_higher", DIRECT_COMPANY_CONNECTORS["Goldman Sachs"])
        self.assertEqual("bny_oracle", DIRECT_COMPANY_CONNECTORS["BNY"])
        self.assertEqual(
            "careers.dexcom.com|dexcom.com",
            KNOWN_EIGHTFOLD_MAPPINGS["Dexcom"],
        )
        self.assertIn(
            ("Enterprise Ireland", "recruitee", "enterprise"),
            REJECTED_DYNAMIC_MAPPINGS,
        )
        self.assertIn("davy", WORKABLE_COMPANIES)

    @patch("scrape.fetch_json")
    def test_davy_workable_jobs_default_to_ireland(self, fetch):
        fetch.return_value = {
            "jobs": [{
                "title": "Investment Analyst",
                "location": {},
                "url": "https://apply.workable.com/davy/j/example/",
            }]
        }
        self.assertEqual("Ireland", scrape_workable("davy")[0]["location"])

    @patch("scrape.fetch_json")
    def test_workable_reads_current_location_shape(self, fetch):
        fetch.return_value = {"jobs": [{
            "title": "Analyst",
            "url": "https://example.test/job",
            "country": "Ireland",
            "city": "Dublin",
        }]}
        self.assertEqual("Dublin, Ireland", scrape_workable("example")[0]["location"])

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

    @patch("scrape._session")
    def test_goldman_sachs_keeps_official_ireland_role_urls(self, session_factory):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"roleSearch": {"totalCount": 1, "items": [{
                    "roleId": "179955_GS_MID_CAREER",
                    "jobTitle": "Customer Operations Manager, Associate, Dublin",
                    "locations": [{"primary": True, "city": "Dublin", "state": "Co. Dublin", "country": "Ireland"}],
                }]}}}

        session_factory.return_value.post.return_value = Response()
        jobs = scrape_goldman_sachs()
        self.assertEqual("Dublin, Co. Dublin, Ireland", jobs[0]["location"])
        self.assertEqual("https://higher.gs.com/roles/179955", jobs[0]["url"])

    @patch("scrape.scrape_oracle_candidate_experience")
    def test_bny_uses_the_paginated_official_oracle_board(self, collect):
        scrape_bny()
        self.assertEqual("BNY", collect.call_args.kwargs["company"])
        self.assertEqual(14, collect.call_args.kwargs["max_pages"])

    def test_gradireland_parser_keeps_only_open_roi_programmes(self):
        job = _parse_gradireland_listing(
            "<html><head><title>2027 Data Graduate Programme - Cork</title></head>"
            '<body><a href="/organisations/grant-thornton">Grant Thornton Verified Employer</a>'
            "Apply by: 22/10/2026</body></html>",
            "https://gradireland.com/jobs/example-1",
            today=date(2026, 9, 1),
        )
        self.assertEqual("Grant Thornton Ireland", job["company"])
        self.assertEqual("Cork, Ireland", job["location"])

    def test_active_registry_is_unique_and_profile_focused(self):
        with open(REGISTRY_PATH, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))

        active = {
            row["company_name"]
            for row in rows
            if row["include_in_scrape_registry"].lower() == "true"
        }

        # Evidence-backed registry currently contains 235 unique active companies.
        self.assertEqual(235, len(active))
        self.assertEqual(235, len(set(active)))

        # Critical profile-focused companies that must remain active.
        required = {
            "Teneo Ireland", "Aer Lingus", "Ornua",
            "Eir", "Dublin Port Company",
            "Hewlett Packard Enterprise (HPE)", "IQVIA",
            "Proofpoint", "Willis Towers Watson (WTW)",
            "BNY", "Goldman Sachs", "Guidewire",
            "RSM Ireland", "Three Ireland",
            "Uisce Éireann (Irish Water)",
            "Deutsche Bank", "SMBC Aviation Capital",
        }
        self.assertTrue(required <= active)

        # Company deliberately replaced in the evidence-backed registry.
        excluded = {
            "Tesco Ireland",
        }
        self.assertFalse(excluded & active)

    @patch("scrape._fetch_html")
    def test_server_rendered_job_parser(self, fetch):
        fetch.return_value = (
            '<section>Ireland <a href="/job/Dublin-Data-Analyst/123/">Data Analyst</a> '
            'Dublin, Ireland 2026-09-02</section>'
        )
        jobs = _scrape_public_careers_page("Example", "https://example.ie/jobs", ("/job/",))
        self.assertEqual("Data Analyst", jobs[0]["title"])


if __name__ == "__main__":
    unittest.main()
