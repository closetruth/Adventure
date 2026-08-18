"""开奖音效：钻石随机选取与 Qt 播放器准备。"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.sfx import SfxPlayer, _GOLD_KEY, _iter_diamond_paths, _probe_sound_files

_app = QApplication.instance() or QApplication([])


class SfxDiamondPickTests(unittest.TestCase):
    def test_pick_skips_marked_bad(self) -> None:
        player = SfxPlayer({"sound_enabled": True})
        bad = Path("bad.mp3")
        good = Path("good.mp3")
        player._diamond_paths = [bad, good]
        player._mark_diamond_bad(bad)
        self.assertEqual(player._pick_random_diamond_path(), good)

    def test_pick_returns_none_when_all_bad(self) -> None:
        player = SfxPlayer({"sound_enabled": True})
        bad = Path("bad.mp3")
        player._diamond_paths = [bad]
        player._mark_diamond_bad(bad)
        self.assertIsNone(player._pick_random_diamond_path())


class SfxAssetProbeTests(unittest.TestCase):
    def test_iter_diamond_paths_sorted(self) -> None:
        paths = _iter_diamond_paths()
        names = [p.name.lower() for p in paths]
        self.assertEqual(names, sorted(names))

    def test_probe_true_when_gold_or_diamond_exists(self) -> None:
        if _iter_diamond_paths() or (
            Path(__file__).resolve().parent.parent
            / "assets"
            / "sounds"
            / "roll_gold.mp3"
        ).exists():
            self.assertTrue(_probe_sound_files())


class SfxQtPlayerTests(unittest.TestCase):
    def test_gold_play_prepares_slot(self) -> None:
        player = SfxPlayer({"sound_enabled": True})
        gold = player._resolve_stem_path("roll_gold")
        if gold is None:
            self.skipTest("没有 roll_gold 音效文件")
        if not player.capable():
            self.skipTest("QtMultimedia 不可用")
        player.play("roll_gold")
        self.assertIn(_GOLD_KEY, player._slots)
        player.shutdown()

    def test_diamond_files_get_slots(self) -> None:
        paths = _iter_diamond_paths()
        if not paths:
            self.skipTest("assets/sounds/diamond 为空")
        player = SfxPlayer({"sound_enabled": True})
        if not player.capable():
            self.skipTest("QtMultimedia 不可用")
        for path in paths:
            slot = player._ensure_slot(player._diamond_slot_key(path), path)
            self.assertIsNotNone(slot)
        self.assertEqual(len(player._slots), len(paths))
        player.shutdown()


if __name__ == "__main__":
    unittest.main()
