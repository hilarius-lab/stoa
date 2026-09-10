/* Host test for the drawing layer: cards, header wording, and the invariants
 * that keep one element from writing into another's space.
 * Runs without ESP-IDF and without hardware:  sh tools/run_ui_test.sh
 */
#define _XOPEN_SOURCE 700
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#include "card.h"
#include "header.h"
#include "history.h"
#include "settings.h"
#include "status_bar.h"
#include "text.h"
#include "dashboard_map.h"

static int failures;
static unsigned char canvas[48000];

static void check(int condition, const char *what) {
    if (!condition) { printf("FAIL %s\n", what); failures++; }
}

static void clear(void) { memset(canvas, 0xFF, sizeof canvas); }

static bool ink_at(int x, int y) {
    if (x < 0 || x >= 480 || y < 0 || y >= 800) return false;
    int px = y, py = 479 - x;
    return (canvas[py * 100 + px / 8] & (0x80 >> (px % 8))) == 0;
}

static void titles(void) {
    /* Codepoints, not bytes: the half width rule would otherwise reject any
     * title with umlauts far too early. */
    check(card_title_length("Termin") == 6, "ascii title length");
    check(card_title_length("Rückmeldung") == 11, "umlaut counts as one");
    check(card_title_length("") == 0, "empty title");
}

static void heights(void) {
    card_content with = {.title = "T", .preview = "P", .severity = ICON_COUNT};
    card_content without = {.title = "T", .severity = ICON_COUNT};
    card_content two_lines = {.title = "Ein Titel, der bei voller Breite ganz sicher zwei Zeilen braucht",
                              .severity = ICON_COUNT};
    check(card_height(&with, CARD_FULL_WIDTH) > card_height(&without, CARD_FULL_WIDTH),
          "a preview line makes the card taller");
    check(card_height(&two_lines, CARD_FULL_WIDTH) > card_height(&without, CARD_FULL_WIDTH),
          "a second title line makes the card taller");
    check(card_height(&without, CARD_FULL_WIDTH) >= CARD_MIN_HEIGHT,
          "cards keep a minimum height");
    /* A half width card never shows a preview, so its height must not depend
     * on whether one was supplied. */
    check(card_height(&with, CARD_HALF_WIDTH) == card_height(&without, CARD_HALF_WIDTH),
          "half width height is independent of the preview");
}

static void containment(void) {
    /* Nothing may leave the card rectangle: two cards side by side would
     * otherwise bleed into each other, and the section frame would be wrong. */
    const int x = 40, y = 200, width = CARD_FULL_WIDTH;
    card_content card = {.title = "Ein sehr langer Titel, der ganz sicher über zwei Zeilen läuft und dann gekürzt wird",
                         .preview = "Eine Vorschau, die ebenfalls deutlich zu lang ist für eine Zeile",
                         .status = "offen", .icon = ICON_TASK, .severity = ICON_SEV_WARNING,
                         .urgency = STRIP_HATCH, .border = CARD_BORDER_CRITICAL};
    clear();
    card_draw(canvas, &card, x, y, width);
    int height = card_height(&card, width);
    int outside = 0;
    for (int py = y - 6; py < y + height + 6; py++)
        for (int px = x - 6; px < x + width + 6; px++)
            if (ink_at(px, py) &&
                (px < x || px >= x + width || py < y || py >= y + height))
                outside++;
    check(outside == 0, "card draws nothing outside its rectangle");

    /* The rounded corners must actually be free. */
    check(!ink_at(x, y), "top left corner is rounded");
    check(!ink_at(x + width - 1, y + height - 1), "bottom right corner is rounded");
}

static void status_fits(void) {
    /* A status mark must never be drawn outside the bubble. The half width card
     * with a wrapping title is the case that used to fail: it showed no preview
     * and therefore reserved no footer row. */
    card_content card = {.title = "Wie soll die Session heißen?", .status = "offen",
                         .icon = ICON_QUESTION, .severity = ICON_COUNT,
                         .urgency = STRIP_LIGHT, .border = CARD_BORDER_THIN};
    card_content silent = card;
    silent.status = NULL;
    check(card_height(&card, CARD_HALF_WIDTH) > card_height(&silent, CARD_HALF_WIDTH),
          "a status mark reserves a footer row");
    const int x = 12, y = 260, width = CARD_HALF_WIDTH;
    int height = card_height(&card, width);
    clear();
    card_draw(canvas, &card, x, y, width);
    int outside = 0;
    for (int py = y - 8; py < y + height + 8; py++)
        for (int px = x - 8; px < x + width + 8; px++)
            if (ink_at(px, py) &&
                (px < x || px >= x + width || py < y || py >= y + height))
                outside++;
    check(outside == 0, "a half width card with a status stays inside itself");
}

