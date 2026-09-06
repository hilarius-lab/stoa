#pragma once
// The history view behind the header button: past recordings, newest first,
// from `GET /api/client/v1/sessions`.
//
// Free of JSON so the layout and the wording can be checked on the host. The
// caller parses the response into rows; this module only draws them.
#include <stdbool.h>

#define HISTORY_ROW_HEIGHT 46
#define HISTORY_HEADER_HEIGHT 30
#define HISTORY_TIME_CHARS 16
#define HISTORY_LABEL_CHARS 24

typedef struct {
    /* Already formatted for display, because the parser knows the source format
     * and the renderer should not. */
    char when[HISTORY_TIME_CHARS];
    char state[HISTORY_LABEL_CHARS];
    /* The server reported an error for this recording. Drawn as a mark, never
     * as the error text: `last_error` may carry server wording of unknown
     * length and is not something the panel should render verbatim. */
    bool failed;
} history_row;

/* The German label for a server session state. Unknown states are returned
 * unchanged rather than guessed at or hidden, so a contract extension shows up
 * as an unfamiliar word instead of silently reading as something it is not. */
const char *history_state_label(const char *state);

/* Format an ISO 8601 UTC timestamp as `06.09. 14:32`. Returns false and writes
 * a placeholder if the text is not a timestamp of the expected shape; a
 * malformed field must not produce a plausible-looking date.
 *
 * With `local` the value is converted into the display timezone, which is only
 * correct once the clock is synchronised — the caller passes the answer to that
 * question rather than this module guessing it. Without it the server's UTC
 * value is shown unchanged and the list header says so, because a local time
 * from an unsynchronised device is wrong in a way nobody can see. */
bool history_format_time(char *out, unsigned capacity, const char *iso, bool local);

/* One row. `focused` inverts it, as it does a card. */
void history_row_draw(unsigned char *canvas, const history_row *row,
                      int x, int y, int width, bool focused);

/* The list header, drawn above the rows. Returns HISTORY_HEADER_HEIGHT, so a
 * measuring pass and a drawing pass cannot disagree about it. `local` selects
 * the wording: without a synchronised clock the header states that the times
 * are UTC, so an unconverted value is never mistaken for a local one. */
int history_header_draw(unsigned char *canvas, int x, int y, int width, bool local);
