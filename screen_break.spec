# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Screen Break
Build with: pyinstaller screen_break.spec

Cross-platform: automatically detects OS and includes appropriate pystray backend.
"""

import sys
import os
from PyInstaller.utils.hooks import collect_submodules

# Generate Windows 3.1 style stopwatch icon with crosshatch shading
def generate_icon():
    from PIL import Image, ImageDraw
    import math

    # Windows 3.1 16-color palette
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    TEAL = (0, 128, 128)
    DARK_TEAL = (0, 80, 80)
    SILVER = (192, 192, 192)
    GRAY = (128, 128, 128)
    DARK_GRAY = (64, 64, 64)
    LIGHT_CYAN = (128, 192, 192)

    def crosshatch_in_circle(draw, cx, cy, r, line_color, spacing, line_w=1):
        r_sq = r * r
        for offset in range(-2 * r, 2 * r + 1, spacing):
            pts = []
            for x in range(cx - r, cx + r + 1):
                y = x + offset
                dx, dy = x - cx, y - cy
                if dx * dx + dy * dy <= r_sq:
                    pts.append((x, y))
            if len(pts) >= 2:
                draw.line([pts[0], pts[-1]], fill=line_color, width=line_w)
        for offset in range(-2 * r, 2 * r + 1, spacing):
            pts = []
            for x in range(cx - r, cx + r + 1):
                y = -x + offset + 2 * cy
                dx, dy = x - cx, y - cy
                if dx * dx + dy * dy <= r_sq:
                    pts.append((x, y))
            if len(pts) >= 2:
                draw.line([pts[0], pts[-1]], fill=line_color, width=line_w)

    def create_stopwatch_icon(size=256):
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        s = size / 64
        w = max(1, int(s))
        w2 = max(1, int(1.5 * s))
        cx, cy = int(32 * s), int(36 * s)
        r_outer = int(23 * s)
        rim_width = max(4, int(5 * s))
        r_inner = r_outer - rim_width
        # Crown / button
        btn_w, btn_h = max(3, int(4 * s)), max(6, int(9 * s))
        btn_top = cy - r_outer - btn_h + max(1, int(2 * s))
        btn_bottom = cy - r_outer + max(2, int(3 * s))
        draw.rectangle([cx-btn_w+w, btn_top+w, cx+btn_w+w, btn_bottom+w], fill=DARK_GRAY)
        draw.rectangle([cx-btn_w, btn_top, cx+btn_w, btn_bottom], fill=TEAL, outline=BLACK, width=w)
        draw.line([(cx-btn_w+w, btn_top+w), (cx+btn_w-w, btn_top+w)], fill=LIGHT_CYAN, width=w)
        draw.line([(cx-btn_w+w, btn_top+w), (cx-btn_w+w, btn_bottom-w)], fill=LIGHT_CYAN, width=w)
        draw.line([(cx+btn_w-w, btn_top+w), (cx+btn_w-w, btn_bottom)], fill=DARK_TEAL, width=w)
        draw.line([(cx-btn_w, btn_bottom-w), (cx+btn_w, btn_bottom-w)], fill=DARK_TEAL, width=w)
        # Outer ring
        draw.ellipse([cx-r_outer, cy-r_outer, cx+r_outer, cy+r_outer], fill=BLACK)
        # Teal rim with 3D bevel
        r_rim = r_outer - w2
        draw.ellipse([cx-r_rim, cy-r_rim, cx+r_rim, cy+r_rim], fill=TEAL)
        bevel = max(2, int(2.5 * s))
        for a_deg in range(200, 345):
            a = math.radians(a_deg)
            for off in range(1, bevel + 1):
                draw.point((int(cx+(r_rim-off)*math.cos(a)), int(cy+(r_rim-off)*math.sin(a))), fill=LIGHT_CYAN)
        for a_deg in range(20, 165):
            a = math.radians(a_deg)
            for off in range(1, bevel + 1):
                draw.point((int(cx+(r_rim-off)*math.cos(a)), int(cy+(r_rim-off)*math.sin(a))), fill=DARK_TEAL)
        # Inner face
        draw.ellipse([cx-r_inner-w, cy-r_inner-w, cx+r_inner+w, cy+r_inner+w], fill=BLACK)
        draw.ellipse([cx-r_inner, cy-r_inner, cx+r_inner, cy+r_inner], fill=WHITE)
        # Crosshatch shading
        crosshatch_in_circle(draw, cx, cy, r_inner-w, TEAL, max(3, int(4*s)), max(1, int(0.8*s)))
        # Sunken bevel
        bi = max(1, int(1.5 * s))
        for a_deg in range(200, 345):
            a = math.radians(a_deg)
            for off in range(0, bi):
                draw.point((int(cx+(r_inner-off)*math.cos(a)), int(cy+(r_inner-off)*math.sin(a))), fill=GRAY)
        for a_deg in range(20, 165):
            a = math.radians(a_deg)
            for off in range(0, bi):
                draw.point((int(cx+(r_inner-off)*math.cos(a)), int(cy+(r_inner-off)*math.sin(a))), fill=WHITE)
        # Tick marks
        tl = max(3, int(5*s));  to = r_inner - max(2, int(3*s));  ti = to - tl;  tw = max(2, int(2.5*s))
        for h in [0, 90, 180, 270]:
            a = math.radians(h - 90)
            draw.line([(int(cx+ti*math.cos(a)), int(cy+ti*math.sin(a))),
                       (int(cx+to*math.cos(a)), int(cy+to*math.sin(a)))], fill=BLACK, width=tw)
        # Clock hand
        ha = math.radians(-60);  hl = r_inner - max(8, int(10*s));  hw = max(2, int(3*s))
        hx, hy = int(cx+hl*math.cos(ha)), int(cy+hl*math.sin(ha))
        draw.line([(cx+w, cy+w), (hx+w, hy+w)], fill=GRAY, width=hw)
        draw.line([(cx, cy), (hx, hy)], fill=BLACK, width=hw)
        # Center hub
        dr = max(2, int(3*s))
        draw.ellipse([cx-dr, cy-dr, cx+dr, cy+dr], fill=TEAL, outline=BLACK, width=w)
        hr = max(1, dr//2)
        draw.ellipse([cx-hr-1, cy-hr-1, cx, cy], fill=LIGHT_CYAN)
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
