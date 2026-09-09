#!/bin/sh
# Host test for the drawing layer. Needs a C compiler and Python; no ESP-IDF,
# no hardware. Run from the project root:  sh tools/run_ui_test.sh
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
    out.append(f"const uint8_t font_{name}_bin[] = {{{','.join(str(b) for b in blob)}}};")
blob = (root / "assets" / "icons.bin").read_bytes()
out.append(f"const uint8_t icons_bin[] = {{{','.join(str(b) for b in blob)}}};")
(work / "blobs.c").write_text("\n".join(out))
PY

# _POSIX_C_SOURCE only for the host build: ESP-IDF compiles as gnu17 and has
# localtime_r without it, while a strict -std=c11 host build hides it.
cc -std=c11 -D_POSIX_C_SOURCE=200809L \
   -Wall -Wextra -Werror -DTEXT_HOST_TEST -DICON_HOST_TEST \
   -I"$root/main" \
   "$root/main/text.c" "$root/main/icons.c" "$root/main/status_bar.c" \
   "$root/main/header.c" "$root/main/card.c" "$root/main/dashboard_map.c" \
   "$root/main/history.c" "$root/main/settings.c" \
   "$root/tools/ui_test.c" "$work/blobs.c" \
   -o "$work/ui_test"
"$work/ui_test"
