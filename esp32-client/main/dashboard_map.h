#pragma once
// The JSON-free half of the dashboard logic: the mapping from the contract's
// vocabulary to this panel's drawing values, and the paging arithmetic.
//
// Both are kept free of JSON so they can be tested on the host, which is where
// the risk sits: every unknown token has to land somewhere sensible, an unknown
// value must never make a card look calmer than it is, and the scroll position
// must never leave the focused card half visible or stop advancing.
#include "card.h"
#include "icons.h"

/* `color_role` to an urgency step. Unknown or missing roles fall to the
 * neutral step, never below it. */
strip_pattern dashboard_urgency(const char *color_role);

/* `icon` token to an art symbol. Unknown or missing tokens become generic. */
icon_id dashboard_icon(const char *token);

/* `border_role` to a line weight. Unknown roles are drawn thin. */
card_border dashboard_border(const char *border_role);

/* `severity` to a mark, or ICON_COUNT for none. Unknown values yield no mark
 * and must not escalate: severity is a free string in the snapshot and is not
 * announced through the capabilities. */
icon_id dashboard_severity(const char *severity);

/* The urgency a card ends up with once severity is taken into account. The
 * contract says the higher urgency wins and that a warning is never weakened,
 * so a severe card cannot be drawn calmer than its colour role alone. */
strip_pattern dashboard_combined_urgency(const char *color_role, const char *severity);

/* Whether the component can take focus: it needs a supported action or a
 * resolvable entity reference. */
bool dashboard_focusable(const char *action_type, bool has_entity_ref);

/* --- layout plan and paging ----------------------------------------------- */

#define DASHBOARD_MAX_ROWS 48

/* One laid out row: a section heading, a full width card, or a pair of half
 * width cards. Focus indices are -1 where the row takes no focus. */
typedef struct {
    int top;           /* offset within the content, before scrolling */
    int height;
    int first_focus;
    int second_focus;
} dashboard_row;

typedef struct {
    dashboard_row rows[DASHBOARD_MAX_ROWS];
    int count;
    int content_height;
    int focusable;
    bool overflowed;   /* more rows than the plan can hold */
    /* The entity behind the focused card, captured by the same walk that laid
     * the rows out. Resolving it separately would count the focusable cards a
     * second time, and the two counts would eventually disagree. */
    bool focus_has_entity;
    char focus_type[32];
    char focus_id[40];
    /* The card's declared action, captured by the same walk. Without it the
     * device knew *what* the focused card refers to but not *how* it is meant
     * to be opened, and it opened everything the one way it knew: a session
     * card was fetched as if it were an entity, which the server answers with
     * 404 because a session is not one. Empty where the card names no action. */
    char focus_action[24];
} dashboard_plan;

/* Scroll position that brings `focus_index` fully into a viewport of
 * `viewport` pixels, starting from `scroll`.
 *
 * Paging advances by about two thirds of the viewport and then snaps to a row
 * boundary, so the reader keeps a strip of context instead of losing their
 * place, and a row is never cut in half. A focus that is already visible does
 * not move the page at all. */
int dashboard_scroll_for(const dashboard_plan *plan, int focus_index,
                         int scroll, int viewport);

/* The row carrying a focus index, or -1. */
int dashboard_row_of(const dashboard_plan *plan, int focus_index);
