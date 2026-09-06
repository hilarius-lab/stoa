"""Generate the monochrome glyph atlases for on-device text rendering.

Produces two artefacts per cut (title, body, preview):

  assets/font_<name>.bin   concatenated 1-bit glyph bitmaps, MSB first,
                           each row padded to a byte boundary, 1 = ink
  main/font_data.h         codepoint index, metrics and per-cut metadata

The device never parses a font file. It looks a codepoint up in the generated
index and blits the bitmap, so the runtime stays free of font machinery.

Two corrections are applied because the panel has one bit per pixel:

  * hairline repair -- any horizontal ink run of a single pixel grows to two,
    so stems that threshold unevenly stop reading lighter than their
    neighbours. Applied per run, never to strokes that already have body, and
    never where it would close a counter.
  * condensing -- the bold title cut is scaled horizontally before
    thresholding, which tightens a wide face without changing its height.

Run from the project root:  python tools/generate_font.py
Optional:  --regular PATH --bold PATH   to pin the source faces,
           --title-condense 0.92, --title-tracking -1, --tracking 0,
           --no-repair.
"""
from pathlib import Path
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
HEADER = ROOT / "main" / "font_data.h"

# Threshold for turning the antialiased render into one bit. Rendering with
# antialiasing and thresholding afterwards keeps stems more even than asking
# FreeType for a pure 1-bit render.
THRESHOLD = 128

REPLACEMENT = 0xFFFD

def repertoire():
    """Codepoints the device can display. Anything else becomes REPLACEMENT."""
    points = list(range(0x20, 0x7F))                       # ASCII incl. punctuation
    points += [0x00A0]                                     # no-break space
    points += [0x00C4, 0x00D6, 0x00DC, 0x00E4, 0x00F6, 0x00FC, 0x00DF]  # German
    points += [0x00C0, 0x00C1, 0x00C2, 0x00C7, 0x00C8, 0x00C9, 0x00CA,
               0x00CD, 0x00CE, 0x00D1, 0x00D3, 0x00D4, 0x00DA, 0x00DB,
               0x00E0, 0x00E1, 0x00E2, 0x00E7, 0x00E8, 0x00E9, 0x00EA,
               0x00ED, 0x00EE, 0x00F1, 0x00F3, 0x00F4, 0x00FA, 0x00FB]  # names
    points += [0x00B0, 0x00B7, 0x00AB, 0x00BB, 0x20AC]     # degree, middot, guillemets, euro
    points += [0x2013, 0x2014,                             # en dash, em dash
               0x2018, 0x2019, 0x201A,                     # single quotes
               0x201C, 0x201D, 0x201E,                     # double quotes
               0x2022, 0x2026]                             # bullet, ellipsis
    points += [REPLACEMENT]
    return sorted(set(points))

def discover(explicit, candidates, what):
    if explicit:
        return Path(explicit)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    sys.exit(
        f"No {what} face found. Pass --{what} PATH.\n"
        "DejaVu Sans is the intended source; it ships with matplotlib and with\n"
        "most Linux distributions, and its licence permits redistribution of the\n"
        "generated bitmaps. See THIRD_PARTY.md."
    )

def bundled(name):
    try:
        import matplotlib
    except ImportError:
        return None
    return Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf" / name

def faces(args):
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    regular = discover(args.regular, [
        bundled("DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        windows / "segoeui.ttf",
    ], "regular")
    bold = discover(args.bold, [
        bundled("DejaVuSans-Bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        windows / "segoeuib.ttf",
    ], "bold")
    for path in (regular, bold):
        if "segoe" in path.name.lower():
            print(f"WARNING: {path.name} is a Microsoft face. Its glyph bitmaps may "
                  "not be redistributable in firmware. Use DejaVu Sans for releases.")
    return regular, bold

def repair_hairlines(bits, width, height):
    """Grow every horizontal ink run of a single pixel to two.

    At one bit per pixel a stem that thresholds to one pixel in some rows and
    two in others reads visibly lighter than its neighbours; `h`, `k`, `n`, `r`,
    `D`, `R` and `f` are the usual victims. The repair works per run, not per
    glyph, so strokes that already have body stay untouched.

    A run only grows into space that is empty on both sides of the new pixel,
    which keeps it from closing a counter or merging with the neighbouring stem
    of an `m` or `n`.
    """
    out = [row[:] for row in bits]
    for y in range(height):
        row = bits[y]
        x = 0
        while x < width:
            if not row[x]:
                x += 1
                continue
            start = x
            while x < width and row[x]:
                x += 1
            if x - start != 1:
                continue
            here = start
            right_free = here + 1 < width and not row[here + 1] and (here + 2 >= width or not row[here + 2])
            left_free = here - 1 >= 0 and not row[here - 1] and (here - 2 < 0 or not row[here - 2])
            if right_free:
                out[y][here + 1] = True
            elif left_free:
                out[y][here - 1] = True
    return out

def render(face, size, points, condense=1.0, repair=True, tracking=0):
    """Render every codepoint once and return glyph records plus the blob.

    `condense` scales glyphs horizontally before thresholding, which tightens a
    wide face without touching its vertical proportions. `repair` fixes hairline
    runs afterwards, so condensing cannot thin a stem out. `tracking` adjusts
    every advance; negative values set the text tighter."""
    font = ImageFont.truetype(str(face), size)
    ascent, descent = font.getmetrics()
    blob = bytearray()
    glyphs = []
    for point in points:
        character = chr(point)
        advance = int(round(font.getlength(character)))
        if point == REPLACEMENT:
            # Drawn by hand: a hollow box, so an unmappable codepoint is visible
            # rather than silently dropped.
            width = max(4, int(size * 0.5))
            height = int(size * 0.62)
            image = Image.new("L", (width, height), 0)
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, width - 1, height - 1), outline=255, width=1)
            left, top, advance = 0, height, width + 2
            image_grey = image
        else:
            box = font.getbbox(character)
            if box is None or box[2] <= box[0] or box[3] <= box[1]:
                glyphs.append((point, 0, 0, 0, 0, 0, advance))
                continue
            left, top = box[0], box[1]
            width, height = box[2] - box[0], box[3] - box[1]
            image = Image.new("L", (width, height), 0)
            ImageDraw.Draw(image).text((-left, -top), character, font=font, fill=255)
            # `top` is measured from the text origin downwards; the device wants
            # the offset from the line box top, which is what PIL already gives.
            top = box[1]
            image_grey = image
            if condense != 1.0 and width > 0:
                narrow = max(1, int(round(width * condense)))
                image_grey = image.resize((narrow, height), Image.LANCZOS)
                width = narrow
                left = int(round(left * condense))
                advance = max(1, int(round(advance * condense)))

        pixels = image_grey.load()
        bits = [[pixels[x, y] >= THRESHOLD for x in range(width)] for y in range(height)]
        if repair and width and height:
            bits = repair_hairlines(bits, width, height)
        advance = max(1, advance + tracking)

        stride = (width + 7) // 8
        offset = len(blob)
        for y in range(height):
            for byte in range(stride):
                value = 0
                for bit in range(8):
                    x = byte * 8 + bit
                    if x < width and bits[y][x]:
                        value |= 0x80 >> bit
                blob.append(value)
        glyphs.append((point, offset, width, height, left, top, advance))
    line_height = ascent + descent
    return glyphs, bytes(blob), line_height, ascent

