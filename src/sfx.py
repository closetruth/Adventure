"""开奖音效：全部用 Qt Multimedia（QMediaPlayer）。

wav / ogg / mp3 / m4a / aac 同一条路径。主线程播放，不碰 pygame.mixer。
没有音效文件或用户关闭音效时，不创建播放器。

金币固定 roll_gold；钻石从 assets/sounds/diamond/ 随机选一。
金钻同时中奖时用两个独立 player 叠播。
"""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from .models import Reward
from .paths import project_root

logger = logging.getLogger(__name__)

_SOUND_EXTS = (".wav", ".ogg", ".mp3", ".m4a", ".aac")
_GOLD_STEM = "roll_gold"
_GOLD_KEY = "gold"
_DIAMOND_SUBDIR = "diamond"
_PREWARM_DELAY_MS = 500


def _sounds_base() -> Path:
    return project_root() / "assets" / "sounds"


def _diamond_dir() -> Path:
    return _sounds_base() / _DIAMOND_SUBDIR


def _has_gold_sound() -> bool:
    base = _sounds_base()
    return any((base / f"{_GOLD_STEM}{ext}").exists() for ext in _SOUND_EXTS)


def _iter_diamond_paths() -> List[Path]:
    folder = _diamond_dir()
    if not folder.is_dir():
        return []
    paths = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _SOUND_EXTS
    ]
    return sorted(paths, key=lambda p: p.name.lower())


def _probe_sound_files() -> bool:
    return _has_gold_sound() or bool(_iter_diamond_paths())


def _qt_multimedia():
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:
        return None
    return QAudioOutput, QMediaPlayer


