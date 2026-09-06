#pragma once
// The top bar: local truth only.
//
// Nothing here comes from a dashboard snapshot, and a snapshot must never
// overwrite it. Every value is either measured on the device or explicitly
// marked unknown; the bar shows a placeholder rather than a plausible-looking
// number, because a wrong clock or battery reading is worse than a visibly
// missing one.
#include <stdbool.h>

#define STATUS_BAR_HEIGHT 48

typedef struct {
    /* Clock. Invalid until a trustworthy SNTP sync; shown as a placeholder. */
    bool time_valid;
    int hour, minute;

    bool wifi_connected;
    bool recording;

    /* Local queue, from memo_queue. */
    unsigned queue_ready;
    unsigned queue_attention;

    bool storage_low;   /* warn, recording continues */
    bool storage_block; /* refuse to start a new recording */

    /* Battery stays unknown until the TG28 power management chip is read
     * against verified documentation; see the roadmap. Until then the cell is
     * rastered rather than left empty: an empty outline would claim an empty
     * battery, which is a different statement from "not measured". */
    bool battery_known;
    unsigned battery_percent;
} status_state;

/* Draw the bar across the top of the logical canvas. */
void status_bar_draw(unsigned char *canvas, const status_state *state);
