"""Pack an arbitrary source image into this project's monochrome panel asset
format: 800x480 landscape, 1 bit per pixel, MSB-first, row-packed.

Unlike generate_h3_assets.py (which draws the startup screens from scratch
with PIL), this takes a real PNG (or anything Pillow can open) someone
designed or downloaded and fits it to the panel without inventing content.

Every screen in this project is authored portrait (480 wide x 800 tall, the
natural way to design a phone-shaped notebook screen) and only rotated to the
panel's actual 800x480 landscape wiring at the very end — see blank()/
startup() in generate_h3_assets.py. A source image is fit against that same
480x800 portrait canvas, not the final landscape one, so a portrait design
(the common case) lands close to full-bleed instead of shrinking into a
narrow strip between wide white bars. It is letterboxed rather than
stretched, so a source with a different aspect ratio keeps its proportions;
converting to mode "1" dithers it to black/white, which tends to read better
on e-paper than a hard threshold.

Usage, from esp32-client/:
    ..\\.venv\\Scripts\\python.exe tools\\pack_image_asset.py path\\to\\source.png --name sleep

Writes assets/<name>.png (the exact fitted, dithered, rotated image that
will be shown — check this before flashing) and assets/<name>.bin (what
gets embedded). Register the new name in main/CMakeLists.txt's EMBED_FILES
and wire an extern symbol/screen_state in main/screen.c, the same way
sleep.bin already is.
"""
import argparse
from pathlib import Path
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "assets"
PORTRAIT_W, PORTRAIT_H = 480, 800  # Design canvas, matching every other screen.
PANEL_W, PANEL_H = 800, 480        # Final packed orientation, after rotation.


def fit_portrait(image):
    fitted = Image.new("L", (PORTRAIT_W, PORTRAIT_H), 255)
    scale = min(PORTRAIT_W / image.width, PORTRAIT_H / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    resized = image.convert("L").resize(size, Image.LANCZOS)
    fitted.paste(resized, ((PORTRAIT_W - size[0]) // 2, (PORTRAIT_H - size[1]) // 2))
    return fitted


def packed(image):
    pixels = image.load()
    result = bytearray()
    for y in range(PANEL_H):
        for bx in range(PANEL_W // 8):
            value = 0
            for bit in range(8):
                if pixels[bx * 8 + bit, y]:
                    value |= 0x80 >> bit
            result.append(value)
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source image (PNG or anything Pillow reads)")
    parser.add_argument("--name", default="sleep", help="Asset name; writes assets/<name>.png and .bin")
    args = parser.parse_args()

    source = Image.open(args.source)
    fitted = fit_portrait(source).rotate(90, expand=True)
    assert fitted.size == (PANEL_W, PANEL_H), fitted.size
    dithered = fitted.convert("1")  # Floyd-Steinberg by default.
    OUT.mkdir(exist_ok=True)
    dithered.save(OUT / f"{args.name}.png")
    (OUT / f"{args.name}.bin").write_bytes(packed(dithered))
    print(f"{args.name}: wrote {OUT / f'{args.name}.png'} and {OUT / f'{args.name}.bin'} "
          f"({PANEL_W}x{PANEL_H}, {PANEL_W * PANEL_H // 8} bytes)")


if __name__ == "__main__":
    main()
