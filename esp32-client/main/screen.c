#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdatomic.h>
#include "qrcode.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "epaper_port.h"
#include "screen.h"
#include "text.h"
#include "icons.h"
#include "status_bar.h"
#include "header.h"
#include "history.h"
#include "clock.h"
#include "card.h"
#include "dashboard.h"
#include "cJSON.h"
#include "api_client.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
extern const unsigned char ready[] asm("_binary_ready_bin_start");
extern const unsigned char recording[] asm("_binary_recording_bin_start");
extern const unsigned char memo_saved[] asm("_binary_memo_saved_bin_start");
extern const unsigned char error[] asm("_binary_error_bin_start");
extern const unsigned char setup[] asm("_binary_setup_bin_start");
extern const unsigned char connecting[] asm("_binary_connecting_bin_start");
extern const unsigned char connected[] asm("_binary_connected_bin_start");
extern const unsigned char saved[] asm("_binary_saved_bin_start");
extern const unsigned char hex[] asm("_binary_hex_bin_start");
typedef struct {
    screen_state state;
    char password[17];
    unsigned seconds;
    /* Diagnostic windowed-update probe; see screen_window_test. */
    bool window_test;
    /* Redraw the current screen with a full update, clearing accumulated
     * ghosting. `state` is filled in from the screen that is currently up. */
    bool force_full;
    unsigned byte_x, row, byte_w, rows;
    /* Diagnostic text sample; see screen_text_test. */
    bool text_test;
    bool icon_test;
    bool pattern_test;
    bool status_demo;
    bool header_demo;
    bool card_demo;
    bool focus_move;
    bool focus_activate;
    /* An ambient redraw rather than a user action; see queue_redraw. */
    bool ambient;
    int focus_delta;
    unsigned cut;
    char sample[160];
} screen_message;

/* Logical rectangle helpers. Logical x runs across the 480 px width and maps to
 * panel rows; logical y runs down the 800 px height and maps to panel columns.
 * Keeping the conversion here stops every caller from re-deriving it. */
static void logical_fill(unsigned char *buffer, int x0, int y0, int x1, int y1) {
    for (int x = x0; x < x1; x++) {
        int py = 479 - x;
        if (py < 0 || py >= 480) continue;
        for (int y = y0; y < y1; y++)
            if (y >= 0 && y < 800) buffer[py * 100 + y / 8] |= (0x80 >> (y % 8));
    }
}

static void logical_push(unsigned char *buffer, int x0, int y0, int x1, int y1) {
    int byte_x = y0 / 8;
    int byte_w = (y1 + 7) / 8 - byte_x;
    int row = 480 - x1;
    int rows = x1 - x0;
    if (byte_x < 0 || row < 0 || byte_w <= 0 || rows <= 0) return;
    EPD_Display_Partial_Window(buffer, (UWORD)byte_x, (UWORD)row,
                               (UWORD)byte_w, (UWORD)rows);
}
static QueueHandle_t queue;
// Queue indication is ambient: it is latched here, and a coalesced redraw
// request puts it on the panel without ever displacing a button press.
static atomic_uint status_pending, status_attention;
static atomic_bool status_storage_low, status_storage_block;
static atomic_bool status_network, status_recording;
static atomic_uint status_minutes; /* minutes since midnight, or UINT_MAX */
static atomic_bool snapshot_seen, snapshot_empty;
static _Atomic int64_t snapshot_at_us;
/* Set from the upload worker's task when a new snapshot arrives, consumed
 * exactly once by the display task (see screen_task's message loop) to reset
 * the three dashboard-family focuses to the header. Not touched directly from
 * there: dashboard_focus/tasks_focus/lists_focus belong to the display task
 * alone, the same reason move_focus() etc. are never called from outside it.
 * Focus identity across revisions is a later step; until then a new snapshot
 * returns to the menu button rather than pointing at a card that may no
 * longer exist. */
static atomic_bool snapshot_focus_reset = true;
/* The server decides when its own snapshot stops being trustworthy; the value
 * comes from `limits.dashboard_cache_max_age_seconds` in the capabilities. 0
 * means the server did not say, in which case the local fallback applies. */
static atomic_uint cache_max_age_s;
/* The snapshot text is held here so the display task can render it in its own
 * context; the upload worker must not draw into the framebuffer it does not
 * own. A mutex is enough: drawing takes milliseconds against a refresh of half
 * a second.
 *
 * Must stay at or above API_RESPONSE_MAX in api_client.c. The copy in
 * screen_snapshot_received uses snprintf, which truncates without a word: a
 * snapshot that passed the fetch would then fail to parse here, and the panel
 * would go empty for a reason no log line names. This buffer lives in PSRAM, so
 * the size is nearly free. */
#define SNAPSHOT_MAX 16384
static char *snapshot_json;
static SemaphoreHandle_t snapshot_lock;
/* Focus and scroll belong to the display task alone; nothing else touches them.
 * -1 is the menu button, which is where the dashboard is entered and which now
 * opens the view selector rather than the recording list directly. */
#define BODY_TOP (STATUS_BAR_HEIGHT + HEADER_HEIGHT + 8)
#define BODY_BOTTOM 792
static int dashboard_focus = -1;
static int dashboard_scroll;
/* The open detail. Its text is a read snapshot: dashboard updates keep arriving
 * in the background but must not change or close what is being read. */
#define ENTITY_MAX 6144
static char *entity_json;
/* Written by the upload worker, read by the display task while drawing: the
 * same handover the snapshot needs, and it needs the same lock. */
static SemaphoreHandle_t entity_lock;
static bool detail_open, detail_waiting;
static int detail_line;
/* The id the detail view is currently showing, captured once when it opens —
 * dashboard_walk() only knows the focused card's id at that moment, and
 * complete_task needs it again later, whenever the reader actually presses
 * the action. 0 = "Zurück" carries the focus, 1 = the action does; only
 * meaningful while the open entity's own action.type is one this build
 * implements (see dashboard_entity_has_action()). */
static char detail_entity_id[40];
static int detail_action_focus;
/* The history view. Same handover as the snapshot and the entity: written by
 * the upload worker, parsed by the display task, so it needs the same lock. */
#define HISTORY_MAX 8192
static char *history_json;
static SemaphoreHandle_t history_lock;
static bool history_open, history_waiting;
/* -1 is the history button in the header, which is how the list is left. It is
 * the same convention the dashboard uses for that button, so "focus -1 means
 * the header button" holds in both views. */
static int history_focus = -1;
static int history_scroll;
/* One past recording, opened from the list. It is an ordinary dashboard
 * envelope and is drawn by the ordinary dashboard renderer. */