static void focus_keeps_urgency(void) {
    /* Focus inverts the text panel only. If it inverted the strip as well, a
     * 25 percent raster would read as 75 and the card would claim a different
     * urgency while selected. */
    const int x = 20, y = 120;
    card_content plain = {.title = "Titel", .icon = ICON_NOTE, .severity = ICON_COUNT,
                          .urgency = STRIP_LIGHT, .border = CARD_BORDER_THIN};
    card_content focused = plain;
    focused.focused = true;

    clear();
    card_draw(canvas, &plain, x, y, CARD_FULL_WIDTH);
    int strip_ink = 0;
    for (int py = y + 20; py < y + 50; py++)
        for (int px = x + 4; px < x + CARD_STRIP - 4; px++)
            if (ink_at(px, py)) strip_ink++;

    clear();
    card_draw(canvas, &focused, x, y, CARD_FULL_WIDTH);
    int focused_strip_ink = 0, panel_ink = 0;
    for (int py = y + 20; py < y + 50; py++) {
        for (int px = x + 4; px < x + CARD_STRIP - 4; px++)
            if (ink_at(px, py)) focused_strip_ink++;
        for (int px = x + CARD_STRIP + 20; px < x + CARD_FULL_WIDTH - 20; px++)
            if (ink_at(px, py)) panel_ink++;
    }
    check(strip_ink == focused_strip_ink, "focus leaves the urgency strip alone");
    check(panel_ink > 30 * 200, "focus fills the text panel");
}

static void shared_row_height(void) {
    /* Two cards in a row are drawn at one height; neither may spill out of it. */
    card_content short_title = {.title = "Kurz", .icon = ICON_FACT, .severity = ICON_COUNT};
    card_content long_title = {.title = "Termin bestätigen", .icon = ICON_TASK,
                               .severity = ICON_COUNT};
    int row = card_height(&long_title, CARD_HALF_WIDTH);
    check(row >= card_height(&short_title, CARD_HALF_WIDTH), "row takes the taller card");
    clear();
    const int x = 12, y = 300;
    card_draw_sized(canvas, &short_title, x, y, CARD_HALF_WIDTH, row);
    int outside = 0;
    for (int py = y - 4; py < y + row + 4; py++)
        for (int px = x - 4; px < x + CARD_HALF_WIDTH + 4; px++)
            if (ink_at(px, py) && (py < y || py >= y + row)) outside++;
    check(outside == 0, "a card drawn at the row height stays inside it");
}

static void section_heading(void) {
    clear();
    const int x = 12, y = 150, width = CARD_FULL_WIDTH;
    section_heading_draw(canvas, "Ein Sektionstitel, der viel zu lang für eine Zeile ist", x, y, width);
    int outside = 0;
    for (int py = y - 6; py < y + SECTION_HEADING_HEIGHT + 6; py++)
        for (int px = x - 6; px < x + width + 6; px++)
            if (ink_at(px, py) &&
                (px < x || px >= x + width || py < y || py >= y + SECTION_HEADING_HEIGHT))
                outside++;
    check(outside == 0, "section heading stays in its box");
    int rule = 0;
    for (int px = x; px < x + width; px++)
        if (ink_at(px, y + SECTION_HEADING_HEIGHT - 3)) rule++;
    check(rule == width, "section heading draws a full width rule");
}

