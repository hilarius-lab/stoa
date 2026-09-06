#include <stdio.h>
#include <string.h>
#include <time.h>
#include "history.h"
#include "card.h"
#include "icons.h"
#include "text.h"

#define PAD 12

const char *history_state_label(const char *state) {
    if (!state || !state[0]) return "unbekannt";
    /* The closed set from the contract's `session_states`. */
    if (!strcmp(state, "created"))           return "angelegt";
    if (!strcmp(state, "recording"))         return "nimmt auf";
    if (!strcmp(state, "paused"))            return "pausiert";
    if (!strcmp(state, "draining"))          return "überträgt";
    if (!strcmp(state, "processing"))        return "verarbeitet";
    if (!strcmp(state, "completed"))         return "fertig";
    if (!strcmp(state, "failed"))            return "fehlgeschlagen";
    if (!strcmp(state, "attention_required"))return "braucht Aufmerksamkeit";
    if (!strcmp(state, "aborted"))           return "abgebrochen";
    /* A state the firmware does not know is shown as it came. Translating it to
     * something familiar would be a guess, and hiding the row would hide a
     * recording that exists. */
    return state;
}

/* Days between 1970-01-01 and the given civil date, proleptic Gregorian.
 * The well-known shift-the-year-to-March formulation: with March as month 0 the
 * leap day falls at the end of the year, so the month-length pattern repeats
 * and no table or special case is needed. Exact for any date in range. */
static long days_from_civil(int year, int month, int day) {
    year -= month <= 2;
    long era = (year >= 0 ? year : year - 399) / 400;
    unsigned year_of_era = (unsigned)(year - era * 400);            /* 0..399 */
    unsigned day_of_year = (unsigned)((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5)
                         + (unsigned)day - 1;                        /* 0..365 */
    unsigned day_of_era = year_of_era * 365 + year_of_era / 4
                        - year_of_era / 100 + day_of_year;           /* 0..146096 */
    return era * 146097 + (long)day_of_era - 719468;
}

static int atoi_fixed(const char *s, int count) {
    int value = 0;
    for (int i = 0; i < count; i++) value = value * 10 + (s[i] - '0');
    return value;
}

static bool digits(const char *s, int count) {
    for (int i = 0; i < count; i++)
        if (s[i] < '0' || s[i] > '9') return false;
    return true;
}

bool history_format_time(char *out, unsigned capacity, const char *iso, bool local) {
    /* Expected: YYYY-MM-DDTHH:MM... — anything else is not turned into a date.
     * A malformed timestamp that rendered as a plausible moment would be worse
     * than an obvious placeholder. */
    if (!iso || strlen(iso) < 16 || iso[4] != '-' || iso[7] != '-' ||
        iso[10] != 'T' || iso[13] != ':' ||
        !digits(iso, 4) || !digits(iso + 5, 2) || !digits(iso + 8, 2) ||
        !digits(iso + 11, 2) || !digits(iso + 14, 2)) {
        snprintf(out, capacity, "--.--. --:--");
        return false;
    }
    int year = atoi_fixed(iso, 4), month = atoi_fixed(iso + 5, 2);
    int day = atoi_fixed(iso + 8, 2), hour = atoi_fixed(iso + 11, 2);
    int minute = atoi_fixed(iso + 14, 2);
    if (local) {
        /* The hard half — which offset applies on this date, and whether summer
         * time is in force — is left to `localtime_r`, because that is where
         * hand-rolled arithmetic goes wrong. Only the UTC instant is computed
         * here: `timegm` is not visible in the toolchain's newlib, and the
         * civil-days formula below is exact for every date this device can
         * ever show, with no calendar table and no edge cases of its own. */
        time_t moment = (time_t)days_from_civil(year, month, day) * 86400
                      + hour * 3600 + minute * 60;
        struct tm shown;
        if (localtime_r(&moment, &shown)) {
            month = shown.tm_mon + 1; day = shown.tm_mday;
            hour = shown.tm_hour; minute = shown.tm_min;
        }
    }
    snprintf(out, capacity, "%02d.%02d. %02d:%02d", day, month, hour, minute);
    return true;
}

int history_header_draw(unsigned char *canvas, int x, int y, int width, bool local) {
    (void)width;
    /* Said once, above the list, rather than as a suffix on every row. The
     * qualifier disappears as soon as the clock is synchronised, because from
     * then on the times need no caveat. */
    const char *note = local ? "Verlauf" : "Verlauf · Zeiten in UTC";
    text_draw(canvas, &text_font_preview, x, y, note, strlen(note));
    return HISTORY_HEADER_HEIGHT;
}

void history_row_draw(unsigned char *canvas, const history_row *row,
                      int x, int y, int width, bool focused) {
    if (!row) return;
    int bottom = y + HISTORY_ROW_HEIGHT - 6;

    /* A hairline under each row rather than a box around it. Twenty-odd boxes
     * would out-shout the entries they contain, and on a 1-bit panel every
     * stroke costs contrast that the text needs. */
    icon_fill(canvas, x, bottom, width, 1, STRIP_MEDIUM);

    int text_y = y + (HISTORY_ROW_HEIGHT - 6 - text_font_preview.line_height) / 2;

    /* The failure mark sits in its own gutter so the time column stays aligned
     * whether or not a row carries one. */
    int mark = icon_size(ICON_SEV_ERROR);
    if (row->failed)
        icon_draw(canvas, ICON_SEV_ERROR, x, y + (HISTORY_ROW_HEIGHT - 6 - mark) / 2, false);
    int left = x + mark + 8;

    text_draw(canvas, &text_font_preview, left, text_y, row->when, strlen(row->when));

    int label = text_measure(&text_font_preview, row->state, strlen(row->state));
    int right = x + width - label;
    if (right < left + text_measure(&text_font_preview, row->when, strlen(row->when)) + 12)
        right = left + text_measure(&text_font_preview, row->when, strlen(row->when)) + 12;
    text_draw(canvas, &text_font_preview, right, text_y, row->state, strlen(row->state));

    /* Focus inverts the row, the same marker the cards and the history button
     * use, so it means one thing everywhere. */
    if (focused) icon_invert(canvas, x - 4, y - 2, width + 8, HISTORY_ROW_HEIGHT - 4);
}
