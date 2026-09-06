#include <string.h>
#include "card.h"
#include "text.h"

#define RADIUS 8
#define PAD 12          /* horizontal padding inside the text panel */
#define PAD_TOP 10
#define PAD_BOTTOM 10
#define TITLE_GAP 2     /* title to preview: they belong together */
#define SEVERITY_GUTTER 24

/* --- rounded rectangle ---------------------------------------------------- */

static bool inside(int x, int y, int x0, int y0, int x1, int y1, int radius) {
    if (x < x0 || x > x1 || y < y0 || y > y1) return false;
    int cx = x < x0 + radius ? x0 + radius : (x > x1 - radius ? x1 - radius : x);
    int cy = y < y0 + radius ? y0 + radius : (y > y1 - radius ? y1 - radius : y);
    if (cx == x || cy == y) return true;
    int dx = x - cx, dy = y - cy;
    return dx * dx + dy * dy <= radius * radius;
}

/* Stroke the outline by testing the band between two nested rounded shapes.
 * The inner shape is inset on all four sides, not merely given a smaller
 * radius: a shape that is only rounded differently still covers every straight
 * edge, and the outline would come out as four detached corners. */
void card_stroke_round(unsigned char *canvas, int x0, int y0, int x1, int y1,
                       int radius, int thickness) {
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            if (inside(x, y, x0, y0, x1, y1, radius) &&
                !inside(x, y, x0 + thickness, y0 + thickness,
                        x1 - thickness, y1 - thickness, radius - thickness))
                icon_fill(canvas, x, y, 1, 1, STRIP_SOLID);
}

void section_heading_draw(unsigned char *canvas, const char *title,
                          int x, int y, int width) {
    if (title && title[0]) {
        text_line line[1];
        if (text_wrap(&text_font_title, title, strlen(title), width, 1, line) == 1) {
            int pen = x + text_draw(canvas, &text_font_title, x, y + 2,
                                    line[0].start, line[0].bytes);
            if (line[0].ellipsis)
                text_draw(canvas, &text_font_title, pen, y + 2, "\xe2\x80\xa6", 3);
        }
    }
    for (int px = x; px < x + width; px++)
        icon_fill(canvas, px, y + SECTION_HEADING_HEIGHT - 3, 1, 1, STRIP_SOLID);
}

/* --- content -------------------------------------------------------------- */

unsigned card_title_length(const char *utf8) {
    if (!utf8) return 0;
    const char *cursor = utf8, *end = utf8 + strlen(utf8);
    unsigned count = 0;
    while (text_utf8_next(&cursor, end)) count++;
    return count;
}

static bool has_status(const card_content *card) {
    return card->status && card->status[0];
}

static bool wants_preview(const card_content *card, int width) {
    /* A half width card has no room for a second text row, and a rule that
     * depended on the neighbouring card would make the same card render
     * differently from one snapshot to the next. */
    return card->preview && card->preview[0] && width >= CARD_FULL_WIDTH;
}

/* One place decides the text box and how the title breaks, so card_height and
 * card_draw can never disagree about how tall a card is. */
static int layout(const card_content *card, int x, int width,
                  text_line *lines, int *text_left, int *text_width) {
    int left = x + CARD_STRIP + PAD;
    int right = x + width - 1 - PAD;
    int available = right - left - (card->severity < ICON_COUNT ? SEVERITY_GUTTER : 0);
    if (available < 16) available = 16;
    *text_left = left;
    *text_width = available;
    if (!card->title || !card->title[0]) return 0;
    return text_wrap(&text_font_title, card->title, strlen(card->title),
                     available, 2, lines);
}

/* The footer row carries the preview, the status mark, or both. It has to be
 * part of the height: a status drawn into a card that made no room for it
 * lands outside the bubble, which is exactly what a half width card with a two
 * line title used to do. */
static bool has_footer(const card_content *card, int width) {
    return wants_preview(card, width) || has_status(card);
}

int card_height(const card_content *card, int width) {
    text_line lines[2];
    int left, available;
    int count = layout(card, 0, width, lines, &left, &available);
    int content = count * text_font_title.line_height;
    if (has_footer(card, width))
        content += TITLE_GAP + text_font_preview.line_height;
    int height = PAD_TOP + content + PAD_BOTTOM;
    return height < CARD_MIN_HEIGHT ? CARD_MIN_HEIGHT : height;
}

void card_draw(unsigned char *canvas, const card_content *card,
               int x, int y, int width) {
    card_draw_sized(canvas, card, x, y, width, card_height(card, width));
}

