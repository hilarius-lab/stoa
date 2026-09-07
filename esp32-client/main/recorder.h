#pragma once
#include <stdbool.h>
void recorder_start(void);
void recorder_hold(bool held);
void recorder_test(void);
void recorder_export_test(void);
void recorder_files(const char *id);
/* Read-only: prints every segment's state, recorded reason and file presence. */
void recorder_explain(const char *id);
/* Discards every eligible session at once. `expected` must equal the number of
 * eligible sessions or nothing is touched. Sessions with deliverable segments
 * are always skipped. */
void recorder_discard_all(unsigned expected);
/* Discards one named session, irreversibly. Refused with `still_deliverable`
 * while any of its segments is still `ready` or `uploading` — only broken or
 * already-delivered sessions can be removed this way. */
void recorder_discard(const char *id);
bool recorder_busy(void);
void recorder_queue_status(void);
