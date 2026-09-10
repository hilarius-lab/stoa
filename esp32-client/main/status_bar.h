#pragma once
// The top bar: local truth only.
//
// Nothing here comes from a dashboard snapshot, and a snapshot must never
// overwrite it. Every value is either measured on the device or explicitly
// marked unknown; the bar shows a placeholder rather than a plausible-looking
// number, because a wrong clock or battery reading is worse than a visibly
// missing one.
#include <stdbool.h>
#include <stddef.h>

#define STATUS_BAR_HEIGHT 48

typedef struct {
    /* Local clock/date. Invalid until trustworthy SNTP sync; placeholder only. */
    bool time_valid;
    int hour, minute;
    unsigned day, month, year;

    bool wifi_connected;
    bool recording;

    /* Local queue, from memo_queue. */
    unsigned queue_ready;
    unsigned queue_attention;

    bool storage_low;   /* warn, recording continues */
    bool storage_block; /* refuse to start a new recording */

    /* A read-only value from the board's AXP2101/TG28-compatible power
     * controller. Failed, absent or implausible samples stay unknown: an empty
     * outline would claim an empty battery, which is a different statement. */
    bool battery_known;
    unsigned battery_percent;
    bool battery_charging;
} status_state;

/* Draw the bar across the top of the logical canvas. */
void status_bar_draw(unsigned char *canvas, const status_state *state);

/* User-facing compact local date, deliberately without leading zeroes on day
 * and month: 2.4.03, 23.5.24, 12.10.89. */
bool status_bar_format_date(char *out, size_t capacity,
                            unsigned day, unsigned month, unsigned year);
