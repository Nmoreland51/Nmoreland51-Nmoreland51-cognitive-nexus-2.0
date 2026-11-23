import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_utils
from modules.file_utils import atomic_write_json, atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_writes_new_file_and_creates_parent_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "memory.json"

            atomic_write_json(target, {"facts": ["a", "é"]})

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"facts": ["a", "é"]})
            self.assertEqual([item.name for item in target.parent.iterdir()], ["memory.json"])  # no temp file left

    def test_replaces_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "profile.json"
            target.write_text("old", encoding="utf-8")

            atomic_write_text(target, "new")

            self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_failed_save_keeps_the_old_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "profile.json"
            target.write_text('{"facts": ["keep me"]}', encoding="utf-8")

            with patch.object(file_utils.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, '{"facts": []}')
            with self.assertRaises(TypeError):
                atomic_write_json(target, {"bad": object()})  # fails before the file is touched

            self.assertEqual(target.read_text(encoding="utf-8"), '{"facts": ["keep me"]}')
            self.assertEqual([item.name for item in Path(tmp).iterdir()], ["profile.json"])

    def test_retries_when_windows_briefly_locks_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "profile.json"
            real_replace = file_utils.os.replace
            attempts = []

            def flaky_replace(source, destination):
                attempts.append(source)
                if len(attempts) < 3:
                    raise PermissionError("file is open in another process")
                real_replace(source, destination)

            with patch.object(file_utils.os, "replace", side_effect=flaky_replace), patch.object(file_utils.time, "sleep"):
                atomic_write_text(target, "saved")

            self.assertEqual(len(attempts), 3)
            self.assertEqual(target.read_text(encoding="utf-8"), "saved")


if __name__ == "__main__":
    unittest.main()
