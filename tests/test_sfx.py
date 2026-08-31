"""开奖音效：钻石随机选取、容器嗅探、声道池叠加播放。"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.models import Reward
from src.sfx import (
    SfxPlayer,
    _MAX_VOICES,
    _iter_diamond_paths,
    _probe_sound_files,
    _qt_types,
    qt_ready_path,
    sniff_audio_kind,
)

_app = QApplication.instance() or QApplication([])


def _write_tiny_wav(path: Path) -> None:
    data = b"\x80" * 8000
    path.write_bytes(
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _busy_count(sfx: SfxPlayer) -> int:
    return sum(1 for voice in sfx._pool if voice.busy)


def _forced_player() -> SfxPlayer:
    qt = _qt_types()
    if qt is None or QApplication.instance() is None:
        raise unittest.SkipTest("QtMultimedia 不可用")
    sfx = SfxPlayer({"sound_enabled": True})
    sfx._has_files = True
    sfx._qt = qt
    return sfx


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
        self.assertGreaterEqual(len(player._pool), 1)
        self.assertGreaterEqual(_busy_count(player), 1)
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
        self.assertGreaterEqual(len(player._pool), 1)
        self.assertGreaterEqual(_busy_count(player), 1)
        player.shutdown()


class SfxVoicePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sfx = _forced_player()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.wav = Path(self._tmp.name) / "beep.wav"
        _write_tiny_wav(self.wav)

    def tearDown(self) -> None:
        self.sfx.shutdown()
        self._tmp.cleanup()

    def test_overlap_uses_two_voices(self) -> None:
        self.sfx._play("gold", self.wav)
        self.sfx._play("gold", self.wav)
        self.assertEqual(_busy_count(self.sfx), 2)
        self.assertEqual(len(self.sfx._pool), 2)
        self.assertIsNot(self.sfx._pool[0].player, self.sfx._pool[1].player)

    def test_reuse_idle_voice_after_end(self) -> None:
        self.sfx._play("gold", self.wav)
        self.assertEqual(len(self.sfx._pool), 1)
        self.sfx._release(self.sfx._pool[0])
        self.assertEqual(_busy_count(self.sfx), 0)
        self.sfx._play("gold", self.wav)
        self.assertEqual(_busy_count(self.sfx), 1)
        self.assertEqual(len(self.sfx._pool), 1)

    def test_end_of_media_releases_voice(self) -> None:
        self.sfx._play("gold", self.wav)
        voice = self.sfx._pool[0]
        _, QMediaPlayer = self.sfx._qt
        voice.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertFalse(voice.busy)
        self.assertEqual(_busy_count(self.sfx), 0)

    def test_shutdown_clears_pool(self) -> None:
        self.sfx._play("gold", self.wav)
        self.sfx.shutdown()
        self.assertEqual(self.sfx._pool, [])

    def test_pool_caps_at_max(self) -> None:
        for _ in range(_MAX_VOICES + 2):
            self.sfx._play("gold", self.wav)
        self.assertEqual(len(self.sfx._pool), _MAX_VOICES)
        self.assertEqual(_busy_count(self.sfx), _MAX_VOICES)


if __name__ == "__main__":
    unittest.main()
