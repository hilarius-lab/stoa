#pragma once
/* Host-test-only compatibility shim, forced in via `-include` from
 * run_journal_test.sh. It exists so journal_test.c and main/journal.c compile
 * unmodified on the native mingw toolchain used on this Windows dev machine,
 * which has no `fsync()` (the POSIX call ESP-IDF's newlib VFS layer provides
 * on-device) but does have the CRT equivalent `_commit()`. On a POSIX host
 * (Linux, macOS, WSL) this file changes nothing. */
#ifdef _WIN32
#include <io.h>
#define fsync _commit
#endif
