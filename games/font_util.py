"""Load UI fonts without relying on pygame.sysfont registry enumeration.

On some Windows setups (notably Python 3.14 + pygame-ce 2.5.7), invalid
non-string values in the Fonts registry crash ``match_font`` / ``SysFont``.
Loading known font files directly avoids that path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pygame

_FONT_FILES = (
    ("microsoftyaheiui", "msyh.ttc", "msyhbd.ttc"),
    ("microsoftyahei", "msyh.ttc", "msyhbd.ttc"),
    ("simhei", "simhei.ttf", "simhei.ttf"),
    ("arial", "arial.ttf", "arialbd.ttf"),
)


def _windows_fonts_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _load_from_known_files(size: int, bold: bool) -> pygame.font.Font | None:
    if sys.platform != "win32":
        return None
    font_dir = _windows_fonts_dir()
    for _name, regular, bold_name in _FONT_FILES:
        filename = bold_name if bold else regular
        path = font_dir / filename
        if path.is_file():
            return pygame.font.Font(str(path), size)
    return None


class CachedFont:
    """缓存 ``render`` 结果。汉字字体每帧重绘是小游戏卡顿的主因。"""

    def __init__(self, font: pygame.font.Font):
        self._font = font
        self._cache: dict[tuple, pygame.Surface] = {}

    def render(self, text, antialias, color, *args, **kwargs):
        if hasattr(color, "r"):
            key_c = (color.r, color.g, color.b, getattr(color, "a", 255))
        else:
            key_c = tuple(color)
        key = (str(text), bool(antialias), key_c)
        surf = self._cache.get(key)
        if surf is None:
            surf = self._font.render(text, antialias, color, *args, **kwargs)
            if len(self._cache) < 1024:
                self._cache[key] = surf
        return surf

    def __getattr__(self, name):
        return getattr(self._font, name)


def load_font(size: int, bold: bool = False) -> CachedFont:
    font = _load_from_known_files(size, bold)
    if font is None:
        names = ("microsoftyaheiui", "microsoftyahei", "simhei", "arial")
        try:
            found = None
            for name in names:
                path = pygame.font.match_font(name, bold=bold)
                if path:
                    found = pygame.font.Font(path, size)
                    break
            font = found or pygame.font.SysFont(None, size, bold=bold)
        except TypeError:
            font = pygame.font.Font(None, size)
    return CachedFont(font)
