import inspect
import unittest
import scrape

class Batch4Tests(unittest.TestCase):
    def test_hcltech_zero_not_trusted(self):
        src = inspect.getsource(scrape.scrape_hcltech)
        self.assertIn('zero vacancies not trusted', src)
        self.assertIn('Official HCLTech Ireland careers completed', src)
    def test_aon_zero_not_trusted(self):
        src = inspect.getsource(scrape.scrape_aon)
        self.assertIn('zero vacancies not trusted', src)
    def test_neither_is_verified_zero(self):
        z = getattr(scrape, 'KNOWN_HEALTHY_ZERO_COMPANIES', set())
        self.assertNotIn('Aon', z)
        self.assertNotIn('HCLTech', z)

if __name__ == '__main__': unittest.main()
