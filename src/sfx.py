"""音效播放：使用 pygame.mixer，兼容 wav/ogg/mp3。

设计要点（避免卡顿/崩溃）：
- 没有音效文件或用户关闭音效时，**完全不创建线程、不 import pygame**（零开销 no-op）。
- 有音效文件时，所有 mixer 操作在专用后台线程串行执行，主线程只投递请求。
- init 失败后进入冷却期，避免在无音频设备的机器上反复卡数秒。
"""
from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .models import Reward

logger = logging.getLogger(__name__)

_SOUND_EXTS = (".wav", ".ogg", ".mp3")
_SOUND_STEMS = ("roll_gold", "roll_diamond")
_MIXER_RETRY_COOLDOWN = 300.0


def project_root() -> Path:
    """Return project root in dev mode and bundle mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _probe_sound_files() -> bool:
    base = project_root() / "assets" / "sounds"
    return any(
        (base / f"{stem}{ext}").exists()
        for stem in _SOUND_STEMS
        for ext in _SOUND_EXTS
    )


class SfxPlayer:
    """Play short UI sound effects when resources are available.

    若未找到音效文件或用户关闭音效，所有公开方法均为即时 no-op，不会触碰 pygame/SDL。
    """

    def __init__(self, settings: dict):
        self._settings = settings
        self._sounds: dict[str, object] = {}
        self._mixer_ready = False
        self._mixer_retry_after = 0.0
        self._has_files = _probe_sound_files()
        self._executor: Optional[ThreadPoolExecutor] = None

        if not self._has_files:
            logger.info("未发现音效文件，音效功能已禁用（不会初始化音频设备）")
        elif self._enabled():
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="sfx"
            )

    def capable(self) -> bool:
        """是否有音效文件且用户未关闭音效（可安全尝试播放）。"""
        return self._has_files and self._enabled()

    # ---------- 主线程侧（非阻塞入口） ----------
    def _enabled(self) -> bool:
        return bool(self._settings.get("sound_enabled", True))

    def _submit(self, fn, *args) -> None:
        if self._executor is None:
            return
        try:
            self._executor.submit(fn, *args)
        except RuntimeError:  # 执行器已关闭
            pass

    def prewarm(self) -> None:
        """后台预热 mixer 并预加载音效。"""
        if not self.capable():
            return
        self._submit(self._prewarm_worker)

    def invalidate(self) -> None:
        """标记 mixer 失效（如休眠唤醒后），后台仅拆除，不重建。"""
        if not self.capable():
            return
        self._submit(self._reset_mixer)

    def play(self, stem: str) -> None:
        if not self.capable():
            return
        self._submit(self._play_worker, stem)

    def play_roll_hit(self, reward: Reward) -> None:
        if not self.capable():
            return
        if reward.diamond > 0:
            self._submit(self._play_worker, "roll_diamond")
        elif reward.gold > 0:
            self._submit(self._play_worker, "roll_gold")

    def shutdown(self) -> None:
        """退出时停止工作线程。"""
        if self._executor is None:
            return
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None

    # ---------- 工作线程侧（可能阻塞） ----------
    def _volume(self) -> float:
        try:
            value = float(self._settings.get("sound_volume", 0.8))
        except (TypeError, ValueError):
            return 0.8
        return max(0.0, min(1.0, value))

    def _resolve_path(self, stem: str) -> Optional[Path]:
        base = project_root() / "assets" / "sounds"
        for ext in _SOUND_EXTS:
            path = base / f"{stem}{ext}"
            if path.exists():
                return path
        return None

    def _reset_mixer(self) -> None:
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.debug("pygame.mixer.quit 失败: %s", exc)
        self._mixer_ready = False
        self._sounds.clear()

    def _ensure_mixer(self) -> bool:
        try:
            import pygame

            if pygame.mixer.get_init():
                self._mixer_ready = True
                return True

            if time.time() < self._mixer_retry_after:
                return False

            self._mixer_ready = False
            pygame.mixer.init()
            self._mixer_ready = True
            self._mixer_retry_after = 0.0
            return True
        except Exception as exc:  # pragma: no cover - runtime fallback
            self._mixer_ready = False
            self._mixer_retry_after = time.time() + _MIXER_RETRY_COOLDOWN
            logger.warning(
                "pygame.mixer 初始化失败（%.0fs 内不再重试）: %s",
                _MIXER_RETRY_COOLDOWN,
                exc,
            )
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

    def _prewarm_worker(self) -> None:
        if not self._ensure_mixer():
            return
        for stem in _SOUND_STEMS:
            self._sound_for(stem)

    def _play_worker(self, stem: str) -> None:
        sound = self._sound_for(stem)
        if sound is None:
            return
        try:
            self._try_play(sound)
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("播放音效失败(%s)，尝试重建 mixer: %s", stem, exc)
            self._reset_mixer()
            sound = self._load_sound(stem)
            if sound is None:
                return
            try:
                self._try_play(sound)
            except Exception as retry_exc:  # pragma: no cover - runtime fallback
                logger.warning("播放音效失败(%s): %s", stem, retry_exc)
