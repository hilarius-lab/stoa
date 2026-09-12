#pragma once
// Local settings shell and content-free diagnostics. No server payload enters
// this renderer; every value comes from device state and remains useful while
// the backend is offline.
#include <stdbool.h>
#include <stdint.h>

#define SETTINGS_ITEM_COUNT 6

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

/* Main shell. Focus 0 is Back, 1..6 are Add WLAN, Diagnostics, SD logs,
 * Timezone, Restart and Shut down. Returns SETTINGS_ITEM_COUNT. */
int settings_draw(unsigned char *canvas, int top, int bottom, int scroll,
                  int focus, bool network_connected, bool logs_available);
int settings_scroll_for(int top, int bottom, int focus, int current_scroll);

/* The diagnostics child has a single focused Back action. */
void settings_diagnostics_draw(unsigned char *canvas, int top, int bottom,
                               const settings_diagnostics *state);

/* A generic two-row confirm: restart and shut down each require an explicit
 * second confirmation before they act, so a stray middle-button press on the
 * settings row cannot trigger either, and the history view reuses the same
 * shape for discarding a local recording. Focus 0 is Back/No; focus 1 is the
 * confirming Yes row, only offered while `locked` is false. `locked_reason`
 * is shown instead of the Yes row while locked -- restart/shutdown name
 * recorder_busy(), the history discard names its own still-deliverable
 * refusal, and neither reason may stand in for the other. */
void settings_confirm_draw(unsigned char *canvas, int top, int bottom,
                           const char *title, const char *confirm_label,
                           bool locked, const char *locked_reason, int focus);

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
