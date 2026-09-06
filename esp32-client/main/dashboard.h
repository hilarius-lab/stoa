#pragma once
// Renders a dashboard snapshot into the body.
//
// The snapshot is walked directly; there is no intermediate model, so nothing
// is copied and nothing can drift out of sync with what the server sent. The
// firmware interprets no business meaning: it maps the announced vocabulary to
// drawing values (dashboard_map.h) and lays the result out for this panel.
//
// Measuring and drawing are the same walk. A separate measuring pass would be
// a second source of truth about how tall the content is, and the two would
// eventually disagree.
#include <stdbool.h>
#include "dashboard_map.h"

/* Walk the snapshot. With `canvas` set, the visible part is drawn between the
 * logical rows `top` and `bottom`, scrolled by `scroll`, with `focus_index`
 * marked; with `canvas` NULL nothing is drawn. With `plan` set, the row
 * geometry is recorded for the paging arithmetic. Either may be omitted. */
void dashboard_walk(unsigned char *canvas, const char *json,
                    int top, int bottom, int scroll, int focus_index,
                    dashboard_plan *plan);

/* Draw an entity response as the detail view. Returns the number of body text
 * lines, and reports through `page` how many of them fit at once. Both come
 * from the same layout the drawing uses. */
int dashboard_entity_draw(unsigned char *canvas, const char *json,
                          int top, int bottom, int line_offset, int *page);
