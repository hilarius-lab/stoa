#pragma once
// Installation-bound AES-256-GCM encryption for audio segments at rest on
// SD, per docs/IMPLEMENTATION_DECISIONS.md's "Lokaler Datenschutz" section.
// The key lives in NVS in plain form for now; ESP32-S3 Flash Encryption is a
// separate, later production step that protects NVS itself.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Loads this installation's random 256-bit audio key from NVS, generating and
// persisting one on first use. Call once, before any encrypt/verify/read
// call; the key then stays resident in RAM for the process lifetime.
bool audio_crypto_init(void);

// Encrypts the plaintext file at `path` in place with AES-256-GCM: streams it
// into a sibling temporary file, fsyncs, then removes the plaintext and
// renames the ciphertext over `path`. `session_id` and `sequence` are bound
// in as associated data, so a ciphertext cannot be silently swapped between
// segments or sessions. On success `iv_hex`/`tag_hex` (JOURNAL_IV_CHARS/
// JOURNAL_TAG_CHARS-sized buffers) carry the nonce and authentication tag,
// and `stored_hex`/`stored_length` describe the resulting ciphertext exactly
// like a journal_hash_fn describes a plaintext file.
bool audio_crypto_encrypt_file(const char *path, const char *session_id, unsigned sequence,
                               char *iv_hex, char *tag_hex, char *stored_hex, uint64_t *stored_length);

// Verifies the GCM tag over the whole ciphertext file at `path` without ever
// emitting plaintext. Meant to run before a segment is handed to the
// uploader or exported, so a corrupted at-rest file is caught locally
// instead of being streamed out under a mismatched content_hash.
bool audio_crypto_verify_file(const char *path, const char *session_id, unsigned sequence,
                              const char *iv_hex, const char *tag_hex);

// Streaming decryptor: opens the ciphertext file and decrypts it in
// caller-sized blocks, so no plaintext copy is ever written to SD. Only meant
// to be used after audio_crypto_verify_file() has passed.
typedef struct audio_crypto_reader audio_crypto_reader;
audio_crypto_reader *audio_crypto_reader_open(const char *path, const char *session_id,
                                              unsigned sequence, const char *iv_hex);
// Decrypts up to `capacity` bytes into `out`. Returns the number of bytes
// produced, 0 at end of file, or a negative value on a read/decrypt error.
int audio_crypto_reader_read(audio_crypto_reader *reader, uint8_t *out, size_t capacity);
void audio_crypto_reader_close(audio_crypto_reader *reader);
