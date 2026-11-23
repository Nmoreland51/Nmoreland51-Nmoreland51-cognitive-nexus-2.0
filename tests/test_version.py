import re
import unittest

import cognitive_nexus
from cognitive_nexus import version


class VersionTests(unittest.TestCase):
    def test_version_is_exposed_and_well_formed(self):
        self.assertEqual(cognitive_nexus.__version__, version.__version__)
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+(\.dev\d+)?$")

    def test_build_info_identifies_the_running_code(self):
        info = version.build_info()

        self.assertEqual(set(info), {"version", "commit", "modified"})
        self.assertTrue(info["commit"] == "unknown" or re.fullmatch(r"[0-9a-f]{7,40}", info["commit"]))
        self.assertIn(info["version"], version.build_label())


if __name__ == "__main__":
    unittest.main()
