#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include "journal.h"

/* ---------------------------------------------------------------- CRC32 */

uint32_t journal_crc32(const void *data, size_t length) {
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < length; i++) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1)));
    }
    return crc ^ 0xFFFFFFFFu;
}

/* ----------------------------------------------------------------- UUID */

void journal_uuid(char *out, journal_random_fn random_source) {
    uint8_t bytes[16];
    random_source(bytes, sizeof(bytes));
    bytes[6] = (uint8_t)((bytes[6] & 0x0F) | 0x40); /* version 4 */
    bytes[8] = (uint8_t)((bytes[8] & 0x3F) | 0x80); /* RFC 4122 variant */
    static const char digits[] = "0123456789abcdef";
    int at = 0;
    for (int i = 0; i < 16; i++) {
        if (i == 4 || i == 6 || i == 8 || i == 10) out[at++] = '-';
        out[at++] = digits[bytes[i] >> 4];
        out[at++] = digits[bytes[i] & 0x0F];
    }
    out[at] = 0;
}

/* ------------------------------------------------- canonical JSON writer */

/* Values are device-generated identifiers, hex digests, 8.3 file names and
 * fixed enum words. Anything outside printable ASCII is rejected rather than
 * escaped, so a payload can never smuggle control characters into the log. */
static bool write_string(char *out, size_t capacity, size_t *at, const char *value) {
    if (*at + 2 >= capacity) return false;
    out[(*at)++] = '"';
    for (const char *c = value; *c; c++) {
        unsigned char ch = (unsigned char)*c;
        if (ch < 0x20 || ch > 0x7E) return false;
        if (ch == '"' || ch == '\\') {
            if (*at + 2 >= capacity) return false;
            out[(*at)++] = '\\';
        }
        if (*at + 2 >= capacity) return false;
        out[(*at)++] = (char)ch;
    }
    out[(*at)++] = '"';
    out[*at] = 0;
    return true;
}

static bool write_raw(char *out, size_t capacity, size_t *at, const char *text) {
    size_t length = strlen(text);
    if (*at + length + 1 >= capacity) return false;
    memcpy(out + *at, text, length);
    *at += length;
    out[*at] = 0;
    return true;
}

static bool write_key(char *out, size_t capacity, size_t *at, const char *key, bool first) {
    if (!first && !write_raw(out, capacity, at, ",")) return false;
    if (!write_string(out, capacity, at, key)) return false;
    return write_raw(out, capacity, at, ":");
}

static bool write_text_field(char *out, size_t capacity, size_t *at,
                             const char *key, const char *value, bool first) {
    if (!write_key(out, capacity, at, key, first)) return false;
    return write_string(out, capacity, at, value);
}

static bool write_number_field(char *out, size_t capacity, size_t *at,
                               const char *key, uint64_t value, bool first) {
    char digits[24];
    snprintf(digits, sizeof(digits), "%" PRIu64, value);
    if (!write_key(out, capacity, at, key, first)) return false;
    return write_raw(out, capacity, at, digits);
}

/* ------------------------------------------------- minimal JSON reader */

static const char *find_key(const char *json, const char *key) {
    char pattern[24];
    int length = snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    if (length <= 0 || (size_t)length >= sizeof(pattern)) return NULL;
    const char *found = strstr(json, pattern);
    return found ? found + length : NULL;
}

static bool read_text(const char *json, const char *key, char *out, size_t capacity) {
    const char *at = find_key(json, key);
    if (!at || *at != '"') return false;
    at++;
    size_t used = 0;
    while (*at && *at != '"') {
        if (*at == '\\') {
            at++;
            if (!*at) return false;
        }
        if (used + 1 >= capacity) return false;
        out[used++] = *at++;
    }
    if (*at != '"') return false;
    out[used] = 0;
    return true;
}

