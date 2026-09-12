#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include "esp_random.h"
#include "esp_log.h"
#include "nvs.h"
#include "mbedtls/gcm.h"
#include "mbedtls/sha256.h"
#include "crypto.h"

// journal.c already defines this for its own file writes; mirrored here
// rather than pulled in, since this module has no other reason to depend on
// the journal header.
#ifndef O_BINARY
#define O_BINARY 0
#endif

#define AUDIO_KEY_BYTES 32
#define GCM_IV_BYTES 12
#define GCM_TAG_BYTES 16
#define IO_BUFFER_BYTES 1024

static uint8_t audio_key[AUDIO_KEY_BYTES];
static bool audio_key_ready;

static void to_hex(const uint8_t *bytes, size_t count, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < count; i++) {
        out[i * 2] = digits[bytes[i] >> 4];
        out[i * 2 + 1] = digits[bytes[i] & 0x0F];
    }
    out[count * 2] = 0;
}

static bool from_hex(const char *hex, uint8_t *out, size_t count) {
    if (!hex || strlen(hex) != count * 2) return false;
    for (size_t i = 0; i < count; i++) {
        unsigned value;
        if (sscanf(hex + i * 2, "%2x", &value) != 1) return false;
        out[i] = (uint8_t)value;
    }
    return true;
}

/* Binds a ciphertext to its own segment: without this, a chunk's ciphertext
 * could be renamed onto a different sequence or session and would still
 * decrypt and authenticate cleanly under the same key. */
static size_t build_aad(char *out, size_t capacity, const char *session_id, unsigned sequence) {
    int n = snprintf(out, capacity, "%s:%u", session_id, sequence);
    return n > 0 && (size_t)n < capacity ? (size_t)n : 0;
}

bool audio_crypto_init(void) {
    if (audio_key_ready) return true;
    nvs_handle_t handle;
    if (nvs_open("notebook", NVS_READWRITE, &handle) != ESP_OK) return false;
    size_t size = sizeof(audio_key);
    if (nvs_get_blob(handle, "audio_key", audio_key, &size) == ESP_OK && size == sizeof(audio_key)) {
        nvs_close(handle);
        audio_key_ready = true;
        return true;
    }
    esp_fill_random(audio_key, sizeof(audio_key));
    bool ok = nvs_set_blob(handle, "audio_key", audio_key, sizeof(audio_key)) == ESP_OK &&
              nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
    if (!ok) {
        ESP_LOGE("crypto", "could not persist a new audio-at-rest key");
        return false;
    }
    audio_key_ready = true;
    return true;
}

