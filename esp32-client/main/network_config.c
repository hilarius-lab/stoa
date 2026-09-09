#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "network_config.h"
#include "esp_log.h"
#include "nvs.h"
#include "cJSON.h"

#define CONFIG_BYTES 1024

bool notebook_network_profile_valid(const char *ssid, const char *password) {
    if (!ssid || !password) return false;
    size_t ssid_length = strlen(ssid);
    size_t password_length = strlen(password);
    return ssid_length > 0 && ssid_length <= 32 && password_length <= 63 &&
           (password_length == 0 || password_length >= 8);
}

bool notebook_server_url_valid(const char *server) {
    if (!server || !server[0]) return true;
    size_t length = strlen(server);
    return length <= 255 &&
           ((strncmp(server, "https://", 8) == 0 && length > 8) ||
            (strncmp(server, "http://", 7) == 0 && length > 7));
}

static bool append_profile(notebook_network_config *out, const char *ssid,
                           const char *password) {
    if (!out || !notebook_network_profile_valid(ssid, password)) return false;
    for (unsigned index = 0; index < out->network_count; index++)
        if (strcmp(out->networks[index].ssid, ssid) == 0) return false;
    if (out->network_count >= NOTEBOOK_NETWORK_MAX) return false;
    notebook_network_profile *profile = &out->networks[out->network_count++];
    snprintf(profile->ssid, sizeof(profile->ssid), "%s", ssid);
    snprintf(profile->password, sizeof(profile->password), "%s", password);
    return true;
}

static void parse_config(const char *encoded, notebook_network_config *out) {
    memset(out, 0, sizeof(*out));
    cJSON *root = encoded && encoded[0] ? cJSON_Parse(encoded) : NULL;
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return;
    }
    cJSON *networks = cJSON_GetObjectItemCaseSensitive(root, "networks");
    if (cJSON_IsArray(networks)) {
        cJSON *entry = NULL;
        cJSON_ArrayForEach(entry, networks) {
            cJSON *ssid = cJSON_GetObjectItemCaseSensitive(entry, "ssid");
            cJSON *password = cJSON_GetObjectItemCaseSensitive(entry, "password");
            if (cJSON_IsString(ssid) && cJSON_IsString(password))
                append_profile(out, ssid->valuestring, password->valuestring);
        }
    }
    /* One-time compatibility with every device configured before profiles
     * existed. It is also useful for downgrades that later return here. */
    cJSON *ssid = cJSON_GetObjectItemCaseSensitive(root, "ssid");
    cJSON *password = cJSON_GetObjectItemCaseSensitive(root, "password");
    if (cJSON_IsString(ssid) && cJSON_IsString(password))
        append_profile(out, ssid->valuestring, password->valuestring);
    cJSON *server = cJSON_GetObjectItemCaseSensitive(root, "server");
    if (cJSON_IsString(server) && notebook_server_url_valid(server->valuestring))
        snprintf(out->server, sizeof(out->server), "%s", server->valuestring);
    cJSON_Delete(root);
}

bool notebook_network_config_load(notebook_network_config *out) {
    if (!out) return false;
    char *encoded = calloc(1, CONFIG_BYTES);
    if (!encoded) {
        memset(out, 0, sizeof(*out));
        return false;
    }
    size_t length = CONFIG_BYTES;
    nvs_handle_t n;
    esp_err_t err = nvs_open("notebook", NVS_READONLY, &n);
    if (err == ESP_OK) {
        err = nvs_get_str(n, "config", encoded, &length);
        nvs_close(n);
    }
    parse_config(err == ESP_OK ? encoded : NULL, out);
    memset(encoded, 0, CONFIG_BYTES);
    free(encoded);
    return out->network_count > 0;
}

esp_err_t notebook_network_config_store(const char *ssid, const char *password,
                                        const char *server,
                                        const char *enrollment_code) {
    if (!notebook_network_profile_valid(ssid, password) ||
        !notebook_server_url_valid(server) ||
        (enrollment_code && strlen(enrollment_code) > 200))
        return ESP_ERR_INVALID_ARG;

    notebook_network_config *previous = calloc(1, sizeof(*previous));
    notebook_network_config *updated = calloc(1, sizeof(*updated));
    if (!previous || !updated) {
        free(previous);
        free(updated);
        return ESP_ERR_NO_MEM;
    }
    notebook_network_config_load(previous);
    append_profile(updated, ssid, password);
    for (unsigned index = 0; index < previous->network_count; index++)
        append_profile(updated, previous->networks[index].ssid,
                       previous->networks[index].password);
    snprintf(updated->server, sizeof(updated->server), "%s",
             server && server[0] ? server : previous->server);

    cJSON *root = cJSON_CreateObject();
    cJSON *networks = cJSON_CreateArray();
    if (!root || !networks) {
        cJSON_Delete(root);
        cJSON_Delete(networks);
        memset(previous, 0, sizeof(*previous));
        memset(updated, 0, sizeof(*updated));
        free(previous);
        free(updated);
        return ESP_ERR_NO_MEM;
    }
    if (!cJSON_AddItemToObject(root, "networks", networks)) {
        cJSON_Delete(networks);
        cJSON_Delete(root);
        memset(previous, 0, sizeof(*previous));
        memset(updated, 0, sizeof(*updated));
        free(previous);
        free(updated);
        return ESP_ERR_NO_MEM;
    }
    for (unsigned index = 0; index < updated->network_count; index++) {
        cJSON *entry = cJSON_CreateObject();
        if (!entry || !cJSON_AddStringToObject(entry, "ssid", updated->networks[index].ssid) ||
            !cJSON_AddStringToObject(entry, "password", updated->networks[index].password) ||
            !cJSON_AddItemToArray(networks, entry)) {
            cJSON_Delete(entry);
            cJSON_Delete(root);
            memset(previous, 0, sizeof(*previous));
            memset(updated, 0, sizeof(*updated));
            free(previous);
            free(updated);
            return ESP_ERR_NO_MEM;
        }
    }
    if (updated->server[0] &&
        !cJSON_AddStringToObject(root, "server", updated->server)) {
        cJSON_Delete(root);
        memset(previous, 0, sizeof(*previous));
        memset(updated, 0, sizeof(*updated));
        free(previous);
        free(updated);
        return ESP_ERR_NO_MEM;
    }
    char *encoded = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    esp_err_t err = !encoded ? ESP_ERR_NO_MEM :
                    strlen(encoded) >= CONFIG_BYTES ? ESP_ERR_INVALID_SIZE : ESP_OK;
    nvs_handle_t n;
    if (err == ESP_OK) err = nvs_open("notebook", NVS_READWRITE, &n);
    if (err == ESP_OK) {
        err = nvs_set_str(n, "config", encoded);
        if (err == ESP_OK && enrollment_code && enrollment_code[0]) {
            err = nvs_set_str(n, "enroll", enrollment_code);
            esp_err_t erased = nvs_erase_key(n, "credential");
            if (err == ESP_OK && erased != ESP_OK &&
                erased != ESP_ERR_NVS_NOT_FOUND) err = erased;
        }
        if (err == ESP_OK) err = nvs_set_u8(n, "setup", 0);
        if (err == ESP_OK) err = nvs_commit(n);
        nvs_close(n);
    }
    if (encoded) {
        memset(encoded, 0, strlen(encoded));
        cJSON_free(encoded);
    }
    if (err == ESP_OK)
        ESP_LOGI("network-config", "stored profiles=%u", updated->network_count);
    memset(previous, 0, sizeof(*previous));
    memset(updated, 0, sizeof(*updated));
    free(previous);
    free(updated);
    return err;
}
