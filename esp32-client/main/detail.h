#pragma once
// The detail view: one card opened full height.
//
// Free of JSON, like the rest of the drawing layer, so the pagination can be
// tested on the host. The caller supplies already resolved strings.
#include <stdbool.h>

typedef struct {
    const char *title;
    const char *reason;  /* reason_text, between title and body; may be NULL */
    const char *body;    /* content, or the question for a query */
    const char *answer;  /* answer, when one exists; may be NULL */
    const char *meta;    /* kind and status, drawn at the foot; hidden when action_label is set */
    /* Set only when the entity offers a mutation beyond navigation — today,
     * "Erledigt" on an open task's `complete_task`. When present it replaces
     * the meta line with two selectable elements, "Zurück" and this label;
     * `action_focused` says which one currently carries the focus. Absent for
     * every other entity, which keeps the plain "short press is always back"
     * behaviour unchanged there. */
    const char *action_label;
    bool action_focused;
} detail_content;

/* Draw the detail between the logical rows `top` and `bottom`, starting at
 * `line_offset` lines into the running text. Returns the number of text lines
 * the body occupies in total, so the caller can page without a second layout
 * pass deciding something different. */
int detail_draw(unsigned char *canvas, const detail_content *detail,
                int top, int bottom, int line_offset);

/* Lines of running text that fit between `top` and `bottom` for a given
 * detail. Paging moves by this many lines at a time. */
int detail_page_lines(const detail_content *detail, int top, int bottom);
