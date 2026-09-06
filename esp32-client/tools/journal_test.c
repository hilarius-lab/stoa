/* Host test for the platform-independent journal and recovery logic.
 *
 * Builds and runs natively (see tools/run_journal_test.sh). It exercises record
 * framing, torn-tail handling, every recovery classification and power loss at
 * every byte boundary of a real journal. No ESP-IDF or hardware required. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "../main/journal.h"

static int failures = 0, checks = 0;
static void check(bool condition, const char *what) {
    checks++;
    if (!condition) { failures++; printf("  FAIL %s\n", what); }
}

/* ------------------------------------------------------------- SHA-256 */

typedef struct { uint32_t state[8]; uint64_t bits; uint8_t buffer[64]; size_t used; } sha256_ctx;
static const uint32_t K[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
static uint32_t ror(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
static void sha256_block(sha256_ctx *c, const uint8_t *p) {
    uint32_t w[64], a, b, cc, d, e, f, g, h;
    for (int i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[i*4] << 24) | ((uint32_t)p[i*4+1] << 16) | ((uint32_t)p[i*4+2] << 8) | p[i*4+3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = ror(w[i-15],7) ^ ror(w[i-15],18) ^ (w[i-15] >> 3);
        uint32_t s1 = ror(w[i-2],17) ^ ror(w[i-2],19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    a=c->state[0];b=c->state[1];cc=c->state[2];d=c->state[3];
    e=c->state[4];f=c->state[5];g=c->state[6];h=c->state[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = ror(e,6) ^ ror(e,11) ^ ror(e,25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + K[i] + w[i];
        uint32_t S0 = ror(a,2) ^ ror(a,13) ^ ror(a,22);
        uint32_t mj = (a & b) ^ (a & cc) ^ (b & cc);
        uint32_t t2 = S0 + mj;
        h=g; g=f; f=e; e=d+t1; d=cc; cc=b; b=a; a=t1+t2;
    }
    c->state[0]+=a;c->state[1]+=b;c->state[2]+=cc;c->state[3]+=d;
    c->state[4]+=e;c->state[5]+=f;c->state[6]+=g;c->state[7]+=h;
}
static void sha256_init(sha256_ctx *c) {
    static const uint32_t iv[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                                   0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    memcpy(c->state, iv, sizeof(iv)); c->bits = 0; c->used = 0;
}
static void sha256_update(sha256_ctx *c, const uint8_t *data, size_t len) {
    c->bits += (uint64_t)len * 8;
    while (len) {
        size_t take = 64 - c->used;
        if (take > len) take = len;
        memcpy(c->buffer + c->used, data, take);
        c->used += take; data += take; len -= take;
        if (c->used == 64) { sha256_block(c, c->buffer); c->used = 0; }
    }
}
static void sha256_final(sha256_ctx *c, char *hex) {
    uint64_t bits = c->bits;
    uint8_t pad = 0x80;
    sha256_update(c, &pad, 1);
    c->bits = bits;
    uint8_t zero = 0;
    while (c->used != 56) { sha256_update(c, &zero, 1); c->bits = bits; }
    uint8_t tail[8];
    for (int i = 0; i < 8; i++) tail[i] = (uint8_t)(bits >> (56 - 8*i));
    memcpy(c->buffer + c->used, tail, 8);
    sha256_block(c, c->buffer);
    for (int i = 0; i < 8; i++) sprintf(hex + i*8, "%08x", c->state[i]);
}
static bool hash_file(const char *path, char *hex, uint64_t *length) {
    FILE *f = fopen(path, "rb");
    if (!f) return false;
    sha256_ctx c; sha256_init(&c);
    uint8_t buffer[4096]; size_t got; uint64_t total = 0;
    while ((got = fread(buffer, 1, sizeof(buffer), f)) > 0) { sha256_update(&c, buffer, got); total += got; }
    fclose(f);
    sha256_final(&c, hex);
    *length = total;
    return true;
}

static uint32_t seed = 12345;
static void fake_random(void *out, size_t length) {
    uint8_t *bytes = (uint8_t *)out;
    for (size_t i = 0; i < length; i++) { seed = seed * 1103515245u + 12345u; bytes[i] = (uint8_t)(seed >> 16); }
}

/* --------------------------------------------------------------- helpers */

static const char *ROOT = "/tmp/journal_test";
static void run(const char *command) { if (system(command) != 0) { /* best effort */ } }

static void make_dir(const char *path) { mkdir(path, 0700); }

static void write_file(const char *path, const char *content, size_t length) {
    FILE *f = fopen(path, "wb");
    if (!f) { printf("  cannot create %s\n", path); exit(1); }
    fwrite(content, 1, length, f);
    fclose(f);
}

static uint64_t size_of(const char *path) {
    struct stat info;
    return stat(path, &info) == 0 ? (uint64_t)info.st_size : 0;
}

/* Build a realistic three-segment session directory with a valid journal. */
static void build_session(const char *dir, unsigned segments) {
    make_dir(dir);
    journal_session *s = malloc(sizeof(journal_session));
    journal_session_init(s, dir);
    char payload[JOURNAL_MAX_PAYLOAD], id[JOURNAL_UUID_CHARS];
    journal_uuid(id, fake_random);
    int n = journal_build_session(payload, sizeof(payload), id, "memo", "test", 100, NULL, false);
    journal_append(s, payload, (size_t)n);
    for (unsigned i = 0; i < segments; i++) {
        char name[16], path[160], body[300];
        snprintf(name, sizeof(name), "%08u.M4A", i);
        snprintf(path, sizeof(path), "%s/%s", dir, name);
        int length = snprintf(body, sizeof(body), "segment-%u-payload-bytes", i);
        write_file(path, body, (size_t)length);
        char chunk_id[JOURNAL_UUID_CHARS];
        journal_uuid(chunk_id, fake_random);
        n = journal_build_chunk_open(payload, sizeof(payload), i, chunk_id, name, i * 10000ull);
        journal_append(s, payload, (size_t)n);
        journal_chunk *chunk = journal_find(s, i);
        char digest[JOURNAL_SHA_CHARS]; uint64_t hashed = 0;
        hash_file(path, digest, &hashed);
        chunk->plain_length = chunk->stored_length = hashed;
        snprintf(chunk->plain_sha256, sizeof(chunk->plain_sha256), "%s", digest);
        snprintf(chunk->stored_sha256, sizeof(chunk->stored_sha256), "%s", digest);
        snprintf(chunk->encryption, sizeof(chunk->encryption), "none");
        chunk->source_start_ms = i * 10000ull;
        chunk->source_end_ms = (i + 1) * 10000ull;
        chunk->duration_ms = 10000;
        n = journal_build_chunk_ready(payload, sizeof(payload), chunk);
        journal_append(s, payload, (size_t)n);
    }
    n = journal_build_finish(payload, sizeof(payload), segments - 1, segments * 10000ull);
    journal_append(s, payload, (size_t)n);
    free(s);
}

static journal_session *load(const char *dir) {
    journal_session *s = malloc(sizeof(journal_session));
    journal_session_init(s, dir);
    journal_replay(s);
    return s;
}

/* ------------------------------------------------------------- the tests */

static void test_crc_and_uuid(void) {
    printf("framing primitives\n");
    check(journal_crc32("123456789", 9) == 0xCBF43926u, "crc32 known vector");
    check(journal_crc32("", 0) == 0, "crc32 of empty input");
    char uuid[JOURNAL_UUID_CHARS];
    journal_uuid(uuid, fake_random);
    check(strlen(uuid) == 36, "uuid length");
    check(uuid[8] == '-' && uuid[13] == '-' && uuid[18] == '-' && uuid[23] == '-', "uuid dashes");
    check(uuid[14] == '4', "uuid version 4");
    check(uuid[19] == '8' || uuid[19] == '9' || uuid[19] == 'a' || uuid[19] == 'b', "uuid variant");
    char other[JOURNAL_UUID_CHARS];
    journal_uuid(other, fake_random);
    check(strcmp(uuid, other) != 0, "uuids differ");
}

static void test_round_trip(void) {
    printf("record round trip\n");
    char payload[JOURNAL_MAX_PAYLOAD];
    int n = journal_build_chunk_open(payload, sizeof(payload), 7,
                                     "0f9a1c2b-3d4e-4f60-8a1b-2c3d4e5f6071", "00000007.M4A", 70000);
    check(n > 0, "chunk_open built");
    check(strstr(payload, "\"seq\":7") != NULL, "sequence present");
    /* keys must be emitted in ascending order for a stable serialisation */
    check(strcmp(payload, "{\"cid\":\"0f9a1c2b-3d4e-4f60-8a1b-2c3d4e5f6071\",\"f\":\"00000007.M4A\","
                          "\"s0\":70000,\"seq\":7,\"t\":\"chunk_open\"}") == 0, "canonical form");
    uint8_t record[JOURNAL_MAX_RECORD];
    int framed = journal_frame(record, sizeof(record), 1, payload, (size_t)n);
    check(framed == JOURNAL_HEADER_BYTES + n + JOURNAL_TRAILER_BYTES, "framed length");
    journal_session *s = malloc(sizeof(journal_session));
    journal_session_init(s, "/tmp");
    size_t consumed = 0;
    journal_apply_buffer(s, record, (size_t)framed, &consumed);
    check(consumed == (size_t)framed, "whole record consumed");
    check(s->chunk_count == 1 && s->chunks[0].sequence == 7, "chunk applied");
    check(strcmp(s->chunks[0].file, "00000007.M4A") == 0, "file name applied");
    check(s->chunks[0].source_start_ms == 70000, "start time applied");

    /* one flipped payload bit must invalidate the record */
    record[JOURNAL_HEADER_BYTES + 3] ^= 0x01;
    journal_session_init(s, "/tmp");
    journal_apply_buffer(s, record, (size_t)framed, &consumed);
    check(consumed == 0 && s->chunk_count == 0, "payload corruption rejected");
    record[JOURNAL_HEADER_BYTES + 3] ^= 0x01;

    /* a corrupted length field must not be trusted */
    record[16] = 0xFF;
    journal_session_init(s, "/tmp");
    journal_apply_buffer(s, record, (size_t)framed, &consumed);
    check(consumed == 0, "header corruption rejected");
    free(s);
}

static void test_truncation(void) {
    printf("torn trailing record\n");
    char dir[160]; snprintf(dir, sizeof(dir), "%s/torn", ROOT);
    build_session(dir, 3);
    char path[200]; snprintf(path, sizeof(path), "%s/%s", dir, JOURNAL_FILE);
    uint64_t full = size_of(path);
    journal_session *whole = load(dir);
    check(whole->chunk_count == 3 && whole->finished, "intact journal replays fully");
    uint64_t good = whole->valid_bytes;
    check(good == full, "intact journal consumed entirely");

    /* Cut the log at every byte and confirm replay always lands on a record
     * boundary, never crashes and never invents a segment. */
    unsigned boundaries = 0;
    for (uint64_t cut = 0; cut < full; cut++) {
        char command[900];
        snprintf(command, sizeof(command), "cp %s %s.bak", path, path);
        run(command);
        int fd = open(path, O_WRONLY);
        if (ftruncate(fd, (off_t)cut) != 0) { /* ignore */ }
        close(fd);
        journal_session *cutS = load(dir);
        if (cutS->valid_bytes == cut) boundaries++;
        check(cutS->valid_bytes <= cut, "never consumes past the cut");
        check(cutS->chunk_count <= 3, "no invented segments");
        for (unsigned i = 0; i < cutS->chunk_count; i++)
            check(cutS->chunks[i].state != CHUNK_UNKNOWN, "every known segment has a state");
        check(size_of(path) == cutS->valid_bytes, "torn tail truncated to a record boundary");
        free(cutS);
        snprintf(command, sizeof(command), "cp %s.bak %s", path, path);
        run(command);
    }
    check(boundaries >= 3, "several exact record boundaries seen");
    free(whole);
}

static void test_recovery_cases(void) {
    printf("recovery classification\n");
    char dir[160], path[220];

    /* healthy */
    snprintf(dir, sizeof(dir), "%s/healthy", ROOT);
    build_session(dir, 3);
    journal_session *s = load(dir);
    journal_recover(s, hash_file);
    check(journal_count_state(s, CHUNK_READY) == 3, "healthy session is fully ready");
    check(journal_count_state(s, CHUNK_ATTENTION) == 0, "healthy session has no attention");
    free(s);
    s = load(dir);
    check(journal_count_state(s, CHUNK_READY) == 3, "recovery result survives a reload");
    free(s);

    /* deleted segment */
    snprintf(dir, sizeof(dir), "%s/missing", ROOT);
    build_session(dir, 3);
    snprintf(path, sizeof(path), "%s/00000001.M4A", dir);
    unlink(path);
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 1)->state == CHUNK_ATTENTION, "missing file is attention");
    check(strcmp(journal_find(s, 1)->reason, "missing") == 0, "missing reason recorded");
    check(journal_find(s, 0)->state == CHUNK_READY, "neighbours stay ready");
    free(s);

    /* truncated segment */
    snprintf(dir, sizeof(dir), "%s/shortfile", ROOT);
    build_session(dir, 2);
    snprintf(path, sizeof(path), "%s/00000000.M4A", dir);
    write_file(path, "short", 5);
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_ATTENTION, "size mismatch is attention");
    check(strcmp(journal_find(s, 0)->reason, "size") == 0, "size reason recorded");
    free(s);

    /* same length, different bytes */
    snprintf(dir, sizeof(dir), "%s/badbytes", ROOT);
    build_session(dir, 2);
    snprintf(path, sizeof(path), "%s/00000000.M4A", dir);
    uint64_t length = size_of(path);
    char *same = malloc(length);
    memset(same, 'x', length);
    write_file(path, same, length);
    free(same);
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_ATTENTION, "hash mismatch is attention");
    check(strcmp(journal_find(s, 0)->reason, "hash") == 0, "hash reason recorded");
    free(s);

    /* opened, renamed, but the ready record never reached the card */
    snprintf(dir, sizeof(dir), "%s/reopened", ROOT);
    make_dir(dir);
    {
        journal_session *w = malloc(sizeof(journal_session));
        journal_session_init(w, dir);
        char payload[JOURNAL_MAX_PAYLOAD], id[JOURNAL_UUID_CHARS];
        journal_uuid(id, fake_random);
        int n = journal_build_session(payload, sizeof(payload), id, "memo", "test", 1, NULL, false);
        journal_append(w, payload, (size_t)n);
        journal_uuid(id, fake_random);
        n = journal_build_chunk_open(payload, sizeof(payload), 0, id, "00000000.M4A", 0);
        journal_append(w, payload, (size_t)n);
        free(w);
        snprintf(path, sizeof(path), "%s/00000000.M4A", dir);
        write_file(path, "complete-audio", 14);
    }
    s = load(dir);
    check(journal_find(s, 0)->state == CHUNK_WRITING, "unfinished segment replays as writing");
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_READY, "renamed segment is recovered to ready");
    check(journal_find(s, 0)->stored_length == 14, "recovered length recorded");
    free(s);
    s = load(dir);
    check(journal_find(s, 0)->state == CHUNK_READY, "recovered ready record is durable");
    free(s);

    /* power lost mid-segment: only the temporary file exists */
    snprintf(dir, sizeof(dir), "%s/partial", ROOT);
    make_dir(dir);
    {
        journal_session *w = malloc(sizeof(journal_session));
        journal_session_init(w, dir);
        char payload[JOURNAL_MAX_PAYLOAD], id[JOURNAL_UUID_CHARS];
        journal_uuid(id, fake_random);
        int n = journal_build_session(payload, sizeof(payload), id, "memo", "test", 1, NULL, false);
        journal_append(w, payload, (size_t)n);
        journal_uuid(id, fake_random);
        n = journal_build_chunk_open(payload, sizeof(payload), 0, id, "00000000.M4A", 0);
        journal_append(w, payload, (size_t)n);
        free(w);
        snprintf(path, sizeof(path), "%s/00000000.TMP", dir);
        write_file(path, "half", 4);
    }
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_ATTENTION, "partial segment is attention");
    check(strcmp(journal_find(s, 0)->reason, "incomplete") == 0, "incomplete reason recorded");
    check(size_of(path) == 4, "partial file is kept, not deleted");
    free(s);

    /* an acked segment keeps its state and is not re-verified */
    snprintf(dir, sizeof(dir), "%s/acked", ROOT);
    build_session(dir, 2);
    {
        journal_session *w = load(dir);
        char payload[JOURNAL_MAX_PAYLOAD];
        int n = journal_build_chunk_state(payload, sizeof(payload), 0, CHUNK_ACKED, "");
        journal_append(w, payload, (size_t)n);
        free(w);
    }
    snprintf(path, sizeof(path), "%s/00000000.M4A", dir);
    unlink(path);
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_ACKED, "acked stays acked after the file is gone");
    free(s);

    /* an upload interrupted in flight simply retries */
    snprintf(dir, sizeof(dir), "%s/inflight", ROOT);
    build_session(dir, 1);
    {
        journal_session *w = load(dir);
        char payload[JOURNAL_MAX_PAYLOAD];
        int n = journal_build_chunk_state(payload, sizeof(payload), 0, CHUNK_UPLOADING, "");
        journal_append(w, payload, (size_t)n);
        free(w);
    }
    s = load(dir);
    check(journal_find(s, 0)->state == CHUNK_UPLOADING, "uploading state replays");
    journal_recover(s, hash_file);
    check(journal_find(s, 0)->state == CHUNK_READY, "interrupted upload collapses to ready");
    free(s);

    /* a file the journal never mentions */
    snprintf(dir, sizeof(dir), "%s/orphan", ROOT);
    build_session(dir, 1);
    snprintf(path, sizeof(path), "%s/00000009.M4A", dir);
    write_file(path, "stray", 5);
    s = load(dir);
    journal_recover(s, hash_file);
    check(journal_find(s, 9) && journal_find(s, 9)->state == CHUNK_ATTENTION, "orphan is attention");
    check(size_of(path) == 5, "orphan file is kept");
    free(s);
}

