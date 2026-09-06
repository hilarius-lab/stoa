#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_sntp.h"
#include "clock.h"
#include "screen.h"

/* Europe/Berlin as a POSIX rule rather than a tzdata lookup: the rule is three
 * lines of the standard, it needs no database on flash, and it is exact for
 * this zone — CET/CEST, last Sunday in March and October. A device shipped
 * elsewhere gets a different string here; the display timezone is a build-time
 * decision until there is a setting for it. */
#define DISPLAY_TZ "CET-1CEST,M3.5.0,M10.5.0/3"

/* Anything before this is not a synchronised clock but the epoch the chip boots
 * with. Used to reject a "successful" sync that produced nonsense. */
#define PLAUSIBLE_AFTER 1735689600 /* 2025-01-01T00:00:00Z */

static atomic_bool synced;
static atomic_bool started;
/* The minute task, so a completed sync can hand the new time straight to the
 * panel instead of waiting for the task's own next beat. */
static TaskHandle_t minute_task;

static void on_sync(struct timeval *received) {
    (void)received;
    time_t now = time(NULL);
    if (now < PLAUSIBLE_AFTER) {
        /* An implausible time is worse than no time: it would make the status
         * bar and the history look authoritative while being wrong. */
        ESP_LOGW("clock", "sync produced an implausible time; still unsynced");
        return;
    }
    bool first = !atomic_exchange(&synced, true);
    if (first) ESP_LOGI("clock", "time synchronised");
    /* Hand the minute task its cue instead of letting it sleep out the rest of
     * its interval. It wakes aligned to the next full minute, so before this the
     * panel could keep the placeholder for up to a minute after the time was
     * already known — the clock was right and only the display was late. Every
     * sync, not only the first: a device that was off for a week comes back with
     * a time that may jump, and the panel should follow it at once. */
    if (minute_task) xTaskNotifyGive(minute_task);
}

/* One tick per minute, which is also the only cadence at which the displayed
 * time can change. The refresh policy asks for exactly this: the clock owns the
 * minute tick and nothing else gets a beat of its own. An unchanged value costs
 * no refresh, because the display task drops an identical frame. */
static void clock_task(void *unused) {
    (void)unused;
    while (true) {
        screen_status_time(clock_minutes());
        /* Aligned to the next full minute rather than a free-running 60 s
         * delay, so the shown minute changes when the minute actually does. */
        time_t now = time(NULL);
        struct tm local;
        localtime_r(&now, &local);
        int wait = 60 - local.tm_sec;
        /* A notification from a completed sync cuts the wait short; otherwise
         * this is the same aligned minute delay as before. */
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS((wait > 0 ? wait : 60) * 1000));
    }
}

void clock_start(void) {
    if (atomic_exchange(&started, true)) return;
    setenv("TZ", DISPLAY_TZ, 1);
    tzset();
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    /* Three independent operators, tried in order. A single name would make the
     * clock depend on one provider staying reachable. */
    esp_sntp_setservername(0, "pool.ntp.org");
    esp_sntp_setservername(1, "time.cloudflare.com");
    esp_sntp_setservername(2, "time.google.com");
    sntp_set_time_sync_notification_cb(on_sync);
    /* Six hours, per the clock decision. The drift of the chip over that span is
     * far below the minute the display shows. */
    sntp_set_sync_interval(6 * 60 * 60 * 1000);
    /* The task exists before the first sync can land, so its handle is always
     * there when the callback wants to wake it. The other order would drop the
     * notification for the very sync that matters most — the first one. */
    if (xTaskCreate(clock_task, "clock", 3072, NULL, 1, &minute_task) != pdPASS)
        ESP_LOGE("clock", "minute task allocation failed");
    esp_sntp_init();
}

void clock_network_up(void) {
    /* A device that was off for a week has a useless clock even though it once
     * synchronised, so every join asks again rather than only the first. */
    if (atomic_load(&started)) esp_sntp_restart();
}

bool clock_ready(void) { return atomic_load(&synced); }

unsigned clock_minutes(void) {
    if (!atomic_load(&synced)) return CLOCK_TIME_UNKNOWN;
    time_t now = time(NULL);
    struct tm local;
    localtime_r(&now, &local);
    return (unsigned)(local.tm_hour * 60 + local.tm_min);
}