bool audio_crypto_encrypt_file(const char *path, const char *session_id, unsigned sequence,
                               char *iv_hex, char *tag_hex, char *stored_hex, uint64_t *stored_length) {
    if (!audio_key_ready) { ESP_LOGE("crypto", "encrypt: key not ready"); return false; }
    FILE *in = fopen(path, "rb");
    if (!in) { ESP_LOGE("crypto", "encrypt: cannot open plaintext, errno=%d", errno); return false; }
    /* Every filename this firmware writes is a strict FAT 8.3 short name
     * (`00000000.M4A`, `JOURNAL.LOG`, ...); FATFS here rejects anything else
     * with EINVAL. `path + ".ENC"` produced a second dot and an over-long
     * name (`00000000.M4A.ENC`) -- real on-device failure, not visible in
     * any build. The extension is replaced instead of appended. */
    char temporary[128];
    const char *dot = strrchr(path, '.');
    if (!dot) {
        ESP_LOGE("crypto", "encrypt: plaintext path has no extension to replace");
        fclose(in);
        return false;
    }
    size_t base_len = (size_t)(dot - path);
    if (base_len + 4 >= sizeof(temporary)) {
        ESP_LOGE("crypto", "encrypt: temporary path too long");
        fclose(in);
        return false;
    }
    memcpy(temporary, path, base_len);
    memcpy(temporary + base_len, ".ENC", 5); /* includes the terminator */
    int out_fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_BINARY, 0600);
    if (out_fd < 0) {
        ESP_LOGE("crypto", "encrypt: cannot open ciphertext temp file, errno=%d", errno);
        fclose(in);
        return false;
    }

    uint8_t iv[GCM_IV_BYTES];
    esp_fill_random(iv, sizeof(iv));
    char aad[80];
    size_t aad_len = build_aad(aad, sizeof(aad), session_id, sequence);

    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    int rc;
    bool ok = true;
    if ((rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, audio_key, 256)) != 0) {
        ESP_LOGE("crypto", "encrypt: gcm_setkey failed, rc=-0x%04x", (unsigned)-rc);
        ok = false;
    } else if ((rc = mbedtls_gcm_starts(&gcm, MBEDTLS_GCM_ENCRYPT, iv, sizeof(iv))) != 0) {
        ESP_LOGE("crypto", "encrypt: gcm_starts failed, rc=-0x%04x", (unsigned)-rc);
        ok = false;
    } else if (aad_len > 0 && (rc = mbedtls_gcm_update_ad(&gcm, (const uint8_t *)aad, aad_len)) != 0) {
        ESP_LOGE("crypto", "encrypt: gcm_update_ad failed, rc=-0x%04x", (unsigned)-rc);
        ok = false;
    } else if ((rc = mbedtls_sha256_starts(&sha, 0)) != 0) {
        ESP_LOGE("crypto", "encrypt: sha256_starts failed, rc=-0x%04x", (unsigned)-rc);
        ok = false;
    }

    /* mbedtls_gcm_update() does not promise output_length == input_length per
     * call -- on this target it may buffer internally (see the vendored
     * gcm.h), so the output buffer needs the documented input+15 headroom
     * and any bytes mbedtls_gcm_finish() still owes at the end must be
     * captured too, not discarded with output_size=0. */
    uint8_t plain[IO_BUFFER_BYTES], cipher[IO_BUFFER_BYTES + 16];
    uint64_t total = 0;
    size_t got;
    while (ok && (got = fread(plain, 1, sizeof(plain), in)) > 0) {
        size_t produced = 0;
        if ((rc = mbedtls_gcm_update(&gcm, plain, got, cipher, sizeof(cipher), &produced)) != 0) {
            ESP_LOGE("crypto", "encrypt: gcm_update failed, rc=-0x%04x got=%u", (unsigned)-rc, (unsigned)got);
            ok = false;
            break;
        }
        if (produced > 0) {
            if (write(out_fd, cipher, produced) != (ssize_t)produced) {
                ESP_LOGE("crypto", "encrypt: ciphertext write failed, errno=%d", errno);
                ok = false;
                break;
            }
            if (mbedtls_sha256_update(&sha, cipher, produced) != 0) {
                ESP_LOGE("crypto", "encrypt: sha256_update failed");
                ok = false;
                break;
            }
        }
        total += produced;
    }
    if (ok && ferror(in)) { ESP_LOGE("crypto", "encrypt: plaintext read error"); ok = false; }
    fclose(in);

    uint8_t tag[GCM_TAG_BYTES], digest[32], tail[16];
    size_t tail_len = 0;
    if (ok && (rc = mbedtls_gcm_finish(&gcm, tail, sizeof(tail), &tail_len, tag, sizeof(tag))) != 0) {
        ESP_LOGE("crypto", "encrypt: gcm_finish failed, rc=-0x%04x", (unsigned)-rc);
        ok = false;
    }
    if (ok && tail_len > 0) {
        if (write(out_fd, tail, tail_len) != (ssize_t)tail_len || mbedtls_sha256_update(&sha, tail, tail_len) != 0) {
            ESP_LOGE("crypto", "encrypt: tail write/hash failed, errno=%d", errno);
            ok = false;
        } else {
            total += tail_len;
        }
    }
    if (ok && mbedtls_sha256_finish(&sha, digest) != 0) {
        ESP_LOGE("crypto", "encrypt: sha256_finish failed");
        ok = false;
    }
    mbedtls_gcm_free(&gcm);
    mbedtls_sha256_free(&sha);

    if (ok && fsync(out_fd) != 0) { ESP_LOGE("crypto", "encrypt: fsync failed, errno=%d", errno); ok = false; }
    if (close(out_fd) != 0) { ESP_LOGE("crypto", "encrypt: close failed, errno=%d", errno); ok = false; }
    if (!ok) { unlink(temporary); return false; }

    /* Replace the plaintext with the ciphertext. A crash between these two
     * calls leaves a `.M4A` still holding plaintext and a finished `.ENC`
     * beside it, with no chunk_ready record yet appended for either: on the
     * next boot journal_recover() finds CHUNK_WRITING with the `.M4A` still
     * present and simply repeats hashing and encryption from there, this
     * time producing a new (still unique) IV. Never leaves a segment
     * unencrypted and marked ready. */
    if (unlink(path) != 0) {
        ESP_LOGE("crypto", "encrypt: cannot remove plaintext, errno=%d", errno);
        unlink(temporary);
        return false;
    }
    if (rename(temporary, path) != 0) {
        ESP_LOGE("crypto", "encrypt: cannot rename ciphertext into place, errno=%d", errno);
        return false;
    }

    to_hex(iv, sizeof(iv), iv_hex);
    to_hex(tag, sizeof(tag), tag_hex);
    to_hex(digest, sizeof(digest), stored_hex);
    *stored_length = total;
    return true;
}