static void mapping(void) {
    /* Every step of the contract's colour roles, and the rule that an unknown
     * role never lands below neutral. */
    check(dashboard_urgency("danger") == STRIP_SOLID, "danger is the darkest step");
    check(dashboard_urgency("warning") == STRIP_HATCH, "warning is hatched");
    check(dashboard_urgency("primary") == STRIP_MEDIUM, "primary is the middle step");
    check(dashboard_urgency("neutral") == STRIP_LIGHT, "neutral is light");
    check(dashboard_urgency("muted") == STRIP_PLAIN, "muted is plain");
    check(dashboard_urgency("a-role-from-the-future") == STRIP_LIGHT,
          "an unknown role is never quieter than neutral");
    check(dashboard_urgency(NULL) == STRIP_LIGHT, "a missing role is never quieter than neutral");

    check(dashboard_icon("question") == ICON_QUESTION, "known icon token");
    check(dashboard_icon("sparkle") == ICON_GENERIC, "unknown icon token falls back");
    check(dashboard_icon(NULL) == ICON_GENERIC, "missing icon token falls back");

    check(dashboard_border("critical") == CARD_BORDER_CRITICAL, "critical border");
    check(dashboard_border("none") == CARD_BORDER_THIN, "none is thin");
    check(dashboard_border("brand-new") == CARD_BORDER_THIN, "unknown border is thin");

    check(dashboard_severity("error") == ICON_SEV_ERROR, "known severity");
    check(dashboard_severity("catastrophic") == ICON_COUNT, "unknown severity has no mark");

    /* Severity may raise the urgency, never lower it. */
    check(dashboard_combined_urgency("muted", "critical") == STRIP_SOLID,
          "a critical card is not drawn as muted");
    check(dashboard_combined_urgency("danger", "info") == STRIP_SOLID,
          "a harmless severity does not calm a dangerous role");
    check(dashboard_combined_urgency("warning", "unknown-value") == STRIP_HATCH,
          "an unknown severity neither escalates nor weakens");
    for (int i = 0; i <= STRIP_SOLID; i++) {
        const char *roles[] = {"muted", "neutral", "primary", "warning", "danger"};
        check(dashboard_combined_urgency(roles[i], NULL) == (strip_pattern)i,
              "roles map to the steps in order");
    }

    check(dashboard_focusable("open_entity", false), "a supported action is focusable");
    check(dashboard_focusable(NULL, true), "an entity reference is focusable");
    check(!dashboard_focusable(NULL, false), "a heading is not focusable");
    check(!dashboard_focusable("delete_everything", false),
          "an unsupported action alone is not focusable");
}

static void paging(void) {
    /* A hand built plan: three rows of 100 px in a 250 px viewport. */
    dashboard_plan plan = {0};
    for (int i = 0; i < 6; i++)
        plan.rows[i] = (dashboard_row){.top = i * 100, .height = 100,
                                       .first_focus = i, .second_focus = -1};
    plan.count = 6;
    plan.focusable = 6;
    plan.content_height = 600;
    const int viewport = 250;

    check(dashboard_row_of(&plan, 3) == 3, "focus index maps to its row");
    check(dashboard_row_of(&plan, 99) == -1, "an unknown focus has no row");

    /* A visible row must not move the page: otherwise the list would crawl
     * under the reader on every step. */
    check(dashboard_scroll_for(&plan, 0, 0, viewport) == 0, "first row needs no paging");
    check(dashboard_scroll_for(&plan, 1, 0, viewport) == 0, "a visible row does not page");

    /* Row 2 spans 200..300 and does not fit in 0..250, so the page advances. */
    int scrolled = dashboard_scroll_for(&plan, 2, 0, viewport);
    check(scrolled > 0, "an invisible row advances the page");
    check(scrolled <= 200, "the page never scrolls past the row itself");
    check(200 - scrolled >= 0 && 300 <= scrolled + viewport,
          "after paging the row is fully visible");
    /* Snapped to a row boundary, so nothing is cut in half. */
    bool on_boundary = false;
    for (int i = 0; i < plan.count; i++)
        if (plan.rows[i].top == scrolled) on_boundary = true;
    check(on_boundary || scrolled == 0, "the page lands on a row boundary");

    /* Walking down through every row must always end up visible and must never
     * scroll past the content. */
    int scroll = 0;
    for (int focus = 0; focus < plan.focusable; focus++) {
        scroll = dashboard_scroll_for(&plan, focus, scroll, viewport);
        int row = dashboard_row_of(&plan, focus);
        check(plan.rows[row].top >= scroll &&
              plan.rows[row].top + plan.rows[row].height <= scroll + viewport,
              "every focus step ends fully visible");
        check(scroll <= plan.content_height - viewport, "never scrolled past the end");
    }
    /* And back up again. */
    for (int focus = plan.focusable - 1; focus >= 0; focus--) {
        scroll = dashboard_scroll_for(&plan, focus, scroll, viewport);
        int row = dashboard_row_of(&plan, focus);
        check(plan.rows[row].top >= scroll &&
              plan.rows[row].top + plan.rows[row].height <= scroll + viewport,
              "every backwards step ends fully visible");
        check(scroll >= 0, "never scrolled above the start");
    }

    /* A row taller than the viewport must still make progress rather than loop. */
    dashboard_plan tall = {0};
    tall.rows[0] = (dashboard_row){.top = 0, .height = 400, .first_focus = 0, .second_focus = -1};
    tall.count = 1; tall.focusable = 1; tall.content_height = 400;
    check(dashboard_scroll_for(&tall, 0, 0, viewport) >= 0, "an oversized row terminates");
}

