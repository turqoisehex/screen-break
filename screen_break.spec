# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Screen Break
Build with: pyinstaller screen_break.spec
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('pystray')

a = Analysis(
    ['screen_break.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports + [
        'pystray._win32',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx', 'gtk',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, optimize=1)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScreenBreak',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
