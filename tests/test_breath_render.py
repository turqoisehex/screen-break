"""The in-place breathing-widget renderer must produce exactly the bytes the
original pipeline produced (RGBA draw -> split -> merge as BGRA -> tobytes),
so the widget looks identical while allocating nothing per frame.

Runs headless — pure Pillow + ctypes buffers, no Tk, no GDI. Mapping the real
Windows DIB section (_breath_map_dib) and falling back when that mapping fails
need a live layered window, so they are not covered here.
"""
import ctypes
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from screen_break import ScreenBreakApp, draw_breath_rings_bgra

TEAL = ScreenBreakApp._BREATH_TEAL
STEP = ScreenBreakApp._BREATH_RING_STEP


def original_frame(w, h, core_r):
    """The pre-optimization per-pixel-alpha frame pipeline: same drawing calls
    and R<->B channel swap as the original, kept here as the reference."""
    n = len(TEAL)
    rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(rgba)
    cx, cy = w // 2, h // 2
    for i, rgb in enumerate(TEAL):
        factor = 1.0 + (n - 1 - i) * STEP
        r = core_r * factor
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb + (255,))
    r_ch, g_ch, b_ch, a_ch = rgba.split()
    bgra = Image.merge("RGBA", (b_ch, g_ch, r_ch, a_ch))
    return bgra.tobytes()


def core_radii(w, h, count):
    """core_r values swept across a full cosine breath, as the widget does."""
    n = len(TEAL)
    outermost = 1.0 + (n - 1) * STEP
    max_r = (min(w, h) / 2 - 4) / outermost
    min_r = max_r * 0.33
    for k in range(count):
        breath = 0.5 - 0.5 * math.cos(2 * math.pi * k / count)
        yield min_r + (max_r - min_r) * breath


def mapped_image(w, h):
    """A PIL image that draws straight into a ctypes buffer, as the widget maps its DIB."""
    buf = (ctypes.c_ubyte * (w * h * 4))()
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", 0, 1)
    img.readonly = 0
    return buf, img, ImageDraw.Draw(img)


@pytest.mark.parametrize("w,h", [(80, 80), (220, 220), (1020, 1020), (301, 157)])
def test_in_place_render_is_byte_identical(w, h):
    buf, img, draw = mapped_image(w, h)
    for core_r in core_radii(w, h, 90):
        draw_breath_rings_bgra(img, draw, w, h, core_r, TEAL, STEP)
        assert bytes(buf) == original_frame(w, h, core_r), f"core_r={core_r}"


def test_previous_frame_is_fully_cleared():
    """Shrinking from a large circle must not leave the old outer ring behind."""
    w = h = 400
    buf, img, draw = mapped_image(w, h)
    radii = list(core_radii(w, h, 20))
    big, small = max(radii), min(radii)
    draw_breath_rings_bgra(img, draw, w, h, big, TEAL, STEP)
    draw_breath_rings_bgra(img, draw, w, h, small, TEAL, STEP)
    assert bytes(buf) == original_frame(w, h, small)
