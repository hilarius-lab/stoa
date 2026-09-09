#pragma once
// The row between the status bar and the dashboard body.
//
// Left: the history button, the only focusable element outside the cards and
// the one focused when the dashboard is entered. Right: how current the shown
// snapshot is. Both are local truth; the server has no say in either.
//
// The age is given relative ("vor 3 min") rather than as a wall clock time.
// That is deliberate: it stays honest before a trustworthy SNTP sync, which
// the device does not have yet, and it answers the question the reader
// actually has.
#include <stdbool.h>

#define HEADER_HEIGHT 40

typedef enum {
    HEADER_NEVER,   /* no schema-valid snapshot has ever arrived */
    HEADER_CURRENT, /* a snapshot is shown and the device is online */
    HEADER_OFFLINE, /* a cached snapshot is shown, the network is down */
    HEADER_EMPTY,   /* a valid snapshot with no sections */
    HEADER_STALE,   /* the cache outlived dashboard_cache_max_age_seconds */
} header_snapshot;

typedef struct {
    header_snapshot snapshot;
    unsigned age_minutes;
    bool focused; /* the menu button carries the focus */
    /* The menu button opens a view selector rather than jumping straight to
     * the recording list. The five view icons (0=dashboard, 1=tasks,
     * 2=lists, 3=history, 4=settings) sit in this row all the time, not only while
     * picking one — a marker that only exists for a few button presses is
     * easy to miss entirely. `active_view` always names which one is
     * currently showing and gets a standing outline. While `selector_open`,
     * that outline steps aside for the moving cursor at `selector_focus`, so
     * the two marks never compete on the same icon. */
    bool selector_open;
    int selector_focus;
    int active_view;
} header_state;

/* Draw the row directly below the status bar. */
void header_draw(unsigned char *canvas, const header_state *state);

/* The age wording, exposed so the host test can check the boundaries. */
void header_age_text(char *out, unsigned capacity, unsigned age_minutes);

/* Resolve the standing view marker defensively. Local full-screen views win if
 * stale dashboard-family flags overlap during a transition. */
int header_active_view(bool tasks, bool lists, bool history, bool settings);

/* Two hours without a successful poll. Applies only when the server states no
 * limit of its own. */
#define HEADER_STALE_FALLBACK_S 7200u

/* Which of the five states a snapshot is in.
 *
 * `age_seconds` is the time since the last accepted poll, not the age of the
 * content: a snapshot the server keeps confirming stays current however old its
 * text is, and only a genuine loss of contact ages it. `limit_seconds` is
 * `limits.dashboard_cache_max_age_seconds` from the capabilities, or 0 when the
 * server stated none, in which case HEADER_STALE_FALLBACK_S applies.
 *
 * Kept out of the display task so the boundaries can be tested on the host. */
header_snapshot header_snapshot_for(bool seen, bool empty, bool online,
                                    unsigned age_seconds, unsigned limit_seconds);
