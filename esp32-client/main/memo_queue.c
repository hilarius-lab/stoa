#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#include "esp_random.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_vfs_fat.h"
#include "mbedtls/sha256.h"
#include "memo_queue.h"
#include "crypto.h"

static memo_queue_status status;

void memo_queue_random(void *out, size_t length) { esp_fill_random(out, length); }

bool memo_queue_hash(const char *path, char *hex, uint64_t *length) {
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    bool ok = mbedtls_sha256_starts(&sha, 0) == 0;
    uint8_t buffer[1024];
    uint64_t total = 0;
    size_t got;
    while (ok && (got = fread(buffer, 1, sizeof(buffer), file)) > 0) {
        ok = mbedtls_sha256_update(&sha, buffer, got) == 0;
        total += got;
    }
    if (ferror(file)) ok = false;
    fclose(file);
    uint8_t digest[32];
    if (ok) ok = mbedtls_sha256_finish(&sha, digest) == 0;
    mbedtls_sha256_free(&sha);
    if (!ok) return false;
    for (int i = 0; i < 32; i++) snprintf(hex + i * 2, 3, "%02x", digest[i]);
    *length = total;
    return true;
}

void memo_queue_update_space(void) {
    uint64_t total = 0, available = 0;
    if (esp_vfs_fat_info("/sdcard", &total, &available) != ESP_OK) return;
    status.bytes_total = total;
    status.bytes_free = available;
    uint64_t percent_limit = total / 100 * MEMO_SPACE_WARN_PERCENT;
    status.space_low = available < MEMO_SPACE_WARN_BYTES || available < percent_limit;
    status.space_block = available < MEMO_SPACE_BLOCK_BYTES;
}

static bool memo_directory_name(const char *name) {
    if (strlen(name) != 8) return false;
    return strspn(name, "0123456789abcdefABCDEF") == 8;
}

static bool has_file(const char *directory, const char *name) {
    char path[96];
    struct stat info;
    snprintf(path, sizeof(path), "%s/%s", directory, name);
    return stat(path, &info) == 0;
}

/* A session with segments but no finish record never ends. It cannot be
 * completed, so the upload pass re-creates it on every sync forever, and no
 * retention rule can ever apply to it.
 *
 * Boot recovery is the one moment where closing it is truthful rather than a
 * guess: nothing is recording yet, and the device has restarted since this
 * session was written, so whatever segments are on the card are all there will
 * ever be. The horizon is taken from the segments themselves — the highest
 * sequence present and its end position — never from a count that was hoped
 * for. Sessions without segments are left untouched; there is nothing to close
 * and an empty stub is not evidence of a recording.
 *
 * The recorder no longer produces this state (the finish record used to hang on
 * the recording's overall success). This exists for the sessions already on the
 * card, and as a backstop for any future path that ends a recording abnormally.
 */
static void close_open_horizon(journal_session *session) {
    if (session->finished || session->chunk_count == 0) return;
    unsigned final_sequence = 0;
    uint64_t end_ms = 0;
    for (unsigned i = 0; i < session->chunk_count; i++) {
        const journal_chunk *chunk = &session->chunks[i];
        if (chunk->sequence < final_sequence) continue;
        final_sequence = chunk->sequence;
        end_ms = chunk->source_end_ms;
    }
    char payload[JOURNAL_MAX_PAYLOAD];
    int length = journal_build_finish(payload, sizeof(payload), final_sequence, end_ms);
    if (length <= 0 || !journal_append(session, payload, (size_t)length)) {
        ESP_LOGW("queue", "could not close an unfinished session");
        return;
    }
    session->finished = true;
    session->final_sequence = final_sequence;
    session->final_source_end_ms = end_ms;
    status.closed++;
    ESP_LOGI("queue", "closed an unfinished session at sequence=%u", final_sequence);
}

/* One session at a time: the replay structure is large, so it lives in PSRAM
 * and is released before the next directory is opened. */
static void scan_one(const char *directory) {
    journal_session *session = heap_caps_malloc(sizeof(journal_session), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!session) {
        ESP_LOGE("queue", "no memory to recover a session");
        return;
    }
    journal_session_init(session, directory);
    bool present = journal_replay(session);
    if (!present) {
        /* No journal: either a recording made before H1, or an empty stub. */
        if (!has_file(directory, "00000000.M4A")) { free(session); return; }
        journal_session_init(session, directory);
        if (!journal_adopt(session, memo_queue_hash, audio_crypto_encrypt_file, memo_queue_random, MEMO_FIRMWARE))
            ESP_LOGW("queue", "adoption incomplete for one session");
        status.adopted++;
    }
    if (!journal_recover(session, memo_queue_hash, audio_crypto_encrypt_file))
        ESP_LOGW("queue", "recovery could not persist every state change");
    close_open_horizon(session);

    unsigned session_attention = journal_count_state(session, CHUNK_ATTENTION) +
                                 (session->create_attention ? 1 : 0);
    status.sessions++;
    status.ready += journal_count_state(session, CHUNK_READY);
    status.acked += journal_count_state(session, CHUNK_ACKED);
    status.attention += session_attention;
    /* Segment identifiers and reasons only; never a file name the user chose
     * or any audio content. */
    ESP_LOGI("queue", "session recovered: segments=%u ready=%u acked=%u attention=%u adopted=%d",
             session->chunk_count,
             journal_count_state(session, CHUNK_READY),
             journal_count_state(session, CHUNK_ACKED),
             session_attention,
             session->adopted ? 1 : 0);
    free(session);
}

