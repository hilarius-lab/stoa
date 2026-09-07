#include "icons.h"

#ifdef ICON_HOST_TEST
extern const uint8_t icons_bin[];
#else
extern const uint8_t icons_bin[] asm("_binary_icons_bin_start");
#endif

#define CANVAS_WIDTH 480
#define CANVAS_HEIGHT 800
#define PANEL_STRIDE 100

/* Logical to panel, identical to text.c. The canvas is stored rotated. */
static inline int panel_x(int y) { return y; }
static inline int panel_y(int x) { return CANVAS_WIDTH - 1 - x; }

static void set(unsigned char *canvas, int x, int y, bool ink) {
    if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return;
    int px = panel_x(y), py = panel_y(x);
    unsigned char mask = 0x80 >> (px % 8);
    if (ink) canvas[py * PANEL_STRIDE + px / 8] &= ~mask;
    else canvas[py * PANEL_STRIDE + px / 8] |= mask;
}

static bool get(const unsigned char *canvas, int x, int y) {
    if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return false;
    int px = panel_x(y), py = panel_y(x);
    return (canvas[py * PANEL_STRIDE + px / 8] & (0x80 >> (px % 8))) == 0;
}

int icon_size(icon_id id) {
    if (id < 0 || id >= ICON_COUNT) return 0;
    return icon_entries[id].size;
}

void icon_draw(unsigned char *canvas, icon_id id, int x, int y, bool knockout) {
    if (id < 0 || id >= ICON_COUNT) return;
    int size = icon_entries[id].size;
    const uint8_t *bitmap = icons_bin + icon_entries[id].offset;
    int stride = (size + 7) / 8;
    for (int row = 0; row < size; row++)
        for (int column = 0; column < size; column++)
            if (bitmap[row * stride + column / 8] & (0x80 >> (column % 8)))
                set(canvas, x + column, y + row, !knockout);
}

/* Patterns are evaluated in canvas coordinates so that neighbouring fills of
 * the same pattern continue each other instead of restarting. */
bool icon_pattern_ink(strip_pattern pattern, int x, int y) {
    switch (pattern) {
    case STRIP_SOLID:  return true;
    case STRIP_HATCH:  return ((x + y) & 3) != 3;  /* 75 percent: darker than MEDIUM, still a diagonal */
    case STRIP_MEDIUM: return ((x + y) & 1) == 0;  /* checkerboard */
    case STRIP_LIGHT:  return (x & 1) == 0 && (y & 1) == 0;
    case STRIP_PLAIN:
    default:           return false;
    }
}

void icon_fill(unsigned char *canvas, int x, int y, int width, int height,
               strip_pattern pattern) {
    for (int row = 0; row < height; row++)
        for (int column = 0; column < width; column++)
            set(canvas, x + column, y + row,
                icon_pattern_ink(pattern, x + column, y + row));
    if (pattern == STRIP_PLAIN)
        for (int row = 0; row < height; row++)
            set(canvas, x + width - 1, y + row, true); /* hairline edge */
}

bool icon_knockout_on(strip_pattern pattern) { return pattern >= STRIP_MEDIUM; }

void icon_plate(unsigned char *canvas, int x, int y, int width, int height) {
    for (int row = 0; row < height; row++)
        for (int column = 0; column < width; column++)
            set(canvas, x + column, y + row, false);
}

#define BADGE_MARGIN 3

void icon_draw_badge(unsigned char *canvas, icon_id id, int x, int y) {
    int size = icon_size(id);
    if (!size) return;
    icon_plate(canvas, x - BADGE_MARGIN, y - BADGE_MARGIN,
               size + 2 * BADGE_MARGIN, size + 2 * BADGE_MARGIN);
    icon_draw(canvas, id, x, y, false);
}

void icon_invert(unsigned char *canvas, int x, int y, int width, int height) {
    for (int row = 0; row < height; row++)
        for (int column = 0; column < width; column++)
            set(canvas, x + column, y + row, !get(canvas, x + column, y + row));
}

void icon_outline(unsigned char *canvas, int x, int y, int width, int height,
                  int thickness) {
    for (int row = 0; row < height; row++)
        for (int column = 0; column < width; column++) {
            bool border = row < thickness || row >= height - thickness ||
                         column < thickness || column >= width - thickness;
            if (border) set(canvas, x + column, y + row, true);
        }
}