static char *session_json;
static SemaphoreHandle_t session_lock;
static bool session_open, session_waiting;
/* Tasks and lists are the same snapshot as the dashboard, just walked with a
 * narrower section filter (dashboard_map.h::dashboard_surface) — no separate
 * fetch, no separate JSON buffer. Each keeps its own focus/scroll so leaving
 * and returning does not lose the reader's place, the same reasoning the
 * dashboard and the history list already follow independently. */
static bool tasks_open, lists_open;
static int tasks_focus = -1, tasks_scroll;
static int lists_focus = -1, lists_scroll;
/* The menu button now opens this instead of jumping straight to the
 * recording list. 0=dashboard, 1=tasks, 2=lists, 3=history. */
static bool selector_open;
static int selector_focus;

/* Which of the three dashboard-family views is showing, and its own focus and
 * scroll — tasks and lists are otherwise the plain dashboard renderer with a
 * narrower section filter, so everything downstream of these three just asks
 * "which one" instead of duplicating draw_dashboard()/move_focus() per view. */
static dashboard_surface active_surface(void) {
    if (tasks_open) return DASHBOARD_SURFACE_TASKS;
    if (lists_open) return DASHBOARD_SURFACE_LISTS;
    return DASHBOARD_SURFACE_MAIN;
}
static int *active_focus_ptr(void) {
    if (tasks_open) return &tasks_focus;
    if (lists_open) return &lists_focus;
    return &dashboard_focus;
}
static int *active_scroll_ptr(void) {
    if (tasks_open) return &tasks_scroll;
    if (lists_open) return &lists_scroll;
    return &dashboard_scroll;
}
#define STATUS_TIME_UNKNOWN 0xFFFFFFFFu
#define PARTIAL_REFRESH_LIMIT 200

/* Non-blocking, and a full queue drops the message rather than stalling its
 * sender: the display task is the slow party at half a second per refresh, and
 * neither the button task nor the upload worker may wait on it.
 *
 * Returns whether the message actually reached the queue. Only the ambient
 * coalescing needs that answer, but it needs it: a dropped request must not
 * leave its latch set. */
static bool post(const screen_message *message) {
    return queue && xQueueSend(queue, message, 0) == pdTRUE;
}

/* At most one ambient redraw waits at a time; see queue_redraw. Declared here
 * because the display task clears it when it takes the message. */
static atomic_bool redraw_pending;

// The embedded hex font is what is left of the provisional badges from H3. Only
// the portrait variant is still used, by the saved message; the landscape one
// went with the recording seconds counter.
static void draw_glyph_portrait(unsigned char *buffer,int glyph,int logical_x,int logical_y) {
    if(glyph<0||glyph>15)return;
    for(int sy=0;sy<40;sy++)for(int sx=0;sx<24;sx++) {
        unsigned char source=hex[glyph*120+sy*3+sx/8];
        if(source&(0x80>>(sx%8))) {
            int px=logical_y+sy,py=479-(logical_x+sx);
            if(px>=0&&px<800&&py>=0&&py<480)buffer[py*100+px/8]&=~(0x80>>(px%8));
        }
    }
}

static void draw_header(unsigned char *buffer) {
    /* While the list is open the header button is its way out, so it carries
     * the focus marker whenever the selection sits on it. Otherwise the marker
     * follows whichever dashboard-family view is active. One button, one
     * meaning, in every view — read directly rather than through a cached
     * flag, since this runs in the same task that owns all four focuses. */
    header_state state = {.focused = history_open ? history_focus < 0
                                                  : *active_focus_ptr() < 0,
                          .selector_open = selector_open,
                          .selector_focus = selector_focus,
                          .active_view = tasks_open ? 1 : lists_open ? 2
                                       : history_open ? 3 : 0};
    /* What ages is the contact, not the content: `snapshot_at_us` is set on
     * every accepted poll, including one that returns an unchanged dashboard.
     * A snapshot the server keeps confirming stays current no matter how old
     * its text is. */
    int64_t age_us = esp_timer_get_time() - atomic_load(&snapshot_at_us);
    if (age_us < 0) age_us = 0;
    unsigned age_s = (unsigned)(age_us / 1000000);
    state.age_minutes = age_s / 60;
    state.snapshot = header_snapshot_for(atomic_load(&snapshot_seen),
                                         atomic_load(&snapshot_empty),
                                         atomic_load(&status_network),
                                         age_s, atomic_load(&cache_max_age_s));
    header_draw(buffer, &state);
}

/* Copy under the lock, then work on the copy: drawing parses the text and must
 * not have it change underneath. */
