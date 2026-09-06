#pragma once
// UTF-8 text rendering onto the logical 480 x 800 portrait canvas.
//
// Server text arrives as UTF-8 and is drawn codepoint by codepoint. Nothing
// here transliterates: a codepoint the atlas does not carry is drawn as a
// visible replacement box, never silently dropped and never rewritten to an
// ASCII approximation, because that would falsify server content.
//
// Coordinates are logical: x runs across the 480 px width, y down the 800 px
// height. The mapping onto the physical panel happens here, in one place.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    const void *glyphs;   /* font_glyph[] from the generated header */
    const uint8_t *atlas; /* embedded bitmap blob */
    uint16_t count;
    uint8_t line_height;
    uint8_t ascent;
} text_font;

extern const text_font text_font_title;   /* card headlines, bold */
extern const text_font text_font_body;    /* detail view running text */
extern const text_font text_font_preview; /* card subtitles, the smallest cut */

/* One laid-out line. `bytes` covers the source slice without its trailing
 * break character; `ellipsis` marks a line that was cut short. */
typedef struct {
    const char *start;
    uint16_t bytes;
    uint16_t width;
    bool ellipsis;
} text_line;

/* Decode one codepoint and advance `cursor`. Invalid input yields the
 * replacement codepoint and consumes exactly one byte, so a damaged string can
 * never desynchronise the parser or loop forever. */
uint32_t text_utf8_next(const char **cursor, const char *end);

/* Width in pixels of a UTF-8 slice, laid out on one line. */
int text_measure(const text_font *font, const char *utf8, size_t bytes);

/* Draw a slice at the logical top-left of its line box. Returns the width
 * drawn. Pixels outside the canvas are clipped. */
int text_draw(unsigned char *canvas, const text_font *font, int x, int y,
              const char *utf8, size_t bytes);

/* Greedy line breaking at spaces and hyphens; a word longer than the line is
 * broken hard. Fills at most `max_lines` entries and returns how many were
 * used. If the text does not fit, the final line is shortened and marked with
 * `ellipsis`. Cutting always happens on codepoint boundaries. */
int text_wrap(const text_font *font, const char *utf8, size_t bytes,
              int max_width, int max_lines, text_line *lines);

/* Convenience: wrap and draw, appending the ellipsis where one was needed.
 * Returns the number of lines drawn. */
int text_draw_wrapped(unsigned char *canvas, const text_font *font, int x, int y,
                      int max_width, int max_lines, const char *utf8);
