# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    'pyvda', 'win32api', 'win32con', 'winreg',
    'pygame', 'games', 'games.pet_arena', 'games.pixel_tactics',
]
hiddenimports += collect_submodules('pynput')
hiddenimports += collect_submodules('PySide6')
try:
    hiddenimports += collect_submodules('pygame')
except Exception:
    pass

# 开发态备用：把 games / assets 目录一并打进包。
datas = [('games', 'games'), ('assets', 'assets')]


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Adventure',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Adventure',
)
