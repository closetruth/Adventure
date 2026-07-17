"""音效播放：使用 pygame.mixer，兼容 wav/ogg/mp3。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from .models import Reward

logger = logging.getLogger(__name__)

_SOUND_EXTS = (".wav", ".ogg", ".mp3")


def project_root() -> Path:
    """Return project root in dev mode and bundle mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class SfxPlayer:
    """Play short UI sound effects when resources are available."""

    _mixer_ready = False

    def __init__(self, settings: dict):
        self._settings = settings
        self._sounds: dict[str, object] = {}

    def _enabled(self) -> bool:
        return bool(self._settings.get("sound_enabled", True))

    def _volume(self) -> float:
        try:
            value = float(self._settings.get("sound_volume", 0.8))
        except (TypeError, ValueError):
            return 0.8
        return max(0.0, min(1.0, value))

    def _candidate_paths(self, stem: str) -> list[Path]:
        base = project_root() / "assets" / "sounds"
        return [base / f"{stem}{ext}" for ext in _SOUND_EXTS]

    def _resolve_path(self, stem: str) -> Optional[Path]:
        for path in self._candidate_paths(stem):
            if path.exists():
                return path
        return None

    def _reset_mixer(self) -> None:
        """Tear down mixer and clear cached sounds (e.g. after sleep/wake)."""
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.debug("pygame.mixer.quit 失败: %s", exc)
        SfxPlayer._mixer_ready = False
        self._sounds.clear()

    def invalidate(self) -> None:
        """Mark mixer stale so the next play re-inits lazily."""
        self._reset_mixer()

    def _ensure_mixer(self) -> bool:
        try:
            import pygame

            if pygame.mixer.get_init():
                SfxPlayer._mixer_ready = True
                return True

            SfxPlayer._mixer_ready = False
            pygame.mixer.init()
            SfxPlayer._mixer_ready = True
            return True
        except Exception as exc:  # pragma: no cover - runtime fallback
            SfxPlayer._mixer_ready = False
            logger.warning("pygame.mixer 初始化失败: %s", exc)
            return False

    def _load_sound(self, stem: str) -> Optional[object]:
        sound_path = self._resolve_path(stem)
        if sound_path is None:
            logger.debug("音效文件缺失: %s", stem)
            return None
        if not self._ensure_mixer():
            return None

        try:
            import pygame

            sound = pygame.mixer.Sound(str(sound_path))
            self._sounds[stem] = sound
            logger.debug("已加载音效: %s (%s)", stem, sound_path.name)
            return sound
        except Exception as exc:  # pragma: no cover - runtime fallback
            # 常见坑：把 m4a/mp4/aac 改名为 .mp3，pygame 无法识别
            header = ""
            try:
                raw = sound_path.read_bytes()[:12]
                header = raw[:4].hex()
                if raw[4:8] == b"ftyp":
                    header = f"mp4/m4a(ftyp={raw[8:12]!r})"
            except Exception:
                pass
            logger.warning(
                "加载音效失败(%s → %s): %s；请使用真正的 wav/ogg/mp3%s",
                stem,
                sound_path.name,
                exc,
                f"（当前文件头: {header}）" if header else "",
            )
            return None

    def _sound_for(self, stem: str) -> Optional[object]:
        existing = self._sounds.get(stem)
        if existing is not None:
            return existing
        return self._load_sound(stem)

    def _try_play(self, sound: object) -> None:
        sound.set_volume(self._volume())
        sound.play()

    def play(self, stem: str) -> bool:
        """Play one sound by stem name when enabled and available."""
        if not self._enabled():
            return False
        sound = self._sound_for(stem)
        if sound is None:
            return False

        try:
            self._try_play(sound)
            return True
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("播放音效失败(%s)，尝试重建 mixer: %s", stem, exc)
            self._reset_mixer()
            sound = self._load_sound(stem)
            if sound is None:
                return False
            try:
                self._try_play(sound)
                return True
            except Exception as retry_exc:  # pragma: no cover - runtime fallback
                logger.warning("播放音效失败(%s): %s", stem, retry_exc)
                return False

    def play_roll_hit(self, reward: Reward) -> bool:
        """Play the configured roll-hit sound based on reward type."""
        if reward.diamond > 0:
            return self.play("roll_diamond")
        if reward.gold > 0:
            return self.play("roll_gold")
        return False
