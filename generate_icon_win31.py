"""
Generate a Windows 3.1 style stopwatch icon for ScreenBreak.
Run standalone to preview, or import generate_icon() for the .spec file.
"""
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
    """Draw diagonal crosshatch lines clipped to a circle."""
    r_sq = r * r
    # Draw lines at 45 degrees (top-left to bottom-right)
    for offset in range(-2 * r, 2 * r + 1, spacing):
        pts = []
        for x in range(cx - r, cx + r + 1):
            y = x + offset  # y = x + offset (45-degree line)
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= r_sq:
                pts.append((x, y))
        if len(pts) >= 2:
            draw.line([pts[0], pts[-1]], fill=line_color, width=line_w)

    # Draw lines at -45 degrees (top-right to bottom-left)
    for offset in range(-2 * r, 2 * r + 1, spacing):
        pts = []
        for x in range(cx - r, cx + r + 1):
            y = -x + offset + 2 * cy  # y = -x + offset (135-degree line)
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= r_sq:
                pts.append((x, y))
        if len(pts) >= 2:
            draw.line([pts[0], pts[-1]], fill=line_color, width=line_w)


def create_win31_stopwatch(size=256):
    """Create a single stopwatch icon in Win 3.1 style."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64  # scale factor (designed at 64px base)
    w = max(1, int(s))  # base line width
    w2 = max(1, int(1.5 * s))  # thicker line width

    cx, cy = int(32 * s), int(36 * s)
    r_outer = int(23 * s)
    rim_width = max(4, int(5 * s))
    r_inner = r_outer - rim_width

    # ── Crown / button at top ──
    btn_w = max(3, int(4 * s))
    btn_h = max(6, int(9 * s))
    btn_top = cy - r_outer - btn_h + max(1, int(2 * s))
    btn_bottom = cy - r_outer + max(2, int(3 * s))

    # Button shadow (offset for depth)
    draw.rectangle([cx - btn_w + w, btn_top + w,
                    cx + btn_w + w, btn_bottom + w], fill=DARK_GRAY)
    # Button body
    draw.rectangle([cx - btn_w, btn_top, cx + btn_w, btn_bottom],
                   fill=TEAL, outline=BLACK, width=w)
    # 3D highlights
    draw.line([(cx - btn_w + w, btn_top + w),
               (cx + btn_w - w, btn_top + w)], fill=LIGHT_CYAN, width=w)
    draw.line([(cx - btn_w + w, btn_top + w),
               (cx - btn_w + w, btn_bottom - w)], fill=LIGHT_CYAN, width=w)
    draw.line([(cx + btn_w - w, btn_top + w),
               (cx + btn_w - w, btn_bottom)], fill=DARK_TEAL, width=w)
    draw.line([(cx - btn_w, btn_bottom - w),
               (cx + btn_w, btn_bottom - w)], fill=DARK_TEAL, width=w)

    # ── Outer ring: thick black outline ──
    draw.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
                 fill=BLACK)

    # ── Teal rim ──
    r_rim = r_outer - w2
    draw.ellipse([cx - r_rim, cy - r_rim, cx + r_rim, cy + r_rim],
                 fill=TEAL)

    # 3D bevel: thick highlight on upper-left arc of rim
    bevel_thickness = max(2, int(2.5 * s))
    for angle_deg in range(200, 345):
        angle = math.radians(angle_deg)
        for offset in range(1, bevel_thickness + 1):
            br = r_rim - offset
            bx = int(cx + br * math.cos(angle))
            by = int(cy + br * math.sin(angle))
            draw.point((bx, by), fill=LIGHT_CYAN)

    # 3D bevel: thick shadow on lower-right arc of rim
    for angle_deg in range(20, 165):
        angle = math.radians(angle_deg)
        for offset in range(1, bevel_thickness + 1):
            br = r_rim - offset
            bx = int(cx + br * math.cos(angle))
            by = int(cy + br * math.sin(angle))
            draw.point((bx, by), fill=DARK_TEAL)

    # ── Inner face: white/silver base ──
    # Black separator ring
    draw.ellipse([cx - r_inner - w, cy - r_inner - w,
                  cx + r_inner + w, cy + r_inner + w],
                 fill=BLACK)
    # White face
    draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
                 fill=WHITE)

    # ── Crosshatch shading on the face ──
    hatch_spacing = max(3, int(4 * s))
    hatch_w = max(1, int(0.8 * s))
    crosshatch_in_circle(draw, cx, cy, r_inner - w,
                         TEAL, hatch_spacing, hatch_w)

    # Sunken bevel inside the face
    bevel_inner = max(1, int(1.5 * s))
    for angle_deg in range(200, 345):
        angle = math.radians(angle_deg)
        for offset in range(0, bevel_inner):
            br = r_inner - offset
            bx = int(cx + br * math.cos(angle))
            by = int(cy + br * math.sin(angle))
            draw.point((bx, by), fill=GRAY)
    for angle_deg in range(20, 165):
        angle = math.radians(angle_deg)
        for offset in range(0, bevel_inner):
            br = r_inner - offset
            bx = int(cx + br * math.cos(angle))
            by = int(cy + br * math.sin(angle))
            draw.point((bx, by), fill=WHITE)

    # ── Tick marks at 12, 3, 6, 9 ──
    tick_len = max(3, int(5 * s))
    tick_outer = r_inner - max(2, int(3 * s))
    tick_inner = tick_outer - tick_len
    tick_w = max(2, int(2.5 * s))
    for hour in [0, 90, 180, 270]:
        angle = math.radians(hour - 90)
        tx0 = int(cx + tick_inner * math.cos(angle))
        ty0 = int(cy + tick_inner * math.sin(angle))
        tx1 = int(cx + tick_outer * math.cos(angle))
        ty1 = int(cy + tick_outer * math.sin(angle))
        draw.line([(tx0, ty0), (tx1, ty1)], fill=BLACK, width=tick_w)

    # ── Clock hand (pointing to ~2 o'clock) ──
    hand_angle = math.radians(-60)
    hand_len = r_inner - max(8, int(10 * s))
    hx = int(cx + hand_len * math.cos(hand_angle))
    hy = int(cy + hand_len * math.sin(hand_angle))
    hand_width = max(2, int(3 * s))
    # Hand shadow
    draw.line([(cx + w, cy + w), (hx + w, hy + w)],
              fill=GRAY, width=hand_width)
    # Hand
    draw.line([(cx, cy), (hx, hy)], fill=BLACK, width=hand_width)

    # Center hub
    dot_r = max(2, int(3 * s))
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                 fill=TEAL, outline=BLACK, width=w)
    # Hub highlight
    hr = max(1, dot_r // 2)
    draw.ellipse([cx - hr - 1, cy - hr - 1, cx, cy],
                 fill=LIGHT_CYAN)

    return img


def generate_icon():
    """Generate icon.ico and icon.png files."""
    sizes = [16, 32, 48, 64, 128, 256]
    images = [create_win31_stopwatch(s) for s in sizes]
    # ICO: save largest first, append smaller — PIL requires this order
    images[-1].save('icon.ico', format='ICO', append_images=images[:-1])
    images[-1].save('icon.png', format='PNG')


if __name__ == "__main__":
    generate_icon()
    preview = create_win31_stopwatch(512)
    preview.save('icon_preview.png', format='PNG')
    print("Generated icon.ico, icon.png, and icon_preview.png (512px)")
