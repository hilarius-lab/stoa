#pragma once
// Local settings shell and content-free diagnostics. No server payload enters
// this renderer; every value comes from device state and remains useful while
// the backend is offline.
#include <stdbool.h>
#include <stdint.h>

#define SETTINGS_ITEM_COUNT 4

typedef struct {
    const char *firmware;
    bool network_connected;
    bool api_configured;
    bool api_authenticated;
    bool api_compatible;
    unsigned gate_ok;
    unsigned gate_failed;
    unsigned queue_ready;
    unsigned queue_acked;
    unsigned queue_attention;
    uint64_t bytes_free;
    uint64_t bytes_total;
    bool space_low;
    bool space_block;
} settings_diagnostics;

/* Main shell. Focus 0 is Back, 1..4 are Add WLAN, Diagnostics, SD logs
 * and Timezone. Returns SETTINGS_ITEM_COUNT. */
int settings_draw(unsigned char *canvas, int top, int bottom, int scroll,
                  int focus, bool network_connected, bool logs_available);
int settings_scroll_for(int top, int bottom, int focus, int current_scroll);

/* The diagnostics child has a single focused Back action. */
void settings_diagnostics_draw(unsigned char *canvas, int top, int bottom,
                               const settings_diagnostics *state);

/* The log viewer receives only the already-sanitized fixed-vocabulary text
 * from diagnostic_log. It has one focused Back action; up/down scroll lines. */
int settings_log_line_count(const char *text);
int settings_log_visible_capacity(int top, int bottom);
int settings_log_scroll_for(const char *text, int top, int bottom,
                            int first_line, int delta);
void settings_logs_draw(unsigned char *canvas, int top, int bottom,
                        const char *text, int first_line);

/* Text helpers are public so the host test can lock down honest fallbacks. */
const char *settings_contract_text(const settings_diagnostics *state);
void settings_queue_text(char *out, unsigned capacity,
                         const settings_diagnostics *state);
void settings_storage_text(char *out, unsigned capacity,
                           const settings_diagnostics *state);
