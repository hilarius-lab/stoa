#!/bin/sh
# Host test for the journal and recovery logic. No ESP-IDF, no hardware.
# Run from the project root:  sh tools/run_journal_test.sh
set -e
BIN="${TMPDIR:-/tmp}/journal_test_bin"
CC=${CC:-gcc}
FLAGS="-std=c11 -D_DEFAULT_SOURCE -Wall -Wextra -Wno-unused-parameter -O1 -include tools/host_compat.h"
SRC="tools/journal_test.c main/journal.c"
# ASan/UBSan runtime libraries are not part of every mingw-w64 toolchain (this
# is the only reason the fallback exists; the sanitized build is otherwise
# preferred and used whenever it links).
if ! $CC $FLAGS -fsanitize=address,undefined -o "$BIN" $SRC 2>/dev/null; then
    echo "sanitizer runtime unavailable on this toolchain; building without it" >&2
    $CC $FLAGS -o "$BIN" $SRC
fi
"$BIN"
