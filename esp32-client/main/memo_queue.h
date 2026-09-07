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
#define MEMO_FIRMWARE "h3-surface"

/* Free-space policy from docs/IMPLEMENTATION_DECISIONS.md. */
#define MEMO_SPACE_WARN_BYTES (1024ull * 1024 * 1024)
#define MEMO_SPACE_WARN_PERCENT 5
#define MEMO_SPACE_BLOCK_BYTES (256ull * 1024 * 1024)

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
