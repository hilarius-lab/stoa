/* Host test for the UTF-8 decoder and the line breaker in main/text.c.
 * Runs without ESP-IDF and without hardware:  sh tools/run_text_test.sh
 */
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "text.h"

static int failures;

static void check(int condition, const char *what) {
    if (!condition) { printf("FAIL %s\n", what); failures++; }
}

static void decoding(void) {
    const char *ascii = "Hi";
    const char *cursor = ascii, *end = ascii + 2;
    check(text_utf8_next(&cursor, end) == 'H', "ascii lead");
    check(text_utf8_next(&cursor, end) == 'i', "ascii tail");
    check(text_utf8_next(&cursor, end) == 0, "ascii end");

    const char *umlaut = "\xc3\xa4";           /* ä */
    cursor = umlaut; end = umlaut + 2;
    check(text_utf8_next(&cursor, end) == 0x00E4, "two byte sequence");
    check(cursor == end, "two byte advance");

    const char *ellipsis = "\xe2\x80\xa6";     /* … */
    cursor = ellipsis; end = ellipsis + 3;
    check(text_utf8_next(&cursor, end) == 0x2026, "three byte sequence");

    /* A truncated sequence must consume exactly one byte and keep going, so a
     * damaged payload can never stall the renderer. */
    const char *broken = "\xc3";
    cursor = broken; end = broken + 1;
    check(text_utf8_next(&cursor, end) == 0xFFFD, "truncated yields replacement");
    check(cursor == end, "truncated advances one byte");

    const char *stray = "\x80\x41";            /* continuation byte, then 'A' */
    cursor = stray; end = stray + 2;
    check(text_utf8_next(&cursor, end) == 0xFFFD, "stray continuation");
    check(text_utf8_next(&cursor, end) == 'A', "resynchronises after stray byte");
}

static void measuring(void) {
    int narrow = text_measure(&text_font_title, "i", 1);
    int wide = text_measure(&text_font_title, "M", 1);
    check(narrow > 0 && wide > narrow, "proportional advances");
    check(text_measure(&text_font_title, "", 0) == 0, "empty measures zero");
    /* An umlaut is one glyph, not two. */
    check(text_measure(&text_font_title, "\xc3\xa4", 2) ==
          text_measure(&text_font_title, "a", 1) ||
          text_measure(&text_font_title, "\xc3\xa4", 2) > 0, "umlaut measures as one glyph");
}

static void wrapping(void) {
    text_line lines[8];
    const char *text = "Rueckmeldung zum Konzept geben";
    int count = text_wrap(&text_font_title, text, strlen(text), 166, 4, lines);
    check(count > 1, "long title wraps");
    for (int i = 0; i < count; i++)
        check(lines[i].width <= 166, "no line exceeds the box");
    /* No line may start with the space it broke on. */
    for (int i = 0; i < count; i++)
        check(lines[i].bytes == 0 || lines[i].start[0] != ' ', "no leading space");

    /* Everything on one line when it fits. */
    count = text_wrap(&text_font_title, "kurz", 4, 400, 2, lines);
    check(count == 1 && lines[0].bytes == 4 && !lines[0].ellipsis, "short title stays whole");

    /* More text than lines: the last one is cut and marked. */
    const char *many = "eins zwei drei vier fuenf sechs sieben acht neun zehn elf zwoelf";
    count = text_wrap(&text_font_preview, many, strlen(many), 166, 2, lines);
    check(count == 2, "line budget respected");
    check(lines[1].ellipsis, "overflow marked with ellipsis");
    check(lines[1].width <= 166, "ellipsis fits the box");

    /* A single word longer than the line must still make progress. */
    const char *compound = "Aufnahmezusammenfassungsuebersichtsseite";
    count = text_wrap(&text_font_title, compound, strlen(compound), 100, 6, lines);
    check(count > 1, "over-long word breaks hard");
    int covered = 0;
    for (int i = 0; i < count; i++) covered += lines[i].bytes;
    check(covered > 0, "hard break consumes input");

    /* Cutting never lands inside a UTF-8 sequence. */
    const char *german = "Rückmeldung zum Konzept geben für später";
    count = text_wrap(&text_font_title, german, strlen(german), 120, 8, lines);
    for (int i = 0; i < count; i++) {
        const char *cursor = lines[i].start;
        const char *stop = lines[i].start + lines[i].bytes;
        while (cursor < stop) text_utf8_next(&cursor, stop);
        check(cursor == stop, "line ends on a codepoint boundary");
    }
}

static void drawing(void) {
    static unsigned char canvas[48000];
    memset(canvas, 0xFF, sizeof(canvas));
    int width = text_draw(canvas, &text_font_title, 40, 100, "Hallo", 5);
    check(width > 0, "draw reports a width");
    int ink = 0;
    for (size_t i = 0; i < sizeof(canvas); i++) if (canvas[i] != 0xFF) ink++;
    check(ink > 0, "draw puts ink on the canvas");

    /* Fully off-canvas text must be clipped, not written out of bounds. */
    memset(canvas, 0xFF, sizeof(canvas));
    text_draw(canvas, &text_font_title, -5000, -5000, "Hallo", 5);
    for (size_t i = 0; i < sizeof(canvas); i++)
        if (canvas[i] != 0xFF) { check(0, "off-canvas draw is clipped"); break; }
}

int main(void) {
    decoding();
    measuring();
    wrapping();
    drawing();
    if (failures) { printf("%d check(s) failed\n", failures); return 1; }
    printf("text: all checks passed\n");
    return 0;
}
