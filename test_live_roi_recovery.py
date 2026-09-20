import inspect, unittest, scrape
class LiveROIRecoveryTests(unittest.TestCase):
 def test_hcltech_contract(self):
  x=inspect.getsource(scrape.scrape_hcltech); self.assertIn("if discovered:",x); self.assertIn("zero vacancies not trusted",x)
 def test_aon_contract(self):
  self.assertIn("zero vacancies not trusted",inspect.getsource(scrape.scrape_aon))
 def test_not_verified_zero(self):
  self.assertNotIn("Aon",scrape.VERIFIED_LIVE_ZERO_COMPANIES); self.assertNotIn("HCLTech",scrape.VERIFIED_LIVE_ZERO_COMPANIES)
 def test_description_cleaner(self):
  raw="window.NREUM foo Job Description Useful role text Information at a Glance junk"
  clean=scrape._clean_live_roi_text_20260921(raw)
  self.assertIn("Useful role text",clean)
  self.assertNotIn("window.NREUM",clean)
  self.assertNotIn("Information at a Glance",clean)
if __name__=="__main__": unittest.main()
