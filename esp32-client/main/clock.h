#pragma once
// Wall clock time. Everything the device shows as a time of day comes from
// here, and nothing shows one before this module says the clock is trustworthy.
//
// Monotone time is a separate matter and stays untouched: audio timestamps,
// snapshot ages and refresh intervals are all measured against `esp_timer` and
// keep working whether or not the clock was ever synchronised.
#include <stdbool.h>

/* Start SNTP and apply the display timezone. Safe to call once at boot; the
 * actual synchronisation happens when the network comes up. */
void clock_start(void);

/* Tell the clock the station has an address. Synchronisation is attempted on
 * every join, because a device that was off for a week has a useless clock even
 * though it once had a good one. */
void clock_network_up(void);

/* True once a plausible synchronisation happened. Until then every caller must
 * treat the wall clock as unknown rather than as an approximation. */
bool clock_ready(void);

/* Value passed to the screen before the first synchronisation. */
#define CLOCK_TIME_UNKNOWN 0xFFFFFFFFu
