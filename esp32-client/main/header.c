#include <stdio.h>
#include <string.h>
#include "header.h"
#include "status_bar.h"
#include "icons.h"
#include "text.h"

#define CANVAS_WIDTH 480
#define MARGIN 12
#define TOP STATUS_BAR_HEIGHT
#define CENTRE (TOP + HEADER_HEIGHT / 2)

void header_age_text(char *out, unsigned capacity, unsigned age_minutes) {
    if (age_minutes == 0) snprintf(out, capacity, "gerade eben");
    else if (age_minutes < 60) snprintf(out, capacity, "vor %u min", age_minutes);
    else {
        unsigned hours = (age_minutes + 30) / 60;
        if (hours < 24) snprintf(out, capacity, "vor %u h", hours);
        else snprintf(out, capacity, "vor %u d", (hours + 12) / 24);
    }
}

header_snapshot header_snapshot_for(bool seen, bool empty, bool online,
                                    unsigned age_seconds, unsigned limit_seconds) {
    if (!seen) return HEADER_NEVER;
    if (limit_seconds == 0) limit_seconds = HEADER_STALE_FALLBACK_S;
    /* Past the limit the snapshot is no longer trustworthy, and that outranks
     * both its emptiness and the link state: an empty dashboard from three
     * hours ago is not evidence that there is nothing to show, and "offline"
     * would understate the case once the data itself has expired. */
    if (age_seconds >= limit_seconds) return HEADER_STALE;
    if (empty) return HEADER_EMPTY;
    return online ? HEADER_CURRENT : HEADER_OFFLINE;
}

void header_draw(unsigned char *canvas, const header_state *state) {
    char age[24];
    char line[48];

    /* The history button. Focus inverts it, as it does a card, so the marker
     * means the same thing everywhere. */
    int size = icon_size(ICON_MENU);
    int button_left = MARGIN, button_top = CENTRE - size / 2;
    icon_draw(canvas, ICON_MENU, button_left, button_top, false);
    if (state->focused)
        icon_invert(canvas, button_left - 6, button_top - 5, size + 12, size + 10);

    switch (state->snapshot) {
    case HEADER_NEVER:
        snprintf(line, sizeof(line), "noch kein Dashboard");
        break;
    case HEADER_EMPTY:
        snprintf(line, sizeof(line), "Dashboard leer");
        break;
    case HEADER_STALE:
        header_age_text(age, sizeof(age), state->age_minutes);
        snprintf(line, sizeof(line), "veraltet · %s", age);
        break;
    case HEADER_OFFLINE:
        header_age_text(age, sizeof(age), state->age_minutes);
        snprintf(line, sizeof(line), "offline · %s", age);
        break;
    case HEADER_CURRENT:
    default:
        header_age_text(age, sizeof(age), state->age_minutes);
        snprintf(line, sizeof(line), "%s", age);
        break;
    }

    int width = text_measure(&text_font_preview, line, strlen(line));
    /* The preview cut sits on a 19 px line; centre it on the row. */
    text_draw(canvas, &text_font_preview, CANVAS_WIDTH - MARGIN - width,
              CENTRE - text_font_preview.line_height / 2, line, strlen(line));
}
