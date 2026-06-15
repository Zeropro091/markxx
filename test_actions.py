# test_actions.py
import unittest
from actions.computer_control import computer_control
from actions.computer_settings import computer_settings
from actions.dev_agent import dev_agent
from actions.file_processor import file_processor

class TestPortedActions(unittest.TestCase):
    def test_computer_control(self):
        print("Testing computer_control action...")
        res = computer_control({"action": "wait", "seconds": 0.05})
        print(f"Result: {res}")
        self.assertIn("Waited", res)

    def test_computer_settings(self):
        print("Testing computer_settings action...")
        res = computer_settings({"action": "volume_up"})
        print(f"Result: {res}")
        self.assertTrue(isinstance(res, str))

    def test_dev_agent(self):
        print("Testing dev_agent action...")
        res = dev_agent({})
        print(f"Result: {res}")
        self.assertIn("describe the project", res)

    def test_file_processor(self):
        print("Testing file_processor action...")
        res = file_processor({})
        print(f"Result: {res}")
        self.assertIn("No file path provided", res)

if __name__ == "__main__":
    unittest.main()
