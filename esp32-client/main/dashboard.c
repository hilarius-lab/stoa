#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include "dashboard.h"
#include "card.h"
#include "text.h"
#include "detail.h"

#define MARGIN 12
#define SECTION_SPACING 8
#define HEADING_GAP 6

static const char *string_of(const cJSON *object, const char *name) {
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(object, name);
    return cJSON_IsString(value) ? value->valuestring : NULL;
}

static bool is_card(const cJSON *item) {
    const char *component = string_of(item, "component");
    return component && strcmp(component, "entity_card") == 0;
}

static card_content to_card(const cJSON *item, bool *focusable) {
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(item, "action");
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "entity_ref");
    const char *color = string_of(item, "color_role");
    const char *severity = string_of(item, "severity");
    *focusable = dashboard_focusable(action ? string_of(action, "type") : NULL,
                                     cJSON_IsObject(entity));
    card_content card = {
        .title = string_of(item, "title"),
        .preview = string_of(item, "preview"),
        .status = string_of(item, "status"),
        .icon = dashboard_icon(string_of(item, "icon")),
        .severity = dashboard_severity(severity),
        .urgency = dashboard_combined_urgency(color, severity),
        .border = dashboard_border(string_of(item, "border_role")),
    };
    return card;
}

static bool pairable(const card_content *card) {
    return card->title && card_title_length(card->title) <= CARD_HALF_MAX_TITLE_CHARS;
}

static void capture_entity(dashboard_plan *plan, const cJSON *item,
                           int focus, int focus_index) {
    if (!plan || focus < 0 || focus != focus_index) return;
    /* The action is read before the reference and independently of it: a card
     * may declare how it wants to be opened without carrying an entity, and
     * losing that distinction is what made every card look like an entity. */
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(item, "action");
    const char *verb = action ? string_of(action, "type") : NULL;
    snprintf(plan->focus_action, sizeof(plan->focus_action), "%s", verb ? verb : "");
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "entity_ref");
    const char *type = entity ? string_of(entity, "type") : NULL;
    const char *id = entity ? string_of(entity, "id") : NULL;
    if (!type || !id) return;
    snprintf(plan->focus_type, sizeof(plan->focus_type), "%s", type);
    snprintf(plan->focus_id, sizeof(plan->focus_id), "%s", id);
    plan->focus_has_entity = true;
}

static void record(dashboard_plan *plan, int top, int height,
                   int first_focus, int second_focus) {
    if (!plan) return;
    if (plan->count >= DASHBOARD_MAX_ROWS) { plan->overflowed = true; return; }
    plan->rows[plan->count++] = (dashboard_row){top, height, first_focus, second_focus};
}

/* "today" and "lists" are the sections the tasks/lists views claim as their
 * own; everything else stays on the main surface. Matched against the same
 * `id` the backend already assigns each section (services/client_dashboard.py
 * ::_idle_content()), not guessed. */
static bool section_wanted(const char *id, dashboard_surface surface) {
    bool is_today = id && strcmp(id, "today") == 0;
    bool is_lists = id && strcmp(id, "lists") == 0;
    switch (surface) {
    case DASHBOARD_SURFACE_TASKS: return is_today;
    case DASHBOARD_SURFACE_LISTS: return is_lists;
    case DASHBOARD_SURFACE_MAIN:  return !is_today && !is_lists;
    case DASHBOARD_SURFACE_ALL:
    default:                      return true;
    }
}