bool audio_crypto_verify_file(const char *path, const char *session_id, unsigned sequence,
                              const char *iv_hex, const char *tag_hex) {
    if (!audio_key_ready) return false;
    uint8_t iv[GCM_IV_BYTES], expected_tag[GCM_TAG_BYTES];
    if (!from_hex(iv_hex, iv, sizeof(iv)) || !from_hex(tag_hex, expected_tag, sizeof(expected_tag))) return false;
    FILE *in = fopen(path, "rb");
    if (!in) return false;
    char aad[80];
    size_t aad_len = build_aad(aad, sizeof(aad), session_id, sequence);

    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    bool ok = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, audio_key, 256) == 0 &&
              mbedtls_gcm_starts(&gcm, MBEDTLS_GCM_DECRYPT, iv, sizeof(iv)) == 0 &&
              (aad_len == 0 || mbedtls_gcm_update_ad(&gcm, (const uint8_t *)aad, aad_len) == 0);

    uint8_t cipher[IO_BUFFER_BYTES], discard[IO_BUFFER_BYTES + 16];
    size_t got;
    while (ok && (got = fread(cipher, 1, sizeof(cipher), in)) > 0) {
        size_t produced = 0;
        if (mbedtls_gcm_update(&gcm, cipher, got, discard, sizeof(discard), &produced) != 0) {
            ok = false;
            break;
        }
    }
    if (ok && ferror(in)) ok = false;
    fclose(in);

    uint8_t tag[GCM_TAG_BYTES], tail[16];
    size_t tail_len = 0;
    if (ok) ok = mbedtls_gcm_finish(&gcm, tail, sizeof(tail), &tail_len, tag, sizeof(tag)) == 0;
    mbedtls_gcm_free(&gcm);
    if (!ok) return false;
    /* Compared locally against a value this same device wrote earlier, not
     * against an attacker-controlled one over a timing-observable channel, so
     * a plain memcmp is adequate here. */
    return memcmp(tag, expected_tag, sizeof(tag)) == 0;
}

/* GCM's per-call output can trail the input by up to a block and mbedtls_gcm_
 * finish() can still owe a final partial block once the file is exhausted
 * (see the encrypt-side comment above) -- so a caller-sized read() cannot
 * just forward one mbedtls_gcm_update() call. Decrypted bytes that do not fit
 * the caller's request yet sit in `pending` until drained by later calls. */
