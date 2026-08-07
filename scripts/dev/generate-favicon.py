#!/usr/bin/env python3
"""Generate the shared Mavis favicon.ico (16/32/48 px) with only stdlib.

The design matches static/img/favicon.svg and apps/gallery-web/src/app/icon.svg:
a violet-to-cyan rounded square with a white M and a spark dot.

Run from the repository root:
    python scripts/dev/generate-favicon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "apps" / "gallery-web" / "src" / "app" / "favicon.ico"


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


def _draw(size: int) -> bytes:
    """Return a BMP DIB (BITMAPINFOHEADER + BGRA + AND mask) for an ICO entry."""
    top_left = (109, 92, 255)   # #6d5cff
    bottom_right = (34, 211, 238)  # #22d3ee
    m_poly = [
        (0.20, 0.28), (0.36, 0.28), (0.50, 0.45), (0.64, 0.28), (0.80, 0.28),
        (0.80, 0.72), (0.68, 0.72), (0.68, 0.48), (0.50, 0.66), (0.32, 0.48),
        (0.32, 0.72), (0.20, 0.72),
    ]
    px: list[tuple[int, int, int, int]] = []
    for y in range(size):
        for x in range(size):
            nx = (x + 0.5) / size
            ny = (y + 0.5) / size
            # rounded-square mask with radius 22%
            r = 0.22
            cx = min(max(nx, r), 1 - r)
            cy = min(max(ny, r), 1 - r)
            dx = nx - cx
            dy = ny - cy
            alpha = 255 if dx * dx + dy * dy <= r * r else 0
            if alpha == 0:
                px.append((0, 0, 0, 0))
                continue
            t = (nx + ny) / 2
            color = _lerp(top_left, bottom_right, t)
            white = _point_in_polygon(nx, ny, m_poly)
            if white:
                color = (255, 255, 255)
            # spark dot at (0.78, 0.18) radius 0.075
            if (nx - 0.78) ** 2 + (ny - 0.18) ** 2 <= 0.075 ** 2:
                color = (255, 255, 255)
            px.append((color[2], color[1], color[0], alpha))  # BGRA

    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(px) * 4, 0, 0, 0, 0)
    rows = b"".join(
        b"".join(bytes(pixel) for pixel in px[(size - 1 - row) * size: (size - row) * size])
        for row in range(size)
    )
    mask_stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * size)
    return header + rows + mask


def build_ico(sizes: list[int]) -> bytes:
    entries = []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        data = _draw(size)
        entries.append((size, len(data), offset))
        offset += len(data)
    out = struct.pack("<HHH", 0, 1, len(sizes))
    for size, length, off in entries:
        out += struct.pack("<BBBBHHII", size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, length, off)
        out += _draw(size)
    return out


def _png_file(size: int, path: Path) -> None:
    header = struct.pack(">IIBBBBBBI", 0x89504E47, 0x0D0A1A0A, 0, 0, 0, 0, 0, 0, 0)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = b""
    for y in range(size):
        raw += b"\x00"
        for x in range(size):
            raw += bytes(_draw_pixel(size, x, y))
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    data = chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(header + data)


def _draw_pixel(size: int, x: int, y: int) -> tuple[int, int, int, int]:
    top_left = (109, 92, 255)
    bottom_right = (34, 211, 238)
    m_poly = [
        (0.20, 0.28), (0.36, 0.28), (0.50, 0.45), (0.64, 0.28), (0.80, 0.28),
        (0.80, 0.72), (0.68, 0.72), (0.68, 0.48), (0.50, 0.66), (0.32, 0.48),
        (0.32, 0.72), (0.20, 0.72),
    ]
    nx = (x + 0.5) / size
    ny = (y + 0.5) / size
    r = 0.22
    cx = min(max(nx, r), 1 - r)
    cy = min(max(ny, r), 1 - r)
    dx = nx - cx
    dy = ny - cy
    alpha = 255 if dx * dx + dy * dy <= r * r else 0
    if alpha == 0:
        return (0, 0, 0, 0)
    t = (nx + ny) / 2
    color = _lerp(top_left, bottom_right, t)
    if _point_in_polygon(nx, ny, m_poly) or (nx - 0.78) ** 2 + (ny - 0.18) ** 2 <= 0.075 ** 2:
        color = (255, 255, 255)
    return (color[0], color[1], color[2], alpha)


def main() -> None:
    data = build_ico([16, 32, 48])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data)} bytes)")
    preview = ROOT / ".tmp" / "favicon-preview.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    _png_file(64, preview)
    print(f"wrote {preview}")


if __name__ == "__main__":
    main()