static void focus_identity(void) {
    dashboard_focus_identity old = {0};
    snprintf(old.component_id, sizeof old.component_id, "home:task:two");
    snprintf(old.entity_type, sizeof old.entity_type, "task");
    snprintf(old.entity_id, sizeof old.entity_id, "two");
    dashboard_focus_identity candidate = {0};
    snprintf(candidate.component_id, sizeof candidate.component_id,
             "home:task:two");
    snprintf(candidate.entity_type, sizeof candidate.entity_type, "task");
    snprintf(candidate.entity_id, sizeof candidate.entity_id, "two");
    check(dashboard_focus_identity_match(&old, &candidate) == 2,
          "component id is the primary focus identity");
    snprintf(candidate.component_id, sizeof candidate.component_id,
             "new-component-id");
    check(dashboard_focus_identity_match(&old, &candidate) == 1,
          "entity reference is the focus identity fallback");
    candidate.entity_id[0] = 0;
    check(dashboard_focus_identity_match(&old, &candidate) == 0,
          "a different target does not retain focus");
    check(dashboard_focus_fallback(1, 3) == 1,
          "removed focus chooses the next ordinal");
    check(dashboard_focus_fallback(3, 2) == 1,
          "removed last focus chooses the previous card");
    check(dashboard_focus_fallback(1, 0) == -1,
          "empty snapshot returns to the menu");
    check(dashboard_focus_fallback(-1, 3) == -1,
          "menu focus stays on the menu");
}

static void history(void) {
    char out[HISTORY_TIME_CHARS];

    check(history_format_time(out, sizeof out, "2026-09-06T14:32:20.659091Z", false), "iso accepted");
    check(!strcmp(out, "06.09. 14:32"), "iso formatted day first");
    check(history_format_time(out, sizeof out, "2026-01-02T03:04:05Z", false), "short iso accepted");
    check(!strcmp(out, "02.01. 03:04"), "leading zeros kept");

    /* A malformed timestamp must never come out as a plausible moment. */
    check(!history_format_time(out, sizeof out, "gestern", false), "prose rejected");
    check(!strcmp(out, "--.--. --:--"), "rejected time is visibly absent");
    check(!history_format_time(out, sizeof out, "", false), "empty rejected");
    check(!history_format_time(out, sizeof out, NULL, false), "null rejected");
    check(!history_format_time(out, sizeof out, "2026-09-06", false), "date without time rejected");
    check(!history_format_time(out, sizeof out, "20x6-09-06T14:32:00Z", false), "non-digits rejected");

    /* Local conversion, in the zone the device displays. These are the cases
     * hand-rolled offset arithmetic gets wrong, which is why the C library does
     * the work: summer time, winter time, and a conversion that moves the date
     * as well as the hour. */
    setenv("TZ", "CET-1CEST,M3.5.0,M10.5.0/3", 1);
    tzset();
    check(history_format_time(out, sizeof out, "2026-09-06T14:32:00Z", true), "summer accepted");
    check(!strcmp(out, "06.09. 16:32"), "summer time is two hours ahead");
    check(history_format_time(out, sizeof out, "2026-01-02T03:04:00Z", true), "winter accepted");
    check(!strcmp(out, "02.01. 04:04"), "winter time is one hour ahead");
    check(history_format_time(out, sizeof out, "2026-09-06T23:30:00Z", true), "late evening accepted");
    check(!strcmp(out, "07.09. 01:30"), "conversion rolls the date over");
    check(history_format_time(out, sizeof out, "2026-12-31T23:30:00Z", true), "new year accepted");
    check(!strcmp(out, "01.01. 00:30"), "conversion rolls the year over");
    /* The switch itself: 00:30 UTC on the last Sunday in October is still CEST. */
    check(history_format_time(out, sizeof out, "2026-10-25T00:30:00Z", true), "switch day accepted");
    check(!strcmp(out, "25.10. 02:30"), "before the autumn switch it is still summer time");

    check(!strcmp(history_state_label("completed"), "fertig"), "known state translated");
    check(!strcmp(history_state_label("draining"), "Upload läuft"),
          "upload state is explicit");
    check(!strcmp(history_state_label("uploads_pending"), "Upload ausstehend"),
          "pending upload state is explicit");
    check(!strcmp(history_state_label("processing"), "in Verarbeitung"),
          "processing is not phrased as already processed");
    check(!strcmp(history_state_label("attention_required"), "Aufmerksamkeit"),
          "multi-word state translated");
    check(history_state_icon("created", false) == ICON_SESSION,
          "created recording has a session mark");
    check(history_state_icon("recording", false) == ICON_RECORDING,
          "live recording has a recording mark");
    check(history_state_icon("draining", false) == ICON_QUEUE,
          "upload has a queue mark");
    check(history_state_icon("processing", false) == ICON_SEV_INFO,
          "processing has an information mark");
    check(history_state_icon("completed", false) == ICON_SEV_SUCCESS,
          "completed has a success mark");
    check(history_state_icon("attention_required", false) == ICON_SEV_WARNING,
          "attention has a warning mark");
    check(history_state_icon("aborted", false) == ICON_SEV_ERROR,
          "aborted has an error mark");
    check(history_state_icon("processing", true) == ICON_SEV_ERROR,
          "last_error overrides a lagging state mark");
    /* An unknown state is shown as it came: not guessed at, not hidden. */
    check(!strcmp(history_state_label("quarantined"), "quarantined"), "unknown state kept");
    check(!strcmp(history_state_label(""), "unbekannt"), "empty state named");
    check(!strcmp(history_state_label(NULL), "unbekannt"), "null state named");
}

