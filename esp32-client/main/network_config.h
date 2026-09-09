#pragma once

#include <stdbool.h>
#include "esp_err.h"

#define NOTEBOOK_NETWORK_MAX 5
#define NOTEBOOK_SSID_CHARS 33
#define NOTEBOOK_PASSWORD_CHARS 64
#define NOTEBOOK_SERVER_CHARS 256

typedef struct {
    char ssid[NOTEBOOK_SSID_CHARS];
    char password[NOTEBOOK_PASSWORD_CHARS];
} notebook_network_profile;

typedef struct {
    notebook_network_profile networks[NOTEBOOK_NETWORK_MAX];
    unsigned network_count;
    char server[NOTEBOOK_SERVER_CHARS];
} notebook_network_config;

/* Reads both the original single-network JSON and the current networks array.
 * Malformed individual profiles are ignored; secrets are never logged here. */
bool notebook_network_config_load(notebook_network_config *out);

/* Adds or replaces one profile and moves it to the first retry position.
 * Existing profiles and a non-empty existing server URL are retained when the
 * submitted server field is empty. The whole JSON plus optional enrollment
 * code is committed in one NVS transaction. */
esp_err_t notebook_network_config_store(const char *ssid, const char *password,
                                        const char *server,
                                        const char *enrollment_code);

bool notebook_network_profile_valid(const char *ssid, const char *password);
bool notebook_server_url_valid(const char *server);
