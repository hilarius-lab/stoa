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

static bool component_is(const cJSON *item, const char *expected) {
    const char *component = string_of(item, "component");
    return component && strcmp(component, expected) == 0;
}

static bool is_renderable(const cJSON *item) {
    return component_is(item, "entity_card") || component_is(item, "alert");
}

static card_content to_card(const cJSON *item, bool *focusable) {
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(item, "action");
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "entity_ref");
    const char *color = string_of(item, "color_role");
    const char *severity = string_of(item, "severity");
    bool entity_card = component_is(item, "entity_card");
    *focusable = entity_card && dashboard_focusable(
        action ? string_of(action, "type") : NULL, cJSON_IsObject(entity));
    card_content card = {
        .title = string_of(item, "title"),
        .preview = entity_card ? string_of(item, "preview") : string_of(item, "text"),
        .status = entity_card ? string_of(item, "status") : NULL,
        .icon = dashboard_icon(string_of(item, "icon")),
        .severity = dashboard_severity(severity),
        .urgency = dashboard_combined_urgency(color, severity),
        .border = dashboard_border(string_of(item, "border_role")),
    };
    return card;
}

static bool pairable(const cJSON *item, const card_content *card) {
    return component_is(item, "entity_card") && card->title &&
           card_title_length(card->title) <= CARD_HALF_MAX_TITLE_CHARS;
}

static bool section_wanted(const char *id, dashboard_surface surface);

static void read_identity(const cJSON *item, dashboard_focus_identity *identity) {
    memset(identity, 0, sizeof(*identity));
    const char *component_id = string_of(item, "id");
    snprintf(identity->component_id, sizeof(identity->component_id), "%s",
             component_id ? component_id : "");
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "entity_ref");
    const char *type = entity ? string_of(entity, "type") : NULL;
    const char *id = entity ? string_of(entity, "id") : NULL;
    snprintf(identity->entity_type, sizeof(identity->entity_type), "%s", type ? type : "");
    snprintf(identity->entity_id, sizeof(identity->entity_id), "%s", id ? id : "");
}

static void capture_focus(dashboard_plan *plan, const cJSON *item,
                          int focus, int focus_index) {
    if (!plan || focus < 0 || focus != focus_index) return;
    read_identity(item, &plan->focus_identity);
    const cJSON *entity = cJSON_GetObjectItemCaseSensitive(item, "entity_ref");
    const char *type = entity ? string_of(entity, "type") : NULL;
    const char *id = entity ? string_of(entity, "id") : NULL;
    /* The action is read before the reference and independently of it: a card
     * may declare how it wants to be opened without carrying an entity, and
     * losing that distinction is what made every card look like an entity. */
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(item, "action");
    const char *verb = action ? string_of(action, "type") : NULL;
    snprintf(plan->focus_action, sizeof(plan->focus_action), "%s", verb ? verb : "");
    if (!type || !id) return;
    snprintf(plan->focus_type, sizeof(plan->focus_type), "%s", type);
    snprintf(plan->focus_id, sizeof(plan->focus_id), "%s", id);
    plan->focus_has_entity = true;
}

