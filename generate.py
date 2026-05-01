#!/usr/bin/env python3
"""Generate HiDPI PNGs from CDE/Motif backdrop .pm files with optional palette colorization."""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCALES = [2, 4, 8]

# --- Motif/CDE color derivation (ported from NsCDE palette_colorgen.in) ---

XmMAX_SHORT = 65535
XmRED_LUMINOSITY = 0.30
XmGREEN_LUMINOSITY = 0.59
XmBLUE_LUMINOSITY = 0.11
XmINTENSITY_FACTOR = 75
XmLIGHT_FACTOR = 0
XmLUMINOSITY_FACTOR = 25
XmCOLOR_PERCENTILE = XmMAX_SHORT / 100

XmCOLOR_DARK_THRESHOLD = 20 * XmCOLOR_PERCENTILE
XmCOLOR_LITE_THRESHOLD = 93 * XmCOLOR_PERCENTILE
XmFOREGROUND_THRESHOLD = 70 * XmCOLOR_PERCENTILE

FACTORS = {
    "dark": {"sel": 15, "bs": 30, "ts": 50},
    "light": {"sel": 15, "bs": 40, "ts": 20},
    "medium_lo": {"sel": 15, "bs": 60, "ts": 50},
    "medium_hi": {"sel": 15, "bs": 40, "ts": 60},
}


def brightness(rgb_16bit: list[int]) -> float:
    r, g, b = rgb_16bit
    intensity = (r + g + b) / 3.0
    luminosity = XmRED_LUMINOSITY * r + XmGREEN_LUMINOSITY * g + XmBLUE_LUMINOSITY * b
    light = (min(r, g, b) + max(r, g, b)) / 2.0
    return (intensity * XmINTENSITY_FACTOR + light * XmLIGHT_FACTOR + luminosity * XmLUMINOSITY_FACTOR) / 100.0


def derive_fg(bg_16bit: list[int]) -> list[int]:
    if brightness(bg_16bit) > XmFOREGROUND_THRESHOLD:
        return [0, 0, 0]
    return [XmMAX_SHORT] * 3


def apply_factor_darken(channel: float, factor: float) -> int:
    return int(channel - (channel * factor) / 100.0)


def apply_factor_lighten(channel: float, factor: float) -> int:
    return int(channel + factor * (XmMAX_SHORT - channel) / 100.0)


def derive_colors(bg_hex_16bit: str) -> dict[str, str]:
    rgb = parse_hex_to_16bit(bg_hex_16bit)
    b = brightness(rgb)

    fg = derive_fg(rgb)

    if b < XmCOLOR_DARK_THRESHOLD:
        f = FACTORS["dark"]
        sel = [apply_factor_lighten(c, f["sel"]) for c in rgb]
        bs = [apply_factor_lighten(c, f["bs"]) for c in rgb]
        ts = [apply_factor_lighten(c, f["ts"]) for c in rgb]
    elif b > XmCOLOR_LITE_THRESHOLD:
        f = FACTORS["light"]
        sel = [apply_factor_darken(c, f["sel"]) for c in rgb]
        bs = [apply_factor_darken(c, f["bs"]) for c in rgb]
        ts = [apply_factor_darken(c, f["ts"]) for c in rgb]
    else:
        lo, hi = FACTORS["medium_lo"], FACTORS["medium_hi"]
        sel_f = lo["sel"] + (b * (hi["sel"] - lo["sel"]) / XmMAX_SHORT)
        bs_f = lo["bs"] + (b * (hi["bs"] - lo["bs"]) / XmMAX_SHORT)
        ts_f = lo["ts"] + (b * (hi["ts"] - lo["ts"]) / XmMAX_SHORT)
        sel = [apply_factor_darken(c, sel_f) for c in rgb]
        bs = [apply_factor_darken(c, bs_f) for c in rgb]
        ts = [apply_factor_lighten(c, ts_f) for c in rgb]

    return {
        "background": bg_hex_16bit,
        "foreground": rgb16_to_hex(fg),
        "topShadowColor": rgb16_to_hex(ts),
        "bottomShadowColor": rgb16_to_hex(bs),
        "selectColor": rgb16_to_hex(sel),
    }


# --- Color format helpers ---

def parse_hex_to_16bit(hex_color: str) -> list[int]:
    h = hex_color.lstrip("#")
    if len(h) == 12:
        return [int(h[i:i+4], 16) for i in (0, 4, 8)]
    if len(h) == 6:
        return [int(h[i:i+2], 16) * 257 for i in (0, 2, 4)]
    return [0, 0, 0]


def rgb16_to_hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{max(0, min(65535, int(c))):04x}" for c in rgb)


