"""开奖音效：Qt 播 wav/ogg/真 mp3；其它格式预热时 ffmpeg 转进 sfx_cache。"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from .models import Reward
from .paths import project_root

logger = logging.getLogger(__name__)

_SOUND_EXTS = (".wav", ".ogg", ".mp3", ".m4a", ".aac", ".mp4")
_NATIVE = {"mp3", "wav", "ogg"}
_GOLD_STEM = "roll_gold"
_PREWARM_MS = 500
_NO_WINDOW = 0x08000000


def _sounds_dir() -> Path:
    return project_root() / "assets" / "sounds"


def _diamond_dir() -> Path:
    return _sounds_dir() / "diamond"


def sniff_audio_kind(path: Path) -> str:
    try:
        head = path.read_bytes()[:12]
    except OSError:
        return "unknown"
    if head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
    ):
        return "mp3"
    if head.startswith(b"RIFF"):
        return "wav"
    if head.startswith(b"OggS"):
        return "ogg"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "mp4"
    return "unknown"


def _iter_diamond_paths() -> List[Path]:
    folder = _diamond_dir()
    if not folder.is_dir():
        return []
    return sorted(
        (
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _SOUND_EXTS
        ),
        key=lambda p: p.name.lower(),
    )


def _probe_sound_files() -> bool:
    gold = any((_sounds_dir() / f"{_GOLD_STEM}{ext}").exists() for ext in _SOUND_EXTS)
    return gold or bool(_iter_diamond_paths())


def _find_ffmpeg() -> Optional[str]:
    found = shutil.which("ffmpeg")
    if found:
        return found
    extra = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "ffmpeg-master-latest-win64-gpl-shared"
        / "bin"
        / "ffmpeg.exe"
    )
    return str(extra) if extra.is_file() else None


def _cache_dir() -> Path:
    root = (
        Path(os.environ.get("APPDATA") or Path.home()) / "Adventure"
        if os.name == "nt"
        else Path.home() / ".adventure"
    )
    d = root / "sfx_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def qt_ready_path(src: Path) -> Path:
    """不能直接播的文件转成缓存 mp3；失败则退回原路径。"""
    if sniff_audio_kind(src) in _NATIVE:
        return src
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        logger.warning("未找到 ffmpeg，可能无法播放 %s", src.name)
        return src
    try:
        st = src.stat()
    except OSError:
        return src
    digest = hashlib.sha1(
        f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8", "replace")
    ).hexdigest()[:16]
    dst = _cache_dir() / f"{digest}.mp3"
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    tmp = dst.with_suffix(".tmp.mp3")
    cmd = [ffmpeg, "-y", "-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(tmp)]
    flags = _NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("转码失败 %s: %s", src.name, exc)
        return src
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size <= 0:
        tmp.unlink(missing_ok=True)
        logger.warning("转码失败 %s", src.name)
        return src
    tmp.replace(dst)
    logger.info("已转码 %s", src.name)
    return dst


def _qt_types():
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:
        return None
    return QAudioOutput, QMediaPlayer


class SfxPlayer(QObject):
    """两路播放器：金币一轨、钻石一轨。无文件或关闭音效时 no-op。"""

    def __init__(self, settings: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._has_files = _probe_sound_files()
        self._qt = _qt_types() if self._has_files else None
        self._players: Dict[str, Tuple[object, object]] = {}
        self._skip: set[str] = set()
        self._diamonds: Optional[List[Path]] = None
        self._prewarm_timer: Optional[QTimer] = None
        if QApplication.instance() is None:
            self._qt = None

    def capable(self) -> bool:
        return bool(
            self._has_files
            and self._qt is not None
            and QApplication.instance() is not None
            and self._settings.get("sound_enabled", True)
        )

    def _volume(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._settings.get("sound_volume", 0.8))))
        except (TypeError, ValueError):
            return 0.8

    def prewarm(self) -> None:
        if not self.capable():
            return
        if self._prewarm_timer is None:
            self._prewarm_timer = QTimer(self)
            self._prewarm_timer.setSingleShot(True)
            self._prewarm_timer.timeout.connect(self._prewarm_now)
        self._prewarm_timer.start(_PREWARM_MS)

    def invalidate(self) -> None:
        self._drop()
        if self.capable():
            self.prewarm()

    def shutdown(self) -> None:
        if self._prewarm_timer is not None:
            self._prewarm_timer.stop()
        self._drop()

    def play_roll_hit(self, reward: Reward) -> None:
        if not self.capable() or reward.is_empty():
            return
        if reward.gold > 0:
            gold = self._gold_path()
            if gold is not None:
                self._play("gold", gold)
        if reward.diamond > 0:
            self.play_random_diamond()

    def play_random_diamond(self) -> None:
        if not self.capable():
            return
        paths = [p for p in self._diamond_paths() if str(p.resolve()) not in self._skip]
        if not paths:
            return
        self._play("diamond", random.choice(paths))

    def _gold_path(self) -> Optional[Path]:
        for ext in _SOUND_EXTS:
            path = _sounds_dir() / f"{_GOLD_STEM}{ext}"
            if path.exists():
                return path
        return None

    def _diamond_paths(self) -> List[Path]:
        if self._diamonds is None:
            self._diamonds = _iter_diamond_paths()
        return self._diamonds

    def _play(self, lane: str, src: Path) -> None:
        slot = self._ensure(lane)
        if slot is None:
            return
        player, output = slot
        ready = qt_ready_path(src)
        try:
            output.setVolume(self._volume())  # type: ignore[attr-defined]
            player.stop()  # type: ignore[attr-defined]
            player.setSource(QUrl.fromLocalFile(str(ready.resolve())))
            player.setPosition(0)  # type: ignore[attr-defined]
            player.play()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("播放失败 %s: %s", src.name, exc)
            self._skip.add(str(src.resolve()))

    def _ensure(self, lane: str) -> Optional[Tuple[object, object]]:
        if lane in self._players:
            return self._players[lane]
        if self._qt is None:
            return None
        QAudioOutput, QMediaPlayer = self._qt
        player = QMediaPlayer(self)
        output = QAudioOutput(self)
        player.setAudioOutput(output)
        player.errorOccurred.connect(
            lambda error, message, name=lane: logger.warning(
                "播放失败(%s): %s %s", name, error, message
            )
        )
        self._players[lane] = (player, output)
        return self._players[lane]

    def _drop(self) -> None:
        for player, _output in self._players.values():
            try:
                player.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._players.clear()

    def _prewarm_now(self) -> None:
        if not self.capable():
            return
        gold = self._gold_path()
        if gold is not None:
            qt_ready_path(gold)
            self._ensure("gold")
        files = self._diamond_paths()
        for path in files:
            qt_ready_path(path)
        if files:
            self._ensure("diamond")
            logger.info("钻石音效 %d 条", len(files))
