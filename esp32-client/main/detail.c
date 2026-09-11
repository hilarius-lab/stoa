#include <string.h>
#include "detail.h"
#include "card.h"
#include "icons.h"
#include "text.h"

#define MARGIN 12
#define PAD 14
#define RADIUS 8
#define BODY_LINES_MAX 64

static int wrapped(const char *utf8, const text_font *font, int width,
                   text_line *lines, int capacity) {
    if (!utf8 || !utf8[0]) return 0;
    return text_wrap(font, utf8, strlen(utf8), width, capacity, lines);
}

/* The head is everything above the running text: title, reason and, where one
 * exists, the answer. Its height decides how much room the body gets, so it is
 * measured and drawn from the same layout. */
static int head_height(const detail_content *detail, int width) {
    text_line lines[8];
    int height = wrapped(detail->title, &text_font_title, width, lines, 3)
                 * text_font_title.line_height;
    int reason = wrapped(detail->reason, &text_font_preview, width, lines, 2);
    if (reason) height += 6 + reason * text_font_preview.line_height;
    return height + 10;
}

int detail_page_lines(const detail_content *detail, int top, int bottom) {
    int width = 480 - 2 * MARGIN - 2 * PAD;
    int foot_rows = detail->action_count > 0 ? detail->action_count + 1 : 1;
    int available = (bottom - top) - 2 * PAD - head_height(detail, width)
                    - foot_rows * text_font_preview.line_height - 8;
    int lines = available / text_font_body.line_height;
    return lines > 0 ? lines : 1;
}

int detail_draw(unsigned char *canvas, const detail_content *detail,
                int top, int bottom, int line_offset) {
    int left = MARGIN, right = 480 - MARGIN - 1;
    int width = right - left + 1 - 2 * PAD;
    int text_left = left + PAD;

    /* One bubble over the whole body, so the detail reads as the card opened
     * rather than as a different screen. */
    card_stroke_round(canvas, left, top, right, bottom, RADIUS, 2);

    int y = top + PAD;
    text_line lines[BODY_LINES_MAX];

    int count = wrapped(detail->title, &text_font_title, width, lines, 3);
    for (int i = 0; i < count; i++) {
        text_draw(canvas, &text_font_title, text_left, y, lines[i].start, lines[i].bytes);
        y += text_font_title.line_height;
    }
    count = wrapped(detail->reason, &text_font_preview, width, lines, 2);
    if (count) {
        y += 6;
        for (int i = 0; i < count; i++) {
            text_draw(canvas, &text_font_preview, text_left, y, lines[i].start, lines[i].bytes);
            y += text_font_preview.line_height;
        }
    }
    y += 10;

    int page = detail_page_lines(detail, top, bottom);
    int total = wrapped(detail->body, &text_font_body, width, lines, BODY_LINES_MAX);
    for (int i = line_offset; i < total && i < line_offset + page; i++) {
        text_draw(canvas, &text_font_body, text_left, y, lines[i].start, lines[i].bytes);
        y += text_font_body.line_height;
    }

    if (detail->answer && detail->answer[0]) {
        int answer = wrapped(detail->answer, &text_font_body, width, lines, 4);
        y += 6;
        for (int i = 0; i < answer; i++) {
            text_draw(canvas, &text_font_body, text_left, y, lines[i].start, lines[i].bytes);
            y += text_font_body.line_height;
        }
    }

    if (detail->action_count > 0) {
        /* A vertical choice list leaves enough width for real entity names.
         * Focus 0 is always the local back action; remaining rows are fixed,
         * server-projected choices and never interpreted by the firmware. */
        int rows = detail->action_count + 1;
        int foot = bottom - PAD - rows * text_font_preview.line_height;
        for (int x = text_left; x < right - PAD; x++)
            icon_fill(canvas, x, foot - 6, 1, 1, STRIP_SOLID);
        static const char back[] = "Zurück";
        int back_width = text_measure(&text_font_preview, back, strlen(back));
        text_draw(canvas, &text_font_preview, text_left, foot, back, strlen(back));
        if (detail->action_focus == 0)
            icon_invert(canvas, text_left - 4, foot - 3, back_width + 8,
                        text_font_preview.line_height + 2);
        for (int index = 0; index < detail->action_count && index < DETAIL_ACTION_MAX; index++) {
            const char *label = detail->action_labels[index];
            if (!label || !label[0]) continue;
            int row = foot + (index + 1) * text_font_preview.line_height;
            text_line choice[1];
            int count = text_wrap(&text_font_preview, label, strlen(label),
                                  width, 1, choice);
            if (!count) continue;
            text_draw_wrapped(canvas, &text_font_preview, text_left, row,
                              width, 1, label);
            if (detail->action_focus == index + 1)
                icon_invert(canvas, text_left - 4, row - 3, choice[0].width + 8,
                            text_font_preview.line_height + 2);
        }
    } else if (detail->meta && detail->meta[0]) {
        int foot = bottom - PAD - text_font_preview.line_height;
        for (int x = text_left; x < right - PAD; x++)
            icon_fill(canvas, x, foot - 6, 1, 1, STRIP_SOLID);
        text_draw(canvas, &text_font_preview, text_left, foot,
                  detail->meta, strlen(detail->meta));
    }
    return total;
}