void card_draw_sized(unsigned char *canvas, const card_content *card,
                     int x, int y, int width, int height) {
    int right = x + width - 1, bottom = y + height - 1;

    /* Urgency strip, clipped to the bubble. A rectangular fill would push the
     * raster past the rounded corners, which is immediately visible on the
     * darker steps. Filling pixel by pixel keeps the pattern anchored to the
     * canvas, so neighbouring cards of the same step still line up. */
    for (int py = y; py <= bottom; py++)
        for (int px = x; px <= x + CARD_STRIP; px++)
            if (inside(px, py, x, y, right, bottom, RADIUS)) {
                if (icon_pattern_ink(card->urgency, px, py))
                    icon_fill(canvas, px, py, 1, 1, STRIP_SOLID);
                else
                    icon_plate(canvas, px, py, 1, 1);
            }
    if (card->urgency == STRIP_PLAIN)
        /* The lightest step is a white strip with an edge, so it still reads as
         * a strip rather than as part of the text panel. */
        for (int py = y + RADIUS / 2; py <= bottom - RADIUS / 2; py++)
            icon_fill(canvas, x + CARD_STRIP, py, 1, 1, STRIP_SOLID);
    icon_draw_badge(canvas, card->icon,
                    x + 1 + (CARD_STRIP - icon_size(card->icon)) / 2,
                    y + (height - icon_size(card->icon)) / 2);

    text_line lines[2];
    int text_left, text_width;
    int count = layout(card, x, width, lines, &text_left, &text_width);
    int text_right = right - PAD;
    bool has_severity = card->severity < ICON_COUNT;

    /* The severity mark keeps a gutter of its own for every line rather than
     * only the first: reserving it once would let a two line title run into it. */
    if (has_severity)
        icon_draw(canvas, card->severity, text_right - icon_size(card->severity),
                  y + PAD - 2, false);

    /* Equal padding centres the block, so no special case is needed for a
     * single line card. */
    int content = count * text_font_title.line_height +
                  (has_footer(card, width)
                       ? TITLE_GAP + text_font_preview.line_height : 0);
    int title_top = y + (height - content) / 2;
    for (int i = 0; i < count; i++) {
        int pen = text_left + text_draw(canvas, &text_font_title, text_left,
                                        title_top + i * text_font_title.line_height,
                                        lines[i].start, lines[i].bytes);
        if (lines[i].ellipsis)
            text_draw(canvas, &text_font_title, pen,
                      title_top + i * text_font_title.line_height, "\xe2\x80\xa6", 3);
    }

    int footer_top = title_top + count * text_font_title.line_height + TITLE_GAP;
    int footer_right = text_right;
    if (has_status(card)) {
        int status_width = text_measure(&text_font_preview, card->status,
                                        strlen(card->status));
        text_draw(canvas, &text_font_preview, footer_right - status_width,
                  footer_top, card->status, strlen(card->status));
        footer_right -= status_width + PAD;
    }
    if (wants_preview(card, width)) {
        text_line preview[1];
        int available = footer_right - text_left;
        if (available > 16 &&
            text_wrap(&text_font_preview, card->preview, strlen(card->preview),
                      available, 1, preview) == 1) {
            int pen = text_left + text_draw(canvas, &text_font_preview, text_left,
                                            footer_top, preview[0].start,
                                            preview[0].bytes);
            if (preview[0].ellipsis)
                text_draw(canvas, &text_font_preview, pen, footer_top,
                          "\xe2\x80\xa6", 3);
        }
    }

    /* Focus inverts the text panel only, never the strip: inverting a raster
     * would turn 25 percent into 75 and silently change the urgency the card
     * claims. The strip keeps its meaning, the panel carries the marker. */
    if (card->focused)
        for (int py = y; py <= bottom; py++)
            for (int px = x + CARD_STRIP + 1; px <= right; px++)
                if (inside(px, py, x, y, right, bottom, RADIUS))
                    icon_invert(canvas, px, py, 1, 1);

    switch (card->border) {
    case CARD_BORDER_EMPHASIS:
        card_stroke_round(canvas, x, y, right, bottom, RADIUS, 3);
        break;
    case CARD_BORDER_CRITICAL:
        card_stroke_round(canvas, x, y, right, bottom, RADIUS, 4);
        card_stroke_round(canvas, x + 7, y + 7, right - 7, bottom - 7, RADIUS - 4, 1);
        break;
    case CARD_BORDER_THIN:
    default:
        card_stroke_round(canvas, x, y, right, bottom, RADIUS, 2);
        break;
    }
}
