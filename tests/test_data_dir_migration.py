"""存档目录从 Adventure → AimLoot 的迁移测试。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage
from src.storage import (
    has_valid_save,
    migrate_legacy_data_dir,
    reset_data_dir_cache,
)


class DataDirMigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.new_dir = self.root / "AimLoot"
        self.old_dir = self.root / "Adventure"
        reset_data_dir_cache()
        self.addCleanup(reset_data_dir_cache)

    def _write_save(self, data_dir: Path, body: str = '{"total_operations": 1}') -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "data.json").write_text(body, encoding="utf-8")

    def test_new_has_valid_save_skips_migration(self):
        self._write_save(self.new_dir, '{"kept": true}')
        self._write_save(self.old_dir, '{"old": true}')
        used, warn = migrate_legacy_data_dir(self.new_dir, self.old_dir)
        self.assertEqual(used, self.new_dir)
        self.assertIsNone(warn)
        self.assertTrue((self.new_dir / "data.json").read_text(encoding="utf-8").find("kept") >= 0)

    def test_copies_old_to_new_when_new_empty(self):
        self._write_save(self.old_dir)
        (self.old_dir / "runtime_intervals.json").write_text("{}", encoding="utf-8")
        used, warn = migrate_legacy_data_dir(self.new_dir, self.old_dir)
        self.assertEqual(used, self.new_dir)
        self.assertIsNone(warn)
        self.assertTrue(has_valid_save(self.new_dir))
        self.assertTrue((self.new_dir / "runtime_intervals.json").is_file())
        self.assertTrue(has_valid_save(self.old_dir), "旧目录应保留")

    def test_both_empty_uses_new(self):
        used, warn = migrate_legacy_data_dir(self.new_dir, self.old_dir)
        self.assertEqual(used, self.new_dir)
        self.assertIsNone(warn)
        self.assertTrue(self.new_dir.is_dir())

    def test_copy_failure_falls_back_to_old(self):
        self._write_save(self.old_dir)
        with mock.patch("src.storage.shutil.copytree", side_effect=OSError("boom")):
            used, warn = migrate_legacy_data_dir(self.new_dir, self.old_dir)
        self.assertEqual(used, self.old_dir)
        self.assertIsNotNone(warn)
        self.assertIn("Adventure", warn or "")
        self.assertFalse(self.new_dir.exists())

    def test_has_valid_save_rejects_garbage(self):
        self.new_dir.mkdir(parents=True, exist_ok=True)
        (self.new_dir / "data.json").write_text("not-json", encoding="utf-8")
        self.assertFalse(has_valid_save(self.new_dir))


if __name__ == "__main__":
    unittest.main()