static bool entity_take(char *into, size_t capacity) {
    if (!entity_json || !entity_lock) return false;
    if (xSemaphoreTake(entity_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    snprintf(into, capacity, "%s", entity_json);
    xSemaphoreGive(entity_lock);
    return into[0] != 0;
}

static void draw_detail(unsigned char *buffer) {
    if (detail_waiting) {
        const char *line = "wird geladen …";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        return;
    }
    char *copy = heap_caps_malloc(ENTITY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy || !entity_take(copy, ENTITY_MAX)) {
        const char *line = "Details nicht abrufbar";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        free(copy);
        return;
    }
    int page = 1;
    int total = dashboard_entity_draw(buffer, copy, BODY_TOP, BODY_BOTTOM,
                                      detail_line, &page, detail_action_focus == 1);
    ESP_LOGI("detail", "line=%d of %d page=%d", detail_line, total, page);
    free(copy);
}

static void page_detail(int delta) {
    char *copy = heap_caps_malloc(ENTITY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy) return;
    if (!entity_take(copy, ENTITY_MAX)) { free(copy); return; }
    int page = 1;
    int total = dashboard_entity_draw(NULL, copy, BODY_TOP, BODY_BOTTOM, 0, &page, false);
    free(copy);
    int next = detail_line + delta * page;
    if (next > total - page) next = total - page;
    if (next < 0) next = 0;
    detail_line = next;
}

/* Whether the currently open detail's own entity carries an action this
 * build implements — decides whether the detail's up/down buttons pick
 * between "Zurück" and it, instead of paging the body text. */
static bool detail_current_has_action(void) {
    char *copy = heap_caps_malloc(ENTITY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy) return false;
    bool has = entity_take(copy, ENTITY_MAX) && dashboard_entity_has_action(copy);
    free(copy);
    return has;
}

static void open_detail(void) {
    dashboard_plan plan = {0};
    if (snapshot_json && snapshot_lock &&
        xSemaphoreTake(snapshot_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        if (snapshot_json[0])
            dashboard_walk(NULL, snapshot_json, BODY_TOP, BODY_BOTTOM, 0,
                           *active_focus_ptr(), &plan, active_surface());
        xSemaphoreGive(snapshot_lock);
    }
    if (!plan.focus_has_entity) {
        ESP_LOGW("detail", "focused card has no entity reference");
        return;
    }
    /* Follow the card's own action rather than assuming every reference is an
     * entity. A session card names `open_session` and points at a session,
     * which the entity endpoint does not serve and answers with 404 — the
     * device was asking the wrong route a question it could not have.
     *
     * `open_session` has a home already: the same view the history list opens,
     * fed by the same request. `open_clarification` is served by the entity
     * route because a question *is* one of its types, so it stays here.
     * Anything else stays visible and does nothing, which is what the contract
     * says an unimplemented action must do. */
    if (strcmp(plan.focus_action, "open_session") == 0) {
        if (session_json && session_lock &&
            xSemaphoreTake(session_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
            session_json[0] = 0;
            xSemaphoreGive(session_lock);
        }
        session_open = true;
        session_waiting = true;
        api_client_open_session(plan.focus_id);
        return;
    }
    if (plan.focus_action[0] && strcmp(plan.focus_action, "open_entity") != 0 &&
        strcmp(plan.focus_action, "open_clarification") != 0) {
        ESP_LOGI("detail", "action '%s' is not implemented on this surface",
                 plan.focus_action);
        return;
    }
    if (entity_json && entity_lock &&
        xSemaphoreTake(entity_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        entity_json[0] = 0;
        xSemaphoreGive(entity_lock);
    }
    detail_open = true;
    detail_waiting = true;
    detail_line = 0;
    detail_action_focus = 0;
    snprintf(detail_entity_id, sizeof(detail_entity_id), "%s", plan.focus_id);
    api_client_open_entity(plan.focus_type, plan.focus_id);
}

/* --- history view --------------------------------------------------------- */

/* The rows are parsed straight out of the response each time it is drawn rather
 * than cached as a struct array: the list is short, the panel redraws at most a
 * couple of times per second, and one representation cannot drift from another.
 * Returns the number of rows the response holds; `canvas` may be NULL to count
 * and measure without drawing. */
static int history_rows(unsigned char *canvas, const char *json,
                        int scroll, int focus, char *selected, size_t capacity) {
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsArray(root)) { cJSON_Delete(root); return 0; }
    /* The status bar and the header row are already on the canvas at this
     * point, so anything scrolled above BODY_TOP must not be drawn at all —
     * clipping here is what keeps the list out of the bars. Rows are drawn only
     * when they fit whole, which the scrolling guarantees for every row that
     * can hold the focus. */
    int y = BODY_TOP - scroll;
    /* The clock is asked once per pass, so every row and the header agree on
     * whether the times are local. */
    bool local = clock_ready();
    if (canvas && y >= BODY_TOP)
        history_header_draw(canvas, 12, y, CARD_FULL_WIDTH, local);
    y += HISTORY_HEADER_HEIGHT;
    int index = 0;
    cJSON *item;
    cJSON_ArrayForEach(item, root) {
        history_row row = {0};
        cJSON *state = cJSON_GetObjectItemCaseSensitive(item, "state");
        cJSON *created = cJSON_GetObjectItemCaseSensitive(item, "created_at");
        history_format_time(row.when, sizeof(row.when),
                            cJSON_IsString(created) ? created->valuestring : NULL, local);
        snprintf(row.state, sizeof(row.state), "%s",
                 history_state_label(cJSON_IsString(state) ? state->valuestring : NULL));
        /* Presence is the signal; the server's wording is never rendered. */
        row.failed = cJSON_IsString(cJSON_GetObjectItemCaseSensitive(item, "last_error"));
        if (selected && index == focus) {
            cJSON *id = cJSON_GetObjectItemCaseSensitive(item, "client_session_id");
            if (cJSON_IsString(id)) snprintf(selected, capacity, "%s", id->valuestring);
        }
        if (canvas && y >= BODY_TOP && y + HISTORY_ROW_HEIGHT <= BODY_BOTTOM)
            history_row_draw(canvas, &row, 12, y, CARD_FULL_WIDTH, index == focus);
        y += HISTORY_ROW_HEIGHT;
        index++;
    }
    cJSON_Delete(root);
    return index;
}

static bool history_take(char *into, size_t capacity) {
    if (!history_json || !history_lock) return false;
    if (xSemaphoreTake(history_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    snprintf(into, capacity, "%s", history_json);
    xSemaphoreGive(history_lock);
    return into[0] != 0;
}

static void draw_history(unsigned char *buffer) {
    if (history_waiting) {
        const char *line = "wird geladen …";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        return;
    }
    char *copy = heap_caps_malloc(HISTORY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy || !history_take(copy, HISTORY_MAX)) {
        const char *line = "Verlauf nicht abrufbar";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        free(copy);
        return;
    }
    if (history_rows(buffer, copy, history_scroll, history_focus, NULL, 0) == 0) {
        const char *line = "Noch keine Aufnahmen";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
    }
    free(copy);
}

/* Move the selection and scroll just enough to keep it visible. The list is a
 * single column of equal rows, so this needs none of the dashboard's paging. */
static void move_history_focus(int delta) {
    char *copy = heap_caps_malloc(HISTORY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy) return;
    if (!history_take(copy, HISTORY_MAX)) { free(copy); return; }
    int count = history_rows(NULL, copy, 0, -1, NULL, 0);
    free(copy);
    if (count <= 0) return;
    int next = history_focus + delta;
    /* The ring runs from the header button through the rows and stops at both
     * ends rather than wrapping: on a panel that takes half a second to redraw,
     * a wrap past the last entry looks like the list jumped. */
    if (next < -1) next = -1;
    if (next > count - 1) next = count - 1;
    history_focus = next;
    if (next < 0) { history_scroll = 0; return; }

    int top = HISTORY_HEADER_HEIGHT + next * HISTORY_ROW_HEIGHT;
    int viewport = BODY_BOTTOM - BODY_TOP;
    if (top - history_scroll < 0) history_scroll = top;
    else if (top + HISTORY_ROW_HEIGHT - history_scroll > viewport)
        history_scroll = top + HISTORY_ROW_HEIGHT - viewport;
    if (history_scroll < 0) history_scroll = 0;
}

static void open_history(void) {
    if (history_json && history_lock &&
        xSemaphoreTake(history_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        history_json[0] = 0;
        xSemaphoreGive(history_lock);
    }
    history_open = true;
    history_waiting = true;
    history_focus = -1;
    history_scroll = 0;
    api_client_open_history();
}

/* --- view selector --------------------------------------------------------- */

/* Reachable from the header button in any of the four views. Lands on
 * whichever one is currently showing, so activating again without moving
 * closes it without changing anything — the same "re-select what's already
 * open" no-op the dashboard-family views give for free. */
static void open_selector(void) {
    selector_open = true;
    selector_focus = tasks_open ? 1 : lists_open ? 2 : history_open ? 3 : 0;
}

static void move_selector_focus(int delta) {
    /* The row runs left to right; the up button sends delta=-1 everywhere
     * else, which would move the cursor left. Flipped here only — reported
     * as more intuitive for a horizontal row than the vertical convention it
     * would otherwise inherit unchanged. */
    int next = selector_focus - delta;
    /* Same non-wrapping ring as the history list: a wrap past either end
     * looks like a jump on a panel that takes half a second to redraw. */
    if (next < 0) next = 0;
    if (next > 3) next = 3;
    selector_focus = next;
}

static void activate_selector(void) {
    selector_open = false;
    if (selector_focus == 3) {
        if (!history_open) open_history();
        return;
    }
    history_open = history_waiting = false;
    tasks_open = selector_focus == 1;
    lists_open = selector_focus == 2;
}

static bool session_take(char *into, size_t capacity) {
    if (!session_json || !session_lock) return false;
    if (xSemaphoreTake(session_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    snprintf(into, capacity, "%s", session_json);
    xSemaphoreGive(session_lock);
    return into[0] != 0;
}

/* One past recording. The payload is an ordinary dashboard envelope, so it goes
 * through the ordinary dashboard renderer: a second renderer for the same
 * schema would be a second place for the layout to drift. Nothing in it is
 * focusable — the only action here is going back. */
static void draw_session(unsigned char *buffer) {
    if (session_waiting) {
        const char *line = "wird geladen …";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        return;
    }
    char *copy = heap_caps_malloc(SNAPSHOT_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy || !session_take(copy, SNAPSHOT_MAX)) {
        const char *line = "Aufnahme nicht abrufbar";
        text_draw(buffer, &text_font_body, 24, BODY_TOP + 24, line, strlen(line));
        free(copy);
        return;
    }
    dashboard_walk(buffer, copy, BODY_TOP, BODY_BOTTOM, 0, -1, NULL,
                   DASHBOARD_SURFACE_ALL);
    free(copy);
}

/* Open the recording the list has selected. */
static void open_session(void) {
    char *copy = heap_caps_malloc(HISTORY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!copy) return;
    char id[40] = {0};
    if (history_take(copy, HISTORY_MAX))
        history_rows(NULL, copy, 0, history_focus, id, sizeof(id));
    free(copy);
    if (!id[0]) {
        ESP_LOGW("history", "selected row carries no session id");
        return;
    }
    if (session_json && session_lock &&
        xSemaphoreTake(session_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        session_json[0] = 0;
        xSemaphoreGive(session_lock);
    }
    session_open = true;
    session_waiting = true;
    api_client_open_session(id);
}

static void draw_dashboard(unsigned char *buffer) {
    if (!snapshot_json || !snapshot_lock) return;
    if (xSemaphoreTake(snapshot_lock, pdMS_TO_TICKS(200)) != pdTRUE) return;
    if (snapshot_json[0])
        dashboard_walk(buffer, snapshot_json, BODY_TOP, BODY_BOTTOM,
                       *active_scroll_ptr(), *active_focus_ptr(), NULL,
                       active_surface());
    xSemaphoreGive(snapshot_lock);
}

/* Rebuild the plan and move the focus. Done here so measuring, scrolling and
 * drawing all see the same snapshot. */
static void move_focus(int delta) {
    dashboard_plan plan = {0};
    dashboard_surface surface = active_surface();
    if (snapshot_json && snapshot_lock &&
        xSemaphoreTake(snapshot_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        if (snapshot_json[0])
            dashboard_walk(NULL, snapshot_json, BODY_TOP, BODY_BOTTOM, 0, -1,
                           &plan, surface);
        xSemaphoreGive(snapshot_lock);
    }
    if (!delta) return;   /* a plain redraw request */
    int *focus = active_focus_ptr(), *scroll = active_scroll_ptr();
    int next = *focus + delta;
    if (next < -1) next = -1;
    if (next >= plan.focusable) next = plan.focusable ? plan.focusable - 1 : -1;
    *focus = next;
    *scroll = next < 0 ? 0
        : dashboard_scroll_for(&plan, next, *scroll, BODY_BOTTOM - BODY_TOP);
    ESP_LOGI("dashboard", "surface=%d focus=%d of %d scroll=%d", surface, next,
             plan.focusable, *scroll);
}

static void draw_status(unsigned char *buffer) {
    unsigned minutes = atomic_load(&status_minutes);
    status_state state = {
        .time_valid = minutes != STATUS_TIME_UNKNOWN,
        .hour = minutes == STATUS_TIME_UNKNOWN ? 0 : (int)(minutes / 60),
        .minute = minutes == STATUS_TIME_UNKNOWN ? 0 : (int)(minutes % 60),
        .wifi_connected = atomic_load(&status_network),
        .recording = atomic_load(&status_recording),
        .queue_ready = atomic_load(&status_pending),
        .queue_attention = atomic_load(&status_attention),
        .storage_low = atomic_load(&status_storage_low),
        .storage_block = atomic_load(&status_storage_block),
        .battery_known = false, /* until the TG28 is read; see the roadmap */
    };
    status_bar_draw(buffer, &state);
}
// Only the display task uses this callback context.
static unsigned char *qr_buffer;
static int qr_left,qr_top;
static void draw_qr(esp_qrcode_handle_t qr) {
    int size = esp_qrcode_get_size(qr);
    int scale = 196 / (size + 8); // Four-module quiet zone on every side.
    int origin_x = qr_left + (196 - size * scale) / 2;
    int origin_y = qr_top + (196 - size * scale) / 2;
    for (int y=0;y<size;y++) for(int x=0;x<size;x++) {
        if (!esp_qrcode_get_module(qr,x,y)) continue;
        for(int dy=0;dy<scale;dy++) for(int dx=0;dx<scale;dx++) {
            int lx=origin_x+x*scale+dx,ly=origin_y+y*scale+dy;
            int px=ly,py=479-lx;
            qr_buffer[py*100+px/8] &= ~(128 >> (px%8));
        }
    }
}
static void screen_task(void *unused) {
    unsigned char *buffer = heap_caps_malloc(48000,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    unsigned char *previous = heap_caps_malloc(48000,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (!buffer || !previous) { free(buffer); free(previous); ESP_LOGE("screen", "No framebuffer memory"); vTaskDelete(NULL); return; }
    bool initialized=false;
    screen_state previous_state=SCREEN_CONNECTING;
    unsigned partial_count=0;
    epaper_port_init();
    screen_message message;
    while (xQueueReceive(queue, &message, portMAX_DELAY)) {
        if (message.ambient) atomic_store(&redraw_pending, false);
        /* Test-and-clear: fires exactly once per snapshot that actually
         * arrived, however many redraws happen between checks. Safe to touch
         * the three focuses directly here — this is the one task that owns
         * them. */
        if (atomic_exchange(&snapshot_focus_reset, false)) {
            dashboard_focus = tasks_focus = lists_focus = -1;
            dashboard_scroll = tasks_scroll = lists_scroll = 0;
        }
        if (message.window_test) {
            /* The probe writes into the live framebuffer instead of reloading a
             * background, so the panel keeps whatever it currently shows and
             * only the rectangle is driven. The next ordinary screen message
             * restores the background through the usual diff path. */
            if (!initialized) {
                ESP_LOGW("screen", "window probe needs an established base first");
                continue;
            }
            if (!message.byte_w || !message.rows ||
                message.byte_x + message.byte_w > 100 || message.row + message.rows > 480) {
                ESP_LOGW("screen", "window probe rectangle out of range");
                continue;
            }
            /* Not a plain bar: a solid rectangle looks identical mirrored. The
             * white stripe sits in the upper third, so the panel shows whether
             * the content inside the window is upright or flipped. */
            for (unsigned row = 0; row < message.rows; row++)
                memset(buffer + (message.row + row) * 100 + message.byte_x, 0x00, message.byte_w);
            unsigned stripe_from = message.rows / 6;
            unsigned stripe_to = message.rows / 3;
            if (stripe_to <= stripe_from) stripe_to = stripe_from + 1;
            if (stripe_to > message.rows) stripe_to = message.rows;
            for (unsigned row = stripe_from; row < stripe_to; row++)
                memset(buffer + (message.row + row) * 100 + message.byte_x, 0xFF, message.byte_w);
            int64_t started = esp_timer_get_time();
            EPD_Display_Partial_Window(buffer, (UWORD)message.byte_x, (UWORD)message.row,
                                       (UWORD)message.byte_w, (UWORD)message.rows);
            int64_t elapsed_ms = (esp_timer_get_time() - started) / 1000;
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen",
                     "window probe: rect bytes x=%u w=%u rows y=%u h=%u -> panel pixels x=%u..%u y=%u..%u in %lld ms",
                     message.byte_x, message.byte_w, message.row, message.rows,
                     message.byte_x * 8, (message.byte_x + message.byte_w) * 8 - 1,
                     message.row, message.row + message.rows - 1, elapsed_ms);
            continue;
        }
        if (message.focus_move || message.focus_activate) {
            if (message.focus_move) {
                /* Whichever view is open owns the buttons: a detail pages its
                 * text, the history and the selector move their own
                 * selection, and only a dashboard-family view (dashboard,
                 * tasks, lists) moves the card focus. */
                if (detail_open) {
                    /* An entity with an action trades paging for choosing
                     * between "Zurück" and it — agreed as the simpler of two
                     * options, since a page-then-choose ring is harder to get
                     * right without hardware to check it against, and the
                     * entities that carry an action today are short enough
                     * that paging was never doing anything there anyway. */
                    if (detail_current_has_action()) {
                        int next = detail_action_focus - message.focus_delta;
                        if (next < 0) next = 0;
                        if (next > 1) next = 1;
                        detail_action_focus = next;
                    } else {
                        page_detail(message.focus_delta);
                    }
                }
                else if (session_open) { /* nothing to move: one page, back only */ }
                else if (selector_open) move_selector_focus(message.focus_delta);
                else if (history_open) move_history_focus(message.focus_delta);
                else move_focus(message.focus_delta);
            } else if (detail_open) {
                /* "Zurück" focused, or no action on this entity at all: leave,
                 * same as before. The action focused: fire the mutation and
                 * stay open — the response redraws the same view once it
                 * lands, through screen_entity_received like any other fetch. */
                if (detail_action_focus == 1 && detail_current_has_action())
                    api_client_complete_task(detail_entity_id);
                else
                    detail_open = detail_waiting = false;   /* back to the overview */
            } else if (session_open) {
                /* Back to whatever opened it: the history list or, since a
                 * session card follows its own action, the dashboard. Closing
                 * this view alone is enough — the draw path picks the next open
                 * one by itself. */
                session_open = session_waiting = false;
            } else if (selector_open) {
                activate_selector();
            } else if (history_open) {
                /* The header button now opens the selector, same as every
                 * other view; a row opens the recording it names. */
                if (history_focus < 0) open_selector();
                else open_session();
            } else if (*active_focus_ptr() < 0) {
                open_selector();
            } else {
                open_detail();
            }
            /* Fall through into the ordinary redraw of the dashboard screen. */
            message.state = previous_state >= SCREEN_READY ? previous_state : SCREEN_READY;
            message.focus_move = message.focus_activate = false;
        }
        if (message.card_demo) {
            if (!initialized) {
                ESP_LOGW("screen", "card sheet needs an established base first");
                continue;
            }
            const int top = STATUS_BAR_HEIGHT + HEADER_HEIGHT, bottom_edge = 792;
            logical_fill(buffer, 0, top, 480, bottom_edge);
            const card_content demo[] = {
                {.title="Rückmeldung zum Konzept geben", .preview="Vor dem nächsten Termin",
                 .icon=ICON_TASK, .severity=ICON_COUNT, .urgency=STRIP_HATCH,
                 .border=CARD_BORDER_EMPHASIS},
                {.title="Wie soll die Session heißen?",
                 .preview="Offene Rückfrage aus der letzten Memo", .status="offen",
                 .icon=ICON_QUESTION, .severity=ICON_COUNT, .urgency=STRIP_LIGHT,
                 .border=CARD_BORDER_THIN, .focused=true},
                {.title="Upload fehlgeschlagen – bitte prüfen",
                 .preview="Zwei Segmente warten seit gestern", .icon=ICON_WARNING,
                 .severity=ICON_SEV_ERROR, .urgency=STRIP_SOLID,
                 .border=CARD_BORDER_CRITICAL},
                {.title="ESP-Dashboard", .preview="Hochformat und servergesteuerte Karten",
                 .icon=ICON_NOTE, .severity=ICON_COUNT, .urgency=STRIP_MEDIUM,
                 .border=CARD_BORDER_THIN},
            };
            int y = top + 8;
            section_heading_draw(buffer, "Heute", 12, y, CARD_FULL_WIDTH);
            y += SECTION_HEADING_HEIGHT + 6;
            for (unsigned i = 0; i < sizeof(demo)/sizeof(demo[0]); i++) {
                card_draw(buffer, &demo[i], 12, y, CARD_FULL_WIDTH);
                y += card_height(&demo[i], CARD_FULL_WIDTH) + CARD_GAP;
            }
            const card_content left = {.title="Kurze Notiz", .icon=ICON_FACT,
                .severity=ICON_COUNT, .urgency=STRIP_PLAIN, .border=CARD_BORDER_THIN};
            const card_content right = {.title="Termin bestätigen", .icon=ICON_TASK,
                .severity=ICON_COUNT, .urgency=STRIP_LIGHT, .border=CARD_BORDER_THIN};
            int row = card_height(&left, CARD_HALF_WIDTH);
            int other = card_height(&right, CARD_HALF_WIDTH);
            if (other > row) row = other;
            card_draw_sized(buffer, &left, 12, y, CARD_HALF_WIDTH, row);
            card_draw_sized(buffer, &right, 12 + CARD_HALF_WIDTH + CARD_GAP, y,
                            CARD_HALF_WIDTH, row);
            int64_t started = esp_timer_get_time();
            logical_push(buffer, 0, top, 480, bottom_edge);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "card sheet drawn, pushed in %lld ms",
                     (esp_timer_get_time() - started) / 1000);
            continue;
        }
        if (message.header_demo) {
            if (!initialized) {
                ESP_LOGW("screen", "header demo needs an established base first");
                continue;
            }
            header_state demo = {0};
            switch (message.cut) {
            case 1: demo = (header_state){.snapshot=HEADER_NEVER,.focused=true}; break;
            case 2: demo = (header_state){.snapshot=HEADER_CURRENT,.age_minutes=0,.focused=true}; break;
            case 3: demo = (header_state){.snapshot=HEADER_CURRENT,.age_minutes=3}; break;
            case 4: demo = (header_state){.snapshot=HEADER_OFFLINE,.age_minutes=47}; break;
            case 5: demo = (header_state){.snapshot=HEADER_EMPTY}; break;
            case 6: demo = (header_state){.snapshot=HEADER_STALE,.age_minutes=185}; break;
            default:
                logical_fill(buffer, 0, STATUS_BAR_HEIGHT, 480,
                             STATUS_BAR_HEIGHT + HEADER_HEIGHT);
                draw_header(buffer);
                goto header_push;
            }
            logical_fill(buffer, 0, STATUS_BAR_HEIGHT, 480,
                         STATUS_BAR_HEIGHT + HEADER_HEIGHT);
            header_draw(buffer, &demo);
        header_push:
            logical_push(buffer, 0, STATUS_BAR_HEIGHT, 480,
                         STATUS_BAR_HEIGHT + HEADER_HEIGHT);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "header demo=%u", message.cut);
            continue;
        }
        if (message.status_demo) {
            if (!initialized) {
                ESP_LOGW("screen", "status demo needs an established base first");
                continue;
            }
            status_state demo = {0};
            switch (message.cut) {
            case 1: break;                                     /* fresh device */
            case 2: demo = (status_state){.time_valid=true,.hour=14,.minute=32,
                                          .wifi_connected=true}; break;
            case 3: demo = (status_state){.time_valid=true,.hour=14,.minute=33,
                                          .wifi_connected=true,.recording=true,
                                          .queue_ready=3}; break;
            case 4: demo = (status_state){.time_valid=true,.hour=9,.minute=5,
                                          .queue_ready=12,.queue_attention=2,
                                          .storage_low=true}; break;
            case 5: demo = (status_state){.time_valid=true,.hour=23,.minute=59,
                                          .wifi_connected=true,.queue_ready=7,
                                          .storage_low=true,.storage_block=true,
                                          .battery_known=true,.battery_percent=42}; break;
            default:
                logical_fill(buffer, 0, 0, 480, STATUS_BAR_HEIGHT);
                draw_status(buffer);
                goto status_push;
            }
            logical_fill(buffer, 0, 0, 480, STATUS_BAR_HEIGHT);
            status_bar_draw(buffer, &demo);
        status_push:
            logical_push(buffer, 0, 0, 480, STATUS_BAR_HEIGHT);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "status demo=%u", message.cut);
            continue;
        }
        if (message.pattern_test) {
            if (!initialized) {
                ESP_LOGW("screen", "pattern sheet needs an established base first");
                continue;
            }
            const int x0 = 0, y0 = 96, x1 = 480, y1 = 792;
            int64_t started = esp_timer_get_time();
            if (message.cut <= STRIP_SOLID) {
                icon_fill(buffer, x0, y0, x1 - x0, y1 - y0, (strip_pattern)message.cut);
            } else {
                /* Five bands across the full width, in order, so neighbouring
                 * steps can be compared where they touch. */
                int band = (y1 - y0) / (STRIP_SOLID + 1);
                for (int step = 0; step <= STRIP_SOLID; step++)
                    icon_fill(buffer, x0, y0 + step * band, x1 - x0, band,
                              (strip_pattern)step);
            }
            logical_push(buffer, x0, y0, x1, y1);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "pattern sheet: step=%u in %lld ms",
                     message.cut, (esp_timer_get_time() - started) / 1000);
            continue;
        }
        if (message.icon_test) {
            if (!initialized) {
                ESP_LOGW("screen", "icon sheet needs an established base first");
                continue;
            }
            const int x0 = 32, y0 = 96, x1 = 448, y1 = 480;
            logical_fill(buffer, x0, y0, x1, y1);
            for (int id = 0; id < ICON_COUNT; id++) {
                int column = id % 8, row = id / 8;
                icon_draw(buffer, (icon_id)id, x0 + 12 + column * 50,
                          y0 + 12 + row * 44, false);
            }
            /* The five urgency steps, in order, as they appear in a side strip,
             * each carrying an art symbol on its plate. This is the actual card
             * treatment, not just the raw pattern. */
            const icon_id kinds[] = {ICON_TASK, ICON_QUESTION, ICON_NOTE,
                                     ICON_WARNING, ICON_RECORDING};
            for (int step = 0; step <= STRIP_SOLID; step++) {
                int left = x0 + 12 + step * 50;
                icon_fill(buffer, left, y1 - 76, 40, 60, (strip_pattern)step);
                icon_draw_badge(buffer, kinds[step], left + 8, y1 - 60);
            }
            logical_push(buffer, x0, y0, x1, y1);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "icon sheet: %d icons and %d strip patterns",
                     ICON_COUNT, STRIP_SOLID + 1);
            continue;
        }
        if (message.text_test) {
            if (!initialized) {
                ESP_LOGW("screen", "text sample needs an established base first");
                continue;
            }
            const int x0 = 40, y0 = 96, x1 = 440, y1 = 400;
            logical_fill(buffer, x0, y0, x1, y1);
            const text_font *font = message.cut == 2 ? &text_font_preview :
                                    message.cut == 1 ? &text_font_body : &text_font_title;
            int64_t started = esp_timer_get_time();
            int drawn = text_draw_wrapped(buffer, font, x0 + 8, y0 + 8,
                                          (x1 - x0) - 16, 8, message.sample);
            logical_push(buffer, x0, y0, x1, y1);
            partial_count++;
            memcpy(previous, buffer, 48000);
            ESP_LOGI("screen", "text sample: cut=%u lines=%d in %lld ms",
                     message.cut, drawn, (esp_timer_get_time() - started) / 1000);
            continue;
        }
        if (message.force_full) message.state = previous_state;
        const unsigned char *background = message.state == SCREEN_SETUP ? setup :
            message.state == SCREEN_CONNECTING ? connecting : message.state == SCREEN_CONNECTED ? connected :
            message.state == SCREEN_READY ? ready : message.state == SCREEN_RECORDING ? recording :
            message.state == SCREEN_MEMO_SAVED ? memo_saved : message.state == SCREEN_ERROR ? error : saved;
        memcpy(buffer, background, 48000);
        if (message.state == SCREEN_ERROR) {
            /* The operating backgrounds are blank now, so this line is drawn
             * live instead of being baked into an asset. */
            const char *line = "Achtung – lokale Diagnose über USB öffnen";
            text_draw(buffer, &text_font_body, 24,
                      STATUS_BAR_HEIGHT + HEADER_HEIGHT + 24, line, strlen(line));
        }
        // Queue, network, clock and storage are local truth and stay visible.
        atomic_store(&status_recording, message.state == SCREEN_RECORDING);
        /* Recording and the moment right after used to swap in a dedicated,
         * mostly blank background and skip the body entirely — a holdover
         * from before the dashboard existed. The status bar's recording dot
         * (above) already says what changed; hiding the dashboard underneath
         * it no longer serves a purpose, so the body stays exactly as it
         * would in SCREEN_READY. */
        if(message.state>=SCREEN_READY){
            draw_status(buffer);
            draw_header(buffer);
            if(message.state==SCREEN_READY || message.state==SCREEN_RECORDING ||
               message.state==SCREEN_MEMO_SAVED){
                if(detail_open)draw_detail(buffer);
                else if(session_open)draw_session(buffer);
                else if(history_open)draw_history(buffer);
                else draw_dashboard(buffer);
            }
        }
        if (message.state == SCREEN_SETUP) {
            qr_buffer = buffer;
            char payload[100];
            snprintf(payload,sizeof(payload),"WIFI:T:WPA;S:Notebook-Setup;P:%s;;",message.password);
            esp_qrcode_config_t config = ESP_QRCODE_CONFIG_DEFAULT();
            config.display_func = draw_qr;
            config.max_qrcode_version = 5;
            config.qrcode_ecc_level = ESP_QRCODE_ECC_MED;
            qr_left = 24; qr_top=122;
            esp_err_t wifi_qr = esp_qrcode_generate(&config,payload);
            qr_left = 24; qr_top=378;
            esp_err_t page_qr = esp_qrcode_generate(&config,"http://192.168.4.1/");
            ESP_LOGI("screen","QR generation: wifi=%s page=%s",esp_err_to_name(wifi_qr),esp_err_to_name(page_qr));
            const char *digits = "0123456789abcdef";
            for (int c=0;c<16 && message.password[c];c++) {
                const char *digit = strchr(digits, message.password[c]);
                if (!digit) continue;
                int glyph = digit - digits;
                draw_glyph_portrait(buffer,glyph,24+c*24,682);
            }
        }
        int left=100,right=-1,top=480,bottom=-1;
        if(initialized) for(int y=0;y<480;y++) for(int x=0;x<100;x++) {
            if(buffer[y*100+x]==previous[y*100+x]) continue;
            if(x<left) left=x;
            if(x>right) right=x;
            if(y<top) top=y;
            if(y>bottom) bottom=y;
        }
        if(initialized && right<0 && !message.force_full) continue;
        // Full update establishes controller base RAM. No deep sleep between partials.
        // Defer periodic ghosting cleanup until recording has ended.
        bool leave_start=previous_state<=SCREEN_SAVED && message.state>=SCREEN_READY;
        /* The ghosting safety net. 20 was far too eager: at one refresh per key
         * press a full update landed in the middle of ordinary navigation. The
         * cleanup rides on view changes, which need a full update anyway; this
         * counter only catches a session that never changes view. See the
         * refresh policy in docs/IMPLEMENTATION_DECISIONS.md. */
        if(!initialized || leave_start || message.force_full ||
           (partial_count>=PARTIAL_REFRESH_LIMIT && message.state!=SCREEN_RECORDING)) {
            int64_t started = esp_timer_get_time();
            EPD_Init(); EPD_Display_Base(buffer); initialized=true; partial_count=0;
            ESP_LOGI("screen","full update state=%d in %lld ms",message.state,
                     (esp_timer_get_time()-started)/1000);
        } else {
            int width=right-left+1;
            int64_t started = esp_timer_get_time();
            EPD_Display_Partial_Frame(buffer);
            partial_count++;
            ESP_LOGI("screen","partial waveform/full canvas state=%d changed=%d,%d %dx%d in %lld ms",
                     message.state,left*8,top,width*8,bottom-top+1,
                     (esp_timer_get_time()-started)/1000);
        }
        memcpy(previous,buffer,48000);
        previous_state=message.state;
    }
}
/* Latching a value is not showing it. These setters only wrote to their atomic,
 * so the bar changed on the panel whenever something else happened to trigger a
 * draw — which meant a crossed-out WLAN symbol on a connected device, and a
 * clock that would never have ticked at all: the minute task calls
 * screen_status_time and nothing else.
 *
 * Asking for a redraw is close to free. The display task compares the new frame
 * against the last one and drops it when nothing moved, so a status that did
 * not actually change costs no refresh. */
static void queue_redraw(void) {
    /* At most one ambient redraw waits at a time. Without this the upload
     * worker, which publishes the queue status twice per pass, would fill the
     * queue with identical requests and crowd out the button presses this whole
     * change exists to protect. The flag is cleared when the display task takes
     * the message, so a later change always gets its own. */
    if (atomic_exchange(&redraw_pending, true)) return;
    screen_message message = {.focus_move=true, .focus_delta=0, .ambient=true};
    /* The latch must not outlive a lost message. `post` never blocks, so a full
     * queue drops the request — and with the flag left standing the display
     * task would never take an ambient message again, which clears it. Every
     * later status change (network, clock, queue counters, storage) would then
     * stay invisible until the next reboot: the counters keep moving, the panel
     * stops following. Observed as a WLAN symbol that never struck through.
     * Clearing it here costs one redundant request at worst. */
    if (!post(&message)) atomic_store(&redraw_pending, false);
}
void screen_status(unsigned pending,unsigned attention,bool storage_low) {
    atomic_store(&status_pending,pending);
    atomic_store(&status_attention,attention);
    atomic_store(&status_storage_low,storage_low);
    queue_redraw();
}
void screen_status_storage_block(bool blocked){atomic_store(&status_storage_block,blocked);queue_redraw();}
void screen_status_network(bool connected){atomic_store(&status_network,connected);queue_redraw();}
void screen_status_time(unsigned minutes_since_midnight){
    atomic_store(&status_minutes,minutes_since_midnight);
    queue_redraw();
}
void screen_memo(screen_state state,unsigned seconds) {
    screen_message message={.state=state,.seconds=seconds};
    post(&message);
}
void screen_start(void) {
    atomic_store(&status_minutes, STATUS_TIME_UNKNOWN);
    snapshot_json = heap_caps_calloc(1, SNAPSHOT_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    entity_json = heap_caps_calloc(1, ENTITY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    history_json = heap_caps_calloc(1, HISTORY_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    session_json = heap_caps_calloc(1, SNAPSHOT_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    snapshot_lock = xSemaphoreCreateMutex();
    entity_lock = xSemaphoreCreateMutex();
    history_lock = xSemaphoreCreateMutex();
    session_lock = xSemaphoreCreateMutex();
    if (!snapshot_json || !entity_json || !history_json || !session_json ||
        !snapshot_lock || !entity_lock || !history_lock || !session_lock)
        ESP_LOGE("screen", "no memory for the dashboard snapshot");
    /* Room for a few messages. It used to be a single slot written with
     * xQueueOverwrite, which was fine while the only producers were rare state
     * changes: a newer screen simply replaced an older one. Once the clock and
     * the status setters also asked for redraws, that same overwrite started
     * swallowing button presses outright — the press never reached the display
     * task and never appeared in the log. User input must not be droppable by
     * background chatter. */
    queue = xQueueCreate(8,sizeof(screen_message));
    if (queue && xTaskCreate(screen_task,"screen",4096,NULL,2,NULL) != pdPASS) {
        vQueueDelete(queue); queue=NULL;
    }
}
void screen_text_test(unsigned which, const char *utf8) {
    screen_message message = {.text_test=true, .cut=which};
    snprintf(message.sample, sizeof(message.sample), "%s", utf8 ? utf8 : "");
    post(&message);
}
void screen_snapshot_cache_limit(unsigned seconds) {
    atomic_store(&cache_max_age_s, seconds);
}
void screen_snapshot_received(const char *json, bool empty) {
    if (snapshot_json && snapshot_lock &&
        xSemaphoreTake(snapshot_lock, pdMS_TO_TICKS(500)) == pdTRUE) {
        snprintf(snapshot_json, SNAPSHOT_MAX, "%s", json ? json : "");
        xSemaphoreGive(snapshot_lock);
    }
    atomic_store(&snapshot_empty, empty);
    atomic_store(&snapshot_at_us, esp_timer_get_time());
    atomic_store(&snapshot_seen, true);
    atomic_store(&snapshot_focus_reset, true);
}
void screen_focus_move(int delta) {
    screen_message message = {.focus_move=true, .focus_delta=delta};
    post(&message);
}
void screen_entity_received(const char *json) {
    if (entity_json && entity_lock &&
        xSemaphoreTake(entity_lock, pdMS_TO_TICKS(500)) == pdTRUE) {
        snprintf(entity_json, ENTITY_MAX, "%s", json ? json : "");
        xSemaphoreGive(entity_lock);
    }
    detail_waiting = false;
    /* Redraw through the queue so the display task stays the only writer. */
    screen_message message = {.focus_move=true, .focus_delta=0};
    post(&message);
}
void screen_history_received(const char *json) {
    if (history_json && history_lock &&
        xSemaphoreTake(history_lock, pdMS_TO_TICKS(500)) == pdTRUE) {
        snprintf(history_json, HISTORY_MAX, "%s", json ? json : "");
        xSemaphoreGive(history_lock);
    }
    history_waiting = false;
    /* A zero move redraws through the ordinary path, so the arrival does not
     * need a drawing path of its own. */
    screen_message message = {.focus_move=true, .focus_delta=0};
    post(&message);
}

void screen_session_received(const char *json) {
    if (session_json && session_lock &&
        xSemaphoreTake(session_lock, pdMS_TO_TICKS(500)) == pdTRUE) {
        snprintf(session_json, SNAPSHOT_MAX, "%s", json ? json : "");
        xSemaphoreGive(session_lock);
    }
    session_waiting = false;
    screen_message message = {.focus_move=true, .focus_delta=0};
    post(&message);
}

void screen_focus_activate(void) {
    screen_message message = {.focus_activate=true};
    post(&message);
}
void screen_card_test(void) {
    screen_message message = {.card_demo=true};
    post(&message);
}
void screen_header_test(unsigned demo) {
    screen_message message = {.header_demo=true, .cut=demo};
    post(&message);
}
void screen_status_test(unsigned demo) {
    screen_message message = {.status_demo=true, .cut=demo};
    post(&message);
}
void screen_pattern_test(unsigned step) {
    screen_message message = {.pattern_test=true, .cut=step};
    post(&message);
}
void screen_icon_test(void) {
    screen_message message = {.icon_test=true};
    post(&message);
}
void screen_refresh(void) {
    screen_message message={.force_full=true};
    post(&message);
}
void screen_window_test(unsigned byte_x, unsigned y,
                        unsigned byte_w, unsigned h) {
    screen_message message = {.window_test=true, .byte_x=byte_x,
                              .row=y, .byte_w=byte_w, .rows=h};
    post(&message);
}
void screen_show(screen_state state, const char *password) {
    screen_message message={.state=state};
    if(password) strncpy(message.password,password,sizeof(message.password)-1);
    post(&message);
}