static bool read_number(const char *json, const char *key, uint64_t *out) {
    const char *at = find_key(json, key);
    if (!at || *at < '0' || *at > '9') return false;
    uint64_t value = 0;
    while (*at >= '0' && *at <= '9') {
        if (value > (UINT64_MAX - (uint64_t)(*at - '0')) / 10) return false;
        value = value * 10 + (uint64_t)(*at - '0');
        at++;
    }
    *out = value;
    return true;
}

/* ------------------------------------------------------ record builders */

const char *journal_state_name(chunk_state state) {
    switch (state) {
        case CHUNK_WRITING: return "writing";
        case CHUNK_READY: return "ready";
        case CHUNK_UPLOADING: return "uploading";
        case CHUNK_ACKED: return "acked";
        case CHUNK_ATTENTION: return "attention";
        default: return "unknown";
    }
}

static chunk_state state_from_name(const char *name) {
    if (strcmp(name, "writing") == 0) return CHUNK_WRITING;
    if (strcmp(name, "ready") == 0) return CHUNK_READY;
    if (strcmp(name, "uploading") == 0) return CHUNK_UPLOADING;
    if (strcmp(name, "acked") == 0) return CHUNK_ACKED;
    if (strcmp(name, "attention") == 0) return CHUNK_ATTENTION;
    return CHUNK_UNKNOWN;
}

/* Keys are emitted in ascending order so the same state always serialises to
 * the same bytes. That keeps the CRC meaningful as an integrity check rather
 * than an artefact of key ordering. */