def emit(handle, name, glyphs, line_height, ascent, size, face):
    handle.write(f"\n/* {name}: {face.name} at {size} px, {len(glyphs)} glyphs. */\n")
    handle.write(f"#define FONT_{name.upper()}_COUNT {len(glyphs)}\n")
    handle.write(f"#define FONT_{name.upper()}_LINE {line_height}\n")
    handle.write(f"#define FONT_{name.upper()}_ASCENT {ascent}\n")
    handle.write(f"static const font_glyph font_{name}_glyphs[] = {{\n")
    for point, offset, width, height, left, top, advance in glyphs:
        handle.write(f"    {{0x{point:04X}, {offset}, {width}, {height}, "
                     f"{left}, {top}, {advance}}},\n")
    handle.write("};\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regular")
    parser.add_argument("--bold")
    parser.add_argument("--title-size", type=int, default=20)
    parser.add_argument("--body-size", type=int, default=18)
    parser.add_argument("--preview-size", type=int, default=16)
    parser.add_argument("--title-condense", type=float, default=0.92,
                        help="horizontal scale for the bold title cut")
    parser.add_argument("--title-tracking", type=int, default=-1,
                        help="advance adjustment for the title cut")
    parser.add_argument("--tracking", type=int, default=0,
                        help="advance adjustment for body and preview")
    parser.add_argument("--no-repair", action="store_true",
                        help="skip the hairline run repair")
    args = parser.parse_args()

    regular, bold = faces(args)
    points = repertoire()
    ASSETS.mkdir(exist_ok=True)

    # 16 px regular is the measured legibility floor on this panel: below it the
    # stems of DejaVu Sans regular drop under two pixels and the text greys out.
    # A smaller cut therefore has to come from the bold face, not from a smaller
    # regular one. See docs/IMPLEMENTATION_DECISIONS.md.
    cuts = [("title", bold, args.title_size, args.title_condense, args.title_tracking),
            ("body", regular, args.body_size, 1.0, args.tracking),
            ("preview", regular, args.preview_size, 1.0, args.tracking)]
    rendered = []
    for name, face, size, condense, tracking in cuts:
        glyphs, blob, line_height, ascent = render(
            face, size, points, condense=condense,
            repair=not args.no_repair, tracking=tracking)
        (ASSETS / f"font_{name}.bin").write_bytes(blob)
        rendered.append((name, glyphs, line_height, ascent, size, face, len(blob)))
        print(f"font_{name}.bin  {len(blob)} bytes  {len(glyphs)} glyphs  "
              f"line {line_height} px  condense {condense:.2f}  tracking {tracking:+d}  "
              f"from {face.name}")

    with HEADER.open("w", encoding="utf-8") as handle:
        handle.write("/* Generated by tools/generate_font.py. Do not edit. */\n")
        handle.write("#pragma once\n#include <stdint.h>\n\n")
        handle.write("typedef struct {\n"
                     "    uint16_t codepoint;\n"
                     "    uint32_t offset;   /* byte offset into the atlas blob */\n"
                     "    uint8_t  width;    /* bitmap width in pixels */\n"
                     "    uint8_t  height;   /* bitmap rows */\n"
                     "    int8_t   left;     /* horizontal bearing */\n"
                     "    int8_t   top;      /* offset from the line box top */\n"
                     "    uint8_t  advance;  /* pen advance */\n"
                     "} font_glyph;\n")
        handle.write(f"\n#define FONT_REPLACEMENT 0x{REPLACEMENT:04X}\n")
        for name, glyphs, line_height, ascent, size, face, _ in rendered:
            emit(handle, name, glyphs, line_height, ascent, size, face)
    print(f"{HEADER.relative_to(ROOT)} written")

if __name__ == "__main__":
    main()
