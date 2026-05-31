import tempfile
import unittest
from pathlib import Path

from modules.project_status import count_matching_files, recent_files


class ProjectStatusTests(unittest.TestCase):
    def test_counts_matching_files_across_patterns_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "report.json").write_text("{}", encoding="utf-8")
            (root / "report.md").write_text("# Report", encoding="utf-8")
            (root / "ignored.txt").write_text("ignore", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "hidden.md").write_text("# Hidden", encoding="utf-8")

            self.assertEqual(count_matching_files(root, ("*.json", "*.md")), 2)
            self.assertEqual(count_matching_files(root, ("*.json", "*.json")), 1)

    def test_recent_files_returns_dashboard_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "report.md"
            path.write_text("# Report", encoding="utf-8")

            rows = recent_files(root, ("*.md",), limit=1)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "report.md")
            self.assertIn("size_bytes", rows[0])
            self.assertIn("modified", rows[0])


if __name__ == "__main__":
    unittest.main()
