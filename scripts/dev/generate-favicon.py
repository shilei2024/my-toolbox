#!/usr/bin/env python3
"""Generate the shared Mavis favicon.ico with Pillow.

The design matches static/img/favicon.svg and apps/gallery-web/src/app/icon.svg:
a violet-to-cyan rounded square with a white M and a spark dot. Pillow encodes
a standard multi-size ICO that the Next.js/sharp pipeline can decode.

Run from the repository root:
    python scripts/dev/generate-favicon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "apps" / "gallery-web" / "src" / "app" / "favicon.ico"
SIZE = 256


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _draw() -> Image.Image:
    top_left = (109, 92, 255)      # #6d5cff
    bottom_right = (34, 211, 238)  # #22d3ee
    m_poly = [
        (0.20, 0.28), (0.36, 0.28), (0.50, 0.45), (0.64, 0.28), (0.80, 0.28),
        (0.80, 0.72), (0.68, 0.72), (0.68, 0.48), (0.50, 0.66), (0.32, 0.48),
        (0.32, 0.72), (0.20, 0.72),
    ]
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    pixels = img.load()
    radius = round(0.22 * SIZE)
    for y in range(SIZE):
        for x in range(SIZE):
            nx = (x + 0.5) / SIZE
            ny = (y + 0.5) / SIZE
            # Rounded-square alpha mask
            cx = min(max(nx, 0.22), 1 - 0.22)
            cy = min(max(ny, 0.22), 1 - 0.22)
            dx = nx - cx
            dy = ny - cy
            if dx * dx + dy * dy > 0.22 * 0.22:
                continue
            t = (nx + ny) / 2
            color = _lerp(top_left, bottom_right, t)
            if _point_in_polygon(nx, ny, m_poly) or (nx - 0.78) ** 2 + (ny - 0.18) ** 2 <= 0.075 ** 2:
                color = (255, 255, 255)
            pixels[x, y] = (color[0], color[1], color[2], 255)
    # Crisp rounded corners via a super-sampled mask
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def main() -> None:
    img = _draw()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