static void test_adoption(void) {
    printf("adopting a pre-journal recording\n");
    char dir[160], path[220];
    snprintf(dir, sizeof(dir), "%s/legacy", ROOT);
    make_dir(dir);
    for (unsigned i = 0; i < 5; i++) {
        char body[64];
        snprintf(path, sizeof(path), "%s/%08u.M4A", dir, i);
        int n = snprintf(body, sizeof(body), "legacy-audio-%u", i);
        write_file(path, body, (size_t)n);
    }
    snprintf(path, sizeof(path), "%s/COMPLETE.TXT", dir);
    write_file(path, "local_memo_v1\nsegments=5\nsamples=1\n", 34);

    journal_session *s = malloc(sizeof(journal_session));
    journal_session_init(s, dir);
    check(!journal_replay(s), "no journal present before adoption");
    check(journal_adopt(s, hash_file, fake_random, "test"), "adoption succeeds");
    free(s);

    s = load(dir);
    check(s->chunk_count == 5, "all legacy segments adopted");
    check(s->adopted, "session marked as adopted");
    check(s->finished, "adopted session is finished");
    check(journal_count_state(s, CHUNK_READY) == 5, "adopted segments are ready");
    check(strlen(s->chunks[0].chunk_id) == 36, "adopted segment has a chunk uuid");
    check(strlen(s->session_id) == 36, "adopted session has a uuid");
    journal_recover(s, hash_file);
    check(journal_count_state(s, CHUNK_ATTENTION) == 0, "adopted session verifies cleanly");
    free(s);
}

static void test_long_session(void) {
    printf("thirty-two segment session\n");
    char dir[160];
    snprintf(dir, sizeof(dir), "%s/long", ROOT);
    build_session(dir, 32);
    journal_session *s = load(dir);
    check(s->chunk_count == 32, "all 32 segments replay");
    check(s->final_sequence == 31, "final sequence recorded");
    journal_recover(s, hash_file);
    check(journal_count_state(s, CHUNK_READY) == 32, "all 32 segments ready");
    for (unsigned i = 0; i < 32; i++) {
        check(s->chunks[i].sequence == i, "sequence order preserved");
        check(s->chunks[i].source_start_ms == i * 10000ull, "monotonic start times");
        check(s->chunks[i].source_end_ms > s->chunks[i].source_start_ms, "positive duration");
    }
    free(s);
}

int main(void) {
    char command[200];
    snprintf(command, sizeof(command), "rm -rf %s && mkdir -p %s", ROOT, ROOT);
    run(command);
    test_crc_and_uuid();
    test_round_trip();
    test_truncation();
    test_recovery_cases();
    test_adoption();
    test_long_session();
    printf("\n%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
