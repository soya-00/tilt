#!/usr/bin/env python3
"""Render the Tilt app icon.

The icon is generated rather than committed as a binary blob so it stays
reviewable: the mark is described here in a dozen lines of geometry, and
regenerating it is one command. No image library is involved — PNG is a chunked
container around zlib-compressed scanlines, which is little enough code to write
directly and saves a dependency that exists only to draw one shape.

The mark: a dim neutral square, a single off-white bar leaning off vertical, and
one blue dot at its head. Leaning is the whole idea of the app, and the dot is
the one accent element the design language allows.

    python3 scripts/make_icons.py
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "apps/desktop/src-tauri/icons"

SS = 4
"""Supersampling factor. Antialiasing by averaging is crude but exact enough for
a mark made of three shapes, and it keeps this file free of a rasteriser."""

BACKDROP = (17, 17, 19)
BAR = (240, 240, 242)
ACCENT = (10, 132, 255)  # the one accent, matching the app's blue

PNG_SIZES = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
}

ICNS_TYPES = [("ic07", 128), ("ic09", 512), ("ic11", 32), ("ic12", 64), ("ic13", 256)]
"""macOS icon types that take embedded PNG payloads directly, so the .icns is a
container of the PNGs we already rendered rather than a separate encoder."""

ICO_SIZES = [16, 32, 48, 256]

TRAY_SIZES = {"tray.png": 22, "tray@2x.png": 44}
"""Menu bar template icons: the bar alone, solid black on transparency, which
macOS inverts for you in dark mode and dims when the bar is inactive."""


def _blend(under: tuple[int, ...], over: tuple[int, ...], a: float) -> tuple[int, ...]:
    return tuple(round(u + (o - u) * a) for u, o in zip(under, over, strict=True))


def _round_rect(x: float, y: float, w: float, r: float) -> float:
    """Signed distance to a rounded square of side ``w``, corner radius ``r``."""
    dx, dy = abs(x - w / 2) - (w / 2 - r), abs(y - w / 2) - (w / 2 - r)
    outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
    return outside + min(max(dx, dy), 0.0) - r


def _capsule(x: float, y: float, ax: float, ay: float, bx: float, by: float, r: float) -> float:
    """Signed distance to a line segment thickened into a capsule."""
    px, py = x - ax, y - ay
    vx, vy = bx - ax, by - ay
    t = 0.0 if (vx * vx + vy * vy) == 0 else (px * vx + py * vy) / (vx * vx + vy * vy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - vx * t, py - vy * t) - r


def _coverage(distance: float) -> float:
    """Hard edge — supersampling supplies the softening."""
    return 1.0 if distance <= 0 else 0.0


def render(size: int, *, template: bool = False) -> bytes:
    """Return raw RGBA rows for the mark at ``size`` pixels.

    ``template`` drops the backdrop and the accent, leaving the bar alone in
    solid black on transparency — the form macOS expects for a menu bar icon,
    which it recolours to match the bar and the current appearance.
    """
    n = size * SS
    u = n  # everything below is expressed as a fraction of the canvas

    # Geometry, in fractions of the icon: a bar leaning ~14° off vertical.
    lean = math.radians(20)
    # Standing alone in the menu bar the mark has no backdrop to sit inside, so
    # it grows to fill the space the rounded square would otherwise occupy.
    half = (0.38 if template else 0.28) * u
    cx, cy = 0.5 * u, (0.5 if template else 0.52) * u
    ax, ay = cx + math.sin(lean) * half, cy - math.cos(lean) * half  # head, leaning right
    bx, by = cx - math.sin(lean) * half, cy + math.cos(lean) * half
    bar_r = 0.072 * u
    dot_r = 0.085 * u
    corner = 0.235 * u

    rows = bytearray()
    for py in range(size):
        row = bytearray([0])  # PNG filter byte: none
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = px * SS + sx + 0.5
                    y = py * SS + sy + 0.5
                    if template:
                        # A menu bar mark is thinner and stands alone; the same
                        # weight as the app icon reads as a smudge at 16pt.
                        if _coverage(_capsule(x, y, ax, ay, bx, by, bar_r * 0.62)) == 0.0:
                            continue
                        acc[3] += 255.0
                        continue
                    if _coverage(_round_rect(x, y, u, corner)) == 0.0:
                        continue
                    colour: tuple[int, ...] = BACKDROP
                    colour = _blend(colour, BAR, _coverage(_capsule(x, y, ax, ay, bx, by, bar_r)))
                    colour = _blend(
                        colour, ACCENT, _coverage(math.hypot(x - ax, y - ay) - dot_r)
                    )
                    acc[0] += colour[0]
                    acc[1] += colour[1]
                    acc[2] += colour[2]
                    acc[3] += 255.0
            total = SS * SS
            a = acc[3] / total
            if a == 0:
                row += bytes(4)
            else:
                # Un-premultiply so partially covered edge pixels keep their hue.
                scale = total / (acc[3] / 255.0)
                row += bytes(
                    (
                        min(255, round(acc[0] * scale / total)),
                        min(255, round(acc[1] * scale / total)),
                        min(255, round(acc[2] * scale / total)),
                        round(a),
                    )
                )
        rows += row
    return bytes(rows)


def png(size: int, *, template: bool = False) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(render(size, template=template), 9))
        + chunk(b"IEND", b"")
    )


def icns(payloads: dict[int, bytes]) -> bytes:
    body = b"".join(
        kind.encode() + struct.pack(">I", len(payloads[size]) + 8) + payloads[size]
        for kind, size in ICNS_TYPES
    )
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def ico(payloads: dict[int, bytes]) -> bytes:
    """ICO with PNG-compressed entries — accepted since Windows Vista."""
    header = struct.pack("<HHH", 0, 1, len(ICO_SIZES))
    offset = len(header) + 16 * len(ICO_SIZES)
    directory, blobs = b"", b""
    for size in ICO_SIZES:
        data = payloads[size]
        directory += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        blobs += data
        offset += len(data)
    return header + directory + blobs


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    needed = sorted({*PNG_SIZES.values(), *(s for _, s in ICNS_TYPES), *ICO_SIZES})
    payloads = {}
    for size in needed:
        print(f"  rendering {size}×{size}", file=sys.stderr)
        payloads[size] = png(size)

    for name, size in PNG_SIZES.items():
        (OUT / name).write_bytes(payloads[size])
    (OUT / "icon.icns").write_bytes(icns(payloads))
    (OUT / "icon.ico").write_bytes(ico(payloads))

    for name, size in TRAY_SIZES.items():
        print(f"  rendering tray {size}×{size}", file=sys.stderr)
        (OUT / name).write_bytes(png(size, template=True))

    print(f"wrote {len(PNG_SIZES) + len(TRAY_SIZES) + 2} files to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