static void ages(void) {
    char out[24];
    header_age_text(out, sizeof out, 0);   check(!strcmp(out, "gerade eben"), "age zero");
    header_age_text(out, sizeof out, 1);   check(!strcmp(out, "vor 1 min"), "age one minute");
    header_age_text(out, sizeof out, 59);  check(!strcmp(out, "vor 59 min"), "age below an hour");
    header_age_text(out, sizeof out, 60);  check(!strcmp(out, "vor 1 h"), "age one hour");
    header_age_text(out, sizeof out, 190); check(!strcmp(out, "vor 3 h"), "age rounds to hours");
    header_age_text(out, sizeof out, 60 * 30); check(!strcmp(out, "vor 1 d"), "age in days");
}

static void active_views(void) {
    check(header_active_view(false, false, false, false) == 0, "home marker");
    check(header_active_view(true, false, false, false) == 1, "task marker");
    check(header_active_view(false, true, false, false) == 2, "list marker");
    check(header_active_view(false, false, true, false) == 3, "history marker");
    check(header_active_view(false, true, true, false) == 3,
          "history marker wins over a stale list flag");
    check(header_active_view(false, false, true, true) == 4,
          "settings marker wins over a stale history flag");
}

static void settings_view(void) {
    settings_diagnostics state = {
        .firmware = "h4-settings-net",
        .network_connected = true,
        .api_configured = true,
        .api_authenticated = true,
        .api_compatible = true,
        .gate_ok = 3,
        .queue_ready = 2,
        .queue_acked = 8,
        .queue_attention = 1,
        .bytes_free = 30455ull * 1024 * 1024,
        .bytes_total = 30456ull * 1024 * 1024,
    };
    char text[64];
    check(!strcmp(settings_contract_text(&state), "kompatibel"),
          "settings shows a compatible contract");
    state.api_compatible = false;
    check(!strcmp(settings_contract_text(&state), "noch nicht geprüft"),
          "settings does not invent a gate result");
    state.gate_failed = 1;
    check(!strcmp(settings_contract_text(&state), "Gate fehlgeschlagen"),
          "settings surfaces a failed gate");
    state.api_authenticated = false;
    check(!strcmp(settings_contract_text(&state), "nicht angemeldet"),
          "settings surfaces missing authentication");
    settings_queue_text(text, sizeof text, &state);
    check(!strcmp(text, "bereit 2 · ACK 8 · Achtung 1"),
          "settings queue summary contains all classes");
    settings_storage_text(text, sizeof text, &state);
    check(!strcmp(text, "30455 MiB frei"), "settings storage is content-free");
    check(settings_scroll_for(100, 260, SETTINGS_ITEM_COUNT, 0) > 0,
          "settings rows scroll to the final item in a short viewport");

    clear();
    check(settings_log_line_count("one\ntwo\n") == 2,
          "settings log counts complete lines");
    check(settings_log_line_count("one\ntwo") == 2,
          "settings log counts a final unterminated line");
    check(settings_log_visible_capacity(100, 792) > 0,
          "settings log has a visible viewport");
    settings_draw(canvas, 100, 792, 0, 0, true, true);
    settings_diagnostics_draw(canvas, 100, 792, &state);
    settings_logs_draw(canvas, 100, 792,
                       "+0s I BOOT\n+2s I STORAGE ok=1 free=100MiB total=200MiB\n",
                       0);
    int outside = 0;
    for (int y = 0; y < 800; y++)
        for (int x = 0; x < 480; x++)
            if (ink_at(x, y) && (y < 100 || y >= 792)) outside++;
    check(outside == 0, "settings renderer stays inside its body");
}

