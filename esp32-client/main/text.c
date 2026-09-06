#include <string.h>
#include "text.h"
#include "font_data.h"

#ifdef TEXT_HOST_TEST
/* The host test supplies the atlases as plain arrays; on the device they are
 * embedded by the build and carry the linker's binary symbol names. */
extern const uint8_t font_title_bin[];
extern const uint8_t font_body_bin[];
extern const uint8_t font_preview_bin[];
#else
extern const uint8_t font_title_bin[] asm("_binary_font_title_bin_start");
extern const uint8_t font_body_bin[] asm("_binary_font_body_bin_start");
extern const uint8_t font_preview_bin[] asm("_binary_font_preview_bin_start");
#endif

const text_font text_font_title = {
    .glyphs = font_title_glyphs, .atlas = font_title_bin,
    .count = FONT_TITLE_COUNT, .line_height = FONT_TITLE_LINE,
    .ascent = FONT_TITLE_ASCENT,
};
const text_font text_font_body = {
    .glyphs = font_body_glyphs, .atlas = font_body_bin,
    .count = FONT_BODY_COUNT, .line_height = FONT_BODY_LINE,
    .ascent = FONT_BODY_ASCENT,
};
const text_font text_font_preview = {
    .glyphs = font_preview_glyphs, .atlas = font_preview_bin,
    .count = FONT_PREVIEW_COUNT, .line_height = FONT_PREVIEW_LINE,
    .ascent = FONT_PREVIEW_ASCENT,
};

#define CANVAS_WIDTH 480
#define CANVAS_HEIGHT 800
#define PANEL_STRIDE 100
#define ELLIPSIS 0x2026

uint32_t text_utf8_next(const char **cursor, const char *end) {
    const unsigned char *p = (const unsigned char *)*cursor;
    if ((const char *)p >= end) return 0;
    unsigned char lead = p[0];
    int extra;
    uint32_t value;
    if (lead < 0x80) { *cursor = (const char *)p + 1; return lead; }
    else if ((lead & 0xE0) == 0xC0) { extra = 1; value = lead & 0x1F; }
    else if ((lead & 0xF0) == 0xE0) { extra = 2; value = lead & 0x0F; }
    else if ((lead & 0xF8) == 0xF0) { extra = 3; value = lead & 0x07; }
    else { *cursor = (const char *)p + 1; return FONT_REPLACEMENT; }
    for (int i = 1; i <= extra; i++) {
        if ((const char *)(p + i) >= end || (p[i] & 0xC0) != 0x80) {
            /* Consume only the lead byte so the caller keeps making progress. */
            *cursor = (const char *)p + 1;
            return FONT_REPLACEMENT;
        }
        value = (value << 6) | (p[i] & 0x3F);
    }
    *cursor = (const char *)p + extra + 1;
    /* Surrogates and out-of-range values are not text. */
    if (value > 0x10FFFF || (value >= 0xD800 && value <= 0xDFFF)) return FONT_REPLACEMENT;
    return value;
}

static const font_glyph *lookup(const text_font *font, uint32_t codepoint) {
    const font_glyph *glyphs = font->glyphs;
    int low = 0, high = (int)font->count - 1;
    while (low <= high) {
        int middle = (low + high) / 2;
        uint32_t here = glyphs[middle].codepoint;
        if (here == codepoint) return &glyphs[middle];
        if (here < codepoint) low = middle + 1; else high = middle - 1;
    }
    /* The replacement box is always present; the generator guarantees it. */
    if (codepoint != FONT_REPLACEMENT) return lookup(font, FONT_REPLACEMENT);
    return &glyphs[0];
}

int text_measure(const text_font *font, const char *utf8, size_t bytes) {
    const char *cursor = utf8, *end = utf8 + bytes;
    int width = 0;
    uint32_t codepoint;
    while ((codepoint = text_utf8_next(&cursor, end))) width += lookup(font, codepoint)->advance;
    return width;
}

static void plot(unsigned char *canvas, int x, int y) {
    if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return;
    /* Logical to panel: the canvas is drawn rotated, exactly as the existing
     * glyph and QR drawing does. Keeping the mapping in one place is the point
     * of this module. */
    int px = y, py = CANVAS_WIDTH - 1 - x;
    canvas[py * PANEL_STRIDE + px / 8] &= ~(0x80 >> (px % 8));
}

