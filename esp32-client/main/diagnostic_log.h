#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef enum {
    DIAG_EVENT_BOOT,
    DIAG_EVENT_STORAGE,
    DIAG_EVENT_WIFI_UP,
    DIAG_EVENT_WIFI_DOWN,
    DIAG_EVENT_SETUP_OPEN,
    DIAG_EVENT_SETUP_CANCEL,
    DIAG_EVENT_SETUP_SAVED,
    DIAG_EVENT_GATE_OK,
    DIAG_EVENT_GATE_FAILED,
    DIAG_EVENT_QUEUE,
    DIAG_EVENT_CAPTURE_START,
    DIAG_EVENT_CAPTURE_END,
} diagnostic_event;

/* Starts the sink only after /sdcard is mounted. Events before that are
 * intentionally dropped rather than buffered with unknown lifetime. */
bool diagnostic_log_start(void);
bool diagnostic_log_available(void);

/* Only numeric arguments enter this interface. The implementation maps each
 * event to a fixed string, so content, IDs, SSIDs, URLs, tokens and arbitrary
 * response text cannot accidentally become durable diagnostics. */
void diagnostic_log_event(diagnostic_event event, int first, int second,
                          int third);

/* Returns the newest complete newline-delimited records from the current log.
 * `out` is always terminated when capacity is non-zero. */
unsigned diagnostic_log_read_tail(char *out, size_t capacity);

/* Content-free USB status: availability and file sizes only, never records. */
void diagnostic_log_report(void);
