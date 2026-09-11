#pragma once
// The detail view: one card opened full height.
//
// Free of JSON, like the rest of the drawing layer, so the pagination can be
// tested on the host. The caller supplies already resolved strings.
#include <stdbool.h>

#define DETAIL_ACTION_MAX 3

typedef struct {
    const char *title;
    const char *reason;  /* reason_text, between title and body; may be NULL */
    const char *body;    /* content, or the question for a query */
    const char *answer;  /* answer, when one exists; may be NULL */
    const char *meta;    /* kind and status, hidden when actions are present */
    /* Focus 0 is "Zurück"; 1..action_count select server-projected answers or
     * the one closed object action. Labels are display-only and bounded here;
     * the caller resolves the selected index back to its fixed content. */
    const char *action_labels[DETAIL_ACTION_MAX];
    int action_count;
    int action_focus;
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
