#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "settings.h"
#include "card.h"
#include "icons.h"
#include "text.h"

#define LEFT 12
#define WIDTH 456
#define PAD 14
#define TITLE_HEIGHT 42
#define ROW_HEIGHT 52
#define ROW_GAP 4
#define LOG_ROW_HEIGHT 27

typedef struct { const char *label; const char *value; } setting_row;

static int content_top(int top) { return top + TITLE_HEIGHT; }
static int content_height(void) {
    return (SETTINGS_ITEM_COUNT + 1) * ROW_HEIGHT + SETTINGS_ITEM_COUNT * ROW_GAP;
}

static void row_draw(unsigned char *canvas, int y, const char *label,
                     const char *value, bool focused) {
    int baseline = y + (ROW_HEIGHT - text_font_body.line_height) / 2;
    text_draw(canvas, &text_font_body, LEFT + PAD, baseline,
              label, strlen(label));
    if (value && value[0]) {
        int width = text_measure(&text_font_preview, value, strlen(value));
        text_draw(canvas, &text_font_preview, LEFT + WIDTH - PAD - width,
                  y + (ROW_HEIGHT - text_font_preview.line_height) / 2,
                  value, strlen(value));
    }
    icon_fill(canvas, LEFT + 6, y + ROW_HEIGHT - 1, WIDTH - 12, 1,
              STRIP_MEDIUM);
    if (focused) icon_invert(canvas, LEFT + 6, y, WIDTH - 12, ROW_HEIGHT - 2);
}

int settings_draw(unsigned char *canvas, int top, int bottom, int scroll,
                  int focus, bool network_connected, bool logs_available) {
    static const setting_row rows[SETTINGS_ITEM_COUNT] = {
        {"WLAN hinzufügen", NULL},
        {"Diagnose", "anzeigen"},
        {"SD-Logs", NULL},
        {"Zeitzone", "Europe/Berlin"},
    };
    static const char title[] = "Einstellungen";
    text_draw(canvas, &text_font_title, LEFT + PAD, top + 4,
              title, strlen(title));
    int y = content_top(top) - scroll;
    if (y >= content_top(top) && y + ROW_HEIGHT <= bottom)
        row_draw(canvas, y, "Zurück", NULL, focus == 0);
    for (int index = 0; index < SETTINGS_ITEM_COUNT; index++) {
        y = content_top(top) + (index + 1) * (ROW_HEIGHT + ROW_GAP) - scroll;
        const char *value = index == 0
            ? (network_connected ? "WLAN verbunden" : "WLAN offline")
            : index == 2 ? (logs_available ? "anzeigen" : "nicht verfügbar")
                         : rows[index].value;
        if (y >= content_top(top) && y + ROW_HEIGHT <= bottom)
            row_draw(canvas, y, rows[index].label, value, focus == index + 1);
    }
    return SETTINGS_ITEM_COUNT;
}

int settings_scroll_for(int top, int bottom, int focus, int current_scroll) {
    if (focus < 0) focus = 0;
    if (focus > SETTINGS_ITEM_COUNT) focus = SETTINGS_ITEM_COUNT;
    int viewport = bottom - content_top(top);
    if (viewport < 1) viewport = 1;
    int row_top = focus * (ROW_HEIGHT + ROW_GAP);
    int row_bottom = row_top + ROW_HEIGHT;
    int scroll = current_scroll;
    if (row_top < scroll) scroll = row_top;
    if (row_bottom > scroll + viewport) scroll = row_bottom - viewport;
    int limit = content_height() - viewport;
    if (limit < 0) limit = 0;
    if (scroll > limit) scroll = limit;
    if (scroll < 0) scroll = 0;
    return scroll;
}

const char *settings_contract_text(const settings_diagnostics *state) {
    if (!state || !state->api_configured) return "nicht konfiguriert";
    if (!state->api_authenticated) return "nicht angemeldet";
    if (state->api_compatible) return "kompatibel";
    if (state->gate_failed) return "Gate fehlgeschlagen";
    return "noch nicht geprüft";
}

void settings_queue_text(char *out, unsigned capacity,
                         const settings_diagnostics *state) {
    if (!out || !capacity) return;
    if (!state) { snprintf(out, capacity, "nicht verfügbar"); return; }
    snprintf(out, capacity, "bereit %u · ACK %u · Achtung %u",
             state->queue_ready, state->queue_acked, state->queue_attention);
}

void settings_storage_text(char *out, unsigned capacity,
                           const settings_diagnostics *state) {
    if (!out || !capacity) return;
    if (!state || !state->bytes_total) {
        snprintf(out, capacity, "nicht verfügbar");
        return;
    }
    const char *mark = state->space_block ? " · blockiert"
                     : state->space_low ? " · niedrig" : "";
    snprintf(out, capacity, "%" PRIu64 " MiB frei%s",
             state->bytes_free / (1024 * 1024), mark);
}

