import subprocess
import unittest
from pathlib import Path


class StaticSecurityTestCase(unittest.TestCase):
    def test_browser_security_behaviors(self):
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["node", "--test", "tests/static_security.test.js"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
