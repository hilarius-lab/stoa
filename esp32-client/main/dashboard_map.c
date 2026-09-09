#include <string.h>
#include "dashboard_map.h"

static bool same(const char *value, const char *expected) {
    return value && strcmp(value, expected) == 0;
}

strip_pattern dashboard_urgency(const char *color_role) {
    if (same(color_role, "danger")) return STRIP_SOLID;
    if (same(color_role, "warning")) return STRIP_HATCH;
    if (same(color_role, "primary") || same(color_role, "recording")) return STRIP_MEDIUM;
    if (same(color_role, "muted") || same(color_role, "success") ||
        same(color_role, "offline")) return STRIP_PLAIN;
    /* neutral, info, secondary and everything unknown. An unknown role must not
     * end up quieter than neutral, or a new server role would silently make a
     * card look calmer than intended. */
    return STRIP_LIGHT;
}

icon_id dashboard_icon(const char *token) {
    static const struct { const char *token; icon_id id; } table[] = {
        {"generic", ICON_GENERIC},   {"microphone", ICON_MICROPHONE},
        {"recording", ICON_RECORDING}, {"session", ICON_SESSION},
        {"question", ICON_QUESTION}, {"warning", ICON_WARNING},
        {"task", ICON_TASK},         {"list", ICON_LIST},
        {"note", ICON_NOTE},         {"fact", ICON_FACT},
        {"decision", ICON_DECISION}, {"topic", ICON_TOPIC},
        {"chat", ICON_CHAT},         {"info", ICON_INFO},
    };
    for (unsigned i = 0; i < sizeof(table) / sizeof(table[0]); i++)
        if (same(token, table[i].token)) return table[i].id;
    return ICON_GENERIC;
}

card_border dashboard_border(const char *border_role) {
    if (same(border_role, "critical")) return CARD_BORDER_CRITICAL;
    if (same(border_role, "emphasis")) return CARD_BORDER_EMPHASIS;
    return CARD_BORDER_THIN; /* none, subtle and unknown */
}

icon_id dashboard_severity(const char *severity) {
    if (same(severity, "info")) return ICON_SEV_INFO;
    if (same(severity, "success")) return ICON_SEV_SUCCESS;
    if (same(severity, "warning")) return ICON_SEV_WARNING;
    if (same(severity, "error")) return ICON_SEV_ERROR;
    if (same(severity, "critical")) return ICON_SEV_CRITICAL;
    return ICON_COUNT;
}

strip_pattern dashboard_combined_urgency(const char *color_role, const char *severity) {
    strip_pattern from_role = dashboard_urgency(color_role);
    strip_pattern from_severity = from_role;
    if (same(severity, "critical")) from_severity = STRIP_SOLID;
    else if (same(severity, "error")) from_severity = STRIP_SOLID;
    else if (same(severity, "warning")) from_severity = STRIP_HATCH;
    /* info and success carry no urgency of their own, and an unknown severity
     * must not escalate: it is a free string in the snapshot. */
    return from_severity > from_role ? from_severity : from_role;
}

bool dashboard_focusable(const char *action_type, bool has_entity_ref) {
    /* open_entity is the only action the contract defines today. A component
     * without a supported action is informational and is skipped by the
     * navigation, even if it looks like a card. */
    return same(action_type, "open_entity") || has_entity_ref;
}

static bool same_nonempty(const char *left, const char *right) {
    return left[0] && right[0] && strcmp(left, right) == 0;
}

int dashboard_focus_identity_match(const dashboard_focus_identity *wanted,
                                   const dashboard_focus_identity *candidate) {
    if (!wanted || !candidate) return 0;
    if (same_nonempty(wanted->component_id, candidate->component_id)) return 2;
    if (same_nonempty(wanted->entity_type, candidate->entity_type) &&
        same_nonempty(wanted->entity_id, candidate->entity_id)) return 1;
    return 0;
}

int dashboard_focus_fallback(int old_focus, int new_count) {
    if (old_focus < 0 || new_count <= 0) return -1;
    return old_focus < new_count ? old_focus : new_count - 1;
}

/* --- layout plan and paging ----------------------------------------------- */

int dashboard_row_of(const dashboard_plan *plan, int focus_index) {
    if (focus_index < 0) return -1;
    for (int i = 0; i < plan->count; i++)
        if (plan->rows[i].first_focus == focus_index ||
            plan->rows[i].second_focus == focus_index)
            return i;
    return -1;
}

int dashboard_scroll_for(const dashboard_plan *plan, int focus_index,
                         int scroll, int viewport) {
    int row = dashboard_row_of(plan, focus_index);
    if (row < 0 || viewport <= 0) return scroll;
    int top = plan->rows[row].top;
    int bottom = top + plan->rows[row].height;

    /* Already fully visible: leave the page alone. Moving it on every step
     * would make the list crawl under the reader. */
    if (top >= scroll && bottom <= scroll + viewport) return scroll;

    if (top < scroll) {
        /* Upwards: put the row at the top of the page. */
        return top;
    }

    /* Downwards: advance by about two thirds, snapped to a row boundary, and
     * keep advancing while the row still does not fit. The loop is bounded by
     * the number of rows, so it always terminates. */
    int next = scroll;
    for (int guard = 0; guard <= plan->count; guard++) {
        int target = next + (viewport * 2) / 3;
        int snapped = next;
        for (int i = 0; i < plan->count; i++)
            if (plan->rows[i].top <= target && plan->rows[i].top > snapped)
                snapped = plan->rows[i].top;
        if (snapped <= next) snapped = top; /* nothing between: jump to the row */
        next = snapped;
        if (bottom <= next + viewport) break;
    }
    /* Never scroll past the end of the content. */
    int limit = plan->content_height - viewport;
    if (limit < 0) limit = 0;
    if (next > limit) next = limit;
    if (next > top) next = top;
    return next;
}