def hex16_to_rgb8(hex_color: str) -> tuple[int, int, int]:
    rgb = parse_hex_to_16bit(hex_color)
    return (rgb[0] >> 8, rgb[1] >> 8, rgb[2] >> 8)


# --- Palette ---

def read_palette(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip().startswith("#")]


def get_slot_colors(palette_path: str, slot: int) -> dict[str, str]:
    palette = read_palette(palette_path)
    if slot < 1 or slot > len(palette):
        raise ValueError(f"Slot {slot} out of range (palette has {len(palette)} colors)")
    base_color = palette[slot - 1]
    if len(base_color.lstrip("#")) == 6:
        base_color = "#" + "".join(c * 2 for c in re.findall("..", base_color.lstrip("#")))
    return derive_colors(base_color)


# --- XPM parsing ---

def parse_xpm(filepath: str, color_overrides: dict[str, str] | None = None) -> Image.Image:
    with open(filepath) as f:
        content = f.read()

    strings = re.findall(r'"([^"]*)"', content)
    header = strings[0].split()
    width, height, ncolors, cpp = int(header[0]), int(header[1]), int(header[2]), int(header[3])

    colors = {}
    for i in range(1, ncolors + 1):
        line = strings[i]
        char = line[:cpp]
        rest = line[cpp:]

        sym_match = re.search(r'\bs\s+(\S+)', rest)
        sym_name = sym_match.group(1) if sym_match else None

        if color_overrides and sym_name and sym_name in color_overrides:
            colors[char] = hex16_to_rgb8(color_overrides[sym_name])
        else:
            c_match = re.search(r'\bc\s+(#[0-9a-fA-F]+)', rest)
            if c_match:
                colors[char] = hex16_to_rgb8(c_match.group(1))
            else:
                colors[char] = (128, 128, 128)

    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y, row_str in enumerate(strings[ncolors + 1 : ncolors + 1 + height]):
        for x in range(width):
            pixels[x, y] = colors.get(row_str[x * cpp : (x + 1) * cpp], (0, 0, 0))
    return img


# --- Scale2x upscaling ---

def scalex(input_png: str, output_png: str, factor: int) -> None:
    subprocess.run(
        ["scalex", "-k", str(factor), input_png, output_png],
        capture_output=True, text=True, check=True,
    )


def upscale(source_png: str, output_dir: str, basename: str, scales: list[int]) -> dict[int, str]:
    results = {}
    for scale in scales:
        out = os.path.join(output_dir, f"{basename}_{scale}x.png")
        if scale == 2:
            scalex(source_png, out, 2)
        elif scale == 4:
            scalex(source_png, out, 4)
        elif scale == 8:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                scalex(source_png, tmp_path, 4)
                scalex(tmp_path, out, 2)
            finally:
                os.unlink(tmp_path)
        results[scale] = out
    return results


# --- Tiled preview ---

def tile_preview(tile_path: str, output_path: str, size: tuple[int, int] = (3840, 2160)) -> None:
    tile = Image.open(tile_path)
    tw, th = tile.size
    desktop = Image.new("RGB", size)
    for y in range(0, size[1], th):
        for x in range(0, size[0], tw):
            desktop.paste(tile, (x, y))
    desktop.save(output_path, "PNG", optimize=True)


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Upscale CDE backdrop .pm files to HiDPI PNGs")
    parser.add_argument("files", nargs="+", help=".pm backdrop files")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument("-p", "--palette", help="palette .dp file")
    parser.add_argument("-s", "--slot", type=int, default=3, help="palette color slot 1-8 (default: 3)")
    parser.add_argument("--scale", type=int, choices=SCALES, help="single scale (default: all)")
    parser.add_argument("--preview", action="store_true", help="generate tiled 4K desktop previews")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    scales = [args.scale] if args.scale else SCALES
    color_overrides = get_slot_colors(args.palette, args.slot) if args.palette else None
    palette_tag = f"_{Path(args.palette).stem}_s{args.slot}" if args.palette else ""

    for filepath in args.files:
        name = Path(filepath).stem
        basename = f"{name}{palette_tag}"
        print(f"{name}: ", end="", flush=True)

        img = parse_xpm(filepath, color_overrides)
        source_png = os.path.join(args.output, f"{basename}_1x.png")
        img.save(source_png, "PNG")

        results = upscale(source_png, args.output, basename, scales)
        for s, path in sorted(results.items()):
            sz = Image.open(path).size
            print(f"{s}x({sz[0]}x{sz[1]}) ", end="", flush=True)

        if args.preview:
            for label, path in [("1x", source_png)] + [(f"{s}x", p) for s, p in sorted(results.items())]:
                preview = os.path.join(args.output, f"{basename}_preview_{label}.png")
                tile_preview(path, preview)
            print("+ previews", end="")
        print()

    print(f"Output: {args.output}/")


if __name__ == "__main__":
    main()