static void staleness(void) {
    /* Nothing has ever arrived: no age can make that better or worse. */
    check(header_snapshot_for(false, false, true, 0, 0) == HEADER_NEVER,
          "never seen outranks everything");
    check(header_snapshot_for(false, false, false, 99999, 60) == HEADER_NEVER,
          "never seen is not stale");

    /* Fresh contact: the link state decides, and emptiness is believable. */
    check(header_snapshot_for(true, false, true, 0, 0) == HEADER_CURRENT, "fresh and online");
    check(header_snapshot_for(true, false, false, 0, 0) == HEADER_OFFLINE, "fresh but offline");
    check(header_snapshot_for(true, true, true, 0, 0) == HEADER_EMPTY, "fresh and empty");

    /* The fallback boundary, exactly at two hours. */
    check(header_snapshot_for(true, false, true, 7199, 0) == HEADER_CURRENT,
          "one second below the fallback limit");
    check(header_snapshot_for(true, false, true, 7200, 0) == HEADER_STALE,
          "at the fallback limit");

    /* A server-stated limit wins over the fallback, in both directions. */
    check(header_snapshot_for(true, false, true, 1200, 600) == HEADER_STALE,
          "server limit shorter than the fallback");
    check(header_snapshot_for(true, false, true, 20000, 86400) == HEADER_CURRENT,
          "server limit longer than the fallback");

    /* Past the limit, staleness outranks both emptiness and the link state. */
    check(header_snapshot_for(true, true, true, 7200, 0) == HEADER_STALE,
          "stale outranks empty");
    check(header_snapshot_for(true, false, false, 7200, 0) == HEADER_STALE,
          "stale outranks offline");
}

static void bar_stays_in_its_row(void) {
    clear();
    status_state state = {.time_valid = true, .hour = 23, .minute = 59,
                          .day = 12, .month = 10, .year = 1989,
                          .queue_ready = 199, .queue_attention = 9,
                          .storage_low = true, .storage_block = true};
    status_bar_draw(canvas, &state);
    int below = 0;
    for (int py = STATUS_BAR_HEIGHT; py < STATUS_BAR_HEIGHT + 20; py++)
        for (int px = 0; px < 480; px++)
            if (ink_at(px, py)) below++;
    check(below == 0, "a busy status bar stays within its 48 px");
}

static void compact_dates(void) {
    char text[16];
    check(status_bar_format_date(text, sizeof text, 2, 4, 2003) &&
          !strcmp(text, "2.4.03"), "single digit day and month stay compact");
    check(status_bar_format_date(text, sizeof text, 23, 5, 2024) &&
          !strcmp(text, "23.5.24"), "two digit day keeps compact month");
    check(status_bar_format_date(text, sizeof text, 12, 10, 1989) &&
          !strcmp(text, "12.10.89"), "two digit date is formatted exactly");
    check(!status_bar_format_date(text, sizeof text, 0, 10, 2026) && !text[0],
          "an invalid date is not displayed");
}

static void charging_changes_battery_symbol(void) {
    status_state state = {.battery_known = true, .battery_percent = 100};
    clear();
    status_bar_draw(canvas, &state);
    check(ink_at(443, 17), "full battery fills the cell corner");

    state.battery_charging = true;
    clear();
    status_bar_draw(canvas, &state);
    check(!ink_at(443, 17), "charging clears a plate inside the battery");
    check(ink_at(453, 18), "charging draws the lightning mark");
}

int main(void) {
    titles();
    heights();
    containment();
    shared_row_height();
    status_fits();
    section_heading();
    mapping();
    paging();
    focus_identity();
    focus_keeps_urgency();
    active_views();
    settings_view();
    ages();
    staleness();
    history();
    bar_stays_in_its_row();
    compact_dates();
    charging_changes_battery_symbol();
    if (failures) { printf("%d check(s) failed\n", failures); return 1; }
    printf("ui: all checks passed\n");
    return 0;
}