#define READER_CIPHER_CHUNK IO_BUFFER_BYTES
#define READER_PENDING_BYTES (READER_CIPHER_CHUNK + 16)

struct audio_crypto_reader {
    FILE *file;
    mbedtls_gcm_context gcm;
    uint8_t pending[READER_PENDING_BYTES];
    size_t pending_length;
    size_t pending_at;
    bool finished; /* mbedtls_gcm_finish() has already run */
    bool failed;
};

audio_crypto_reader *audio_crypto_reader_open(const char *path, const char *session_id,
                                              unsigned sequence, const char *iv_hex) {
    if (!audio_key_ready) return NULL;
    uint8_t iv[GCM_IV_BYTES];
    if (!from_hex(iv_hex, iv, sizeof(iv))) return NULL;
    audio_crypto_reader *reader = calloc(1, sizeof(*reader));
    if (!reader) return NULL;
    reader->file = fopen(path, "rb");
    if (!reader->file) { free(reader); return NULL; }
    char aad[80];
    size_t aad_len = build_aad(aad, sizeof(aad), session_id, sequence);
    mbedtls_gcm_init(&reader->gcm);
    bool ok = mbedtls_gcm_setkey(&reader->gcm, MBEDTLS_CIPHER_ID_AES, audio_key, 256) == 0 &&
              mbedtls_gcm_starts(&reader->gcm, MBEDTLS_GCM_DECRYPT, iv, sizeof(iv)) == 0 &&
              (aad_len == 0 || mbedtls_gcm_update_ad(&reader->gcm, (const uint8_t *)aad, aad_len) == 0);
    if (!ok) {
        fclose(reader->file);
        mbedtls_gcm_free(&reader->gcm);
        free(reader);
        return NULL;
    }
    return reader;
}

int audio_crypto_reader_read(audio_crypto_reader *reader, uint8_t *out, size_t capacity) {
    if (!reader || reader->failed) return -1;
    size_t delivered = 0;
    while (delivered < capacity) {
        if (reader->pending_at < reader->pending_length) {
            size_t available = reader->pending_length - reader->pending_at;
            size_t take = capacity - delivered < available ? capacity - delivered : available;
            memcpy(out + delivered, reader->pending + reader->pending_at, take);
            reader->pending_at += take;
            delivered += take;
            continue;
        }
        reader->pending_at = reader->pending_length = 0;
        if (reader->finished) break; /* nothing left, ever */
        uint8_t cipher[READER_CIPHER_CHUNK];
        size_t got = fread(cipher, 1, sizeof(cipher), reader->file);
        if (got == 0) {
            if (ferror(reader->file)) { reader->failed = true; return -1; }
            /* End of ciphertext: mbedtls_gcm_finish() may still owe up to a
             * block of plaintext it had buffered internally. The tag output
             * is discarded here -- audio_crypto_verify_file() already
             * authenticated this exact file before this reader was opened. */
            uint8_t tag[GCM_TAG_BYTES];
            if (mbedtls_gcm_finish(&reader->gcm, reader->pending, sizeof(reader->pending),
                                   &reader->pending_length, tag, sizeof(tag)) != 0) {
                reader->failed = true;
                return -1;
            }
            reader->finished = true;
            if (reader->pending_length == 0) break;
            continue;
        }
        if (mbedtls_gcm_update(&reader->gcm, cipher, got, reader->pending, sizeof(reader->pending),
                               &reader->pending_length) != 0) {
            reader->failed = true;
            return -1;
        }
    }
    return (int)delivered;
}

void audio_crypto_reader_close(audio_crypto_reader *reader) {
    if (!reader) return;
    fclose(reader->file);
    mbedtls_gcm_free(&reader->gcm);
    free(reader);
}