void dashboard_walk(unsigned char *canvas, const char *json,
                    int top, int bottom, int scroll, int focus_index,
                    dashboard_plan *plan, dashboard_surface surface) {
    if (plan) memset(plan, 0, sizeof(*plan));
    cJSON *root = cJSON_Parse(json);
    const cJSON *sections = cJSON_GetObjectItemCaseSensitive(root, "sections");
    if (!cJSON_IsArray(sections)) { cJSON_Delete(root); return; }

    int cursor = 0;
    int focus_counter = 0;
    const cJSON *section;
    cJSON_ArrayForEach(section, sections) {
        if (!section_wanted(string_of(section, "id"), surface)) continue;
        const char *heading = string_of(section, "title");
        const cJSON *items = cJSON_GetObjectItemCaseSensitive(section, "items");
        if (heading && heading[0]) {
            int y = top + cursor - scroll;
            if (canvas && y >= top && y + SECTION_HEADING_HEIGHT <= bottom)
                section_heading_draw(canvas, heading, MARGIN, y, CARD_FULL_WIDTH);
            record(plan, cursor, SECTION_HEADING_HEIGHT + HEADING_GAP, -1, -1);
            cursor += SECTION_HEADING_HEIGHT + HEADING_GAP;
        }
        if (!cJSON_IsArray(items)) { cursor += SECTION_SPACING; continue; }

        const cJSON *item = items->child;
        while (item) {
            if (!is_card(item)) { item = item->next; continue; }
            bool focusable = false;
            card_content first = to_card(item, &focusable);
            int first_focus = focusable ? focus_counter++ : -1;
            capture_entity(plan, item, first_focus, focus_index);

            const cJSON *next = item->next;
            while (next && !is_card(next)) next = next->next;
            bool paired = false;
            card_content second = {0};
            int second_focus = -1;
            if (next && pairable(&first)) {
                bool next_focusable = false;
                card_content candidate = to_card(next, &next_focusable);
                if (pairable(&candidate)) {
                    paired = true;
                    second = candidate;
                    second_focus = next_focusable ? focus_counter++ : -1;
                    capture_entity(plan, next, second_focus, focus_index);
                }
            }

            int width = paired ? CARD_HALF_WIDTH : CARD_FULL_WIDTH;
            int height = card_height(&first, width);
            if (paired) {
                int other = card_height(&second, width);
                if (other > height) height = other;
            }

            int y = top + cursor - scroll;
            /* A row that the lower edge would cut is not drawn at all: paging
             * snaps to row boundaries, so half a card is never the picture the
             * reader is meant to see. */
            if (canvas && y >= top && y + height <= bottom) {
                first.focused = (first_focus >= 0 && first_focus == focus_index);
                card_draw_sized(canvas, &first, MARGIN, y, width, height);
                if (paired) {
                    second.focused = (second_focus >= 0 && second_focus == focus_index);
                    card_draw_sized(canvas, &second, MARGIN + CARD_HALF_WIDTH + CARD_GAP,
                                    y, width, height);
                }
            }
            record(plan, cursor, height + CARD_GAP, first_focus, second_focus);
            cursor += height + CARD_GAP;
            item = paired ? next->next : item->next;
        }
        cursor += SECTION_SPACING;
    }
    if (plan) {
        plan->content_height = cursor;
        plan->focusable = focus_counter;
    }
    cJSON_Delete(root);
}

/* A short, local description of the kind. The server sends a machine token; it
 * is not user facing text, so the device supplies the wording. */
static const char *kind_word(const char *type) {
    if (!type) return "Eintrag";
    if (!strcmp(type, "task")) return "Aufgabe";
    if (!strcmp(type, "question")) return "Rückfrage";
    if (!strcmp(type, "note")) return "Notiz";
    if (!strcmp(type, "fact")) return "Fakt";
    if (!strcmp(type, "decision")) return "Entscheidung";
    if (!strcmp(type, "topic")) return "Thema";
    return type;
}

int dashboard_entity_draw(unsigned char *canvas, const char *json,
                          int top, int bottom, int line_offset, int *page) {
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); if (page) *page = 1; return 0; }

    const char *type = string_of(root, "type");
    const char *status = string_of(root, "status");
    char meta[64];
    snprintf(meta, sizeof(meta), "%s%s%s", kind_word(type),
             status ? " · " : "", status ? status : "");

    /* A question carries its text in `question`; everything else in `content`.
     * Falling back to the description keeps a sparse entity from showing an
     * empty page. */
    const char *body = string_of(root, "question");
    if (!body) body = string_of(root, "content");
    if (!body) body = string_of(root, "description");

    detail_content detail = {
        .title = string_of(root, "title"),
        .reason = string_of(root, "question") ? string_of(root, "description") : NULL,
        .body = body,
        .answer = string_of(root, "answer"),
        .meta = meta,
    };
    if (page) *page = detail_page_lines(&detail, top, bottom);
    int total = canvas ? detail_draw(canvas, &detail, top, bottom, line_offset)
                       : 0;
    cJSON_Delete(root);
    return total;
}
