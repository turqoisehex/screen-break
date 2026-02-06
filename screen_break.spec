# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Screen Break
Build with: pyinstaller screen_break.spec

Cross-platform: automatically detects OS and includes appropriate pystray backend.
"""

import sys
import os
from PyInstaller.utils.hooks import collect_submodules

# Generate flat Android-style stopwatch icon
def generate_icon():
    from PIL import Image, ImageDraw
    import math

    def create_stopwatch_icon(size=256):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        s = size / 64
        FILL = (14, 165, 233, 255)    # Sky blue
        ACCENT = (255, 255, 255, 255)  # White
        cx, cy, r = int(32 * s), int(34 * s), int(22 * s)
        # Main circle
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=FILL)
        # Button at top
        bw, bh = int(4 * s), int(8 * s)
        draw.rectangle([cx-bw, int(4*s), cx+bw, int(12*s)], fill=FILL)
        draw.ellipse([cx-int(5*s), int(2*s), cx+int(5*s), int(8*s)], fill=FILL)
        # Clock hand
        hand_angle = math.radians(-60)
        hand_len = r - int(6 * s)
        hx, hy = int(cx + hand_len * math.cos(hand_angle)), int(cy + hand_len * math.sin(hand_angle))
        draw.line([(cx, cy), (hx, hy)], fill=ACCENT, width=max(4, int(4 * s)))
        # Center dot
        dot_r = int(4 * s)
        draw.ellipse([cx-dot_r, cy-dot_r, cx+dot_r, cy+dot_r], fill=ACCENT)
        return img

    sizes = [16, 32, 48, 64, 128, 256]
    images = [create_stopwatch_icon(s) for s in sizes]
    images[0].save('icon.ico', format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    images[-1].save('icon.png', format='PNG')

# Always regenerate
generate_icon()

# Determine icon file based on platform
icon_file = 'icon.ico' if sys.platform == 'win32' else 'icon.png'

hiddenimports = collect_submodules('pystray')

# Platform-specific pystray backends
if sys.platform == 'win32':
    platform_imports = ['pystray._win32']
elif sys.platform == 'darwin':
    platform_imports = ['pystray._darwin']
else:  # Linux
    platform_imports = ['pystray._gtk', 'pystray._appindicator', 'pystray._xorg']

a = Analysis(
    ['screen_break.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports + platform_imports + [
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx',
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
    icon=icon_file,
)
