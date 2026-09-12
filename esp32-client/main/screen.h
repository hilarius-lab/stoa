#pragma once
typedef enum { SCREEN_SETUP, SCREEN_SETUP_TEMP, SCREEN_WAKEUP, SCREEN_CONNECTING, SCREEN_CONNECTED, SCREEN_SAVED,
    SCREEN_READY, SCREEN_RECORDING, SCREEN_MEMO_SAVED, SCREEN_ERROR, SCREEN_SLEEP } screen_state;
void screen_start(void);
void screen_show(screen_state state, const char *password);
void screen_memo(screen_state state, unsigned seconds);
/* Draws the sleep background with a full refresh, puts the panel controller
 * itself to sleep (EPD_Sleep — never called before this, so the chip used to
 * stay powered through every prior deep sleep), then enters ESP32 deep sleep
 * with BOOT (GPIO0) as the sole wake source. Never returns on success.
 * Refused while recorder_busy(): the confirmed Settings "Herunterfahren"
 * action and a critically low, non-charging battery reading both call this,
 * and neither may cut power out from under an active recording or SD write. */
void screen_enter_sleep_if_safe(void);
/* Ends the SCREEN_WAKEUP hold and falls back to the plain SCREEN_CONNECTING
 * diagnostics screen. Call this once, from main.c, if boot is taking
 * unusually long without a dashboard yet -- never called if the dashboard
 * arrives first, since screen_snapshot_received() already ends the hold by
 * itself in that case. */
void screen_wakeup_timeout(void);
// Local queue indication drawn into the top-right corner of the idle screens.
// Provisional glyph badges until H3 designs the real status line.
void screen_status(unsigned pending, unsigned attention, bool storage_low);
void screen_status_storage_block(bool blocked);
void screen_status_network(bool connected);
/* Read-only PMIC result. `known=false` deliberately keeps the rastered unknown
 * battery instead of turning a failed read into a false empty cell. */
void screen_status_battery(bool known, unsigned percent, bool charging);
/* The local Settings row hands the actual Wi-Fi transition to app_main, which
 * owns the driver and portal. Taking the request is atomic and edge-like. */
bool screen_take_network_setup_request(void);
/* Explicitly releases the temporary setup screen. Ordinary API/queue/status
 * redraws cannot do this; only the user's cancel action may return to Settings. */
void screen_network_setup_end(void);
/* Local minute and calendar date from the same verified SNTP reading. Before
 * synchronisation, pass 0xFFFFFFFF and zeroes; the bar then shows only the
 * time placeholder rather than a plausible-looking date. */
void screen_status_time(unsigned minutes_since_midnight, unsigned day,
                        unsigned month, unsigned year);
/* Diagnostic: draw a marked rectangle into the live framebuffer and push it
 * with the windowed partial update. Coordinates are framebuffer coordinates:
 * byte columns of 8 pixels and rows. Kept past the H4 bring-up because it is
 * the quickest way to re-check window alignment after a driver change. */
void screen_window_test(unsigned byte_x, unsigned y,
                        unsigned byte_w, unsigned h);
/* Redraw the screen that is currently up with a full update, which also clears
 * accumulated ghosting. Used between windowed-update probes, from the
 * "epd-clear" USB command, and from the settings menu's "Bildschirm
 * reinigen" row. */
void screen_refresh(void);
/* Diagnostic: draw the whole icon atlas and the five strip patterns as a grid,
 * so the symbols can be judged on the panel rather than on a monitor. */
void screen_icon_test(void);
/* Diagnostic: show the five strip patterns large. `step` 0 to 4 fills the whole
 * body with one pattern, anything else shows all five as bands. Dithering has
 * to be judged on the panel: pixel pitch and the partial waveform can make a
 * raster look different from any simulation. */
void screen_pattern_test(unsigned step);
/* Diagnostic: draw the status bar in one of a few representative states, so
 * every combination can be seen without producing it for real. Case 0 is the
 * live state. */
void screen_status_test(unsigned demo);
/* Diagnostic: the header row in one of its states; 0 is the live state. */
void screen_header_test(unsigned demo);
/* Diagnostic: a representative set of cards in the body, to judge the card
 * layout on the panel before any snapshot is rendered for real. */
void screen_card_test(void);

/* A schema-valid dashboard snapshot arrived. The text is copied, so the caller
 * keeps ownership of its buffer. `empty` marks a snapshot without sections,
 * which is a valid but empty dashboard. Resets the displayed age. */
void screen_snapshot_received(const char *json, bool empty);
/* `limits.dashboard_cache_max_age_seconds` from the capabilities: how long the
 * server considers its own dashboard snapshot usable. 0 means the server did
 * not state a limit, and a local fallback of two hours applies. The age that is
 * measured against it is the time since the last accepted poll, not the age of
 * the content. */
void screen_snapshot_cache_limit(unsigned seconds);
/* Move the focus by `delta` steps through the history button and the focusable
 * cards. The work happens in the display task, which owns both the framebuffer
 * and the snapshot. */
void screen_focus_move(int delta);
/* Act on whatever currently carries the focus: open a dashboard card, refresh
 * a focused history row, or close an open detail. */
void screen_focus_activate(void);
/* The entity for an open detail arrived, or NULL if the fetch failed. */
void screen_entity_received(const char *json);
/* A background preload for one dashboard card's entity succeeded. Only warms
 * the detail cache -- unlike screen_entity_received, never touches an open
 * detail's own displayed copy, so a fetch the reader is actually waiting on
 * can never be overwritten by a speculative one that happens to land later. */
void screen_entity_preload_received(const char *type, const char *id, const char *json);
/* A bound answer has reached durable local storage. Hide that one card now;
 * later server snapshots may show any still-required clarification again. */
void screen_clarification_answered(const char *question_id);
/* The session list for the history view arrived, or NULL if the fetch failed. */
void screen_history_received(const char *json);
/* A session dashboard requested by a server-driven card arrived, or NULL. The
 * history list itself no longer opens this detail surface. */
void screen_session_received(const char *json);
/* Diagnostic: render a UTF-8 sample with the title (0), body (1) or preview (2) cut into
 * a cleared area of the body and push it through the windowed update. Exists to
 * judge legibility and line breaking on real hardware before any card layout. */
void screen_text_test(unsigned which, const char *utf8);
