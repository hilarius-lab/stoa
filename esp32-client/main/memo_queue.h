#pragma once
// Device-side view of the local upload queue: boot recovery across every memo
// directory on the card, free-space policy, and the counts the display and the
// USB diagnostic report use. Nothing here talks to a backend.
#include <stdbool.h>
#include <stdint.h>
#include "journal.h"

#define MEMO_ROOT "/sdcard/MEMOS"
/* Reported to the backend during enrollment and inside `device_metadata`. It
 * names the roadmap stage the running firmware actually implements and is
 * raised together with every stage, so the server never sees a stale claim. */
#define MEMO_FIRMWARE "h4-w05.2"

/* Free-space policy from docs/IMPLEMENTATION_DECISIONS.md. */
#define MEMO_SPACE_WARN_BYTES (1024ull * 1024 * 1024)
#define MEMO_SPACE_WARN_PERCENT 5
#define MEMO_SPACE_BLOCK_BYTES (256ull * 1024 * 1024)

/* One local session found in `attention` during the most recent scan pass --
 * the history view's on-device replacement for what USB memo-list/memo-why
 * used to be the only way to see. `session_id` is the journal's own UUID (the
 * wire `client_session_id`), so a caller can line this up with a visible
 * server row without either side knowing about the other's storage. `blocked`
 * mirrors recorder_discard()'s `still_deliverable` refusal ahead of time, so
 * the UI can grey out a confirming row instead of offering a discard that
 * would only come back as an error. */
#define MEMO_QUEUE_ATTENTION_MAX 16
typedef struct {
    char id[9];
    char session_id[JOURNAL_UUID_CHARS];
    char reason[24];
    bool blocked;
} memo_queue_attention_entry;

typedef struct {
    unsigned sessions;
    unsigned adopted;
    /* Sessions that carried segments but no finish record and were closed at
     * boot against the segments actually present. Nonzero after an update is
     * expected once; a count that keeps growing means recordings are still
     * ending without closing their horizon. */
    unsigned closed;
    unsigned ready;
    unsigned acked;
    unsigned attention;
    uint64_t bytes_total;
    uint64_t bytes_free;
    bool space_low;   /* warn the user, recording continues */
    bool space_block; /* refuse to start a new recording */
    bool scanned;
} memo_queue_status;

/* Streaming SHA-256 of a file; shared by recovery and the recorder. */
bool memo_queue_hash(const char *path, char *hex, uint64_t *length);
void memo_queue_random(void *out, size_t length);

/* Replay and verify every session on the card. Recovers renamed-but-unrecorded
 * segments, adopts pre-journal directories and classifies the rest. Never
 * deletes or reformats anything. */
void memo_queue_scan(void);

/* Refresh only the free-space part of the status. */
void memo_queue_update_space(void);

memo_queue_status memo_queue_get(void);
/* Copies up to `max` entries found during the last scan pass and returns how
 * many exist. Rebuilt (and reset) every memo_queue_scan() call exactly like
 * `status` above, so it shares the same bounded, self-correcting lag on a
 * card holding more sessions than one pass's SCAN_WINDOW covers -- a session
 * outside this pass's window is temporarily absent until rotation reaches it
 * again, closed within a few passes. Lock-free on purpose, the same as
 * memo_queue_get(): both are a plain-struct read of state the recorder task
 * alone writes, read by the display task the way it already reads that one. */
unsigned memo_queue_attention_snapshot(memo_queue_attention_entry *out, unsigned max);
void memo_queue_note_ready(uint64_t bytes);
/* Every other state change goes through here, with the state the segment left
 * and the state it reached. Both are needed: counting only arrivals lets a
 * segment sit in two buckets forever, which is how `attention` once became
 * unclearable. Uses the same bucket rule as `memo_queue_scan`, so the counters
 * stay equal to what a rescan would produce. */
void memo_queue_note_transition(chunk_state from, chunk_state to);
/* Same rule, for the session-level create-attention flag rather than a chunk
 * state — see journal_session::create_attention. */
void memo_queue_note_session_transition(bool from_attention, bool to_attention);
void memo_queue_report(void);