void settings_diagnostics_draw(unsigned char *canvas, int top, int bottom,
                               const settings_diagnostics *state) {
    if (!state) return;
    char gate[40], queue[64], storage[48];
    snprintf(gate, sizeof(gate), "ok %u · fehl %u",
             state->gate_ok, state->gate_failed);
    settings_queue_text(queue, sizeof(queue), state);
    settings_storage_text(storage, sizeof(storage), state);
    setting_row rows[] = {
        {"Software", state->firmware ? state->firmware : "unbekannt"},
        {"Vertrag", settings_contract_text(state)},
        {"Gate-Läufe", gate},
        {"Netzwerk", state->network_connected ? "verbunden" : "offline"},
        {"Queue", queue},
        {"Speicher", storage},
    };
    static const char title[] = "Diagnose";
    text_draw(canvas, &text_font_title, LEFT + PAD, top + 4,
              title, strlen(title));
    int y = content_top(top);
    row_draw(canvas, y, "Zurück", NULL, true);
    for (unsigned index = 0; index < sizeof(rows) / sizeof(rows[0]); index++) {
        y += ROW_HEIGHT + ROW_GAP;
        if (y + ROW_HEIGHT > bottom) break;
        row_draw(canvas, y, rows[index].label, rows[index].value, false);
    }
}

int settings_log_line_count(const char *text) {
    if (!text || !text[0]) return 0;
    int lines = 0;
    bool has_text = false;
    for (const char *at = text; *at; at++) {
        if (*at == '\n') {
            if (has_text) lines++;
            has_text = false;
        } else if (*at != '\r') {
            has_text = true;
        }
    }
    return lines + (has_text ? 1 : 0);
}

int settings_log_visible_capacity(int top, int bottom) {
    int available = bottom - (content_top(top) + ROW_HEIGHT + ROW_GAP);
    return available > 0 ? available / LOG_ROW_HEIGHT : 0;
}

int settings_log_scroll_for(const char *text, int top, int bottom,
                            int first_line, int delta) {
    int total = settings_log_line_count(text);
    int visible = settings_log_visible_capacity(top, bottom);
    int limit = total > visible ? total - visible : 0;
    int next = first_line + delta;
    if (next < 0) next = 0;
    if (next > limit) next = limit;
    return next;
}

void settings_logs_draw(unsigned char *canvas, int top, int bottom,
                        const char *text, int first_line) {
    static const char title[] = "SD-Logs";
    text_draw(canvas, &text_font_title, LEFT + PAD, top + 4,
              title, strlen(title));
    int y = content_top(top);
    row_draw(canvas, y, "Zurück", NULL, true);
    int total = settings_log_line_count(text);
    int visible = settings_log_visible_capacity(top, bottom);
    first_line = settings_log_scroll_for(text, top, bottom, first_line, 0);
    if (total) {
        char position[32];
        int last = first_line + visible;
        if (last > total) last = total;
        snprintf(position, sizeof(position), "%d–%d / %d",
                 first_line + 1, last, total);
        int width = text_measure(&text_font_preview, position,
                                 strlen(position));
        text_draw(canvas, &text_font_preview, LEFT + WIDTH - PAD - width,
                  top + 10, position, strlen(position));
    }
    if (!text || !text[0]) {
        static const char empty[] = "Noch keine Diagnoseereignisse.";
        text_draw(canvas, &text_font_preview, LEFT + PAD,
                  y + ROW_HEIGHT + ROW_GAP + 6, empty, strlen(empty));
        return;
    }
    const char *at = text;
    int line = 0;
    while (*at && line < first_line) {
        if (*at++ == '\n') line++;
    }
    y += ROW_HEIGHT + ROW_GAP;
    for (int shown = 0; shown < visible && *at; shown++) {
        const char *end = strchr(at, '\n');
        size_t length = end ? (size_t)(end - at) : strlen(at);
        while (length && at[length - 1] == '\r') length--;
        text_line clipped[1];
        if (length && text_wrap(&text_font_preview, at, length,
                                WIDTH - PAD * 2, 1, clipped) == 1) {
            text_draw(canvas, &text_font_preview, LEFT + PAD, y + 4,
                      clipped[0].start, clipped[0].bytes);
            if (clipped[0].ellipsis) {
                static const char dots[] = "…";
                int width = text_measure(&text_font_preview,
                                         clipped[0].start, clipped[0].bytes);
                text_draw(canvas, &text_font_preview, LEFT + PAD + width,
                          y + 4, dots, strlen(dots));
            }
        }
        icon_fill(canvas, LEFT + PAD, y + LOG_ROW_HEIGHT - 1,
                  WIDTH - PAD * 2, 1, STRIP_LIGHT);
        y += LOG_ROW_HEIGHT;
        at = end ? end + 1 : at + length;
    }
}
