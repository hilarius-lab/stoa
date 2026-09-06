#pragma once
// One dashboard card: a rounded bubble with an urgency strip on the left and
// the server's text on the right.
//
// The renderer never interprets content. It is handed the values a
// DashboardComponent already carries, mapped to local drawing decisions by the
// caller, and lays them out for this panel.
#include <stdbool.h>
#include "icons.h"

#define CARD_FULL_WIDTH 456
#define CARD_HALF_WIDTH 222
#define CARD_GAP 12
/* Heights follow the content: one or two title lines, optionally a preview
 * line. A fixed height wasted a band of white between title and preview, and
 * that band is exactly the room a second card needs. */
#define CARD_MIN_HEIGHT 52
#define CARD_STRIP 36

/* Half width is only offered to short titles; see docs/DASHBOARD_UI.md. */
#define CARD_HALF_MAX_TITLE_CHARS 28

typedef enum {
    CARD_BORDER_THIN,     /* none and subtle */
    CARD_BORDER_EMPHASIS,
    CARD_BORDER_CRITICAL, /* thick outside, thin inside */
} card_border;

typedef struct {
    const char *title;    /* UTF-8, at most two lines are drawn */
    const char *preview;  /* one line, full width cards only; may be NULL */
    const char *status;   /* short mark on the preview line; may be NULL */
    icon_id icon;         /* art symbol, kind */
    icon_id severity;     /* ICON_COUNT for none */
    strip_pattern urgency;
    card_border border;
    bool focused;
} card_content;

/* Height the card will occupy at this width. */
int card_height(const card_content *card, int width);

/* Draw the card with its top-left corner at (x, y), at its natural height. */
void card_draw(unsigned char *canvas, const card_content *card,
               int x, int y, int width);

/* Draw at a given height. Two cards sharing a row must share a height, or the
 * row frays; the row decides, not the card. */
void card_draw_sized(unsigned char *canvas, const card_content *card,
                     int x, int y, int width, int height);

/* --- sections ------------------------------------------------------------- */
//
// A section is the grouping the server makes; the device shows it as a heading
// with a hairline, not as a frame. A frame costs outer padding, a border and
// inner padding at every section, which on a 712 px body is a whole card, and
// it groups no more clearly than a heading does.

#define SECTION_HEADING_HEIGHT 34

/* Draw a section heading across the content width. */
void section_heading_draw(unsigned char *canvas, const char *title,
                          int x, int y, int width);

/* Stroke a rounded rectangle. Shared so the detail view cannot grow a second,
 * subtly different implementation: the first attempt at one drew only the
 * corners, because its inner test treated every straight edge as inside. */
void card_stroke_round(unsigned char *canvas, int x0, int y0, int x1, int y1,
                       int radius, int thickness);

/* Number of codepoints in a UTF-8 string, for the half width rule. */
unsigned card_title_length(const char *utf8);