class SfxPlayer(QObject):
    """主线程开奖音效。无文件或关闭音效时公开方法均为 no-op。"""

    def __init__(self, settings: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._has_files = _probe_sound_files()
        self._qt_types = _qt_multimedia() if self._has_files else None
        self._slots: dict[str, tuple[object, object]] = {}
        self._slot_paths: dict[str, Path] = {}
        self._diamond_paths: Optional[List[Path]] = None
        self._diamond_bad_paths: set[str] = set()
        self._prewarm_timer: Optional[QTimer] = None

        if not self._has_files:
            logger.info("未发现音效文件，音效功能已禁用")
        elif self._qt_types is None:
            logger.warning("QtMultimedia 不可用，开奖音效已禁用")
        elif QApplication.instance() is None:
            logger.warning("没有 QApplication，开奖音效已禁用")
            self._qt_types = None

    def capable(self) -> bool:
        return (
            self._has_files
            and self._qt_types is not None
            and QApplication.instance() is not None
            and self._enabled()
        )

    def _enabled(self) -> bool:
        return bool(self._settings.get("sound_enabled", True))

    def _volume(self) -> float:
        try:
            value = float(self._settings.get("sound_volume", 0.8))
        except (TypeError, ValueError):
            return 0.8
        return max(0.0, min(1.0, value))

    def prewarm(self) -> None:
        """延迟预热，避免启动瞬间抢音频设备。"""
        if not self.capable():
            return
        if self._prewarm_timer is None:
            self._prewarm_timer = QTimer(self)
            self._prewarm_timer.setSingleShot(True)
            self._prewarm_timer.timeout.connect(self._prewarm_now)
        self._prewarm_timer.start(_PREWARM_DELAY_MS)

    def invalidate(self) -> None:
        """休眠唤醒后丢掉旧 player，下次播放或预热再建。"""
        self._drop_slots()
        if self.capable():
            self.prewarm()

    def play(self, stem: str) -> None:
        if not self.capable():
            return
        path = self._resolve_stem_path(stem)
        if path is None:
            logger.debug("音效文件缺失: %s", stem)
            return
        key = _GOLD_KEY if stem == _GOLD_STEM else stem
        self._play_path(key, path)

    def play_roll_hit(self, reward: Reward) -> None:
        if not self.capable():
            return
        if reward.gold <= 0 and reward.diamond <= 0:
            return
        if reward.gold > 0:
            gold = self._resolve_stem_path(_GOLD_STEM)
            if gold is not None:
                self._play_path(_GOLD_KEY, gold)
        if reward.diamond > 0:
            self.play_random_diamond()

    def play_random_diamond(self) -> None:
        """从 diamond/ 里随机播一条；无文件或关闭音效时 no-op。"""
        if not self.capable():
            return
        diamond = self._pick_random_diamond_path()
        if diamond is not None:
            self._play_path(self._diamond_slot_key(diamond), diamond)

    def shutdown(self) -> None:
        if self._prewarm_timer is not None:
            self._prewarm_timer.stop()
        self._drop_slots()

    def _resolve_stem_path(self, stem: str) -> Optional[Path]:
        for ext in _SOUND_EXTS:
            path = _sounds_base() / f"{stem}{ext}"
            if path.exists():
                return path
        return None

    def _diamond_cache_key(self, path: Path) -> str:
        return str(path.resolve())

    def _diamond_slot_key(self, path: Path) -> str:
        return f"diamond:{self._diamond_cache_key(path)}"

    def _list_diamond_paths(self) -> List[Path]:
        if self._diamond_paths is None:
            self._diamond_paths = _iter_diamond_paths()
        return [
            p for p in self._diamond_paths
            if self._diamond_cache_key(p) not in self._diamond_bad_paths
        ]

    def _mark_diamond_bad(self, path: Path) -> None:
        self._diamond_bad_paths.add(self._diamond_cache_key(path))

    def _pick_random_diamond_path(self) -> Optional[Path]:
        paths = self._list_diamond_paths()
        if not paths:
            if self._diamond_paths:
                logger.warning(
                    "钻石音效均无法播放（%d 个文件），请检查 assets/sounds/diamond/",
                    len(self._diamond_paths),
                )
            else:
                logger.debug("钻石音效目录为空: %s", _diamond_dir())
            return None
        return random.choice(paths)

    def _ensure_slot(self, key: str, path: Path) -> Optional[tuple[object, object]]:
        existing = self._slots.get(key)
        if existing is not None:
            return existing
        if self._qt_types is None:
            return None
        QAudioOutput, QMediaPlayer = self._qt_types
        player = QMediaPlayer(self)
        output = QAudioOutput(self)
        player.setAudioOutput(output)
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        player.errorOccurred.connect(
            lambda error, message, slot_key=key: self._on_player_error(
                slot_key, error, message,
            )
        )
        self._slots[key] = (player, output)
        self._slot_paths[key] = path
        logger.debug("已准备音效: %s", path.name)
        return self._slots[key]

    def _on_player_error(self, key: str, error: object, message: str) -> None:
        path = self._slot_paths.get(key)
        name = path.name if path is not None else key
        logger.warning("播放音效失败(%s): %s %s", name, error, message)
        if key.startswith("diamond:") and path is not None:
            self._mark_diamond_bad(path)

    def _stop_other_diamonds(self, keep_key: str) -> None:
        for key, (player, _output) in self._slots.items():
            if key.startswith("diamond:") and key != keep_key:
                try:
                    player.stop()  # type: ignore[attr-defined]
                except Exception:
                    pass

    def _play_path(self, key: str, path: Path) -> None:
        slot = self._ensure_slot(key, path)
        if slot is None:
            return
        if key.startswith("diamond:"):
            self._stop_other_diamonds(key)
        player, output = slot
        try:
            output.setVolume(self._volume())  # type: ignore[attr-defined]
            player.stop()  # type: ignore[attr-defined]
            player.setPosition(0)  # type: ignore[attr-defined]
            player.play()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("播放音效失败(%s): %s", path.name, exc)

    def _drop_slots(self) -> None:
        for player, _output in self._slots.values():
            try:
                player.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._slots.clear()
        self._slot_paths.clear()

    def _prewarm_now(self) -> None:
        if not self.capable():
            return
        gold = self._resolve_stem_path(_GOLD_STEM)
        if gold is not None:
            self._ensure_slot(_GOLD_KEY, gold)
        all_paths = _iter_diamond_paths()
        self._diamond_paths = all_paths
        ok = 0
        for path in all_paths:
            if self._ensure_slot(self._diamond_slot_key(path), path) is not None:
                ok += 1
        if all_paths:
            logger.info("钻石音效预热: %d/%d", ok, len(all_paths))
