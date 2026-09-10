#include <stdio.h>
#include <string.h>
#include "status_bar.h"
#include "icons.h"
#include "text.h"

#define CANVAS_WIDTH 480
#define MARGIN 12
#define ICON_CENTRE 24   /* icons are centred on this line, whatever their size */
#define ICON_TOP 14      /* top of a 20 px glyph on that centre line */
#define TEXT_TOP 13      /* body cut: 18 px on a 22 px line */
#define GAP 8

/* Right-to-left packing: every element reports the width it consumed, and the
 * pen walks left. Elements that have nothing to say consume nothing, so the bar
 * stays quiet when the device is idle and healthy. */
static int place_icon(unsigned char *canvas, icon_id id, int right) {
    int size = icon_size(id);
    icon_draw(canvas, id, right - size, ICON_CENTRE - size / 2, false);
    return size;
}

static int place_text(unsigned char *canvas, const char *utf8, int right) {
    int width = text_measure(&text_font_preview, utf8, strlen(utf8));
    text_draw(canvas, &text_font_preview, right - width, TEXT_TOP + 2,
              utf8, strlen(utf8));
    return width;
}

static void draw_charge_mark(unsigned char *canvas, int left, int top) {
    /* A two-pixel-weight lightning mark on a white plate. Keeping the percent
     * beside the cell preserves the measured level while the cell itself now
     * communicates the changing state. */
    icon_plate(canvas, left, top, 19, 14);
    icon_fill(canvas, left + 10, top,      4, 2, STRIP_SOLID);
    icon_fill(canvas, left + 8,  top + 2,  5, 2, STRIP_SOLID);
    icon_fill(canvas, left + 6,  top + 4,  9, 2, STRIP_SOLID);
    icon_fill(canvas, left + 10, top + 6,  5, 2, STRIP_SOLID);
    icon_fill(canvas, left + 9,  top + 8,  4, 2, STRIP_SOLID);
    icon_fill(canvas, left + 8,  top + 10, 4, 2, STRIP_SOLID);
    icon_fill(canvas, left + 7,  top + 12, 3, 2, STRIP_SOLID);
}

bool status_bar_format_date(char *out, size_t capacity,
                            unsigned day, unsigned month, unsigned year) {
    if (!out || !capacity) return false;
    out[0] = 0;
    if (day < 1 || day > 31 || month < 1 || month > 12) return false;
    int written = snprintf(out, capacity, "%u.%u.%02u", day, month, year % 100);
    return written > 0 && (size_t)written < capacity;
}

void status_bar_draw(unsigned char *canvas, const status_state *state) {
    char buffer[16];

    /* Clock on the left. A missing sync is shown, not hidden. */
    if (state->time_valid)
        snprintf(buffer, sizeof(buffer), "%02d:%02d", state->hour, state->minute);
    else
        snprintf(buffer, sizeof(buffer), "--:--");
    text_draw(canvas, &text_font_body, MARGIN, TEXT_TOP, buffer, strlen(buffer));
    int clock_right = MARGIN + text_measure(&text_font_body, buffer, strlen(buffer));
    if (state->time_valid && status_bar_format_date(
            buffer, sizeof(buffer), state->day, state->month, state->year)) {
        int date_left = clock_right + GAP;
        text_draw(canvas, &text_font_body, date_left, TEXT_TOP,
                  buffer, strlen(buffer));
        clock_right = date_left + text_measure(&text_font_body, buffer, strlen(buffer));
    }

    /* Recording is the one state that earns a mark next to the clock, because
     * it is the only one the user can change by holding a button. */
    if (state->recording) {
        int left = clock_right + GAP + 4;
        icon_draw(canvas, ICON_RECORDING, left, ICON_TOP + 2, false);
    }

    int pen = CANVAS_WIDTH - MARGIN;

    /* Battery first from the right, as on a phone. */
    int battery_size = icon_size(ICON_BATTERY);
    int battery_left = pen - battery_size;
    pen -= place_icon(canvas, ICON_BATTERY, pen);
    {
        /* The interior of the cell, derived from the shape the generator draws:
         * a rounded rectangle from (1,5) to (size-4,size-6) with a two pixel
         * stroke, which leaves x from +3 and y from +7. Derived rather than
         * written out, because the constants only held for one icon size and
         * would have silently mispositioned the fill the moment it changed. */
        int top = ICON_CENTRE - battery_size / 2;
        int inner_left = battery_left + 3, inner_top = top + 7;
        int inner_width = battery_size - 9, inner_height = battery_size - 14;
        if (!state->battery_known) {
            /* An empty outline would read as an empty battery, which is a
             * different claim from "not measured yet". The raster holds the
             * slot without asserting a level. */
            icon_fill(canvas, inner_left, inner_top, inner_width, inner_height,
                      STRIP_LIGHT);
        } else if (state->battery_charging) {
            draw_charge_mark(canvas, inner_left, inner_top);
            snprintf(buffer, sizeof(buffer), "%u%%", state->battery_percent > 100
                     ? 100 : state->battery_percent);
            pen -= 4;
            pen -= place_text(canvas, buffer, pen);
        } else {
            /* Fill the cell interior to the measured level, solid. The outline
             * alone would make a full and an empty battery look the same. */
            unsigned percent = state->battery_percent > 100 ? 100 : state->battery_percent;
            int filled = (int)((inner_width * percent + 50) / 100);
            if (filled > 0)
                icon_fill(canvas, inner_left, inner_top, filled, inner_height, STRIP_SOLID);
            snprintf(buffer, sizeof(buffer), "%u%%", percent);
            pen -= 4;
            pen -= place_text(canvas, buffer, pen);
        }
    }
    pen -= GAP;

    pen -= place_icon(canvas, state->wifi_connected ? ICON_WIFI : ICON_WIFI_OFF, pen);
    pen -= GAP;

    if (state->storage_low || state->storage_block) {
        int size = icon_size(ICON_STORAGE);
        if (state->storage_block) {
            /* A blocked card is not a hint any more: it stops new recordings.
             * It gets its own treatment rather than a second warning triangle,
             * because that mark already means "segments need attention" two
             * positions further left. */
            icon_fill(canvas, pen - size - 3, ICON_TOP - 3, size + 6, size + 6, STRIP_SOLID);
            icon_draw(canvas, ICON_STORAGE, pen - size, ICON_TOP, true);
            pen -= size;
        } else {
            pen -= place_icon(canvas, ICON_STORAGE, pen);
        }
        pen -= GAP;
    }

    if (state->queue_attention) {
        snprintf(buffer, sizeof(buffer), "%u", state->queue_attention);
        pen -= place_text(canvas, buffer, pen);
        pen -= 4;
        pen -= place_icon(canvas, ICON_SEV_WARNING, pen);
        pen -= GAP;
    }

    if (state->queue_ready) {
        snprintf(buffer, sizeof(buffer), "%u", state->queue_ready);
        pen -= place_text(canvas, buffer, pen);
        pen -= 4;
        pen -= place_icon(canvas, ICON_QUEUE, pen);
    }

    /* Hairline against the body, so the bar reads as its own region. */
    for (int x = 0; x < CANVAS_WIDTH; x++)
        icon_fill(canvas, x, STATUS_BAR_HEIGHT - 1, 1, 1, STRIP_SOLID);
}