int journal_build_session(char *out, size_t capacity, const char *session_id,
                          const char *capture_mode, const char *firmware,
                          uint64_t monotonic_ms, const char *captured_at, bool adopted) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    bool first = true;
    if (ok && captured_at && captured_at[0]) {
        ok = write_text_field(out, capacity, &at, "at", captured_at, first);
        first = false;
    }
    if (ok) { ok = write_text_field(out, capacity, &at, "cm", capture_mode, first); first = false; }
    if (ok) ok = write_text_field(out, capacity, &at, "fw", firmware, false);
    if (ok && adopted) ok = write_number_field(out, capacity, &at, "og", 1, false);
    if (ok) ok = write_text_field(out, capacity, &at, "sid", session_id, false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "session", false);
    if (ok) ok = write_number_field(out, capacity, &at, "tm", monotonic_ms, false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

int journal_build_chunk_open(char *out, size_t capacity, unsigned sequence,
                             const char *chunk_id, const char *file, uint64_t source_start_ms) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    if (ok) ok = write_text_field(out, capacity, &at, "cid", chunk_id, true);
    if (ok) ok = write_text_field(out, capacity, &at, "f", file, false);
    if (ok) ok = write_number_field(out, capacity, &at, "s0", source_start_ms, false);
    if (ok) ok = write_number_field(out, capacity, &at, "seq", sequence, false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "chunk_open", false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

int journal_build_chunk_ready(char *out, size_t capacity, const journal_chunk *chunk) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    if (ok) ok = write_number_field(out, capacity, &at, "d", chunk->duration_ms, true);
    if (ok) ok = write_text_field(out, capacity, &at, "enc",
                                  chunk->encryption[0] ? chunk->encryption : "none", false);
    if (ok) ok = write_text_field(out, capacity, &at, "ph", chunk->plain_sha256, false);
    if (ok) ok = write_number_field(out, capacity, &at, "pl", chunk->plain_length, false);
    if (ok) ok = write_number_field(out, capacity, &at, "s0", chunk->source_start_ms, false);
    if (ok) ok = write_number_field(out, capacity, &at, "s1", chunk->source_end_ms, false);
    if (ok) ok = write_number_field(out, capacity, &at, "seq", chunk->sequence, false);
    if (ok) ok = write_text_field(out, capacity, &at, "sh", chunk->stored_sha256, false);
    if (ok) ok = write_number_field(out, capacity, &at, "sl", chunk->stored_length, false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "chunk_ready", false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

int journal_build_chunk_state(char *out, size_t capacity, unsigned sequence,
                              chunk_state state, const char *reason) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    if (ok) ok = write_text_field(out, capacity, &at, "r", reason ? reason : "", true);
    if (ok) ok = write_number_field(out, capacity, &at, "seq", sequence, false);
    if (ok) ok = write_text_field(out, capacity, &at, "st", journal_state_name(state), false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "chunk_state", false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

int journal_build_finish(char *out, size_t capacity, unsigned final_sequence,
                         uint64_t final_source_end_ms) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    if (ok) ok = write_number_field(out, capacity, &at, "fe", final_source_end_ms, true);
    if (ok) ok = write_number_field(out, capacity, &at, "fs", final_sequence, false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "session_finish", false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

int journal_build_session_state(char *out, size_t capacity, bool attention,
                                const char *reason) {
    size_t at = 0;
    bool ok = write_raw(out, capacity, &at, "{");
    if (ok) ok = write_number_field(out, capacity, &at, "a", attention ? 1 : 0, true);
    if (ok) ok = write_text_field(out, capacity, &at, "r", reason ? reason : "", false);
    if (ok) ok = write_text_field(out, capacity, &at, "t", "session_state", false);
    if (ok) ok = write_raw(out, capacity, &at, "}");
    return ok ? (int)at : -1;
}

/* ---------------------------------------------------------------- framing */

static void put32(uint8_t *out, uint32_t value) {
    out[0] = (uint8_t)value; out[1] = (uint8_t)(value >> 8);
    out[2] = (uint8_t)(value >> 16); out[3] = (uint8_t)(value >> 24);
}
static void put64(uint8_t *out, uint64_t value) {
    for (int i = 0; i < 8; i++) out[i] = (uint8_t)(value >> (8 * i));
}
static uint32_t get32(const uint8_t *in) {
    return (uint32_t)in[0] | ((uint32_t)in[1] << 8) | ((uint32_t)in[2] << 16) | ((uint32_t)in[3] << 24);
}
static uint64_t get64(const uint8_t *in) {
    uint64_t value = 0;
    for (int i = 0; i < 8; i++) value |= (uint64_t)in[i] << (8 * i);
    return value;
}

/* The header carries its own CRC so that a corrupt payload length can never
 * make recovery read past the end of an intact record. */
int journal_frame(uint8_t *out, size_t capacity, uint64_t record_number,
                  const char *payload, size_t payload_length) {
    if (payload_length == 0 || payload_length > JOURNAL_MAX_PAYLOAD) return -1;
    size_t total = JOURNAL_HEADER_BYTES + payload_length + JOURNAL_TRAILER_BYTES;
    if (total > capacity) return -1;
    put32(out + 0, JOURNAL_MAGIC);
    out[4] = JOURNAL_FORMAT_VERSION; out[5] = 0;
    out[6] = JOURNAL_HEADER_BYTES; out[7] = 0;
    put64(out + 8, record_number);
    put32(out + 16, (uint32_t)payload_length);
    put32(out + 20, journal_crc32(out, 20));
    memcpy(out + JOURNAL_HEADER_BYTES, payload, payload_length);
    put32(out + JOURNAL_HEADER_BYTES + payload_length, journal_crc32(payload, payload_length));
    return (int)total;
}

/* ------------------------------------------------------------- replaying */

journal_chunk *journal_find(journal_session *session, unsigned sequence) {
    for (unsigned i = 0; i < session->chunk_count; i++)
        if (session->chunks[i].sequence == sequence) return &session->chunks[i];
    return NULL;
}

static journal_chunk *chunk_slot(journal_session *session, unsigned sequence) {
    journal_chunk *chunk = journal_find(session, sequence);
    if (chunk) return chunk;
    if (session->chunk_count >= JOURNAL_MAX_SEGMENTS) return NULL;
    chunk = &session->chunks[session->chunk_count++];
    memset(chunk, 0, sizeof(*chunk));
    chunk->sequence = sequence;
    chunk->state = CHUNK_UNKNOWN;
    return chunk;
}

static void apply_payload(journal_session *session, const char *json) {
    char type[20];
    if (!read_text(json, "t", type, sizeof(type))) return;
    if (strcmp(type, "session") == 0) {
        read_text(json, "sid", session->session_id, sizeof(session->session_id));
        read_text(json, "cm", session->capture_mode, sizeof(session->capture_mode));
        uint64_t adopted = 0;
        if (read_number(json, "og", &adopted)) session->adopted = adopted != 0;
        return;
    }
    if (strcmp(type, "session_finish") == 0) {
        uint64_t final_sequence = 0, final_end = 0;
        if (read_number(json, "fs", &final_sequence)) session->final_sequence = (unsigned)final_sequence;
        if (read_number(json, "fe", &final_end)) session->final_source_end_ms = final_end;
        session->finished = true;
        return;
    }
    if (strcmp(type, "session_state") == 0) {
        uint64_t attention = 0;
        read_number(json, "a", &attention);
        session->create_attention = attention != 0;
        read_text(json, "r", session->create_reason, sizeof(session->create_reason));
        return;
    }
    uint64_t sequence = 0;
    if (!read_number(json, "seq", &sequence)) return;
    journal_chunk *chunk = chunk_slot(session, (unsigned)sequence);
    if (!chunk) return;
    if (strcmp(type, "chunk_open") == 0) {
        read_text(json, "cid", chunk->chunk_id, sizeof(chunk->chunk_id));
        read_text(json, "f", chunk->file, sizeof(chunk->file));
        read_number(json, "s0", &chunk->source_start_ms);
        chunk->state = CHUNK_WRITING;
        return;
    }
    if (strcmp(type, "chunk_ready") == 0) {
        read_number(json, "d", &chunk->duration_ms);
        read_number(json, "pl", &chunk->plain_length);
        read_number(json, "sl", &chunk->stored_length);
        read_number(json, "s0", &chunk->source_start_ms);
        read_number(json, "s1", &chunk->source_end_ms);
        read_text(json, "ph", chunk->plain_sha256, sizeof(chunk->plain_sha256));
        read_text(json, "sh", chunk->stored_sha256, sizeof(chunk->stored_sha256));
        read_text(json, "enc", chunk->encryption, sizeof(chunk->encryption));
        chunk->state = CHUNK_READY;
        return;
    }
    if (strcmp(type, "chunk_state") == 0) {
        char name[16];
        if (!read_text(json, "st", name, sizeof(name))) return;
        chunk_state state = state_from_name(name);
        if (state != CHUNK_UNKNOWN) chunk->state = state;
        read_text(json, "r", chunk->reason, sizeof(chunk->reason));
        return;
    }
}

void journal_apply_buffer(journal_session *session, const uint8_t *data,
                          size_t length, size_t *consumed) {
    size_t at = 0;
    char payload[JOURNAL_MAX_PAYLOAD + 1];
    while (at + JOURNAL_HEADER_BYTES + JOURNAL_TRAILER_BYTES <= length) {
        const uint8_t *record = data + at;
        if (get32(record) != JOURNAL_MAGIC) break;
        if (record[4] != JOURNAL_FORMAT_VERSION || record[5] != 0) break;
        if (record[6] != JOURNAL_HEADER_BYTES || record[7] != 0) break;
        if (get32(record + 20) != journal_crc32(record, 20)) break;
        uint64_t number = get64(record + 8);
        /* A gap or repeat in the record numbers means the tail is not the log
         * we wrote; stop rather than replaying an ambiguous history. */
        if (number != session->next_record) break;
        uint32_t payload_length = get32(record + 16);
        if (payload_length == 0 || payload_length > JOURNAL_MAX_PAYLOAD) break;
        size_t total = JOURNAL_HEADER_BYTES + payload_length + JOURNAL_TRAILER_BYTES;
        if (at + total > length) break;
        if (get32(record + JOURNAL_HEADER_BYTES + payload_length) !=
            journal_crc32(record + JOURNAL_HEADER_BYTES, payload_length)) break;
        memcpy(payload, record + JOURNAL_HEADER_BYTES, payload_length);
        payload[payload_length] = 0;
        apply_payload(session, payload);
        session->next_record = number + 1;
        at += total;
    }
    if (consumed) *consumed = at;
}

/* ---------------------------------------------------------- file backing */

void journal_session_init(journal_session *session, const char *directory) {
    memset(session, 0, sizeof(*session));
    snprintf(session->directory, sizeof(session->directory), "%s", directory);
    session->next_record = 1;
    snprintf(session->capture_mode, sizeof(session->capture_mode), "memo");
}

static void journal_path(const journal_session *session, char *out, size_t capacity, const char *name) {
    snprintf(out, capacity, "%s/%s", session->directory, name);
}

bool journal_append(journal_session *session, const char *payload, size_t payload_length) {
    uint8_t record[JOURNAL_MAX_RECORD];
    int framed = journal_frame(record, sizeof(record), session->next_record, payload, payload_length);
    if (framed < 0) return false;
    char path[96];
    journal_path(session, path, sizeof(path), JOURNAL_FILE);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0) return false;
    bool ok = write(fd, record, (size_t)framed) == framed;
    if (ok) ok = fsync(fd) == 0;
    if (close(fd) != 0) ok = false;
    if (!ok) return false;
    session->next_record++;
    session->valid_bytes += (uint64_t)framed;
    /* Keep the in-memory view identical to what a fresh replay would produce. */
    char copy[JOURNAL_MAX_PAYLOAD + 1];
    size_t length = payload_length < JOURNAL_MAX_PAYLOAD ? payload_length : JOURNAL_MAX_PAYLOAD;
    memcpy(copy, payload, length);
    copy[length] = 0;
    apply_payload(session, copy);
    return true;
}

/* Drop everything after the last intact record. `ftruncate` is the direct
 * route; where the filesystem refuses it the log is rebuilt through a
 * temporary file and an atomic rename, so a crash here leaves either the old
 * log or the trimmed one, never a half-written mixture. */
static void journal_trim(journal_session *session, uint64_t keep) {
    char path[96], temporary[96];
    journal_path(session, path, sizeof(path), JOURNAL_FILE);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) {
        bool done = ftruncate(fd, (off_t)keep) == 0;
        if (done) fsync(fd);
        close(fd);
        if (done) return;
    }
    journal_path(session, temporary, sizeof(temporary), JOURNAL_TMP);
    int in = open(path, O_RDONLY);
    if (in < 0) return;
    int out = open(temporary, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (out < 0) { close(in); return; }
    uint8_t buffer[512];
    uint64_t copied = 0;
    bool ok = true;
    while (copied < keep) {
        size_t want = keep - copied < sizeof(buffer) ? (size_t)(keep - copied) : sizeof(buffer);
        ssize_t got = read(in, buffer, want);
        if (got <= 0) { ok = false; break; }
        if (write(out, buffer, (size_t)got) != got) { ok = false; break; }
        copied += (uint64_t)got;
    }
    if (ok) ok = fsync(out) == 0;
    if (close(out) != 0) ok = false;
    close(in);
    if (ok) rename(temporary, path); else unlink(temporary);
}

bool journal_replay(journal_session *session) {
    char path[96];
    journal_path(session, path, sizeof(path), JOURNAL_FILE);
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    /* Records are read in windows so that a long session never needs the whole
     * journal resident; a record straddling a window is retried in the next. */
    uint8_t window[4096];
    size_t filled = 0;
    uint64_t offset = 0;
    bool truncated = false;
    while (true) {
        ssize_t got = read(fd, window + filled, sizeof(window) - filled);
        if (got < 0) { close(fd); return false; }
        filled += (size_t)got;
        size_t consumed = 0;
        journal_apply_buffer(session, window, filled, &consumed);
        offset += consumed;
        if (consumed < filled) {
            memmove(window, window + consumed, filled - consumed);
            filled -= consumed;
            if (got == 0 || filled == sizeof(window)) { truncated = true; break; }
        } else {
            filled = 0;
            if (got == 0) break;
        }
    }
    close(fd);
    session->valid_bytes = offset;
    /* A torn trailing record is dropped so the next append starts on a record
     * boundary. Only the unreadable tail is removed; no user data is touched. */
    if (truncated) journal_trim(session, offset);
    return true;
}

unsigned journal_count_state(const journal_session *session, chunk_state state) {
    unsigned count = 0;
    for (unsigned i = 0; i < session->chunk_count; i++)
        if (session->chunks[i].state == state) count++;
    return count;
}

/* ----------------------------------------------------------- recovery */

static bool file_size(const char *path, uint64_t *size) {
    struct stat info;
    if (stat(path, &info) != 0) return false;
    *size = (uint64_t)info.st_size;
    return true;
}

static bool mark(journal_session *session, journal_chunk *chunk,
                 chunk_state state, const char *reason) {
    if (chunk->state == state && strcmp(chunk->reason, reason ? reason : "") == 0) return true;
    char payload[JOURNAL_MAX_PAYLOAD];
    int length = journal_build_chunk_state(payload, sizeof(payload), chunk->sequence, state, reason);
    if (length < 0) return false;
    return journal_append(session, payload, (size_t)length);
}

bool journal_recover(journal_session *session, journal_hash_fn hash) {
    bool ok = true;
    for (unsigned i = 0; i < session->chunk_count; i++) {
        journal_chunk *chunk = &session->chunks[i];
        if (chunk->state == CHUNK_ACKED || chunk->state == CHUNK_ATTENTION) continue;
        char final_path[112], partial_path[112];
        snprintf(final_path, sizeof(final_path), "%s/%08u.M4A", session->directory, chunk->sequence);
        snprintf(partial_path, sizeof(partial_path), "%s/%08u.TMP", session->directory, chunk->sequence);
        uint64_t size = 0;
        bool present = file_size(final_path, &size);

        if (chunk->state == CHUNK_WRITING) {
            /* Opened but never completed. If the rename happened the segment is
             * intact and only the record is missing, so hash it now. Otherwise
             * the partial file is kept and shown, never silently discarded. */
            if (!present) {
                uint64_t partial = 0;
                const char *reason = file_size(partial_path, &partial) ? "incomplete" : "lost";
                if (!mark(session, chunk, CHUNK_ATTENTION, reason)) ok = false;
                continue;
            }
            char digest[JOURNAL_SHA_CHARS];
            uint64_t length = 0;
            if (!hash(final_path, digest, &length)) {
                if (!mark(session, chunk, CHUNK_ATTENTION, "unreadable")) ok = false;
                continue;
            }
            chunk->plain_length = chunk->stored_length = length;
            snprintf(chunk->plain_sha256, sizeof(chunk->plain_sha256), "%s", digest);
            snprintf(chunk->stored_sha256, sizeof(chunk->stored_sha256), "%s", digest);
            snprintf(chunk->encryption, sizeof(chunk->encryption), "none");
            if (chunk->source_end_ms < chunk->source_start_ms)
                chunk->source_end_ms = chunk->source_start_ms;
            char payload[JOURNAL_MAX_PAYLOAD];
            int written = journal_build_chunk_ready(payload, sizeof(payload), chunk);
            if (written < 0 || !journal_append(session, payload, (size_t)written)) ok = false;
            continue;
        }

        /* READY or an upload that was in flight when power was lost. An
         * interrupted request is simply retried, so it collapses to READY. */
        if (!present) {
            if (!mark(session, chunk, CHUNK_ATTENTION, "missing")) ok = false;
            continue;
        }
        if (size != chunk->stored_length) {
            if (!mark(session, chunk, CHUNK_ATTENTION, "size")) ok = false;
            continue;
        }
        char digest[JOURNAL_SHA_CHARS];
        uint64_t length = 0;
        if (!hash(final_path, digest, &length)) {
            if (!mark(session, chunk, CHUNK_ATTENTION, "unreadable")) ok = false;
            continue;
        }
        if (strcmp(digest, chunk->stored_sha256) != 0) {
            if (!mark(session, chunk, CHUNK_ATTENTION, "hash")) ok = false;
            continue;
        }
        if (chunk->state != CHUNK_READY && !mark(session, chunk, CHUNK_READY, "")) ok = false;
    }

    /* A segment file the journal never mentions is reported, never adopted
     * into a journalled session and never removed. */
    DIR *directory = opendir(session->directory);
    if (directory) {
        struct dirent *entry;
        while ((entry = readdir(directory))) {
            const char *name = entry->d_name;
            size_t length = strlen(name);
            if (length != 12 || strcmp(name + 8, ".M4A") != 0) continue;
            unsigned sequence = (unsigned)strtoul(name, NULL, 10);
            journal_chunk *chunk = journal_find(session, sequence);
            if (chunk) continue;
            chunk = chunk_slot(session, sequence);
            if (!chunk) continue;
            memcpy(chunk->file, name, 12);
            chunk->file[12] = 0;
            if (!mark(session, chunk, CHUNK_ATTENTION, "orphan")) ok = false;
        }
        closedir(directory);
    }
    return ok;
}

/* ----------------------------------------------------------- adoption */

/* Directories recorded before the journal existed still hold valid audio. They
 * are given a journal so the H2 uploader can treat every recording alike. */
bool journal_adopt(journal_session *session, journal_hash_fn hash,
                   journal_random_fn random_source, const char *firmware) {
    char payload[JOURNAL_MAX_PAYLOAD];
    char session_id[JOURNAL_UUID_CHARS];
    journal_uuid(session_id, random_source);
    int length = journal_build_session(payload, sizeof(payload), session_id, "memo",
                                       firmware, 0, NULL, true);
    if (length < 0 || !journal_append(session, payload, (size_t)length)) return false;

    bool ok = true;
    uint64_t position = 0;
    for (unsigned sequence = 0; sequence < JOURNAL_MAX_SEGMENTS; sequence++) {
        char path[112], name[16];
        snprintf(name, sizeof(name), "%08u.M4A", sequence);
        snprintf(path, sizeof(path), "%s/%s", session->directory, name);
        uint64_t size = 0;
        if (!file_size(path, &size)) break;
        char chunk_id[JOURNAL_UUID_CHARS];
        journal_uuid(chunk_id, random_source);
        length = journal_build_chunk_open(payload, sizeof(payload), sequence, chunk_id, name, position);
        if (length < 0 || !journal_append(session, payload, (size_t)length)) { ok = false; break; }
        journal_chunk *chunk = journal_find(session, sequence);
        if (!chunk) { ok = false; break; }
        char digest[JOURNAL_SHA_CHARS];
        uint64_t hashed = 0;
        if (!hash(path, digest, &hashed)) {
            if (!mark(session, chunk, CHUNK_ATTENTION, "unreadable")) ok = false;
            continue;
        }
        /* Segment timing was not recorded before H1. The nominal ten-second
         * grid is used so ordering is preserved; the backend reassembles from
         * the sequence, not from these estimates. */
        chunk->plain_length = chunk->stored_length = hashed;
        snprintf(chunk->plain_sha256, sizeof(chunk->plain_sha256), "%s", digest);
        snprintf(chunk->stored_sha256, sizeof(chunk->stored_sha256), "%s", digest);
        snprintf(chunk->encryption, sizeof(chunk->encryption), "none");
        chunk->source_start_ms = position;
        chunk->source_end_ms = position + 10000;
        chunk->duration_ms = 10000;
        position = chunk->source_end_ms;
        length = journal_build_chunk_ready(payload, sizeof(payload), chunk);
        if (length < 0 || !journal_append(session, payload, (size_t)length)) { ok = false; break; }
    }
    if (ok && session->chunk_count) {
        length = journal_build_finish(payload, sizeof(payload),
                                      session->chunk_count - 1, position);
        if (length < 0 || !journal_append(session, payload, (size_t)length)) ok = false;
    }
    return ok;
}
