#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "diagnostic_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define DIAG_DIRECTORY "/sdcard/DIAG"
#define DIAG_CURRENT DIAG_DIRECTORY "/DIAG0.LOG"
#define DIAG_PREVIOUS DIAG_DIRECTORY "/DIAG1.LOG"
#define DIAG_OLDEST DIAG_DIRECTORY "/DIAG2.LOG"
#define DIAG_ROTATE_BYTES (16 * 1024)

static SemaphoreHandle_t log_lock;
static atomic_bool log_ready;
static bool queue_seen;
static int queue_ready, queue_acked, queue_attention;

static bool rotate_for(size_t incoming) {
    struct stat state;
    if (stat(DIAG_CURRENT, &state) != 0) return errno == ENOENT;
    if ((size_t)state.st_size + incoming <= DIAG_ROTATE_BYTES) return true;
    /* Diagnostics are recoverable and non-authoritative. A power loss between
     * these explicit renames may lose an old log, never memo/audio state. */
    unlink(DIAG_OLDEST);
    if (rename(DIAG_PREVIOUS, DIAG_OLDEST) != 0 && errno != ENOENT) return false;
    if (rename(DIAG_CURRENT, DIAG_PREVIOUS) != 0) return false;
    return true;
}

bool diagnostic_log_start(void) {
    if (atomic_load(&log_ready)) return true;
    if (!log_lock) log_lock = xSemaphoreCreateMutex();
    if (!log_lock) return false;
    if (mkdir(DIAG_DIRECTORY, 0700) != 0 && errno != EEXIST) return false;
    atomic_store(&log_ready, true);
    diagnostic_log_event(DIAG_EVENT_BOOT, 0, 0, 0);
    return true;
}

bool diagnostic_log_available(void) { return atomic_load(&log_ready); }

static bool event_text(char *out, size_t capacity, diagnostic_event event,
                       int first, int second, int third) {
    switch (event) {
        case DIAG_EVENT_BOOT:
            snprintf(out, capacity, "I BOOT"); break;
        case DIAG_EVENT_STORAGE:
            snprintf(out, capacity, "I STORAGE ok=%d free=%dMiB total=%dMiB",
                     first, second, third); break;
        case DIAG_EVENT_WIFI_UP:
            snprintf(out, capacity, "I WIFI connected"); break;
        case DIAG_EVENT_WIFI_DOWN:
            snprintf(out, capacity, "W WIFI disconnected"); break;
        case DIAG_EVENT_SETUP_OPEN:
            snprintf(out, capacity, "I WLAN_SETUP open profiles=%d", first); break;
        case DIAG_EVENT_SETUP_CANCEL:
            snprintf(out, capacity, "I WLAN_SETUP cancel profiles=%d", first); break;
        case DIAG_EVENT_SETUP_SAVED:
            snprintf(out, capacity, "I WLAN_SETUP saved profiles=%d result=%d",
                     first, second); break;
        case DIAG_EVENT_GATE_OK:
            snprintf(out, capacity, "I CONTRACT ok http=%d", first); break;
        case DIAG_EVENT_GATE_FAILED:
            snprintf(out, capacity, "W CONTRACT fail http=%d", first); break;
        case DIAG_EVENT_QUEUE:
            snprintf(out, capacity, "I QUEUE ready=%d ack=%d attention=%d",
                     first, second, third); break;
        case DIAG_EVENT_CAPTURE_START:
            snprintf(out, capacity, "I CAPTURE started"); break;
        case DIAG_EVENT_CAPTURE_END:
            snprintf(out, capacity, "I CAPTURE ended ok=%d segments=%d",
                     first, second); break;
        default:
            return false;
    }
    return true;
}

void diagnostic_log_event(diagnostic_event event, int first, int second,
                          int third) {
    if (!atomic_load(&log_ready) || !log_lock) return;
    char event_part[104];
    if (!event_text(event_part, sizeof(event_part), event, first, second, third))
        return;
    char line[144];
    unsigned long long seconds =
        (unsigned long long)(esp_timer_get_time() / 1000000);
    int length = snprintf(line, sizeof(line), "+%llus %s\n", seconds, event_part);
    if (length <= 0 || length >= (int)sizeof(line)) return;
    if (xSemaphoreTake(log_lock, pdMS_TO_TICKS(50)) != pdTRUE) return;
    if (event == DIAG_EVENT_QUEUE && queue_seen &&
        queue_ready == first && queue_acked == second &&
        queue_attention == third) {
        xSemaphoreGive(log_lock);
        return;
    }
    if (rotate_for((size_t)length)) {
        FILE *file = fopen(DIAG_CURRENT, "ab");
        if (file) {
            bool written = fwrite(line, 1, (size_t)length, file) ==
                           (size_t)length;
            if (fclose(file) == 0 && written && event == DIAG_EVENT_QUEUE) {
                queue_seen = true;
                queue_ready = first;
                queue_acked = second;
                queue_attention = third;
            }
        }
    }
    xSemaphoreGive(log_lock);
}

unsigned diagnostic_log_read_tail(char *out, size_t capacity) {
    if (!out || capacity == 0) return 0;
    out[0] = 0;
    if (!atomic_load(&log_ready) || !log_lock || capacity < 2) return 0;
    if (xSemaphoreTake(log_lock, pdMS_TO_TICKS(200)) != pdTRUE) return 0;
    FILE *file = fopen(DIAG_CURRENT, "rb");
    if (!file) {
        xSemaphoreGive(log_lock);
        return 0;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        xSemaphoreGive(log_lock);
        return 0;
    }
    long size = ftell(file);
    if (size < 0) {
        fclose(file);
        xSemaphoreGive(log_lock);
        return 0;
    }
    long start = size > (long)capacity - 1 ? size - ((long)capacity - 1) : 0;
    if (fseek(file, start, SEEK_SET) != 0) {
        fclose(file);
        xSemaphoreGive(log_lock);
        return 0;
    }
    size_t used = fread(out, 1, capacity - 1, file);
    fclose(file);
    xSemaphoreGive(log_lock);
    out[used] = 0;
    if (start > 0) {
        char *complete = strchr(out, '\n');
        if (complete) {
            complete++;
            used -= (size_t)(complete - out);
            memmove(out, complete, used + 1);
        } else {
            out[0] = 0;
            return 0;
        }
    }
    unsigned lines = 0;
    for (size_t index = 0; index < used; index++)
        if (out[index] == '\n') lines++;
    return lines;
}

void diagnostic_log_report(void) {
    struct stat current = {0}, previous = {0}, oldest = {0};
    bool have_current = stat(DIAG_CURRENT, &current) == 0;
    bool have_previous = stat(DIAG_PREVIOUS, &previous) == 0;
    bool have_oldest = stat(DIAG_OLDEST, &oldest) == 0;
    printf("@DIAGLOG available=%u current=%ld previous=%ld oldest=%ld limit=%u\n",
           atomic_load(&log_ready) ? 1u : 0u,
           have_current ? (long)current.st_size : 0L,
           have_previous ? (long)previous.st_size : 0L,
           have_oldest ? (long)oldest.st_size : 0L,
           (unsigned)DIAG_ROTATE_BYTES);
}
