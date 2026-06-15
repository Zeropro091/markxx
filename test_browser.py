import unittest
from actions.browser_control import browser_control

class TestBrowserControl(unittest.TestCase):

    def setUp(self):
        # Clean up any residual sessions before each test
        browser_control({"action": "close_all"})

    def tearDown(self):
        # Clean up sessions after each test
        browser_control({"action": "close_all"})

    def test_list_browsers_empty(self):
        res = browser_control({"action": "list_browsers"})
        self.assertIn("No active browser sessions", res)

    def test_go_to_and_get_url(self):
        # Test navigation to a blank page (or local test file)
        res_goto = browser_control({"action": "go_to", "url": "about:blank"})
        self.assertTrue(res_goto.startswith("Opened:") or "about:blank" in res_goto, f"Unexpected go_to result: {res_goto}")
        
        # Test get_url action
        res_url = browser_control({"action": "get_url"})
        self.assertIn("about:blank", res_url)

    def test_list_browsers_active(self):
        browser_control({"action": "go_to", "url": "about:blank"})
        res = browser_control({"action": "list_browsers"})
        self.assertIn("chrome", res.lower())

if __name__ == "__main__":
    unittest.main()
