#!/bin/sh
# Host test for the text renderer. Needs a C compiler and Python; no ESP-IDF,
# no hardware. Run from the project root:  sh tools/run_text_test.sh
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

python3 - "$root" "$work" <<'PY'
import sys, pathlib
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out = ["#include <stdint.h>"]
for name in ("title", "body", "preview"):
    blob = (root / "assets" / f"font_{name}.bin").read_bytes()
    body = ",".join(str(b) for b in blob)
    out.append(f"const uint8_t font_{name}_bin[] = {{{body}}};")
(work / "font_blobs.c").write_text("\n".join(out))
PY

cc -std=c11 -Wall -Wextra -Werror -DTEXT_HOST_TEST \
   -I"$root/main" \
   "$root/main/text.c" "$root/tools/text_test.c" "$work/font_blobs.c" \
   -o "$work/text_test"
"$work/text_test"
