"""Render the VESTNIO bot avatar (640×640 PNG) from the app's pulse mark.

    python scripts/make_avatar.py            # writes assets/bot-avatar.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "bot-avatar.png"
SIZE = 640
SS = 4  # supersampling for smooth edges

# Same polyline as the in-app BrandMark (24×24 viewBox)
MARK = [(2.5, 13), (6.7, 13), (8.9, 7.5), (12.5, 17.5), (15.1, 10.5), (16.4, 13), (21.5, 13)]


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def main() -> None:
    n = SIZE * SS
    # diagonal gradient: accent #9555F5 → deep violet, on the app's dark base
    top, bottom = (0xA8, 0x6C, 0xFF), (0x4B, 0x23, 0xB0)
    grad = Image.new("RGB", (n, n))
    px = grad.load()
    for y in range(n):
        for x in range(0, n, SS):
            c = lerp(top, bottom, (x + y) / (2 * n))
            for dx in range(SS):
                px[x + dx, y] = c

    # soft glow behind the mark
    glow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(glow).ellipse((n * 0.18, n * 0.22, n * 0.82, n * 0.78), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.08))
    grad = Image.composite(Image.new("RGB", (n, n), (0xC9, 0xA6, 0xFF)), grad, glow)

    # the pulse line, scaled to ~66% of the width and centred (safe inside the circle crop)
    scale = n * 0.66 / (21.5 - 2.5)
    ox = (n - (21.5 - 2.5) * scale) / 2 - 2.5 * scale
    oy = n / 2 - 12.5 * scale
    pts = [(ox + x * scale, oy + y * scale) for x, y in MARK]
    draw = ImageDraw.Draw(grad)
    width = round(n * 0.062)
    draw.line(pts, fill=(255, 255, 255), width=width, joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):  # round caps
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    grad.resize((SIZE, SIZE), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
