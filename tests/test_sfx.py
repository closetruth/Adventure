"""开奖音效：钻石随机选取、容器嗅探、Qt 两轨播放。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.models import Reward
from src.sfx import (
    SfxPlayer,
    _iter_diamond_paths,
    _probe_sound_files,
    qt_ready_path,
    sniff_audio_kind,
)

_app = QApplication.instance() or QApplication([])


class SfxDiamondPickTests(unittest.TestCase):
    def test_skip_filters_bad(self) -> None:
        player = SfxPlayer({"sound_enabled": True})
        bad = Path("bad.mp3")
        good = Path("good.mp3")
        player._diamonds = [bad, good]
        player._skip.add(str(bad.resolve()))
        remain = [p for p in player._diamond_paths() if str(p.resolve()) not in player._skip]
        self.assertEqual(remain, [good])


class SfxAssetProbeTests(unittest.TestCase):
    def test_iter_diamond_paths_sorted(self) -> None:
        names = [p.name.lower() for p in _iter_diamond_paths()]
        self.assertEqual(names, sorted(names))

    def test_sniff_mp3_id3(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(b"ID3" + b"\x00" * 20)
            path = Path(handle.name)
        try:
            self.assertEqual(sniff_audio_kind(path), "mp3")
        finally:
            path.unlink(missing_ok=True)

    def test_sniff_mp4_ftyp(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(b"\x00\x00\x00\x18ftypisom")
            path = Path(handle.name)
        try:
            self.assertEqual(sniff_audio_kind(path), "mp4")
        finally:
            path.unlink(missing_ok=True)

    def test_probe_true_when_gold_or_diamond_exists(self) -> None:
        if _iter_diamond_paths() or (
            Path(__file__).resolve().parent.parent / "assets" / "sounds" / "roll_gold.mp3"
        ).exists():
            self.assertTrue(_probe_sound_files())


class SfxQtPlayerTests(unittest.TestCase):
    def test_gold_play_prepares_lane(self) -> None:
        player = SfxPlayer({"sound_enabled": True})
        if player._gold_path() is None:
            self.skipTest("没有 roll_gold 音效文件")
        if not player.capable():
            self.skipTest("QtMultimedia 不可用")
        player.play_roll_hit(Reward(gold=0.1))
        self.assertIn("gold", player._players)
        player.shutdown()

    def test_diamond_files_are_playable(self) -> None:
        paths = _iter_diamond_paths()
        if not paths:
            self.skipTest("assets/sounds/diamond 为空")
        player = SfxPlayer({"sound_enabled": True})
        if not player.capable():
            self.skipTest("QtMultimedia 不可用")
        for path in paths:
            ready = qt_ready_path(path)
            self.assertTrue(ready.is_file())
        player.play_random_diamond()
        self.assertIn("diamond", player._players)
        player.shutdown()


if __name__ == "__main__":
    unittest.main()
