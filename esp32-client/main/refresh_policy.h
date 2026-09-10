#pragma once

/* A healthy idle client starts after at most four minutes, leaving one minute
 * inside the five-minute success target for DNS, TLS and response validation.
 * A shorter server freshness window can pull that forward, but never below the
 * local thirty-second floor: capabilities describe data validity, not
 * permission to turn every device into an unbounded request loop. */
#define DASHBOARD_REFRESH_FALLBACK_S 240u
#define DASHBOARD_REFRESH_MIN_S 30u
#define DASHBOARD_REFRESH_MAX_S 240u

static inline unsigned dashboard_refresh_interval_s(unsigned cache_max_age_s) {
    unsigned window = cache_max_age_s
        ? cache_max_age_s : DASHBOARD_REFRESH_FALLBACK_S;
    unsigned interval = window / 2;
    if (interval < DASHBOARD_REFRESH_MIN_S)
        interval = DASHBOARD_REFRESH_MIN_S;
    if (interval > DASHBOARD_REFRESH_MAX_S)
        interval = DASHBOARD_REFRESH_MAX_S;
    return interval;
}
