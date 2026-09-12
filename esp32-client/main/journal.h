#pragma once
// Append-only, checksummed per-session journal for the local upload queue.
//
// The journal is the only authority for what the device believes about a
// recording. Audio files are immutable; every state change is a new record.
// Nothing here interprets backend semantics: it records what was written to
// the SD card and what was confirmed, so that boot recovery can classify each
// segment as ready, acked or attention without ever losing one silently.
//
// The record payload already carries the fields that later SD encryption will
// need (plain vs stored length and digest, IV and tag). Until encryption is
// enabled the plain and stored values are identical and `enc` is "none", so
// H6 does not require a journal format migration.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define JOURNAL_MAGIC 0x314A4E53u /* "SNJ1" little-endian on disk */
#define JOURNAL_FORMAT_VERSION 1
#define JOURNAL_HEADER_BYTES 24
#define JOURNAL_TRAILER_BYTES 4
#define JOURNAL_MAX_PAYLOAD 512
#define JOURNAL_MAX_RECORD (JOURNAL_HEADER_BYTES + JOURNAL_MAX_PAYLOAD + JOURNAL_TRAILER_BYTES)
#define JOURNAL_MAX_SEGMENTS 512
#define JOURNAL_FILE "JOURNAL.LOG"
#define JOURNAL_TMP "JOURNAL.TMP"

#define JOURNAL_UUID_CHARS 37 /* 36 characters plus terminator */
/* Segments are numbered from zero, locally and on the wire. Declared once here
 * because the create request states it as part of the session's identity and
 * the response is checked against it; two places holding the number separately
 * is how the two would eventually disagree. */
#define JOURNAL_SEQUENCE_BASE 0
#define JOURNAL_SHA_CHARS 65  /* 64 lowercase hex characters plus terminator */
#define JOURNAL_CONTEXT_TYPE_CHARS 16

typedef enum {
    CHUNK_UNKNOWN = 0, /* referenced by no record; never persisted */
    CHUNK_WRITING,     /* opened, not yet completed */
    CHUNK_READY,       /* durable locally, awaiting upload */
    CHUNK_UPLOADING,   /* request in flight; collapses to READY on boot */
    CHUNK_ACKED,       /* durable ACK persisted */
    CHUNK_ATTENTION    /* visible defect; never silently dropped */
} chunk_state;

typedef struct {
    unsigned sequence;
    char chunk_id[JOURNAL_UUID_CHARS];
    char file[16];
    chunk_state state;
    char reason[24];
    uint64_t plain_length;
    uint64_t stored_length;
    char plain_sha256[JOURNAL_SHA_CHARS];
    char stored_sha256[JOURNAL_SHA_CHARS];
    uint64_t source_start_ms;
    uint64_t source_end_ms;
    uint64_t duration_ms;
    char encryption[12];
    /* Real per-segment backoff timing for retry_class=backoff (API_INTERACTION.md's
     * Segmentupload table), persisted so it survives a reboot. `backoff_until` is
     * a wall-clock unix second, not a monotonic one: a monotonic deadline would
     * outlive its own clock across a reboot, since the new boot's esp_timer
     * restarts near zero and could never catch up to an old, larger value. Zero
     * means unrestricted. `backoff_attempts` drives the exponential growth and is
     * reset by any ordinary chunk_state transition, not only a successful one. */
    unsigned backoff_attempts;
    uint64_t backoff_until;
} journal_chunk;

typedef struct {
    char directory[64];
    char session_id[JOURNAL_UUID_CHARS];
    char capture_mode[12];
    char context_type[JOURNAL_CONTEXT_TYPE_CHARS];
    char context_id[JOURNAL_UUID_CHARS];
    uint64_t next_record;   /* record number to use for the next append */
    uint64_t valid_bytes;   /* journal length up to the last intact record */
    unsigned chunk_count;
    bool adopted;           /* reconstructed from a pre-journal recording */
    bool finished;
    /* Session-level defect, distinct from any chunk: the server was reached
     * and gave a definitive answer that was not the expected success — a
     * rejected identity, not a network hiccup. Set only from a real response,
     * so a DNS or connectivity gap never lights this up. */
    bool create_attention;
    char create_reason[24];
    unsigned final_sequence;
    uint64_t final_source_end_ms;
    journal_chunk chunks[JOURNAL_MAX_SEGMENTS];
} journal_session;

/* Streaming digest of a file, supplied by the caller so that this module stays
 * free of platform crypto. Returns true and fills `hex` with 64 lowercase hex
 * characters and `length` with the byte count. */
typedef bool (*journal_hash_fn)(const char *path, char *hex, uint64_t *length);

uint32_t journal_crc32(const void *data, size_t length);

/* RFC 4122 version 4 UUID from a caller-supplied random source. */
typedef void (*journal_random_fn)(void *out, size_t length);
void journal_uuid(char *out, journal_random_fn random_source);

/* --- record construction (pure, canonical, sorted keys) --- */
int journal_build_session(char *out, size_t capacity, const char *session_id,
                          const char *capture_mode, const char *firmware,
                          uint64_t monotonic_ms, const char *captured_at, bool adopted);
int journal_build_session_context(char *out, size_t capacity, const char *session_id,
                                  const char *capture_mode, const char *context_type,
                                  const char *context_id, const char *firmware,
                                  uint64_t monotonic_ms, const char *captured_at,
                                  bool adopted);
int journal_build_chunk_open(char *out, size_t capacity, unsigned sequence,
                             const char *chunk_id, const char *file, uint64_t source_start_ms);
int journal_build_chunk_ready(char *out, size_t capacity, const journal_chunk *chunk);
int journal_build_chunk_state(char *out, size_t capacity, unsigned sequence,
                              chunk_state state, const char *reason);
/* A chunk sent back to READY with a persisted wall-clock "not before" time and
 * an attempt count, distinct from journal_build_chunk_state so an ordinary
 * transition (which always clears backoff on replay) never has to special-case
 * this one. */
int journal_build_chunk_backoff(char *out, size_t capacity, unsigned sequence,
                                unsigned attempts, uint64_t until_unix);
int journal_build_finish(char *out, size_t capacity, unsigned final_sequence,
                         uint64_t final_source_end_ms);
/* Session-level defect, set or cleared. `reason` is truncated the same way as
 * a chunk's; empty clears it. */
int journal_build_session_state(char *out, size_t capacity, bool attention,
                                const char *reason);

/* Frame one payload into `out`. Returns the framed length or -1. */
int journal_frame(uint8_t *out, size_t capacity, uint64_t record_number,
                  const char *payload, size_t payload_length);

/* Apply a framed buffer to `session`. `consumed` receives the length of the
 * intact prefix, so a torn trailing record is simply ignored. */
void journal_apply_buffer(journal_session *session, const uint8_t *data,
                          size_t length, size_t *consumed);

/* --- file-backed operations --- */
void journal_session_init(journal_session *session, const char *directory);
bool journal_append(journal_session *session, const char *payload, size_t payload_length);
bool journal_replay(journal_session *session);

/* Verify every segment against the recorded size and digest and classify it.
 * Recovers a renamed-but-unrecorded segment by hashing it and appending the
 * missing record. Never deletes, truncates or reformats user data. */
bool journal_recover(journal_session *session, journal_hash_fn hash);

/* Reconstruct a journal for a directory recorded before H1. */
bool journal_adopt(journal_session *session, journal_hash_fn hash,
                   journal_random_fn random_source, const char *firmware);

const char *journal_state_name(chunk_state state);
journal_chunk *journal_find(journal_session *session, unsigned sequence);
unsigned journal_count_state(const journal_session *session, chunk_state state);