static int blit(unsigned char *canvas, const text_font *font,
                const font_glyph *glyph, int x, int y) {
    const uint8_t *bitmap = font->atlas + glyph->offset;
    int stride = (glyph->width + 7) / 8;
    for (int row = 0; row < glyph->height; row++)
        for (int column = 0; column < glyph->width; column++)
            if (bitmap[row * stride + column / 8] & (0x80 >> (column % 8)))
                plot(canvas, x + glyph->left + column, y + glyph->top + row);
    return glyph->advance;
}

int text_draw(unsigned char *canvas, const text_font *font, int x, int y,
              const char *utf8, size_t bytes) {
    const char *cursor = utf8, *end = utf8 + bytes;
    int pen = x;
    uint32_t codepoint;
    while ((codepoint = text_utf8_next(&cursor, end)))
        pen += blit(canvas, font, lookup(font, codepoint), pen, y);
    return pen - x;
}

int text_wrap(const text_font *font, const char *utf8, size_t bytes,
              int max_width, int max_lines, text_line *lines) {
    const char *end = utf8 + bytes;
    const char *line_start = utf8;
    int used = 0;
    int ellipsis_width = lookup(font, ELLIPSIS)->advance;

    while (line_start < end && used < max_lines) {
        while (line_start < end && *line_start == ' ') line_start++;
        if (line_start >= end) break;

        const char *cursor = line_start;
        const char *break_at = NULL;       /* end of the last fitting word */
        const char *break_resume = NULL;   /* where the next line starts */
        const char *fits_until = line_start;
        int width = 0, width_at_break = 0;

        while (cursor < end) {
            const char *before = cursor;
            uint32_t codepoint = text_utf8_next(&cursor, end);
            if (!codepoint) break;
            int advance = lookup(font, codepoint)->advance;
            if (width + advance > max_width) { cursor = before; break; }
            width += advance;
            fits_until = cursor;
            if (codepoint == ' ') { break_at = before; break_resume = cursor; width_at_break = width; }
            else if (codepoint == '-' || codepoint == 0x2013) { break_at = cursor; break_resume = cursor; width_at_break = width; }
        }

        bool last_line = (used == max_lines - 1);
        const char *stop, *resume;
        if (cursor >= end) { stop = end; resume = end; width_at_break = width; }
        else if (break_at) { stop = break_at; resume = break_resume; }
        else { stop = fits_until; resume = fits_until; width_at_break = width; } /* hard break */

        if (stop == line_start) {
            /* A single glyph wider than the line: consume it anyway, otherwise
             * this loop would never advance. */
            const char *forced = line_start;
            uint32_t codepoint = text_utf8_next(&forced, end);
            width_at_break = codepoint ? lookup(font, codepoint)->advance : 0;
            stop = resume = forced;
        }

        lines[used].start = line_start;
        lines[used].bytes = (uint16_t)(stop - line_start);
        lines[used].width = (uint16_t)width_at_break;
        lines[used].ellipsis = false;

        if (last_line && resume < end) {
            /* Shorten on codepoint boundaries until the ellipsis fits too. */
            const char *scan = line_start;
            const char *keep = line_start;
            int running = 0;
            while (scan < stop) {
                const char *before = scan;
                uint32_t codepoint = text_utf8_next(&scan, stop);
                if (!codepoint) break;
                int advance = lookup(font, codepoint)->advance;
                if (running + advance + ellipsis_width > max_width) { scan = before; break; }
                running += advance;
                keep = scan;
            }
            lines[used].bytes = (uint16_t)(keep - line_start);
            lines[used].width = (uint16_t)(running + ellipsis_width);
            lines[used].ellipsis = true;
        }
        used++;
        line_start = resume;
    }
    return used;
}

int text_draw_wrapped(unsigned char *canvas, const text_font *font, int x, int y,
                      int max_width, int max_lines, const char *utf8) {
    text_line lines[8];
    if (max_lines > 8) max_lines = 8;
    int count = text_wrap(font, utf8, strlen(utf8), max_width, max_lines, lines);
    for (int i = 0; i < count; i++) {
        int pen = x + text_draw(canvas, font, x, y + i * font->line_height,
                                lines[i].start, lines[i].bytes);
        if (lines[i].ellipsis) {
            const font_glyph *glyph = lookup(font, ELLIPSIS);
            blit(canvas, font, glyph, pen, y + i * font->line_height);
        }
    }
    return count;
}
