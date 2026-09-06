"""Generate the monochrome icon atlas.

Icons are drawn as code rather than traced from a font or an SVG: at one bit
per pixel a symbol has to be laid out on the pixel grid deliberately, with
strokes of at least two pixels, or it greys out the way a hairline stem does.
Drawing them here keeps that decision reproducible.

Produces:

  assets/icons.bin     concatenated 1-bit bitmaps, MSB first, 1 = ink
  main/icon_data.h     the index: id order, offsets and sizes
  .work/icons.png      a contact sheet for visual review, not checked in

Run from the project root:  python tools/generate_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
HEADER = ROOT / "main" / "icon_data.h"
PREVIEW = ROOT / ".work" / "icons.png"

ART = 24      # art symbols in the card's side strip
SEVERITY = 16 # severity marks at the card's top right
STATUS = 20   # status bar glyphs
WIFI = 24     # arcs need a larger box to carry the same visual weight
BATTERY = 28  # the cell has to show a fill level, so it needs interior area:
              # at the 20 px status size the inside was 11 x 6 pixels and a
              # half-full cell was barely distinguishable from an empty one
STROKE = 2    # never thinner: a one pixel stroke reads grey

def new(size):
    image = Image.new("L", (size, size), 0)
    return image, ImageDraw.Draw(image)

# --- art symbols -----------------------------------------------------------

def generic(s):
    image, d = new(s)
    d.rounded_rectangle((2, 4, s - 3, s - 5), radius=3, outline=255, width=STROKE)
    return image

def microphone(s):
    image, d = new(s)
    d.rounded_rectangle((s // 2 - 4, 2, s // 2 + 4, 13), radius=4, fill=255)
    d.arc((s // 2 - 8, 6, s // 2 + 8, 18), start=0, end=180, fill=255, width=STROKE)
    d.line((s // 2, 18, s // 2, s - 3), fill=255, width=STROKE)
    d.line((s // 2 - 5, s - 3, s // 2 + 5, s - 3), fill=255, width=STROKE)
    return image

def recording(s):
    image, d = new(s)
    d.ellipse((4, 4, s - 5, s - 5), fill=255)
    return image

def session(s):
    """Waveform in a frame. The bars need a clear gap or the frame fills in."""
    image, d = new(s)
    d.rounded_rectangle((1, 4, s - 2, s - 5), radius=3, outline=255, width=STROKE)
    for index, height in enumerate((2, 5, 3, 6)):
        x = 6 + index * 4
        d.line((x, s // 2 - height, x, s // 2 + height), fill=255, width=STROKE)
    return image

def question(s):
    """A question mark needs room, so the ring stays thin and the hook large."""
    image, d = new(s)
    d.ellipse((0, 0, s - 1, s - 1), outline=255, width=STROKE)
    d.arc((6, 4, s - 7, 14), start=170, end=20, fill=255, width=STROKE)
    d.line((s - 8, 10, s // 2, 15), fill=255, width=STROKE)
    d.rectangle((s // 2 - 1, 17, s // 2 + 1, 19), fill=255)
    return image

def triangle(d, points):
    """polygon() only draws a one pixel outline, which greys out. Stroke the
    edges as lines instead so the frame keeps its weight."""
    d.line(list(points) + [points[0]], fill=255, width=STROKE, joint="curve")

def warning(s):
    image, d = new(s)
    triangle(d, [(s // 2, 2), (s - 3, s - 4), (3, s - 4)])
    d.line((s // 2, 10, s // 2, 15), fill=255, width=STROKE)
    d.rectangle((s // 2 - 1, 17, s // 2, 18), fill=255)
    return image

def task(s):
    image, d = new(s)
    d.rounded_rectangle((3, 3, s - 4, s - 4), radius=3, outline=255, width=STROKE)
    return image

def listing(s):
    image, d = new(s)
    for row in range(3):
        y = 5 + row * 6
        d.rectangle((3, y, 5, y + 2), fill=255)
        d.line((9, y + 1, s - 3, y + 1), fill=255, width=STROKE)
    return image

def note(s):
    image, d = new(s)
    d.polygon([(4, 2), (s - 7, 2), (s - 4, 6), (s - 4, s - 3), (4, s - 3)], outline=255)
    d.line((s - 7, 2, s - 7, 6), fill=255, width=1)
    d.line((s - 7, 6, s - 4, 6), fill=255, width=1)
    for row in range(3):
        y = 10 + row * 4
        d.line((7, y, s - 7, y), fill=255, width=1)
    return image

def fact(s):
    """A tag: pointed on the right, with the eyelet as a solid dot."""
    image, d = new(s)
    points = [(2, 4), (s - 8, 4), (s - 3, s // 2), (s - 8, s - 5), (2, s - 5)]
    d.line(points + [points[0]], fill=255, width=STROKE, joint="curve")
    d.ellipse((6, s // 2 - 3, 11, s // 2 + 2), fill=255)
    return image

def decision(s):
    """A fork whose taken branch is solid and whose alternative is dotted."""
    image, d = new(s)
    stem = s // 2
    d.line((stem, s - 3, stem, 14), fill=255, width=STROKE)
    d.line((stem, 14, s - 6, 7), fill=255, width=STROKE)   # taken branch
    d.line((stem, 14, 5, 7), fill=255, width=STROKE)       # alternative
    d.ellipse((s - 9, 2, s - 3, 8), fill=255)              # marked end
    d.ellipse((2, 2, 8, 8), outline=255, width=STROKE)     # open end
    return image

def topic(s):
    image, d = new(s)
    centre = (s // 2, s // 2)
    nodes = [(4, 5), (s - 5, 5), (4, s - 5), (s - 5, s - 5)]
    for node in nodes:
        d.line((centre[0], centre[1], node[0], node[1]), fill=255, width=1)
    d.ellipse((centre[0] - 3, centre[1] - 3, centre[0] + 3, centre[1] + 3), fill=255)
    for node in nodes:
        d.ellipse((node[0] - 2, node[1] - 2, node[0] + 2, node[1] + 2), fill=255)
    return image

def chat(s):
    image, d = new(s)
    d.rounded_rectangle((2, 3, s - 3, s - 8), radius=4, outline=255, width=STROKE)
    d.polygon([(7, s - 8), (7, s - 3), (13, s - 8)], fill=255)
    return image

def info(s):
    image, d = new(s)
    d.ellipse((1, 1, s - 2, s - 2), outline=255, width=STROKE)
    d.rectangle((s // 2 - 1, 6, s // 2 + 1, 8), fill=255)
    d.line((s // 2, 11, s // 2, s - 6), fill=255, width=STROKE)
    return image

# --- severity marks --------------------------------------------------------

def sev_info(s):
    image, d = new(s)
    d.ellipse((0, 0, s - 1, s - 1), outline=255, width=STROKE)
    d.rectangle((s // 2 - 1, 3, s // 2, 4), fill=255)
    d.line((s // 2 - 1, 6, s // 2 - 1, s - 4), fill=255, width=STROKE)
    return image

def sev_success(s):
    image, d = new(s)
    d.line((3, s // 2, s // 2 - 1, s - 4), fill=255, width=STROKE)
    d.line((s // 2 - 1, s - 4, s - 3, 3), fill=255, width=STROKE)
    return image

def sev_warning(s):
    image, d = new(s)
    triangle(d, [(s // 2, 0), (s - 2, s - 2), (1, s - 2)])
    d.line((s // 2 - 1, 6, s // 2 - 1, s - 7), fill=255, width=STROKE)
    d.rectangle((s // 2 - 2, s - 5, s // 2 - 1, s - 4), fill=255)
    return image

def sev_error(s):
    image, d = new(s)
    d.ellipse((0, 0, s - 1, s - 1), outline=255, width=STROKE)
    d.line((5, 5, s - 6, s - 6), fill=255, width=STROKE)
    d.line((s - 6, 5, 5, s - 6), fill=255, width=STROKE)
    return image

def sev_critical(s):
    image, d = new(s)
    step = s // 3
    d.polygon([(step, 0), (s - step - 1, 0), (s - 1, step), (s - 1, s - step - 1),
               (s - step - 1, s - 1), (step, s - 1), (0, s - step - 1), (0, step)], fill=255)
    d.line((5, 5, s - 6, s - 6), fill=0, width=STROKE)
    d.line((s - 6, 5, 5, s - 6), fill=0, width=STROKE)
    return image

# --- status bar and interface ---------------------------------------------

def wifi(s):
    """Drawn a little larger than the other status glyphs: three thin arcs read
    smaller than a closed shape of the same box, so at equal size the battery
    visually dominates it."""
    image, d = new(s)
    base = s - 4
    for radius in (11, 7, 4):
        d.arc((s // 2 - radius, base - radius, s // 2 + radius, base + radius),
              start=205, end=335, fill=255, width=STROKE)
    d.ellipse((s // 2 - 2, base - 2, s // 2 + 1, base + 1), fill=255)
    return image

def wifi_off(s):
    """The stroke is knocked out first so it stays visible over the arcs."""
    image = wifi(s)
    d = ImageDraw.Draw(image)
    d.line((1, s - 1, s - 1, 1), fill=0, width=STROKE + 2)
    d.line((1, s - 1, s - 1, 1), fill=255, width=STROKE)
    return image

def battery(s):
    image, d = new(s)
    d.rounded_rectangle((1, 5, s - 4, s - 6), radius=2, outline=255, width=STROKE)
    d.rectangle((s - 3, 8, s - 2, s - 9), fill=255)
    return image

def storage(s):
    image, d = new(s)
    d.rounded_rectangle((3, 2, s - 4, s - 3), radius=2, outline=255, width=STROKE)
    d.line((s - 7, 2, s - 7, 7), fill=255, width=STROKE)
    d.rectangle((6, s - 9, s - 7, s - 3), outline=255, width=1)
    return image

def queue(s):
    image, d = new(s)
    for row in range(3):
        y = 4 + row * 5
        d.line((3, y, s - 4, y), fill=255, width=STROKE)
    d.line((3, s - 4, s // 2, s - 4), fill=255, width=STROKE)
    return image

def offline(s):
    image, d = new(s)
    d.ellipse((2, 2, s - 3, s - 3), outline=255, width=STROKE)
    d.line((5, 5, s - 6, s - 6), fill=255, width=STROKE)
    return image

def menu(s):
    image, d = new(s)
    for index in range(3):
        x = 4 + index * 6
        d.ellipse((x, s // 2 - 2, x + 3, s // 2 + 1), fill=255)
    return image

ICONS = [
    ("generic", generic, ART), ("microphone", microphone, ART),
    ("recording", recording, ART), ("session", session, ART),
    ("question", question, ART), ("warning", warning, ART),
    ("task", task, ART), ("list", listing, ART), ("note", note, ART),
    ("fact", fact, ART), ("decision", decision, ART), ("topic", topic, ART),
    ("chat", chat, ART), ("info", info, ART),
    ("sev_info", sev_info, SEVERITY), ("sev_success", sev_success, SEVERITY),
    ("sev_warning", sev_warning, SEVERITY), ("sev_error", sev_error, SEVERITY),
    ("sev_critical", sev_critical, SEVERITY),
    ("wifi", wifi, WIFI), ("wifi_off", wifi_off, WIFI),
    ("battery", battery, BATTERY), ("storage", storage, STATUS),
    ("queue", queue, STATUS), ("offline", offline, STATUS),
    ("menu", menu, ART),
]

def pack(image, size):
    pixels = image.load()
    stride = (size + 7) // 8
    data = bytearray()
    for y in range(size):
        for byte in range(stride):
            value = 0
            for bit in range(8):
                x = byte * 8 + bit
                if x < size and pixels[x, y] >= 128:
                    value |= 0x80 >> bit
            data.append(value)
    return bytes(data)

def contact_sheet(images):
    scale, columns, cell = 4, 7, ART + 6
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("L", (columns * cell * scale, rows * (cell + 8) * scale), 255)
    draw = ImageDraw.Draw(sheet)
    for index, (name, image, size) in enumerate(images):
        column, row = index % columns, index // columns
        big = image.resize((size * scale, size * scale), Image.NEAREST)
        big = big.point(lambda value: 0 if value >= 128 else 255)
        x = column * cell * scale + 3 * scale
        y = row * (cell + 8) * scale + 3 * scale
        sheet.paste(big, (x, y))
        draw.text((x, y + (size + 3) * scale), name, fill=0)
    return sheet

def main():
    ASSETS.mkdir(exist_ok=True)
    PREVIEW.parent.mkdir(exist_ok=True)
    blob = bytearray()
    entries = []
    rendered = []
    for name, function, size in ICONS:
        image = function(size)
        rendered.append((name, image, size))
        entries.append((name, len(blob), size))
        blob += pack(image, size)
    (ASSETS / "icons.bin").write_bytes(bytes(blob))

    with HEADER.open("w", encoding="utf-8") as handle:
        handle.write("/* Generated by tools/generate_icons.py. Do not edit. */\n")
        handle.write("#pragma once\n#include <stdint.h>\n\n")
        handle.write("typedef enum {\n")
        for name, _, _ in entries:
            handle.write(f"    ICON_{name.upper()},\n")
        handle.write("    ICON_COUNT\n} icon_id;\n\n")
        handle.write("typedef struct { uint16_t offset; uint8_t size; } icon_entry;\n")
        handle.write("static const icon_entry icon_entries[ICON_COUNT] = {\n")
        for name, offset, size in entries:
            handle.write(f"    {{{offset}, {size}}}, /* {name} */\n")
        handle.write("};\n")

    contact_sheet(rendered).save(PREVIEW)
    print(f"icons.bin  {len(blob)} bytes  {len(entries)} icons")
    print(f"{HEADER.relative_to(ROOT)} written")
    print(f"{PREVIEW.relative_to(ROOT)} written for review")

if __name__ == "__main__":
    main()
