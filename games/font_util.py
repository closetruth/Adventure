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


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    font = _load_from_known_files(size, bold)
    if font is not None:
        return font

    names = ("microsoftyaheiui", "microsoftyahei", "simhei", "arial")
    try:
        for name in names:
            path = pygame.font.match_font(name, bold=bold)
            if path:
                return pygame.font.Font(path, size)
        return pygame.font.SysFont(None, size, bold=bold)
    except TypeError:
        return pygame.font.Font(None, size)