static int find_focus(const char *json, dashboard_surface surface,
                      const dashboard_focus_identity *wanted) {
    cJSON *root = cJSON_Parse(json);
    const cJSON *sections = cJSON_GetObjectItemCaseSensitive(root, "sections");
    if (!cJSON_IsArray(sections)) { cJSON_Delete(root); return -1; }
    int focus = 0, entity_fallback = -1;
    const cJSON *section;
    cJSON_ArrayForEach(section, sections) {
        if (!section_wanted(string_of(section, "id"), surface)) continue;
        const cJSON *items = cJSON_GetObjectItemCaseSensitive(section, "items");
        const cJSON *item;
        cJSON_ArrayForEach(item, items) {
            if (!component_is(item, "entity_card")) continue;
            bool focusable = false;
            (void)to_card(item, &focusable);
            if (!focusable) continue;
            dashboard_focus_identity candidate;
            read_identity(item, &candidate);
            int match = dashboard_focus_identity_match(wanted, &candidate);
            if (match == 2) { cJSON_Delete(root); return focus; }
            if (match == 1 && entity_fallback < 0) entity_fallback = focus;
            focus++;
        }
    }
    cJSON_Delete(root);
    return entity_fallback;
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
            if (!is_renderable(item)) { item = item->next; continue; }
            bool focusable = false;
            card_content first = to_card(item, &focusable);
            int first_focus = focusable ? focus_counter++ : -1;
            capture_focus(plan, item, first_focus, focus_index);

            const cJSON *next = item->next;
            while (next && !is_renderable(next)) next = next->next;
            bool paired = false;
            card_content second = {0};
            int second_focus = -1;
            if (next && pairable(item, &first)) {
                bool next_focusable = false;
                card_content candidate = to_card(next, &next_focusable);
                if (pairable(next, &candidate)) {
                    paired = true;
                    second = candidate;
                    second_focus = next_focusable ? focus_counter++ : -1;
                    capture_focus(plan, next, second_focus, focus_index);
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

int dashboard_remap_focus(const char *old_json, const char *new_json,
                          dashboard_surface surface, int old_focus,
                          int old_scroll, int viewport, int *new_scroll) {
    if (new_scroll) *new_scroll = 0;
    if (old_focus < 0) return -1;

    dashboard_plan plan = {0};
    dashboard_walk(NULL, old_json, 0, viewport, 0, old_focus, &plan, surface);
    bool had_focus = old_focus < plan.focusable;
    dashboard_focus_identity wanted = plan.focus_identity;
    memset(&plan, 0, sizeof(plan));
    dashboard_walk(NULL, new_json, 0, viewport, 0, -1, &plan, surface);
    if (plan.focusable <= 0) return -1;

    int next = had_focus ? find_focus(new_json, surface, &wanted) : -1;
    if (next < 0) next = dashboard_focus_fallback(old_focus, plan.focusable);
    if (new_scroll)
        *new_scroll = dashboard_scroll_for(&plan, next, old_scroll, viewport);
    return next;
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

static const cJSON *capture_params_for(const cJSON *root) {
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(root, "action");
    const char *type = action ? string_of(action, "type") : NULL;
    const cJSON *params = action ? cJSON_GetObjectItemCaseSensitive(action, "params") : NULL;
    return type && strcmp(type, "submit_capture") == 0 && cJSON_IsObject(params)
        ? params : NULL;
}

static bool capture_context_for(const cJSON *root, const char **id) {
    const cJSON *params = capture_params_for(root);
    const cJSON *context = params
        ? cJSON_GetObjectItemCaseSensitive(params, "context_ref") : NULL;
    const char *type = context ? string_of(context, "type") : NULL;
    const char *value = context ? string_of(context, "id") : NULL;
    if (!cJSON_IsObject(context) || !type || strcmp(type, "clarification") != 0 ||
        !value || strlen(value) != 36) return false;
    if (id) *id = value;
    return true;
}

/* Action labels are server-owned, but only for the closed action vocabulary
 * this build implements. A bare submit_capture is intentionally not focusable:
 * it binds BOOT recording, while a label plus fixed content makes a selectable
 * suggested answer. */
static const char *action_label_for(const cJSON *root) {
    const cJSON *action = cJSON_GetObjectItemCaseSensitive(root, "action");
    const char *type = action ? string_of(action, "type") : NULL;
    if (type && strcmp(type, "complete_task") == 0) return "Erledigt";
    const cJSON *params = capture_params_for(root);
    const char *label = params ? string_of(params, "label") : NULL;
    const char *content = params ? string_of(params, "content") : NULL;
    if (label && label[0] && content && content[0] && capture_context_for(root, NULL))
        return label;
    return NULL;
}

bool dashboard_entity_has_action(const char *json) {
    cJSON *root = cJSON_Parse(json);
    bool has = cJSON_IsObject(root) && action_label_for(root) != NULL;
    cJSON_Delete(root);
    return has;
}

bool dashboard_entity_capture_context(const char *json, char *question_id,
                                      size_t capacity) {
    if (!question_id || capacity < 37) return false;
    question_id[0] = 0;
    cJSON *root = cJSON_Parse(json);
    const char *id = NULL;
    bool valid = cJSON_IsObject(root) && capture_context_for(root, &id);
    if (valid) snprintf(question_id, capacity, "%s", id);
    cJSON_Delete(root);
    return valid;
}

bool dashboard_entity_suggested_capture(const char *json, char *content,
                                        size_t content_capacity,
                                        char *question_id, size_t id_capacity) {
    if (!content || !content_capacity || !question_id || !id_capacity) return false;
    content[0] = question_id[0] = 0;
    cJSON *root = cJSON_Parse(json);
    const cJSON *params = cJSON_IsObject(root) ? capture_params_for(root) : NULL;
    const char *value = params ? string_of(params, "content") : NULL;
    const char *id = NULL;
    bool valid = value && value[0] && strlen(value) < content_capacity &&
                 id_capacity >= 37 && action_label_for(root) &&
                 capture_context_for(root, &id);
    if (valid) {
        snprintf(content, content_capacity, "%s", value);
        snprintf(question_id, id_capacity, "%s", id);
    }
    cJSON_Delete(root);
    return valid;
}

int dashboard_entity_draw(unsigned char *canvas, const char *json,
                          int top, int bottom, int line_offset, int *page,
                          bool action_focused) {
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
        .action_label = action_label_for(root),
        .action_focused = action_focused,
    };
    if (page) *page = detail_page_lines(&detail, top, bottom);
    int total = canvas ? detail_draw(canvas, &detail, top, bottom, line_offset)
                       : 0;
    cJSON_Delete(root);
    return total;
}