/* Bounded per pass, like api_client.c's SESSION_WINDOW/session_offset: a full
 * journal_recover() can stat, hash and (for a still-open segment) encrypt a
 * file, so a window of unbounded size on a card holding months of history
 * would turn one scan into a multi-second stall. The window start rotates
 * between passes so a card holding more sessions than one pass covers is
 * still scanned completely -- just spread over more passes, exactly like the
 * upload path already does.
 *
 * Real gap this closes: without rotation, a fixed first-N scan revisits the
 * same N directories every single pass (POSIX readdir() order does not change
 * on its own), so anything past position N could never be recovered at all.
 * That is what stranded three interrupted test recordings in `writing` state
 * indefinitely once the card passed thirty-two sessions -- discovered while
 * investigating a live ESP32 during the H2 encryption work.
 *
 * `status` is reset every pass, so a session outside this pass's window is
 * temporarily absent from `ready`/`acked`/`attention` until rotation reaches
 * it again -- a bounded, self-correcting lag (closed within a few passes,
 * each triggered by any queue state change), not the unresolved counter drift
 * the 6 September incident this file's other comments describe. */
#define SCAN_WINDOW 32
static unsigned scan_offset;

void memo_queue_scan(void) {
    memset(&status, 0, sizeof(status));
    memo_queue_update_space();
    DIR *root = opendir(MEMO_ROOT);
    if (!root) {
        ESP_LOGW("queue", "memo root unavailable; nothing recovered");
        return;
    }
    /* The directory stream is not held open across the per-session work, so a
     * long recovery cannot be disturbed by the reads it performs itself. */
    char names[SCAN_WINDOW][12];
    unsigned found = 0, matching = 0, examined = 0;
    struct dirent *entry;
    while ((entry = readdir(root))) {
        if (!memo_directory_name(entry->d_name)) continue;
        unsigned index = matching++;
        if (index < scan_offset || found == SCAN_WINDOW) continue;
        examined++;
        /* memo_directory_name has already established the exact 8-character
         * form, so the copy is bounded by construction. */
        memcpy(names[found], entry->d_name, 8); names[found][8] = 0; found++;
    }
    closedir(root);
    if (scan_offset >= matching) scan_offset = 0; /* Sessions vanished under the offset. */
    else if (matching > SCAN_WINDOW && examined) scan_offset = (scan_offset + examined) % matching;
    else scan_offset = 0;
    bool more = matching > found;
    for (unsigned i = 0; i < found; i++) {
        char directory[64];
        snprintf(directory, sizeof(directory), "%s/%s", MEMO_ROOT, names[i]);
        scan_one(directory);
    }
    if (more) ESP_LOGW("queue", "scan window: %u of %u sessions this pass; next start=%u",
                       found, matching, scan_offset);
    status.scanned = true;
    memo_queue_report();
}

memo_queue_status memo_queue_get(void) { return status; }

void memo_queue_note_ready(uint64_t bytes) {
    (void)bytes;
    status.ready++;
    memo_queue_update_space();
}

/* The counters are a cache of what the card says, and a cache is only worth
 * having if it cannot drift. The earlier `note_acked`/`note_attention` pair
 * incremented the destination but knew nothing about where a segment came from,
 * so nothing ever left `attention`: a segment marked `server_conflict` and later
 * recovered through reconciliation was counted as both. On 6 September that
 * showed as three permanent exclamation marks over a card whose journals held no
 * marked segment at all — a warning that could not be cleared because it
 * described nothing.
 *
 * One entry point instead, driven by the transition itself, with exactly the
 * bucket rule `memo_queue_scan` uses. Anything that is not READY, ACKED or
 * ATTENTION — writing, uploading — belongs to no bucket, so a segment in flight
 * leaves `ready` and comes back. That is what a rescan would show, and the
 * status bar must not tell a nicer story than the card. */
static unsigned *bucket_for(chunk_state state) {
    switch (state) {
        case CHUNK_READY: return &status.ready;
        case CHUNK_ACKED: return &status.acked;
        case CHUNK_ATTENTION: return &status.attention;
        default: return NULL;
    }
}

void memo_queue_note_transition(chunk_state from, chunk_state to) {
    if (from == to) return;
    unsigned *leaving = bucket_for(from);
    unsigned *entering = bucket_for(to);
    if (leaving && *leaving) (*leaving)--;
    if (entering) (*entering)++;
}

void memo_queue_note_session_transition(bool from_attention, bool to_attention) {
    if (from_attention == to_attention) return;
    if (from_attention && status.attention) status.attention--;
    if (to_attention) status.attention++;
}

void memo_queue_report(void) {
    ESP_LOGI("queue",
             "sessions=%u adopted=%u closed=%u ready=%u acked=%u attention=%u free=%" PRIu64 " total=%" PRIu64
             " space_low=%d space_block=%d",
             status.sessions, status.adopted, status.closed, status.ready, status.acked, status.attention,
             status.bytes_free, status.bytes_total, status.space_low ? 1 : 0,
             status.space_block ? 1 : 0);
}
