import unittest

import scrape


class SourceReliabilityBatch3Tests(unittest.TestCase):

    def test_publicjobs_identity_ignores_language_and_xf(self):
        a = {
            "url": (
                "https://publicjobs.tal.net/vx/lang-en-GB/"
                "mobile-0/appcentre-ext/brand-4/xf-AAA/"
                "candidate/jobboard/vacancy/6/adv/"
            )
        }

        b = {
            "url": (
                "https://publicjobs.tal.net/vx/lang-ga/"
                "mobile-0/appcentre-ext/brand-4/xf-BBB/"
                "candidate/jobboard/vacancy/6/adv/"
            )
        }

        self.assertEqual(
            scrape._publicjobs_vacancy_identity_20260920(a),
            scrape._publicjobs_vacancy_identity_20260920(b),
        )

    def test_publicjobs_prefers_english_variant(self):
        ga = {
            "title": "Comhairligh Leighis",
            "url": (
                "https://publicjobs.tal.net/vx/lang-ga/"
                "candidate/jobboard/vacancy/6/adv/"
            ),
        }

        en = {
            "title": "Medical Consultants",
            "url": (
                "https://publicjobs.tal.net/vx/lang-en-GB/"
                "candidate/jobboard/vacancy/6/adv/"
            ),
        }

        self.assertIs(
            scrape._prefer_publicjobs_english_20260920(
                ga,
                en,
            ),
            en,
        )

    def test_hcltech_repair_is_not_verified_zero(self):
        self.assertNotIn(
            "HCLTech",
            getattr(
                scrape,
                "KNOWN_HEALTHY_ZERO_COMPANIES",
                set(),
            ),
        )

    def test_aon_repair_is_not_verified_zero(self):
        self.assertNotIn(
            "Aon",
            getattr(
                scrape,
                "KNOWN_HEALTHY_ZERO_COMPANIES",
                set(),
            ),
        )


if __name__ == "__main__":
    unittest.main()
