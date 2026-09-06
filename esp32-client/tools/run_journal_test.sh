#!/bin/sh
# Host test for the journal and recovery logic. No ESP-IDF, no hardware.
# Run from the project root:  sh tools/run_journal_test.sh
set -e
BIN="${TMPDIR:-/tmp}/journal_test_bin"
${CC:-gcc} -std=c11 -D_DEFAULT_SOURCE -Wall -Wextra -Wno-unused-parameter -O1 \
    -fsanitize=address,undefined \
    -o "$BIN" tools/journal_test.c main/journal.c
"$BIN"
